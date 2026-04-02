from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, engine, get_db
from .models import IngestTask, Paper
from .queue import queue_client
from .schemas import (
    AdminPaperActionOut,
    CategoryListResponse,
    IngestUrlIn,
    PaperListResponse,
    PaperOut,
    PaperUpdateIn,
    SearchResponse,
    TaskOut,
)
from .search import search_papers
from .security import require_admin_token
from .services import (
    create_task,
    list_categories,
    list_papers,
    paper_to_dict,
    set_publish_status,
    task_to_dict,
    update_paper,
)


app = FastAPI(title="Remote Literature API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_event() -> None:
    settings.ensure_dirs()
    Base.metadata.create_all(bind=engine)
    # Backward-compatible online schema patch for existing PostgreSQL instances.
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE papers ADD COLUMN IF NOT EXISTS list_summary_zh TEXT DEFAULT ''"))
        conn.execute(
            text("ALTER TABLE papers ADD COLUMN IF NOT EXISTS publish_status VARCHAR(32) DEFAULT 'published'")
        )
        conn.execute(text("ALTER TABLE papers ADD COLUMN IF NOT EXISTS analysis_confidence DOUBLE PRECISION DEFAULT 1.0"))


ui_dir = (Path(__file__).resolve().parent.parent / "remote-ui").resolve()
if ui_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(ui_dir)), name="assets")


@app.get("/")
def home() -> FileResponse:
    index_path = ui_dir / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="index_not_found")
    return FileResponse(index_path)


@app.get("/admin.html")
def admin_home() -> FileResponse:
    index_path = ui_dir / "admin.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="admin_not_found")
    return FileResponse(index_path)


@app.get("/api/health")
def health(db: Session = Depends(get_db)) -> dict:
    try:
        paper_count = db.query(Paper).count()
    except Exception:
        paper_count = -1
    return {
        "ok": True,
        "paper_count": paper_count,
        "queue_key": settings.queue_key,
        "llm_enabled": settings.llm_enabled,
        "llm_model": settings.llm_model or "",
    }


@app.get("/api/search", response_model=SearchResponse)
def api_search(
    q: str = Query(default="", min_length=0),
    limit: int = Query(default=settings.default_search_limit, ge=1, le=settings.max_search_limit),
    db: Session = Depends(get_db),
) -> SearchResponse:
    result = search_papers(db, q, limit=limit)
    return SearchResponse(**result)


@app.get("/api/categories", response_model=CategoryListResponse)
def api_categories(db: Session = Depends(get_db)) -> CategoryListResponse:
    items = list_categories(db, status="published")
    return CategoryListResponse(ok=True, items=items, total_categories=len(items))


@app.get("/api/papers", response_model=PaperListResponse)
def api_papers(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    category: str = Query(default=""),
    sort: str = Query(default="updated_desc"),
    q: str = Query(default=""),
    db: Session = Depends(get_db),
) -> PaperListResponse:
    payload = list_papers(
        db,
        page=page,
        page_size=page_size,
        category=category,
        sort=sort,
        q=q,
        status="published",
    )
    payload["items"] = [PaperOut(**x) for x in payload["items"]]
    return PaperListResponse(**payload)


@app.get("/api/papers/{paper_id}", response_model=PaperOut)
def api_paper_detail(paper_id: str, db: Session = Depends(get_db)) -> PaperOut:
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=404, detail="paper_not_found")
    if (paper.publish_status or "published") != "published":
        raise HTTPException(status_code=404, detail="paper_not_found")
    return PaperOut(**paper_to_dict(paper))


@app.get("/api/admin/papers", response_model=PaperListResponse)
def api_admin_papers(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    category: str = Query(default=""),
    sort: str = Query(default="updated_desc"),
    q: str = Query(default=""),
    status: str = Query(default="pending_review"),
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> PaperListResponse:
    payload = list_papers(
        db,
        page=page,
        page_size=page_size,
        category=category,
        sort=sort,
        q=q,
        status=status,
    )
    payload["items"] = [PaperOut(**x) for x in payload["items"]]
    return PaperListResponse(**payload)


@app.post("/api/admin/papers/{paper_id}/publish", response_model=AdminPaperActionOut)
def api_admin_publish_paper(
    paper_id: str,
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> AdminPaperActionOut:
    ok, result = set_publish_status(db, paper_id, "published")
    if not ok:
        raise HTTPException(status_code=400, detail=result)
    return AdminPaperActionOut(**result)


@app.post("/api/admin/papers/{paper_id}/reject", response_model=AdminPaperActionOut)
def api_admin_reject_paper(
    paper_id: str,
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> AdminPaperActionOut:
    ok, result = set_publish_status(db, paper_id, "rejected")
    if not ok:
        raise HTTPException(status_code=400, detail=result)
    return AdminPaperActionOut(**result)


@app.post("/api/papers/{paper_id}/update")
def api_paper_update(
    paper_id: str,
    payload: PaperUpdateIn,
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> dict:
    ok, result = update_paper(db, paper_id, payload.updates)
    if not ok:
        raise HTTPException(status_code=400, detail=result)
    return result


@app.post("/api/ingest/upload")
def api_ingest_upload(
    file: UploadFile = File(...),
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".docx", ".txt", ".md", ".html", ".htm", ".zip"}:
        raise HTTPException(status_code=400, detail=f"unsupported_file_type:{suffix}")
    tmp_name = f"{uuid.uuid4().hex}_{Path(file.filename or 'upload.bin').name}"
    tmp_path = settings.upload_tmp_dir / tmp_name
    with tmp_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    task = create_task(
        db,
        task_type="upload_file",
        payload={"file_path": str(tmp_path), "filename": file.filename},
    )
    queue_client.enqueue(task.id)
    return {"ok": True, "task_id": task.id}


@app.post("/api/ingest/url")
def api_ingest_url(
    payload: IngestUrlIn,
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> dict:
    task = create_task(db, task_type="parse_url", payload={"url": str(payload.url)})
    queue_client.enqueue(task.id)
    return {"ok": True, "task_id": task.id}


@app.get("/api/tasks/{task_id}", response_model=TaskOut)
def api_task(task_id: str, _: None = Depends(require_admin_token), db: Session = Depends(get_db)) -> TaskOut:
    task = db.query(IngestTask).filter(IngestTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="task_not_found")
    return TaskOut(**task_to_dict(task))


@app.get("/api/tasks", response_model=list[TaskOut])
def api_tasks(
    limit: int = Query(default=20, ge=1, le=100),
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
) -> list[TaskOut]:
    tasks = db.query(IngestTask).order_by(IngestTask.created_at.desc()).limit(limit).all()
    return [TaskOut(**task_to_dict(task)) for task in tasks]
