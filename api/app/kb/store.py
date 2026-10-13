"""Chroma vector store. One collection per embedding model, so vectors from different models (different dimensions and
meanings) are never mixed; changing the model means re-indexing, which the registry makes visible."""

import re
from dataclasses import dataclass
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.kb.types import Chunk

PREFIX = "kb_"


def collection_name(model: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-._")[:80] or "model"
    return f"{PREFIX}{slug}"


@dataclass
class Hit:
    doc_id: str
    chunk_index: int
    page_start: int | None
    page_end: int | None
    section: str | None
    text: str
    score: float  # cosine similarity, 1.0 = identical direction


class ChromaStore:
    def __init__(self, path: Path | str, embedding_model: str):
        # Telemetry off: nothing leaves the machine.
        self._client = chromadb.PersistentClient(path=str(path), settings=ChromaSettings(anonymized_telemetry=False))
        self.model = embedding_model
        self.name = collection_name(embedding_model)
        self._col = self._client.get_or_create_collection(self.name, metadata={"hnsw:space": "cosine"})

    # ---- writes ---------------------------------------------------------------------------------
    def replace_document(self, doc_id: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        """Remove any existing chunks of this document (in every model's collection), then add the new ones."""
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must match")
        self.delete_document(doc_id)
        metas = []
        for c in chunks:
            m: dict = {"doc_id": doc_id, "chunk_index": c.index}
            if c.page_start is not None:
                m["page_start"], m["page_end"] = c.page_start, c.page_end if c.page_end is not None else c.page_start
            if c.section:
                m["section"] = c.section
            metas.append(m)
        step = 500  # stay well under Chroma's per-call batch limit
        for i in range(0, len(chunks), step):
            self._col.add(
                ids=[f"{doc_id}:{c.index}" for c in chunks[i:i + step]],
                embeddings=vectors[i:i + step],
                documents=[c.text for c in chunks[i:i + step]],
                metadatas=metas[i:i + step],
            )

    def delete_document(self, doc_id: str) -> None:
        """Delete from all knowledge-base collections, so a model switch cannot leave orphaned chunks behind."""
        for col in self._client.list_collections():
            name = col if isinstance(col, str) else col.name
            if name.startswith(PREFIX):
                self._client.get_collection(name).delete(where={"doc_id": doc_id})

    # ---- reads ----------------------------------------------------------------------------------
    def query(self, vector: list[float], n: int, doc_ids: list[str]) -> list[Hit]:
        if not doc_ids or self._col.count() == 0:
            return []
        res = self._col.query(
            query_embeddings=[vector], n_results=min(n, self._col.count()),
            where={"doc_id": {"$in": doc_ids}}, include=["documents", "metadatas", "distances"],
        )
        hits = []
        for text, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
            hits.append(Hit(
                doc_id=meta["doc_id"], chunk_index=int(meta.get("chunk_index", 0)), page_start=meta.get("page_start"),
                page_end=meta.get("page_end"), section=meta.get("section"), text=text, score=round(1.0 - float(dist), 4),
            ))
        return hits

    def chunks_of(self, doc_id: str, limit: int = 20) -> list[Hit]:
        res = self._col.get(where={"doc_id": doc_id}, include=["documents", "metadatas"])
        rows = sorted(zip(res["documents"], res["metadatas"]), key=lambda x: int(x[1].get("chunk_index", 0)))[:limit]
        return [Hit(doc_id, int(m.get("chunk_index", 0)), m.get("page_start"), m.get("page_end"), m.get("section"), t, 0.0) for t, m in rows]

    def all_chunks(self) -> list[Hit]:
        """Every chunk (text and position) for the exact-word index. Scores are 0.0; the caller computes what it needs."""
        res = self._col.get(include=["documents", "metadatas"])
        out = []
        for text, m in zip(res["documents"], res["metadatas"]):
            out.append(Hit(m["doc_id"], int(m.get("chunk_index", 0)), m.get("page_start"), m.get("page_end"), m.get("section"), text, 0.0))
        return out

    def cosines(self, vector: list[float], chunk_ids: list[str]) -> dict[str, float]:
        """Cosine similarity of the query to specific chunks (ids look like 'docid:index')."""
        if not chunk_ids:
            return {}
        res = self._col.get(ids=chunk_ids, include=["embeddings"])
        qn = sum(x * x for x in vector) ** 0.5 or 1.0
        out: dict[str, float] = {}
        for cid, emb in zip(res["ids"], res["embeddings"]):
            en = sum(float(x) * float(x) for x in emb) ** 0.5 or 1.0
            out[cid] = round(sum(float(a) * b for a, b in zip(emb, vector)) / (en * qn), 4)
        return out

    def count_chunks(self, doc_id: str) -> int:
        return len(self._col.get(where={"doc_id": doc_id}, include=[])["ids"])
