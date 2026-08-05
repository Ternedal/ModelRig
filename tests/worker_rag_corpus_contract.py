#!/usr/bin/env python3
"""RAG corpus contract and ingest atomicity.

Two failures this pins, both found by external review on 2026-08-04:

1. ``ingest`` deleted a source, then embedded and committed chunk by chunk. A
   failed embed part-way through left the previous version permanently gone and
   a partial one committed -- a valid but semantically corrupt corpus.
2. The corpus recorded no embedding model or dimension. ``cosine`` returns 0.0
   for mismatched lengths and ``query`` drops everything below ``min_score``, so
   swapping the model produced zero matches -- indistinguishable from a
   legitimate "no relevant sources", while the model answered from its own
   knowledge instead.
"""
import asyncio
import json
import os
import sqlite3
import sys
import tempfile

os.environ.setdefault("MODELRIG_DB", os.path.join(tempfile.mkdtemp(), "rag.db"))
sys.path.insert(0, "worker")

import app.ollama_client as oc  # noqa: E402
import app.rag as rag  # noqa: E402
from app.store import DocStore  # noqa: E402

passed = 0
failed = 0


def check(label: str, ok: bool) -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


def _db_path() -> str:
    """A path inside a private 0700 directory.

    A bare temp NAME only reserves a string -- another process can create that
    path between the call and the open, so CodeQL flags it. mkdtemp creates the
    directory atomically with owner-only permissions, and the database file is
    made inside it.
    """
    return os.path.join(tempfile.mkdtemp(), "corpus.db")


def _vec(text: str, dims: int = 26) -> list[float]:
    v = [0.0] * dims
    for ch in text.lower():
        i = ord(ch) - 97
        if 0 <= i < dims:
            v[i] += 1.0
    return v


async def _embed(text, model=None):
    return _vec(text)


def _fresh() -> DocStore:
    oc.embed = _embed
    oc.EMBED_MODEL = "nomic-embed-text"
    return DocStore(_db_path())


DOC = {"text": "alpha beta gamma delta epsilon " * 40, "source": "a.txt"}


# 4 -- first ingest records the contract
store = _fresh()
asyncio.run(rag.ingest(store, [DOC], chunk_size=60, overlap=10))
check("first ingest records model, dimension and chunker version",
      store.meta("embedding_model") == "nomic-embed-text"
      and store.meta("embedding_dimensions") == "26"
      and store.meta("chunker_version") == rag.CHUNKER_VERSION)

# 1 -- an embedding failure mid re-ingest leaves the old source untouched
before = store.count()
seen = {"n": 0}


async def _failing(text, model=None):
    seen["n"] += 1
    if seen["n"] >= 3:
        raise RuntimeError("embedding backend down")
    return _vec(text)


oc.embed = _failing
try:
    asyncio.run(rag.ingest(store, [{"text": "replacement " * 60, "source": "a.txt"}],
                           chunk_size=60, overlap=10))
    check("embedding failure aborts the re-ingest", False)
except RuntimeError:
    check("embedding failure aborts the re-ingest", True)
check("a failed re-ingest leaves the previous source fully intact",
      store.count() == before)
oc.embed = _embed

# 2 -- a failure inside the transaction rolls back delete AND inserts
store2 = _fresh()
asyncio.run(rag.ingest(store2, [DOC], chunk_size=60, overlap=10))
baseline = store2.count()
rows = [("x", _vec("x"), "a.txt", 0), ("y", "NOT-JSON-SERIALISABLE" * 0, "a.txt", 1)]
try:
    store2.apply_ingest(["a.txt"], [(t, e, s, i) for t, e, s, i in
                                    [("x", _vec("x"), "a.txt", 0),
                                     ("y", object(), "a.txt", 1)]])
    check("a failure inside the transaction rolls back the delete too", False)
except Exception:
    check("a failure inside the transaction rolls back the delete too",
          store2.count() == baseline)

# 3 -- replacing a source is one transaction, not one per chunk
store3 = _fresh()
asyncio.run(rag.ingest(store3, [DOC], chunk_size=60, overlap=10))
first = store3.count()
asyncio.run(rag.ingest(store3, [DOC], chunk_size=60, overlap=10))
check("re-ingesting the same source replaces rather than duplicates",
      store3.count() == first)

# 5 -- dimension mismatch fails closed at query time
store4 = _fresh()
asyncio.run(rag.ingest(store4, [DOC], chunk_size=60, overlap=10))


async def _wide(text, model=None):
    return _vec(text, 40)


oc.embed = _wide
try:
    asyncio.run(rag.query(store4, "alpha", synthesize=False))
    check("a dimension mismatch raises instead of returning nothing", False)
except rag.CorpusModelMismatch as exc:
    check("a dimension mismatch raises instead of returning nothing", True)
    check("the mismatch error names both sides and the fix",
          "26d" in str(exc) and "40d" in str(exc) and "eindex" in str(exc))
oc.embed = _embed

# 6 -- same dimension, different model still fails closed
oc.EMBED_MODEL = "some-other-model"
try:
    asyncio.run(rag.query(store4, "alpha", synthesize=False))
    check("a model swap at the same dimension still fails closed", False)
except rag.CorpusModelMismatch:
    check("a model swap at the same dimension still fails closed", True)
oc.EMBED_MODEL = "nomic-embed-text"

# 7 -- a pre-contract corpus records its MEASURED dimension, never a guessed model
legacy = _db_path()
conn = sqlite3.connect(legacy)
conn.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY AUTOINCREMENT, "
             "text TEXT NOT NULL, source TEXT, chunk_index INTEGER NOT NULL DEFAULT 0, "
             "embedding TEXT NOT NULL, created_at REAL NOT NULL)")
conn.execute("INSERT INTO documents (text, source, chunk_index, embedding, created_at) "
             "VALUES (?,?,?,?,?)", ("old", "legacy.txt", 0, json.dumps(_vec("old")), 1.0))
conn.commit()
conn.close()
store5 = DocStore(legacy)
check("a pre-contract corpus backfills the measured dimension",
      store5.meta("embedding_dimensions") == "26")
check("a pre-contract corpus never guesses the model name",
      store5.meta("embedding_model") == "unknown")
try:
    asyncio.run(rag.query(store5, "old", synthesize=False))
    check("an unknown model does not block a matching dimension", True)
except rag.CorpusModelMismatch:
    check("an unknown model does not block a matching dimension", False)

# 8 -- the write lock is taken at transaction START, not at first write.
# Grepping the source would also match the explanation in the docstring, so
# this records what is actually executed on the connection instead.
store7 = _fresh()
asyncio.run(rag.ingest(store7, [DOC], chunk_size=60, overlap=10))
statements: list[str] = []
store7._conn.set_trace_callback(lambda sql: statements.append(str(sql).strip().upper()))
store7.apply_ingest(["a.txt"], [("z", _vec("z"), "a.txt", 0)])
store7._conn.set_trace_callback(None)
check("apply_ingest opens the transaction with BEGIN IMMEDIATE",
      any(s.startswith("BEGIN IMMEDIATE") for s in statements))
check("the write lock is taken before any DELETE or INSERT",
      statements and statements[0].startswith("BEGIN IMMEDIATE"))

# an empty corpus imposes no contract
store6 = _fresh()
try:
    asyncio.run(rag.query(store6, "anything", synthesize=False))
    check("an empty corpus imposes no contract", True)
except rag.CorpusModelMismatch:
    check("an empty corpus imposes no contract", False)

print(f"\n===== RAG CORPUS CONTRACT: {passed} passed, {failed} failed =====")
sys.exit(1 if failed else 0)
