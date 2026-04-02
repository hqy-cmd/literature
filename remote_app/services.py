from __future__ import annotations

import json
import math
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session

from .ingest_parser import (
    SUPPORTED_EXTENSIONS,
    build_paper_payload,
    extract_text_from_file,
    extract_texts_from_zip,
    fetch_url_text,
    persist_uploaded_file,
)
from .models import IngestTask, Paper, PaperChunk, Source
from .utils import chunk_text, ensure_list, hash_vector, normalize_top_category, now_text, tokenize


EDITABLE_FIELDS = {
    "title",
    "authors",
    "year",
    "category",
    "collections",
    "tags",
    "abstract_summary_zh",
    "source_note",
}

ARRAY_FIELDS = {"authors", "collections", "tags"}


def build_search_text(payload: dict) -> str:
    fields = [
        payload.get("title", ""),
        " ".join(payload.get("authors") or []),
        payload.get("year", ""),
        payload.get("category", ""),
        " ".join(payload.get("collections") or []),
        " ".join(payload.get("tags") or []),
        payload.get("abstract_original", ""),
        payload.get("abstract_summary_zh", ""),
        payload.get("filename", ""),
        payload.get("source_note", ""),
    ]
    return "\n".join(str(x) for x in fields if x)


def upsert_paper(db: Session, payload: dict) -> Paper:
    paper = db.query(Paper).filter(Paper.id == payload["id"]).first()
    if not paper:
        paper = Paper(id=payload["id"])
        db.add(paper)
    for key, value in payload.items():
        if hasattr(paper, key):
            setattr(paper, key, value)
    paper.search_text = build_search_text(payload)
    paper.token_vector = hash_vector(tokenize(paper.search_text))
    paper.updated_at = datetime.utcnow()

    db.query(PaperChunk).filter(PaperChunk.paper_id == paper.id).delete()
    chunks = chunk_text(f"{paper.abstract_summary_zh}\n{paper.abstract_original}")
    for idx, content in enumerate(chunks[:32]):
        token_list = tokenize(content)
        db.add(
            PaperChunk(
                paper_id=paper.id,
                chunk_index=idx,
                content=content,
                token_count=len(token_list),
                token_vector=hash_vector(token_list),
            )
        )
    return paper


def normalize_updates(updates: dict) -> dict:
    normalized = {}
    for key, value in updates.items():
        if key not in EDITABLE_FIELDS:
            continue
        if key in ARRAY_FIELDS:
            normalized[key] = ensure_list(value)
        else:
            normalized[key] = "" if value is None else str(value).strip()
    return normalized


def update_paper(db: Session, paper_id: str, updates: dict) -> tuple[bool, dict]:
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        return False, {"ok": False, "error": "paper_not_found", "id": paper_id}
    normalized = normalize_updates(updates)
    if not normalized:
        return False, {"ok": False, "error": "no_valid_updates", "id": paper_id}
    locked = set(paper.locked_fields or [])
    for key, value in normalized.items():
        setattr(paper, key, value)
        locked.add(key)
    paper.manual_edit = True
    paper.locked_fields = sorted(locked)
    paper.updated_at = datetime.utcnow()

    payload = {
        "title": paper.title,
        "authors": paper.authors or [],
        "year": paper.year,
        "category": paper.category,
        "collections": paper.collections or [],
        "tags": paper.tags or [],
        "abstract_original": paper.abstract_original,
        "abstract_summary_zh": paper.abstract_summary_zh,
        "filename": paper.filename,
        "source_note": paper.source_note,
    }
    paper.search_text = build_search_text(payload)
    paper.token_vector = hash_vector(tokenize(paper.search_text))
    db.commit()
    return True, {
        "ok": True,
        "updated_id": paper_id,
        "updated_fields": sorted(normalized.keys()),
    }


def create_task(db: Session, task_type: str, payload: dict) -> IngestTask:
    task = IngestTask(
        task_type=task_type,
        status="queued",
        progress=0,
        message="任务已进入队列",
        payload=payload,
        result={},
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def mark_task_running(db: Session, task: IngestTask, message: str = "处理中") -> None:
    task.status = "running"
    task.started_at = datetime.utcnow()
    task.progress = max(task.progress, 5)
    task.message = message
    db.commit()


def mark_task_success(db: Session, task: IngestTask, result: dict) -> None:
    task.status = "success"
    task.progress = 100
    task.message = "处理完成"
    task.result = result
    task.finished_at = datetime.utcnow()
    db.commit()


def mark_task_failed(db: Session, task: IngestTask, error_message: str) -> None:
    task.status = "failed"
    task.message = "处理失败"
    task.error_message = (error_message or "")[:2000]
    task.finished_at = datetime.utcnow()
    db.commit()


def _source_record(
    db: Session,
    paper_id: str | None,
    source_type: str,
    source_path: str = "",
    source_url: str = "",
    content_type: str = "",
    status: str = "success",
    error_message: str = "",
) -> None:
    db.add(
        Source(
            paper_id=paper_id,
            source_type=source_type,
            source_path=source_path,
            source_url=source_url,
            content_type=content_type,
            status=status,
            error_message=error_message[:2000],
        )
    )


def process_upload_file_task(db: Session, task: IngestTask, library_files_dir: Path) -> dict:
    payload = task.payload or {}
    file_path = Path(payload.get("file_path", "")).expanduser()
    if not file_path.exists():
        raise RuntimeError("上传文件不存在")
    suffix = file_path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise RuntimeError(f"不支持的格式: {suffix}")

    created_ids: list[str] = []
    if suffix == ".zip":
        entries = extract_texts_from_zip(file_path)
        if not entries:
            raise RuntimeError("ZIP 中未解析到可用文献")
        for idx, (name, text) in enumerate(entries):
            record = build_paper_payload(name, text)
            record["id"] = f"{record['id']}-{idx}"
            upsert_paper(db, record)
            _source_record(
                db,
                paper_id=record["id"],
                source_type="file",
                source_path=str(file_path),
                content_type="application/zip",
            )
            created_ids.append(record["id"])
    else:
        text = extract_text_from_file(file_path)
        if not text:
            raise RuntimeError("文档内容解析失败")
        moved_file, relative = persist_uploaded_file(file_path, library_files_dir)
        record = build_paper_payload(moved_file.name, text)
        record["file_path"] = relative
        record["file_url"] = relative
        upsert_paper(db, record)
        _source_record(
            db,
            paper_id=record["id"],
            source_type="file",
            source_path=str(moved_file),
            content_type=suffix.lstrip("."),
        )
        created_ids.append(record["id"])

    db.commit()
    return {"created_count": len(created_ids), "paper_ids": created_ids, "ts": int(time.time())}


def process_url_task(db: Session, task: IngestTask) -> dict:
    payload = task.payload or {}
    url = str(payload.get("url", "")).strip()
    if not url:
        raise RuntimeError("缺少 URL")
    title, text = fetch_url_text(url)
    if not text:
        raise RuntimeError("网页正文解析失败")
    filename = reformat_url_title(title, url)
    record = build_paper_payload(filename, text)
    record["source_note"] = f"网页解析导入: {url}"
    upsert_paper(db, record)
    _source_record(
        db,
        paper_id=record["id"],
        source_type="url",
        source_url=url,
        content_type="text/html",
    )
    db.commit()
    return {"created_count": 1, "paper_ids": [record["id"]], "url": url}


def reformat_url_title(title: str, url: str) -> str:
    clean = (title or "").strip()
    if clean:
        return clean[:160]
    return url.replace("https://", "").replace("http://", "").replace("/", "_")[:160]


def paper_to_dict(paper: Paper) -> dict:
    top_category = normalize_top_category(paper.category, paper.collections or [])
    return {
        "id": paper.id,
        "title": paper.title or "",
        "authors": paper.authors or [],
        "year": paper.year or "",
        "category": top_category,
        "collections": paper.collections or [],
        "tags": paper.tags or [],
        "abstract_original": paper.abstract_original or "",
        "abstract_summary_zh": paper.abstract_summary_zh or "",
        "filename": paper.filename or "",
        "source_note": paper.source_note or "",
        "added_at": paper.added_at or "",
        "file_path": paper.file_path or "",
        "file_url": paper.file_url or "",
        "manual_edit": bool(paper.manual_edit),
        "locked_fields": paper.locked_fields or [],
    }


def task_to_dict(task: IngestTask) -> dict:
    return {
        "id": task.id,
        "task_type": task.task_type,
        "status": task.status,
        "progress": task.progress,
        "message": task.message or "",
        "payload": task.payload or {},
        "result": task.result or {},
        "error_message": task.error_message or "",
        "created_at": task.created_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
    }


def list_categories(db: Session) -> list[dict]:
    papers = db.query(Paper).all()
    counter: dict[str, int] = {}
    for paper in papers:
        top = normalize_top_category(paper.category, paper.collections or [])
        counter[top] = counter.get(top, 0) + 1
    items = [{"name": k, "count": v} for k, v in counter.items() if k]
    items.sort(key=lambda x: (-x["count"], x["name"]))
    return items


def list_papers(
    db: Session,
    page: int = 1,
    page_size: int = 24,
    category: str = "",
    sort: str = "updated_desc",
    q: str = "",
) -> dict:
    papers = db.query(Paper).all()
    cat = (category or "").strip().lower()
    query = (q or "").strip().lower()

    filtered: list[Paper] = []
    for paper in papers:
        top_category = normalize_top_category(paper.category, paper.collections or [])
        if cat:
            if cat != top_category.lower():
                continue
        if query:
            hay = "\n".join(
                [
                    paper.title or "",
                    " ".join(paper.authors or []),
                    top_category,
                    " ".join(paper.collections or []),
                    " ".join(paper.tags or []),
                    paper.abstract_summary_zh or "",
                    paper.filename or "",
                ]
            ).lower()
            if query not in hay:
                continue
        filtered.append(paper)

    if sort == "year_desc":
        filtered.sort(key=lambda p: (str(p.year or ""), str(p.updated_at or "")), reverse=True)
    elif sort == "year_asc":
        filtered.sort(key=lambda p: (str(p.year or "9999"), str(p.updated_at or "")))
    elif sort == "title_asc":
        filtered.sort(key=lambda p: str(p.title or "").lower())
    else:
        filtered.sort(key=lambda p: (str(p.updated_at or ""), str(p.created_at or "")), reverse=True)

    total = len(filtered)
    page = max(1, int(page))
    page_size = max(1, min(100, int(page_size)))
    total_pages = max(1, math.ceil(total / page_size)) if total else 1
    if page > total_pages:
        page = total_pages
    start = (page - 1) * page_size
    end = start + page_size
    items = [paper_to_dict(paper) for paper in filtered[start:end]]
    return {
        "ok": True,
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "category": category or "",
        "sort": sort,
        "q": q or "",
    }


def dump_result_to_json(task: IngestTask) -> str:
    return json.dumps(task_to_dict(task), ensure_ascii=False, default=str)
