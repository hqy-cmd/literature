from __future__ import annotations

import time
import traceback

from .config import settings
from .database import Base, SessionLocal, engine
from .models import IngestTask
from .queue import queue_client
from .services import (
    mark_task_failed,
    mark_task_running,
    mark_task_success,
    process_upload_file_task,
    process_url_task,
)


def process_one(task_id: str) -> None:
    db = SessionLocal()
    try:
        task = db.query(IngestTask).filter(IngestTask.id == task_id).first()
        if not task:
            return
        mark_task_running(db, task, "任务处理中")
        if task.task_type == "upload_file":
            result = process_upload_file_task(db, task, settings.library_files_dir)
        elif task.task_type == "parse_url":
            result = process_url_task(db, task)
        else:
            raise RuntimeError(f"未知任务类型: {task.task_type}")
        mark_task_success(db, task, result)
    except Exception as exc:
        tb = traceback.format_exc(limit=3)
        try:
            task = db.query(IngestTask).filter(IngestTask.id == task_id).first()
            if task:
                mark_task_failed(db, task, f"{exc}\n{tb}")
        except Exception:
            pass
    finally:
        db.close()


def main() -> None:
    settings.ensure_dirs()
    Base.metadata.create_all(bind=engine)
    while True:
        task_id = queue_client.dequeue(timeout=10)
        if not task_id:
            time.sleep(0.2)
            continue
        process_one(task_id)


if __name__ == "__main__":
    main()

