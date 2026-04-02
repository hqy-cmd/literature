from __future__ import annotations

import os
from pathlib import Path


class Settings:
    def __init__(self) -> None:
        base_dir = Path(__file__).resolve().parent.parent
        self.base_dir = base_dir
        self.database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://literature:literature@localhost:5432/literature",
        )
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.llm_enabled = os.getenv("LLM_ENABLED", "false").lower() == "true"
        self.llm_base_url = os.getenv("LLM_BASE_URL", "").strip()
        self.llm_api_key = os.getenv("LLM_API_KEY", "").strip()
        self.llm_model = os.getenv("LLM_MODEL", "").strip()
        self.api_admin_token = os.getenv("API_ADMIN_TOKEN", "").strip()

        self.storage_root = Path(os.getenv("STORAGE_ROOT", str(base_dir / "remote-data")))
        self.library_files_dir = Path(
            os.getenv("LIBRARY_FILES_DIR", str(base_dir / "literature-library" / "files"))
        )
        self.upload_tmp_dir = Path(
            os.getenv("UPLOAD_TMP_DIR", str(self.storage_root / "uploads"))
        )
        self.queue_key = os.getenv("REDIS_QUEUE_KEY", "literature:ingest:queue")
        self.default_search_limit = int(os.getenv("DEFAULT_SEARCH_LIMIT", "20"))
        self.max_search_limit = int(os.getenv("MAX_SEARCH_LIMIT", "50"))

    def ensure_dirs(self) -> None:
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.library_files_dir.mkdir(parents=True, exist_ok=True)
        self.upload_tmp_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()

