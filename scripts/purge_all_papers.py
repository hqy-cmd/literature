#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from remote_app.config import settings  # noqa: E402
from remote_app.database import Base, SessionLocal, engine  # noqa: E402
from remote_app.models import IngestTask, Paper, PaperChunk, Source  # noqa: E402


def _within_dir(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _resolve_paper_file_paths(paper: Paper, library_root: Path) -> list[Path]:
    items: list[Path] = []
    refs = [str(paper.file_path or "").strip(), str(paper.file_url or "").strip()]
    for raw in refs:
        if not raw or raw.startswith("http://") or raw.startswith("https://"):
            continue
        norm = raw.replace("\\", "/").lstrip("/")
        if norm.startswith("files/"):
            candidate = library_root / norm[len("files/") :]
        elif "/files/" in norm:
            candidate = library_root / norm.split("/files/", 1)[1].lstrip("/")
        elif "/" not in norm:
            candidate = library_root / norm
        else:
            candidate = Path(norm)
        if candidate.exists() and candidate.is_file() and _within_dir(candidate, library_root):
            items.append(candidate)
    uniq: dict[str, Path] = {}
    for p in items:
        uniq[str(p.resolve())] = p
    return list(uniq.values())


def main() -> None:
    parser = argparse.ArgumentParser(description="Purge all papers from Agent文献库")
    parser.add_argument("--delete-files", action="store_true", help="Also delete files under literature-library/files")
    parser.add_argument("--clear-tasks", action="store_true", help="Also clear ingest task history")
    args = parser.parse_args()

    settings.ensure_dirs()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    report = {
        "ok": True,
        "papers_deleted": 0,
        "chunks_deleted": 0,
        "sources_deleted": 0,
        "tasks_deleted": 0,
        "files_deleted": 0,
        "files_failed": [],
    }
    try:
        papers = db.query(Paper).all()
        report["papers_deleted"] = len(papers)

        file_paths: dict[str, Path] = {}
        if args.delete_files:
            for paper in papers:
                for p in _resolve_paper_file_paths(paper, settings.library_files_dir):
                    file_paths[str(p)] = p

        report["chunks_deleted"] = db.query(PaperChunk).delete(synchronize_session=False)
        report["sources_deleted"] = db.query(Source).delete(synchronize_session=False)
        report["papers_deleted"] = db.query(Paper).delete(synchronize_session=False)
        if args.clear_tasks:
            report["tasks_deleted"] = db.query(IngestTask).delete(synchronize_session=False)
        db.commit()

        if args.delete_files:
            for path in file_paths.values():
                try:
                    path.unlink(missing_ok=True)
                    report["files_deleted"] += 1
                except Exception as exc:
                    report["files_failed"].append({"path": str(path), "error": str(exc)})
    finally:
        db.close()

    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
