from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class DocumentOut(BaseModel):
    id: str
    filename: str
    title: str
    category: str
    category_label: str
    publisher: str | None
    licence: str | None
    source_url: str | None
    kind: Literal["pdf", "txt", "md", "csv"]
    size_bytes: int
    pages: int | None
    chunk_count: int
    status: Literal["indexing", "ready", "failed"]
    error: str | None
    notes: list[str]
    embedding_model: str | None
    # True when it was indexed with a different embedding model than the one now configured.
    needs_reindex: bool
    content_hash: str
    created_at: datetime
    indexed_at: datetime | None
    # Research tags: pollutants, places, topics mentioned; for tables also rows, columns, period and resolution.
    meta: dict | None = None


class KbLimits(BaseModel):
    max_upload_mb: int
    extensions: list[str]
    categories: dict[str, str]
    max_pdf_pages: int


class DocumentList(BaseModel):
    documents: list[DocumentOut]
    limits: KbLimits


class EmbeddingStatus(BaseModel):
    available: bool
    provider: str
    model: str
    code: str | None
    message: str | None


class KbStatus(BaseModel):
    embedding: EmbeddingStatus
    documents_total: int
    documents_ready: int
    documents_failed: int
    documents_indexing: int
    min_score: float
    limits: KbLimits


class PassageOut(BaseModel):
    document_id: str
    title: str
    category: str
    category_label: str
    publisher: str | None
    licence: str | None
    source_url: str | None
    location: str
    text: str
    score: float


class SearchOut(BaseModel):
    status: Literal["ok", "no_relevant_passages", "empty", "document_not_found", "unavailable"]
    reason: str | None
    best_score: float | None
    min_score: float
    passages: list[PassageOut]
    available_documents: list[str]


class ChunkOut(BaseModel):
    index: int
    page_start: int | None
    page_end: int | None
    section: str | None
    text: str
