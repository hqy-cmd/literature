#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from remote_app.config import settings  # noqa: E402
from remote_app.database import Base, SessionLocal, engine  # noqa: E402
from remote_app.models import Paper  # noqa: E402
from remote_app.services import upsert_paper  # noqa: E402


PAPERS_JSON = BASE_DIR / "literature-library" / "papers.json"


def main() -> None:
    settings.ensure_dirs()
    Base.metadata.create_all(bind=engine)
    if not PAPERS_JSON.exists():
        print(json.dumps({"ok": False, "error": "papers_json_not_found", "path": str(PAPERS_JSON)}, ensure_ascii=False))
        return

    data = json.loads(PAPERS_JSON.read_text(encoding="utf-8"))
    papers = data.get("papers", [])
    db = SessionLocal()
    inserted = 0
    updated = 0
    try:
        for item in papers:
            paper_id = str(item.get("id") or "").strip()
            if not paper_id:
                continue
            exists = db.query(Paper.id).filter(Paper.id == paper_id).first()
            payload = {
                "id": paper_id,
                "title": item.get("title", ""),
                "authors": item.get("authors") or [],
                "year": item.get("year", ""),
                "category": item.get("category", ""),
                "collections": item.get("collections") or [],
                "tags": item.get("tags") or [],
                "abstract_original": item.get("abstract_original", ""),
                "abstract_summary_zh": item.get("abstract_summary_zh", ""),
                "filename": item.get("filename", ""),
                "source_note": item.get("source_note", ""),
                "added_at": item.get("added_at", ""),
                "file_path": item.get("file_path", ""),
                "file_url": item.get("file_url", ""),
                "manual_edit": bool(item.get("manual_edit", False)),
                "locked_fields": item.get("locked_fields") or [],
            }
            upsert_paper(db, payload)
            if exists:
                updated += 1
            else:
                inserted += 1
        db.commit()
    finally:
        db.close()

    print(
        json.dumps(
            {"ok": True, "inserted": inserted, "updated": updated, "total": len(papers)},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

