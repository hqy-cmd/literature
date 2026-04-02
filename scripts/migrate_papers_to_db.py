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
from remote_app.utils import build_list_summary, normalize_top_category  # noqa: E402
from sqlalchemy import text  # noqa: E402


PAPERS_JSON = BASE_DIR / "literature-library" / "papers.json"


def ensure_online_columns() -> None:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE papers ADD COLUMN IF NOT EXISTS list_summary_zh TEXT DEFAULT ''"))
        conn.execute(text("ALTER TABLE papers ADD COLUMN IF NOT EXISTS publish_status VARCHAR(32) DEFAULT 'published'"))
        conn.execute(text("ALTER TABLE papers ADD COLUMN IF NOT EXISTS analysis_confidence DOUBLE PRECISION DEFAULT 1.0"))
        conn.execute(
            text(
                "ALTER TABLE papers ADD COLUMN IF NOT EXISTS analysis_confidence_breakdown JSON DEFAULT '{}'::json"
            )
        )
        conn.execute(text("ALTER TABLE papers ADD COLUMN IF NOT EXISTS analysis_warnings JSON DEFAULT '[]'::json"))
        conn.execute(text("ALTER TABLE papers ADD COLUMN IF NOT EXISTS classification_evidence JSON DEFAULT '[]'::json"))


def main() -> None:
    settings.ensure_dirs()
    Base.metadata.create_all(bind=engine)
    ensure_online_columns()
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
                "list_summary_zh": item.get("list_summary_zh", ""),
                "filename": item.get("filename", ""),
                "source_note": item.get("source_note", ""),
                "added_at": item.get("added_at", ""),
                "file_path": item.get("file_path", ""),
                "file_url": item.get("file_url", ""),
                "manual_edit": bool(item.get("manual_edit", False)),
                "locked_fields": item.get("locked_fields") or [],
                "publish_status": item.get("publish_status", "published"),
                "analysis_confidence": float(item.get("analysis_confidence", 1.0) or 1.0),
                "analysis_confidence_breakdown": item.get("analysis_confidence_breakdown") or {},
                "analysis_warnings": item.get("analysis_warnings") or [],
                "classification_evidence": item.get("classification_evidence") or [],
            }
            if not str(payload["list_summary_zh"]).strip():
                payload["list_summary_zh"] = build_list_summary(
                    payload["title"],
                    normalize_top_category(payload["category"], payload["collections"]),
                    payload["abstract_summary_zh"] or payload["abstract_original"],
                )
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
