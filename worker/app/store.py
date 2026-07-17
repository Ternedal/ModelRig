"""SQLite-backed document store for RAG.

Embeddings are stored as JSON text. This is deliberately simple: it keeps the
worker dependency-light (stdlib sqlite3, no vector DB) and works fine up to a
few thousand chunks with brute-force cosine. Swap in Qdrant (or sqlite-vec) when
corpus size makes linear scan too slow. See STATUS.md.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time

from . import paths as _paths
# Anchored under the data root so a worker started from a different folder
# does not read an EMPTY index (the 401 footgun, applied to knowledge).
DB_PATH = _paths.resolve("./modelrig-rag.db", env="MODELRIG_DB")


class DocStore:
    """A SQLite-backed document store.

    Owns a connection, so it owns closing it (F-620). CPython usually collects a
    transient store the moment the caller drops it, and "usually" is not a
    lifecycle: on Windows an unclosed handle keeps the file locked, which is the
    platform this actually runs on, and PyPy or a future runtime need not
    collect at all. Use it as a context manager when it is transient.
    """

    def __init__(self, path: str = DB_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._closed = False
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                text        TEXT NOT NULL,
                source      TEXT,
                chunk_index INTEGER NOT NULL DEFAULT 0,
                embedding   TEXT NOT NULL,
                created_at  REAL NOT NULL
            )
            """
        )
        self._conn.commit()

    def add(self, text: str, embedding: list[float], source: str | None = None,
            chunk_index: int = 0) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO documents (text, source, chunk_index, embedding, created_at) "
                "VALUES (?,?,?,?,?)",
                (text, source, chunk_index, json.dumps(embedding), time.time()),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def all(self, source: str | None = None) -> list[tuple[int, str, str | None, int, list[float]]]:
        with self._lock:
            if source is None:
                rows = self._conn.execute(
                    "SELECT id, text, source, chunk_index, embedding FROM documents"
                ).fetchall()
            elif source == "(none)":
                rows = self._conn.execute(
                    "SELECT id, text, source, chunk_index, embedding FROM documents "
                    "WHERE source IS NULL"
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT id, text, source, chunk_index, embedding FROM documents "
                    "WHERE source = ?", (source,)
                ).fetchall()
        return [(r[0], r[1], r[2], r[3], json.loads(r[4])) for r in rows]

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])

    def sources(self) -> list[tuple[str, int, float]]:
        """Return (source, chunk_count, last_ingested_at) grouped by source,
        newest first. A NULL source is reported as the string '(none)'."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT COALESCE(source, '(none)') AS s, COUNT(*), MAX(created_at) "
                "FROM documents GROUP BY s ORDER BY MAX(created_at) DESC"
            ).fetchall()
        return [(r[0], int(r[1]), float(r[2])) for r in rows]

    def delete_source(self, source: str) -> int:
        """Delete every chunk for a source. Pass '(none)' to clear NULL-source
        chunks. Returns the number of chunks removed."""
        with self._lock:
            if source == "(none)":
                cur = self._conn.execute("DELETE FROM documents WHERE source IS NULL")
            else:
                cur = self._conn.execute("DELETE FROM documents WHERE source = ?", (source,))
            self._conn.commit()
            return int(cur.rowcount)

    def stats(self) -> dict:
        """Corpus totals: distinct sources and total chunks."""
        with self._lock:
            chunks = int(self._conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
            srcs = int(self._conn.execute(
                "SELECT COUNT(DISTINCT COALESCE(source, '(none)')) FROM documents"
            ).fetchone()[0])
        return {"sources": srcs, "chunks": chunks}

    def close(self) -> None:
        """Release the connection. Idempotent, so a double close is not a crash."""
        with self._lock:
            if not self._closed:
                self._conn.close()
                self._closed = True

    def __enter__(self) -> "DocStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
