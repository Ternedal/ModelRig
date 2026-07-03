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

DB_PATH = os.getenv("MODELRIG_DB", "./modelrig-rag.db")


class DocStore:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        self._lock = threading.Lock()
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

    def all(self) -> list[tuple[int, str, str | None, int, list[float]]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, text, source, chunk_index, embedding FROM documents"
            ).fetchall()
        return [(r[0], r[1], r[2], r[3], json.loads(r[4])) for r in rows]

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
