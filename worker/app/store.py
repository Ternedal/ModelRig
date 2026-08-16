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
from collections.abc import Sequence

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
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS corpus_meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        # Sources the user has switched OFF. A row here means "do not retrieve
        # from this source"; the chunks stay in the index untouched, so the
        # switch is reversible and costs no re-ingest. Absence = enabled, so
        # every source predating this table keeps working exactly as before.
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS disabled_sources (
                source      TEXT PRIMARY KEY,
                disabled_at REAL NOT NULL
            )
            """
        )
        self._conn.commit()
        self._backfill_measured_dimension()

    # ---- corpus contract -------------------------------------------------
    # The index is only meaningful together with the embedding model that
    # built it. Without that recorded, swapping MODELRIG_EMBED_MODEL makes
    # cosine() return 0.0 for every chunk (mismatched lengths), min_score
    # filters them all out, and the query returns nothing -- byte-identical
    # to a legitimate "no relevant sources". The model then answers from its
    # own parametric knowledge while the corpus is silently disconnected.

    def meta(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM corpus_meta WHERE key = ?", (key,)
            ).fetchone()
        return None if row is None else str(row[0])

    def set_meta(self, values: dict[str, str]) -> None:
        with self._lock:
            self._conn.executemany(
                "INSERT INTO corpus_meta (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                [(k, str(v)) for k, v in values.items()],
            )
            self._conn.commit()

    def _backfill_measured_dimension(self) -> None:
        """Record what an existing index can PROVE about itself, nothing more.

        A corpus built before the contract existed has no recorded model. The
        dimension, however, is measurable from the stored vectors, so it is a
        fact rather than an assumption -- record it. The model name stays
        ``unknown`` on purpose: guessing it (for instance from the currently
        configured model) would write an assumption into the database as if it
        were established, which is exactly the failure this table exists to
        prevent. Consequence, accepted deliberately: for pre-contract indexes a
        model swap that keeps the same dimension is not detectable."""
        with self._lock:
            has_meta = self._conn.execute(
                "SELECT 1 FROM corpus_meta LIMIT 1"
            ).fetchone()
            if has_meta is not None:
                return
            row = self._conn.execute(
                "SELECT embedding FROM documents LIMIT 1"
            ).fetchone()
            if row is None:
                return  # empty corpus: nothing to prove, nothing to record
            try:
                measured = len(json.loads(row[0]))
            except (ValueError, TypeError):
                return
            if measured <= 0:
                return
            self._conn.executemany(
                "INSERT OR IGNORE INTO corpus_meta (key, value) VALUES (?,?)",
                [("embedding_model", "unknown"),
                 ("embedding_dimensions", str(measured))],
            )
            self._conn.commit()

    def apply_ingest(
        self,
        clear_sources: "Sequence[str]",
        rows: "Sequence[tuple[str, list[float], str | None, int]]",
    ) -> int:
        """Replace sources and insert their chunks in ONE transaction.

        The old order deleted a source, then embedded and committed chunk by
        chunk. A failed embed at chunk 14 of 50 left the previous version gone
        and a partial one committed -- a valid but semantically corrupt corpus
        that nothing detected afterwards. Every embedding is now computed
        before this call, so the only work inside the transaction is local
        SQLite writes.

        BEGIN IMMEDIATE takes the write lock at transaction start rather than
        at first write, matching the Agent 3 campaign adapter (ADR-A4-008
        slice 4). Any failure rolls the whole thing back: there is no
        intermediate state in which the old source is gone and the new one is
        incomplete."""
        replaced = 0
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                for source in clear_sources:
                    cur = self._conn.execute(
                        "DELETE FROM documents WHERE source = ?", (source,)
                    )
                    replaced += int(cur.rowcount or 0)
                now = time.time()
                self._conn.executemany(
                    "INSERT INTO documents (text, source, chunk_index, embedding, created_at) "
                    "VALUES (?,?,?,?,?)",
                    [(text, source, idx, json.dumps(emb), now)
                     for text, emb, source, idx in rows],
                )
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise
        return replaced

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

    def all(
        self,
        source: str | None = None,
        include_disabled: bool = True,
    ) -> list[tuple[int, str, str | None, int, list[float]]]:
        """Every chunk, optionally narrowed to one source.

        include_disabled=False drops chunks whose source the user switched
        off. Retrieval passes False; administrative counts pass True, so the
        Viden-screen can still say how large a switched-off source is.
        """
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
        out = [(r[0], r[1], r[2], r[3], json.loads(r[4])) for r in rows]
        if include_disabled:
            return out
        off = self.disabled_sources()
        # NULL source is reported as '(none)' everywhere else, so it can be
        # switched off under that name too.
        return [row for row in out if (row[2] or "(none)") not in off]

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0])

    # ---- per-source retrieval switch -------------------------------------

    def disabled_sources(self) -> set[str]:
        with self._lock:
            rows = self._conn.execute("SELECT source FROM disabled_sources").fetchall()
        return {r[0] for r in rows}

    def set_source_enabled(self, source: str, enabled: bool) -> bool:
        """Turn retrieval for one source on or off. Returns the new state.

        Deliberately does NOT check that the source exists: a source can be
        switched off, re-ingested later, and keep its setting. The opposite
        (dropping the row on re-ingest) would silently re-enable a source the
        user turned off, which is the failure worth avoiding.
        """
        with self._lock:
            if enabled:
                self._conn.execute("DELETE FROM disabled_sources WHERE source = ?", (source,))
            else:
                self._conn.execute(
                    "INSERT OR REPLACE INTO disabled_sources (source, disabled_at) VALUES (?, ?)",
                    (source, time.time()),
                )
            self._conn.commit()
        return enabled

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
