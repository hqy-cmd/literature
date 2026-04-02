from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class PaperOut(BaseModel):
    id: str
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: str = ""
    category: str = ""
    collections: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    abstract_original: str = ""
    abstract_summary_zh: str = ""
    filename: str = ""
    source_note: str = ""
    added_at: str = ""
    file_path: str = ""
    file_url: str = ""
    manual_edit: bool = False
    locked_fields: list[str] = Field(default_factory=list)
    search_score: float | None = None
    hit_reasons: list[str] = Field(default_factory=list)
    matched_fields: list[str] = Field(default_factory=list)

    class Config:
        from_attributes = True


class PaperUpdateIn(BaseModel):
    updates: dict[str, Any]


class SearchResponse(BaseModel):
    ok: bool = True
    query: str
    normalized_query: str
    rewritten_terms: list[str]
    summary: str
    results: list[PaperOut]


class PaperListResponse(BaseModel):
    ok: bool = True
    items: list[PaperOut]
    total: int
    page: int
    page_size: int
    total_pages: int
    category: str = ""
    sort: str = "updated_desc"
    q: str = ""


class CategoryItem(BaseModel):
    name: str
    count: int


class CategoryListResponse(BaseModel):
    ok: bool = True
    items: list[CategoryItem]
    total_categories: int


class IngestUrlIn(BaseModel):
    url: HttpUrl


class TaskOut(BaseModel):
    id: str
    task_type: str
    status: str
    progress: int
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    error_message: str = ""
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    class Config:
        from_attributes = True
