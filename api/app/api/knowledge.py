from functools import lru_cache

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile

from app.core.config import Settings, get_settings
from app.kb.embeddings import EmbeddingError
from app.kb.extract import ALLOWED
from app.kb.registry import DocRecord
from app.kb.service import KnowledgeBaseService
from app.kb.tables import QuerySpec
from app.kb.types import CATEGORIES, KbError
from app.schemas.kb import (
    ChunkOut, DocumentList, DocumentOut, EmbeddingStatus, KbLimits, KbStatus, PassageOut, SearchOut,
)

router = APIRouter(prefix="/kb", tags=["knowledge base"])


@lru_cache
def get_kb_service() -> KnowledgeBaseService:
    # One service per process: it owns the vector store and the document registry.
    return KnowledgeBaseService(get_settings())


def _http(exc: KbError) -> HTTPException:
    detail: dict = {"code": exc.code, "message": exc.message}
    if hasattr(exc, "existing_id"):
        detail["details"] = {"existing_document_id": exc.existing_id}
    return HTTPException(exc.status, detail)


def _limits(s: Settings) -> KbLimits:
    return KbLimits(max_upload_mb=s.kb_max_upload_mb, extensions=sorted(ALLOWED), categories=CATEGORIES, max_pdf_pages=s.kb_max_pdf_pages)


def _out(rec: DocRecord, svc: KnowledgeBaseService) -> DocumentOut:
    return DocumentOut(
        id=rec.id, filename=rec.filename, title=rec.title, category=rec.category, category_label=CATEGORIES.get(rec.category, rec.category),
        publisher=rec.publisher, licence=rec.licence, source_url=rec.source_url, kind=rec.kind,  # type: ignore[arg-type]
        size_bytes=rec.size_bytes, pages=rec.pages, chunk_count=rec.chunk_count, status=rec.status,  # type: ignore[arg-type]
        error=rec.error, notes=[n for n in (rec.notes or "").split("\n") if n], embedding_model=rec.embedding_model,
        needs_reindex=svc.needs_reindex(rec), content_hash=rec.content_hash, created_at=rec.created_at,  # type: ignore[arg-type]
        indexed_at=rec.indexed_at,  # type: ignore[arg-type]
        meta=svc.document_meta(rec.id),
    )


async def reject_oversized_body(request: Request, settings: Settings = Depends(get_settings)) -> None:
    """Runs before the upload body is parsed, so an obviously oversized request is refused without reading it."""
    limit = settings.kb_max_upload_mb * 1024 * 1024
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit + 64 * 1024:  # allow for multipart framing
        raise _http(KbError("file_too_large", f"The upload is larger than the {settings.kb_max_upload_mb} MB limit.", 413))


@router.get("/status", response_model=KbStatus, summary="Embedding availability and document counts")
async def status(svc: KnowledgeBaseService = Depends(get_kb_service), settings: Settings = Depends(get_settings)):
    try:
        await svc.embedder.check()
        emb = EmbeddingStatus(available=True, provider=settings.embedding_provider, model=svc.embedder.model, code=None, message=None)
    except EmbeddingError as exc:
        emb = EmbeddingStatus(available=False, provider=settings.embedding_provider, model=svc.embedder.model, code=exc.code, message=exc.message)
    docs = svc.list_documents()
    count = lambda st: sum(d.status == st for d in docs)  # noqa: E731
    return KbStatus(embedding=emb, documents_total=len(docs), documents_ready=count("ready"), documents_failed=count("failed"),
                    documents_indexing=count("indexing"), min_score=settings.kb_min_score, limits=_limits(settings))


@router.get("/documents", response_model=DocumentList, summary="All documents and their indexing status")
async def list_documents(svc: KnowledgeBaseService = Depends(get_kb_service), settings: Settings = Depends(get_settings)):
    return DocumentList(documents=[_out(d, svc) for d in svc.list_documents()], limits=_limits(settings))


@router.post("/documents", response_model=DocumentOut, status_code=202, summary="Upload a document (indexing runs in the background)",
             dependencies=[Depends(reject_oversized_body)])
async def upload(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    category: str = Form(...),
    title: str | None = Form(None),
    publisher: str | None = Form(None),
    licence: str | None = Form(None),
    source_url: str | None = Form(None),
    svc: KnowledgeBaseService = Depends(get_kb_service),
    settings: Settings = Depends(get_settings),
):
    limit = settings.kb_max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)  # never buffer more than one byte over the limit
    try:
        rec = await svc.add_document(file.filename or "", data, category, title, publisher, licence, source_url)
    except KbError as exc:
        raise _http(exc) from exc
    background.add_task(svc.index, rec.id)
    return _out(rec, svc)


@router.get("/documents/{doc_id}", response_model=DocumentOut)
async def get_document(doc_id: str, svc: KnowledgeBaseService = Depends(get_kb_service)):
    try:
        return _out(svc.get(doc_id), svc)
    except KbError as exc:
        raise _http(exc) from exc


@router.get("/datasets", summary="Indexed tables with their columns, period and time resolution")
async def datasets(svc: KnowledgeBaseService = Depends(get_kb_service)):
    return {"datasets": svc.datasets()}


@router.get("/documents/{doc_id}/profile", summary="Typed columns, ranges, period and assumptions of an uploaded table")
async def dataset_profile(doc_id: str, svc: KnowledgeBaseService = Depends(get_kb_service)):
    try:
        return svc.dataset_profile(doc_id)
    except KbError as exc:
        raise _http(exc) from exc


@router.post("/documents/{doc_id}/query", summary="Filter, group and aggregate an uploaded table (validated specification, no SQL)")
async def dataset_query(doc_id: str, spec: QuerySpec, svc: KnowledgeBaseService = Depends(get_kb_service)):
    try:
        return svc.query_dataset(doc_id, spec)
    except KbError as exc:
        raise _http(exc) from exc


@router.get("/documents/{doc_id}/relationship", summary="Does a column of an uploaded table relate to measured pollution?")
async def dataset_relationship(
    doc_id: str,
    column: str = Query(min_length=1, max_length=80),
    pollutant: str = Query("pm25"),
    zone: str | None = Query(None, max_length=40),
    max_lag: int | None = Query(None, ge=0, le=24),
    known_in_advance: bool = Query(False, description="True if the series value for the target time is known beforehand (a forecast or a calendar)."),
    svc: KnowledgeBaseService = Depends(get_kb_service),
):
    try:
        return await svc.relationship(doc_id, column, pollutant, zone, max_lag, known_in_advance)
    except KbError as exc:
        raise _http(exc) from exc


@router.get("/documents/{doc_id}/chunks", response_model=list[ChunkOut], summary="The first indexed passages of a document")
async def document_chunks(doc_id: str, limit: int = Query(20, ge=1, le=100), svc: KnowledgeBaseService = Depends(get_kb_service)):
    try:
        hits = await svc.chunks(doc_id, limit)
    except KbError as exc:
        raise _http(exc) from exc
    return [ChunkOut(index=h.chunk_index, page_start=h.page_start, page_end=h.page_end, section=h.section, text=h.text) for h in hits]


@router.post("/documents/{doc_id}/reindex", response_model=DocumentOut, status_code=202, summary="Re-extract, re-chunk and re-embed a document")
async def reindex(doc_id: str, background: BackgroundTasks, svc: KnowledgeBaseService = Depends(get_kb_service)):
    try:
        rec = svc.start_reindex(doc_id)
    except KbError as exc:
        raise _http(exc) from exc
    background.add_task(svc.index, rec.id)
    return _out(rec, svc)


@router.delete("/documents/{doc_id}", status_code=204, summary="Delete a document, its file and all its indexed passages")
async def delete_document(doc_id: str, svc: KnowledgeBaseService = Depends(get_kb_service)):
    try:
        await svc.delete(doc_id)
    except KbError as exc:
        raise _http(exc) from exc
    return Response(status_code=204)


@router.get("/search", response_model=SearchOut, summary="Semantic search over indexed documents")
async def search(
    q: str = Query(min_length=2, max_length=300),
    top_k: int = Query(None, ge=1, le=50),
    category: list[str] = Query(default=[]),
    document: str | None = Query(None, max_length=120),
    svc: KnowledgeBaseService = Depends(get_kb_service),
    settings: Settings = Depends(get_settings),
):
    bad = [c for c in category if c not in CATEGORIES]
    if bad:
        raise HTTPException(422, {"code": "invalid_category", "message": f"Unknown category: {', '.join(bad)}."})
    res = await svc.search(q, top_k, document=document, categories=category or None)
    return SearchOut(
        status=res.status, reason=res.reason, best_score=res.best_score, min_score=settings.kb_min_score,  # type: ignore[arg-type]
        passages=[PassageOut(document_id=p.document_id or "", title=p.document, category=p.category, category_label=p.category_label,
                             publisher=p.publisher or None, licence=p.licence or None, source_url=p.url, location=p.location,
                             text=p.text, score=p.score) for p in res.passages],
        available_documents=res.available_documents,
    )
