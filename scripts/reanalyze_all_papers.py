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
from remote_app.services import reanalyze_paper  # noqa: E402
from sqlalchemy import text  # noqa: E402


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

    db = SessionLocal()
    report = {
        "ok": True,
        "total": 0,
        "re_analyzed": 0,
        "fixed": 0,
        "downgraded_to_pending_review": 0,
        "failed": 0,
        "failed_ids": [],
    }
    try:
        papers = db.query(Paper).order_by(Paper.created_at.asc()).all()
        report["total"] = len(papers)
        for paper in papers:
            before_status = (paper.publish_status or "published").strip().lower()
            ok, result = reanalyze_paper(db, paper.id, settings.library_files_dir)
            if not ok:
                report["failed"] += 1
                report["failed_ids"].append(paper.id)
                continue
            report["re_analyzed"] += 1
            if result.get("updated_fields"):
                report["fixed"] += 1
            after_status = str(result.get("publish_status") or "").strip().lower()
            if before_status == "published" and after_status == "pending_review":
                report["downgraded_to_pending_review"] += 1
    finally:
        db.close()

    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
