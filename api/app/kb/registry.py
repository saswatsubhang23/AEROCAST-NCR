"""Document registry: one row per uploaded document (status, errors, content hash, provenance).

SQLite from the standard library keeps this a single local file with no extra infrastructure. It sits behind this small
class so it can move to PostgreSQL later without changing callers. Timestamps are UTC ISO strings.
"""

import sqlite3
import threading
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
create table if not exists documents (
    id text primary key,
    filename text not null,
    title text not null,
    category text not null,
    publisher text,
    licence text,
    source_url text,
    kind text not null,
    content_hash text not null unique,
    size_bytes integer not null,
    pages integer,
    chunk_count integer not null default 0,
    status text not null,
    error text,
    notes text,
    embedding_model text,
    created_at text not null,
    indexed_at text
)
"""


@dataclass
class DocRecord:
    id: str
    filename: str
    title: str
    category: str
    publisher: str | None
    licence: str | None
    source_url: str | None
    kind: str
    content_hash: str
    size_bytes: int
    pages: int | None
    chunk_count: int
    status: str
    error: str | None
    notes: str | None
    embedding_model: str | None
    created_at: str
    indexed_at: str | None

    def as_dict(self) -> dict:
        return asdict(self)


_COLUMNS = [f.name for f in fields(DocRecord)]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class DocumentRegistry:
    def __init__(self, path: Path | str):
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute(SCHEMA)
            self._db.commit()

    def _rec(self, row: sqlite3.Row | None) -> DocRecord | None:
        return None if row is None else DocRecord(**{c: row[c] for c in _COLUMNS})

    def insert(self, rec: DocRecord) -> None:
        with self._lock:
            self._db.execute(
                f"insert into documents ({', '.join(_COLUMNS)}) values ({', '.join('?' for _ in _COLUMNS)})",
                [getattr(rec, c) for c in _COLUMNS],
            )
            self._db.commit()

    def get(self, doc_id: str) -> DocRecord | None:
        with self._lock:
            return self._rec(self._db.execute("select * from documents where id = ?", (doc_id,)).fetchone())

    def by_hash(self, content_hash: str) -> DocRecord | None:
        with self._lock:
            return self._rec(self._db.execute("select * from documents where content_hash = ?", (content_hash,)).fetchone())

    def list(self) -> list[DocRecord]:
        with self._lock:
            rows = self._db.execute("select * from documents order by created_at desc").fetchall()
        return [self._rec(r) for r in rows]  # type: ignore[misc]

    def update(self, doc_id: str, **values) -> None:
        unknown = set(values) - set(_COLUMNS)
        if unknown:
            raise ValueError(f"unknown columns: {unknown}")
        with self._lock:
            self._db.execute(
                f"update documents set {', '.join(f'{k} = ?' for k in values)} where id = ?", [*values.values(), doc_id]
            )
            self._db.commit()

    def delete(self, doc_id: str) -> bool:
        with self._lock:
            cur = self._db.execute("delete from documents where id = ?", (doc_id,))
            self._db.commit()
            return cur.rowcount > 0

    def mark_interrupted(self) -> int:
        """Documents left 'indexing' by a crash or restart can never finish; show them as failed so they can be re-indexed."""
        with self._lock:
            cur = self._db.execute(
                "update documents set status = 'failed', error = ? where status = 'indexing'",
                ("Indexing was interrupted (the server restarted). Use Re-index to try again.",),
            )
            self._db.commit()
            return cur.rowcount

    def close(self) -> None:
        with self._lock:
            self._db.close()
