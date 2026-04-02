from __future__ import annotations

import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .ingest_parser import (
    SUPPORTED_EXTENSIONS,
    build_paper_payload,
    clean_text,
    extract_text_from_file,
    extract_texts_from_zip,
    fetch_url_text,
    persist_uploaded_file,
)
from .models import IngestTask, Paper, PaperChunk, Source
from .utils import (
    build_list_summary,
    chunk_text,
    ensure_list,
    hash_vector,
    normalize_file_url,
    now_text,
    resolve_category,
    tokenize,
)


EDITABLE_FIELDS = {
    "title",
    "authors",
    "year",
    "category",
    "collections",
    "tags",
    "abstract_summary_zh",
    "list_summary_zh",
    "source_note",
}

ARRAY_FIELDS = {"authors", "collections", "tags"}
PUBLISH_STATUSES = {"published", "pending_review", "rejected", "trashed"}


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
        payload.get("list_summary_zh", ""),
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
    if not (paper.list_summary_zh or "").strip():
        paper.list_summary_zh = build_list_summary(
            paper.title or "",
            resolve_category(paper.category, paper.collections or [], bool(paper.manual_edit)),
            paper.abstract_summary_zh or paper.abstract_original or "",
        )
    status = str(getattr(paper, "publish_status", "") or "published").strip()
    if status not in PUBLISH_STATUSES:
        paper.publish_status = "published"
    if getattr(paper, "analysis_confidence", None) is None:
        paper.analysis_confidence = 1.0
    if not isinstance(getattr(paper, "analysis_confidence_breakdown", None), dict):
        paper.analysis_confidence_breakdown = {}
    if not isinstance(getattr(paper, "analysis_warnings", None), list):
        paper.analysis_warnings = []
    if not isinstance(getattr(paper, "classification_evidence", None), list):
        paper.classification_evidence = []
    paper.search_text = build_search_text(
        {
            "title": paper.title,
            "authors": paper.authors or [],
            "year": paper.year,
            "category": paper.category,
            "collections": paper.collections or [],
            "tags": paper.tags or [],
            "abstract_original": paper.abstract_original,
            "abstract_summary_zh": paper.abstract_summary_zh,
            "list_summary_zh": paper.list_summary_zh,
            "filename": paper.filename,
            "source_note": paper.source_note,
        }
    )
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
        "list_summary_zh": paper.list_summary_zh,
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
    top_category = resolve_category(paper.category, paper.collections or [], bool(paper.manual_edit))
    file_url = normalize_file_url(paper.file_url, paper.file_path, paper.filename)
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
        "list_summary_zh": paper.list_summary_zh or "",
        "filename": paper.filename or "",
        "source_note": paper.source_note or "",
        "added_at": paper.added_at or "",
        "file_path": paper.file_path or "",
        "file_url": file_url,
        "manual_edit": bool(paper.manual_edit),
        "locked_fields": paper.locked_fields or [],
        "publish_status": paper.publish_status or "published",
        "analysis_confidence": float(paper.analysis_confidence or 0.0),
        "analysis_confidence_breakdown": paper.analysis_confidence_breakdown or {},
        "analysis_warnings": paper.analysis_warnings or [],
        "classification_evidence": paper.classification_evidence or [],
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


def list_categories(db: Session, status: str = "published") -> list[dict]:
    papers = db.query(Paper).all()
    counter: dict[str, int] = {}
    for paper in papers:
        if status and (paper.publish_status or "published") != status:
            continue
        top = resolve_category(paper.category, paper.collections or [], bool(paper.manual_edit))
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
    status: str = "published",
) -> dict:
    papers = db.query(Paper).all()
    cat = (category or "").strip().lower()
    query = (q or "").strip().lower()

    filtered: list[Paper] = []
    for paper in papers:
        if status and (paper.publish_status or "published") != status:
            continue
        top_category = resolve_category(paper.category, paper.collections or [], bool(paper.manual_edit))
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
                    paper.list_summary_zh or "",
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
        "status": status or "",
    }


def set_publish_status(db: Session, paper_id: str, status: str) -> tuple[bool, dict]:
    next_status = (status or "").strip().lower()
    if next_status not in PUBLISH_STATUSES:
        return False, {"ok": False, "error": "invalid_status", "status": status}
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        return False, {"ok": False, "error": "paper_not_found", "id": paper_id}
    paper.publish_status = next_status
    paper.updated_at = datetime.utcnow()
    db.commit()
    return True, {"ok": True, "id": paper_id, "publish_status": next_status}


def _resolve_local_file_path(paper: Paper, library_files_dir: Path) -> Path | None:
    for raw in (paper.file_path, paper.file_url):
        value = str(raw or "").strip()
        if not value:
            continue
        if value.startswith("http://") or value.startswith("https://"):
            continue
        norm = value.replace("\\", "/").lstrip("/")
        if norm.startswith("files/"):
            candidate = library_files_dir / norm[len("files/") :]
        elif "/files/" in norm:
            candidate = library_files_dir / norm.split("/files/", 1)[1]
        elif "/" not in norm:
            candidate = library_files_dir / norm
        else:
            candidate = Path(norm)
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _apply_reanalysis_payload(
    db: Session,
    paper: Paper,
    payload: dict[str, Any],
    keep_status_on_trashed_or_rejected: bool = True,
) -> tuple[list[str], Paper]:
    before = paper_to_dict(paper)
    merged = {
        "id": paper.id,
        "title": paper.title or "",
        "authors": paper.authors or [],
        "year": paper.year or "",
        "category": paper.category or "",
        "collections": paper.collections or [],
        "tags": paper.tags or [],
        "abstract_original": paper.abstract_original or "",
        "abstract_summary_zh": paper.abstract_summary_zh or "",
        "list_summary_zh": paper.list_summary_zh or "",
        "filename": paper.filename or "",
        "source_note": paper.source_note or "",
        "added_at": paper.added_at or now_text(),
        "file_path": paper.file_path or "",
        "file_url": paper.file_url or "",
        "manual_edit": bool(paper.manual_edit),
        "locked_fields": paper.locked_fields or [],
        "publish_status": paper.publish_status or "pending_review",
        "analysis_confidence": float(paper.analysis_confidence or 0.0),
        "analysis_confidence_breakdown": paper.analysis_confidence_breakdown or {},
        "analysis_warnings": paper.analysis_warnings or [],
        "classification_evidence": paper.classification_evidence or [],
    }

    for key, value in payload.items():
        if key in merged:
            merged[key] = value

    locked = set(paper.locked_fields or [])
    for key in locked:
        if hasattr(paper, key) and key in merged:
            merged[key] = getattr(paper, key)

    if keep_status_on_trashed_or_rejected and (paper.publish_status in {"trashed", "rejected"}):
        merged["publish_status"] = paper.publish_status

    updated = upsert_paper(db, merged)
    after = paper_to_dict(updated)
    changed_fields = sorted(key for key in after.keys() if after.get(key) != before.get(key))
    return changed_fields, updated


def trash_paper(db: Session, paper_id: str) -> tuple[bool, dict]:
    return set_publish_status(db, paper_id, "trashed")


def restore_paper(db: Session, paper_id: str) -> tuple[bool, dict]:
    return set_publish_status(db, paper_id, "pending_review")


def _latest_source_url(db: Session, paper_id: str) -> str:
    source = (
        db.query(Source)
        .filter(Source.paper_id == paper_id, Source.source_type == "url")
        .order_by(Source.created_at.desc())
        .first()
    )
    return str(source.source_url or "").strip() if source else ""


def reanalyze_paper(db: Session, paper_id: str, library_files_dir: Path) -> tuple[bool, dict]:
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        return False, {"ok": False, "error": "paper_not_found", "id": paper_id}

    text = ""
    filename = paper.filename or paper.id
    source_mode = "fallback"

    local_file = _resolve_local_file_path(paper, library_files_dir)
    if local_file and local_file.suffix.lower() in SUPPORTED_EXTENSIONS and local_file.suffix.lower() != ".zip":
        text = extract_text_from_file(local_file)
        filename = local_file.name
        source_mode = "file"
    else:
        source_url = _latest_source_url(db, paper.id)
        if source_url:
            try:
                title, page_text = fetch_url_text(source_url)
                text = page_text
                filename = reformat_url_title(title, source_url)
                source_mode = "url"
            except Exception:
                text = ""

    if not text:
        text = clean_text(
            "\n".join(
                [
                    paper.title or "",
                    paper.abstract_original or "",
                    paper.abstract_summary_zh or "",
                    " ".join(paper.tags or []),
                ]
            )
        )
        source_mode = "fallback"

    if not text:
        return False, {"ok": False, "error": "reanalyze_text_empty", "id": paper_id}

    payload = build_paper_payload(filename, text)
    payload["id"] = paper.id
    if paper.file_path:
        payload["file_path"] = paper.file_path
    if paper.file_url:
        payload["file_url"] = paper.file_url
    if paper.added_at:
        payload["added_at"] = paper.added_at
    if paper.source_note:
        payload["source_note"] = paper.source_note

    changed_fields, updated = _apply_reanalysis_payload(db, paper, payload)
    db.commit()
    return True, {
        "ok": True,
        "id": paper_id,
        "publish_status": updated.publish_status or "pending_review",
        "analysis_confidence": float(updated.analysis_confidence or 0.0),
        "warnings": ensure_list(updated.analysis_warnings),
        "updated_fields": changed_fields,
        "source_mode": source_mode,
    }


def purge_paper(
    db: Session,
    paper_id: str,
    library_files_dir: Path,
    delete_file: bool = True,
) -> tuple[bool, dict]:
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        return False, {"ok": False, "error": "paper_not_found", "id": paper_id}

    file_deleted = False
    file_kept_reason = ""
    if delete_file:
        local_file = _resolve_local_file_path(paper, library_files_dir)
        if local_file and local_file.exists():
            raw_refs = [str(paper.file_path or "").strip(), str(paper.file_url or "").strip()]
            refs: list[str] = []
            for raw in raw_refs:
                if not raw:
                    continue
                refs.append(raw)
                norm = raw.replace("\\", "/").lstrip("/")
                if norm.startswith("files/"):
                    refs.append(norm)
                    refs.append(f"/{norm}")
                elif "/files/" in norm:
                    tail = norm.split("/files/", 1)[1].lstrip("/")
                    refs.append(f"files/{tail}")
                    refs.append(f"/files/{tail}")
                elif "/" not in norm:
                    refs.append(norm)
                    refs.append(f"files/{norm}")
                    refs.append(f"/files/{norm}")
            refs = sorted(set(x for x in refs if x))
            same_ref_count = 0
            if refs:
                conds = []
                for ref in refs:
                    conds.append(Paper.file_path == ref)
                    conds.append(Paper.file_url == ref)
                same_ref_count = db.query(Paper).filter(Paper.id != paper.id, or_(*conds)).count()
            if same_ref_count == 0:
                try:
                    local_file.unlink(missing_ok=True)
                    file_deleted = True
                except Exception:
                    file_deleted = False
                    file_kept_reason = "file_delete_failed"
            else:
                file_kept_reason = "file_referenced_by_other_papers"
        elif delete_file:
            file_kept_reason = "file_not_found"

    db.query(PaperChunk).filter(PaperChunk.paper_id == paper.id).delete()
    db.query(Source).filter(Source.paper_id == paper.id).update({Source.paper_id: None})
    db.delete(paper)
    db.commit()
    return True, {
        "ok": True,
        "id": paper_id,
        "purged": True,
        "file_deleted": file_deleted,
        "file_kept_reason": file_kept_reason,
    }


def dump_result_to_json(task: IngestTask) -> str:
    return json.dumps(task_to_dict(task), ensure_ascii=False, default=str)
