"""Knowledge-base service: upload validation, indexing, re-indexing, deletion and semantic search."""

import asyncio
import hashlib
import logging
import re
import threading
import uuid
from pathlib import Path
from urllib.parse import urlparse

from app.assistant.kb import KbPassage, KbResult
from app.core.config import Settings
from app.kb.chunking import chunk_document
from app.kb.embeddings import Embedder, EmbeddingError, make_embedder
from app.kb.extract import extract, file_kind, safe_filename
from app.kb.lexical import LexicalIndex
from app.kb.meta import table_meta, text_meta
from app.kb import research
from app.kb.tables import DatasetStore, QuerySpec
from app.kb.registry import DocRecord, DocumentRegistry, now_iso
from app.kb.store import ChromaStore, Hit
from app.kb.types import CATEGORIES, KbError

logger = logging.getLogger("app.kb")


def _clip(value: str | None, limit: int) -> str | None:
    value = (value or "").strip()
    return value[:limit] or None


_GENERIC = {"document", "doc", "title", "paper", "file", "report", "pdf", "the", "an", "of", "about", "from", "knowledge",
            "base", "kb", "this", "that"}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def matches_document(needle: str, title: str, filename: str) -> bool:
    """True if `needle` names the document. Accepts an exact substring, or a name whose meaningful words (ignoring generic
    ones like "document" or "title") all appear in the title or file name, so "the CPCB document" finds "CPCB: How is AQI
    calculated"."""
    needle = needle.strip().lower()
    if not needle:
        return False
    if needle in title.lower() or needle in filename.lower():
        return True
    wanted = {w for w in _words(needle) if w not in _GENERIC and len(w) >= 2}
    return bool(wanted) and wanted <= (_words(title) | _words(filename))


def _location(h: Hit) -> str:
    if h.page_start is not None:
        return f"p. {h.page_start}" if h.page_end in (None, h.page_start) else f"pp. {h.page_start}-{h.page_end}"
    return f"section '{h.section}'" if h.section else ""


class KnowledgeBaseService:
    def __init__(self, settings: Settings, embedder: Embedder | None = None, registry: DocumentRegistry | None = None,
                 store: ChromaStore | None = None):
        self._s = settings
        root = Path(settings.kb_dir)
        self._files = root / "files"
        self._files.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder or make_embedder(settings)
        self.registry = registry or DocumentRegistry(root / "registry.sqlite")
        self.store = store or ChromaStore(root / "chroma", self.embedder.model)
        self.data = DatasetStore(root / "tables.sqlite")  # CSV tables (queryable) and research metadata per document
        self._lex: LexicalIndex | None = None  # exact-word index, rebuilt lazily after any write
        self._chunk_meta: dict[str, Hit] = {}
        self._lex_lock = threading.Lock()
        interrupted = self.registry.mark_interrupted()
        if interrupted:
            logger.warning("Marked %d interrupted indexing job(s) as failed", interrupted)

    # ---- assistant protocol ---------------------------------------------------------------------
    @property
    def ready(self) -> bool:
        return any(d.status == "ready" and d.embedding_model == self.embedder.model for d in self.registry.list())

    @property
    def note(self) -> str:
        docs = self.registry.list()
        if not docs:
            return "The knowledge base has no documents yet. Upload some on the Knowledge Base page."
        ready = sum(d.status == "ready" for d in docs)
        return f"{ready} of {len(docs)} document(s) are indexed and searchable."

    # ---- upload ---------------------------------------------------------------------------------
    async def add_document(self, filename: str, data: bytes, category: str, title: str | None = None,
                           publisher: str | None = None, licence: str | None = None, source_url: str | None = None) -> DocRecord:
        """Validate and store an upload. Raises KbError for anything invalid; indexing then runs via `index()`."""
        if category not in CATEGORIES:
            raise KbError("invalid_category", f"Category must be one of: {', '.join(CATEGORIES)}.", 422)
        name = safe_filename(filename)
        kind = file_kind(name)
        url = _clip(source_url, 500)
        if url and urlparse(url).scheme not in ("http", "https"):
            raise KbError("invalid_url", "The source link must start with http:// or https://.", 422)

        # Extraction and chunking run here so a bad file is rejected immediately and never stored.
        extracted = await self._run_extract(name, data)
        chunk_document(extracted, self._s.kb_chunk_chars, self._s.kb_chunk_overlap, self._s.kb_max_chunks_per_doc)

        digest = hashlib.sha256(data).hexdigest()
        existing = self.registry.by_hash(digest)
        if existing:
            err = KbError("duplicate", f"This exact file is already in the knowledge base as '{existing.title}'.", 409)
            err.existing_id = existing.id  # type: ignore[attr-defined]
            raise err

        doc_id = uuid.uuid4().hex
        ext = {"pdf": "pdf", "txt": "txt", "md": "md", "csv": "csv"}[kind]
        await asyncio.to_thread((self._files / f"{doc_id}.{ext}").write_bytes, data)
        rec = DocRecord(
            id=doc_id, filename=name, title=_clip(title, 200) or Path(name).stem[:200], category=category,
            publisher=_clip(publisher, 120), licence=_clip(licence, 120), source_url=url, kind=kind, content_hash=digest,
            size_bytes=len(data), pages=extracted.page_count, chunk_count=0, status="indexing", error=None,
            notes="\n".join(extracted.warnings) or None, embedding_model=None, created_at=now_iso(), indexed_at=None,
        )
        self.registry.insert(rec)
        return rec

    async def _run_extract(self, name: str, data: bytes):
        try:
            return await asyncio.wait_for(asyncio.to_thread(extract, name, data, self._s), self._s.kb_extract_timeout_s)
        except asyncio.TimeoutError:
            raise KbError("extraction_timeout", "Reading the file took too long; it may be too complex.", 422) from None

    def _path(self, rec: DocRecord) -> Path:
        return self._files / f"{rec.id}.{rec.kind}"

    # ---- indexing -------------------------------------------------------------------------------
    async def index(self, doc_id: str) -> None:
        """Extract, chunk, embed and store one document. Failures are recorded on the document, never raised."""
        rec = self.registry.get(doc_id)
        if rec is None:
            return
        self.registry.update(doc_id, status="indexing", error=None)
        try:
            data = await asyncio.to_thread(self._path(rec).read_bytes)
            extracted = await self._run_extract(rec.filename, data)
            chunks = chunk_document(extracted, self._s.kb_chunk_chars, self._s.kb_chunk_overlap, self._s.kb_max_chunks_per_doc)
            vectors = await self.embedder.embed_documents([c.text for c in chunks])
            if self.registry.get(doc_id) is None:  # deleted while we were embedding
                return
            await asyncio.to_thread(self.store.replace_document, doc_id, chunks, vectors)
            if self.registry.get(doc_id) is None:  # deleted while we were writing: leave nothing behind
                await asyncio.to_thread(self.store.delete_document, doc_id)
                return
            await asyncio.to_thread(self._record_research_data, doc_id, extracted)
            self._lex = None
            self.registry.update(
                doc_id, status="ready", error=None, chunk_count=len(chunks), pages=extracted.page_count,
                notes="\n".join(extracted.warnings) or None, embedding_model=self.embedder.model, indexed_at=now_iso(),
            )
        except (KbError, EmbeddingError) as exc:
            await self._fail(doc_id, exc.message)
        except FileNotFoundError:
            await self._fail(doc_id, "The stored file is missing; delete this document and upload it again.")
        except Exception:
            logger.exception("Indexing %s failed", doc_id)
            await self._fail(doc_id, "Indexing failed unexpectedly. The server log has details.")

    def _record_research_data(self, doc_id: str, extracted) -> None:
        """Load a CSV as a real table and store the document's research metadata (pollutants, places, period)."""
        sample = "\n".join(p.text for p in extracted.pages)[:60_000]
        if extracted.table is not None:
            profile = self.data.load(doc_id, extracted.table, self._s.kb_dataset_timezone)
            extracted.warnings.extend(w for w in profile.get("warnings", []) if w not in extracted.warnings)
            self.data.set_meta(doc_id, table_meta(profile, sample))
        else:
            self.data.drop(doc_id)
            self.data.set_meta(doc_id, {"kind": "document", **text_meta(sample)})

    async def _fail(self, doc_id: str, message: str) -> None:
        try:
            await asyncio.to_thread(self.store.delete_document, doc_id)  # no half-indexed documents
            await asyncio.to_thread(self.data.drop, doc_id)
        except Exception:
            logger.exception("Could not clean up chunks of %s", doc_id)
        self._lex = None
        if self.registry.get(doc_id):
            self.registry.update(doc_id, status="failed", error=message, chunk_count=0)

    def start_reindex(self, doc_id: str) -> DocRecord:
        rec = self.registry.get(doc_id)
        if rec is None:
            raise KbError("not_found", "Document not found.", 404)
        if rec.status == "indexing":
            raise KbError("already_indexing", "This document is already being indexed.", 409)
        self.registry.update(doc_id, status="indexing", error=None)
        return self.registry.get(doc_id)  # type: ignore[return-value]

    # ---- delete ---------------------------------------------------------------------------------
    async def delete(self, doc_id: str) -> None:
        rec = self.registry.get(doc_id)
        if rec is None:
            raise KbError("not_found", "Document not found.", 404)
        await asyncio.to_thread(self.store.delete_document, doc_id)
        await asyncio.to_thread(self.data.drop, doc_id)
        self._lex = None
        self.registry.delete(doc_id)
        try:
            self._path(rec).unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove file for %s", doc_id)
        # An indexing job still running for this id notices the missing row and cleans up after itself.

    # ---- read -----------------------------------------------------------------------------------
    def list_documents(self) -> list[DocRecord]:
        return self.registry.list()

    def get(self, doc_id: str) -> DocRecord:
        rec = self.registry.get(doc_id)
        if rec is None:
            raise KbError("not_found", "Document not found.", 404)
        return rec

    def needs_reindex(self, rec: DocRecord) -> bool:
        return rec.status == "ready" and rec.embedding_model != self.embedder.model

    async def chunks(self, doc_id: str, limit: int = 20) -> list[Hit]:
        self.get(doc_id)
        return await asyncio.to_thread(self.store.chunks_of, doc_id, limit)

    # ---- exact-word retrieval and fusion ----------------------------------------------------------
    def _lexical_index(self) -> LexicalIndex:
        with self._lex_lock:
            if self._lex is None:
                chunks = self.store.all_chunks()
                keys = [f"{c.doc_id}:{c.chunk_index}" for c in chunks]
                self._chunk_meta = dict(zip(keys, chunks))
                self._lex = LexicalIndex([(key, c.doc_id, c.text) for key, c in zip(keys, chunks)])
            return self._lex

    async def _fuse(self, query: str, vector: list[float], hits: list[Hit], by_id: dict, threshold: float, k: int) -> list[Hit]:
        """Combine the embedding ranking with an exact-word (BM25) ranking.

        A passage is admitted if its similarity clears the threshold, OR it contains most of the words asked for (names,
        station ids, numbers) and its similarity is within `kb_lexical_relax` of the threshold. Ordering is by reciprocal-rank
        fusion; the displayed score stays the cosine similarity."""
        sem = [h for h in hits if h.doc_id in by_id]
        sem_key = {f"{h.doc_id}:{h.chunk_index}": h for h in sem}
        rank_sem = {key: i for i, key in enumerate(sem_key, 1)}
        try:
            index = await asyncio.to_thread(self._lexical_index)
            lex = await asyncio.to_thread(index.search, query, set(by_id), max(k * 5, 20))
        except Exception:
            logger.exception("Exact-word search failed; using the embedding ranking only")
            lex = []
        lex_by = {h.key: h for h in lex}
        rank_lex = {h.key: i for i, h in enumerate(lex, 1)}
        floor = threshold - self._s.kb_lexical_relax

        def words_match(key: str) -> bool:
            h = lex_by.get(key)
            return h is not None and h.coverage >= 0.6 and h.matched >= min(2, h.total)

        pool: dict[str, Hit] = {}
        for key, h in sem_key.items():
            if h.score >= threshold or (words_match(key) and h.score >= floor):
                pool[key] = h
        extra = [h.key for h in lex if h.key not in sem_key and words_match(h.key)]
        if extra:
            cosine = await asyncio.to_thread(self.store.cosines, vector, extra)
            for key in extra:
                c = cosine.get(key)
                base = self._chunk_meta.get(key)
                if c is not None and base is not None and c >= floor and base.doc_id in by_id:
                    pool[key] = Hit(base.doc_id, base.chunk_index, base.page_start, base.page_end, base.section, base.text, c)

        def fused(key: str) -> float:
            return 1 / (60 + rank_sem.get(key, 10_000)) + 1 / (60 + rank_lex.get(key, 10_000))

        return [pool[key] for key in sorted(pool, key=lambda x: -fused(x))][:k]

    # ---- tables and research ----------------------------------------------------------------------
    def document_meta(self, doc_id: str) -> dict | None:
        return self.data.get_meta(doc_id)

    def dataset_profile(self, doc_id: str) -> dict:
        self.get(doc_id)
        profile = self.data.profile(doc_id)
        if profile is None:
            raise KbError("not_a_dataset", "This document is not an indexed table.", 422)
        return profile

    def datasets(self) -> list[dict]:
        """Every indexed table with enough detail for a caller (or the assistant) to ask a valid question of it."""
        out = []
        for d in self.registry.list():
            if d.kind != "csv" or d.status != "ready":
                continue
            p = self.data.profile(d.id)
            if p is None:
                continue
            out.append({
                "document_id": d.id, "title": d.title, "rows": p["rows"], "time_column": p["time_column"],
                "time_start": p["time_start"], "time_end": p["time_end"], "resolution": p["resolution"],
                "station_column": p["station_column"], "zone_column": p["zone_column"], "pollutant_columns": p["pollutant_columns"],
                "columns": [{"name": c["name"], "type": c["type"], **({"examples": c["examples"][:5]} if c.get("examples") else {})}
                            for c in p["columns"]],
            })
        return out

    def query_dataset(self, doc_id: str, spec: QuerySpec) -> dict:
        rec = self.get(doc_id)
        if rec.status != "ready":
            raise KbError("not_ready", "This document is not indexed yet.", 409)
        result = self.data.query(doc_id, spec)
        return {"document_id": rec.id, "document": rec.title, "file": rec.filename, **result}

    async def relationship(self, doc_id: str, column: str, pollutant: str, zone: str | None = None, max_lag: int | None = None,
                           known_in_advance: bool = False) -> dict:
        rec = self.get(doc_id)
        if rec.status != "ready":
            raise KbError("not_ready", "This document is not indexed yet.", 409)
        history = Path(self._s.ml_history_db or Path(self._s.data_dir) / "history.sqlite")
        result = await asyncio.to_thread(research.relationship, self.data, doc_id, column, pollutant, history, zone=zone, max_lag=max_lag,
                                         known_in_advance=known_in_advance)
        return {"document": rec.title, **result}

    # ---- search ---------------------------------------------------------------------------------
    async def search(self, query: str, top_k: int | None = None, document: str | None = None,
                     categories: list[str] | None = None, min_score: float | None = None) -> KbResult:
        s = self._s
        k = max(1, min(top_k or s.kb_top_k_default, s.kb_top_k_max))
        threshold = s.kb_min_score if min_score is None else min_score
        docs = self.registry.list()
        if not docs:
            return KbResult("empty", "The knowledge base has no documents.")
        searchable = [d for d in docs if d.status == "ready" and d.embedding_model == self.embedder.model]
        if document:
            matched = [d for d in searchable if matches_document(document, d.title, d.filename)]
            if not matched:
                return KbResult("document_not_found", f"No searchable document matches '{document[:80]}'.",
                                available_documents=[d.title for d in searchable][:10])
            searchable = matched
            if min_score is None:
                threshold = max(0.0, threshold - s.kb_named_document_relax)
        if categories:
            searchable = [d for d in searchable if d.category in categories]
        if not searchable:
            return KbResult("empty", "No indexed documents are available to search "
                                     "(documents may still be indexing, failed, or need re-indexing).")
        try:
            vector = await self.embedder.embed_query(query)
        except EmbeddingError as exc:
            return KbResult("unavailable", exc.message)
        by_id = {d.id: d for d in searchable}
        hits = await asyncio.to_thread(self.store.query, vector, max(k * 3, k), list(by_id))
        best = max((h.score for h in hits), default=None)
        relevant = await self._fuse(query, vector, hits, by_id, threshold, k)
        if not relevant:
            return KbResult(
                "no_relevant_passages",
                f"No passage was relevant enough (best similarity {best:.2f}, required {threshold:.2f})." if best is not None
                else "No passages were found.",
                best_score=best,
            )
        passages = []
        for h in relevant:
            d = by_id[h.doc_id]
            passages.append(KbPassage(
                document=d.title, publisher=d.publisher or "", licence=d.licence or "", text=h.text, location=_location(h),
                url=d.source_url, category=d.category, category_label=CATEGORIES[d.category], score=h.score, document_id=d.id,
            ))
        return KbResult("ok", passages=passages, best_score=best)
