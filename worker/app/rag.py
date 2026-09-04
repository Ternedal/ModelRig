"""RAG orchestration: embed, brute-force cosine retrieval, optional synthesis."""
from __future__ import annotations

import math

from . import ollama_client as oc
from .store import DocStore


CHUNKER_VERSION = "v1"


class CorpusModelMismatch(RuntimeError):
    """The active embedding model cannot read this corpus."""


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity; returns 0.0 for empty or mismatched vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 150) -> list[str]:
    """Split text into overlapping chunks, preferring sentence-ending
    punctuation, then whitespace, as break points.

    Overlap preserves context across chunk boundaries so a fact split mid-way
    is still retrievable. Short text passes through as a single chunk.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    if overlap >= chunk_size:
        overlap = chunk_size // 4

    chunks: list[str] = []
    start, n = 0, len(text)
    while start < n:
        end = min(start + chunk_size, n)
        if end < n:  # try to break within the window's back half
            window_start = start + overlap
            # Prefer a sentence boundary (". ", "? ", "! ", or a real newline)
            # over a plain space -- keeps chunks semantically whole more often,
            # which matters for retrieval quality more than raw character count.
            brk = -1
            for punct in (". ", "? ", "! ", "\n"):
                idx = text.rfind(punct, window_start, end)
                if idx > brk:
                    brk = idx + (len(punct) - 1) if punct != "\n" else idx
            if brk <= start:
                brk = text.rfind(" ", window_start, end)
            if brk > start:
                end = brk
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


async def ingest(store: DocStore, documents: list[dict],
                 chunk_size: int = 800, overlap: int = 150) -> tuple[int, int]:
    """Chunk each document, embed every chunk, store it.

    REPLACE-BY-SOURCE: re-ingesting a source replaces its previous chunks
    instead of appending duplicates. Without this, every re-ingest (an updated
    PDF, a double tap) doubled the source's chunks -- retrieval then returned
    near-identical duplicates that crowded other sources out of top_k, and the
    index only ever grew (audit 1.58.36 / RAG_DESIGN.md R1). The delete happens
    once per distinct source per CALL, so several documents sharing a source in
    one request still land together. A None/empty source is never deleted --
    unnamed snippets keep append semantics on purpose (there is no identity to
    replace).

    Returns (chunks_added, chunks_replaced).

    ATOMICITY: every embedding is computed BEFORE anything is deleted or
    inserted. The old order deleted the source first and then embedded and
    committed chunk by chunk, so a failed embed at chunk 14 of 50 -- Ollama
    down, a timeout, a swapped model -- left the previous version permanently
    gone and a partial one committed. The call failed while the corpus stayed
    valid but semantically corrupt, and nothing detected it afterwards. Now the
    only failure point before the write is embedding, where nothing has been
    touched yet; the delete and all inserts then happen in one transaction that
    rolls back as a unit."""
    cleared: list[str] = []
    seen: set[str] = set()
    rows: list[tuple[str, list[float], str | None, int]] = []
    for d in documents:
        source = d.get("source")
        if source and source not in seen:
            seen.add(source)
            cleared.append(source)
        for idx, piece in enumerate(chunk_text(d.get("text") or "", chunk_size, overlap)):
            emb = await oc.embed(piece)
            rows.append((piece, emb, source, idx))
    if not rows and not cleared:
        return 0, 0
    replaced = store.apply_ingest(cleared, rows)
    _record_corpus_contract(store, rows)
    return len(rows), replaced


def _record_corpus_contract(store: DocStore, rows) -> None:
    """Bind the corpus to the model that built it, once it holds anything."""
    if not rows:
        return
    dims = len(rows[0][1])
    if dims <= 0:
        return
    existing_dims = store.meta("embedding_dimensions")
    if existing_dims is None:
        store.set_meta({
            "embedding_model": oc.EMBED_MODEL,
            "embedding_dimensions": str(dims),
            "chunker_version": CHUNKER_VERSION,
        })
        return
    # A corpus backfilled from pre-contract data knows its dimension but not
    # its model. Once new chunks arrive from a known model at that same
    # dimension, the name can be recorded truthfully.
    if store.meta("embedding_model") == "unknown" and existing_dims == str(dims):
        store.set_meta({"embedding_model": oc.EMBED_MODEL})


def assert_corpus_matches_active_model(store: DocStore, query_dims: int) -> None:
    """Fail closed when the active model cannot read this corpus.

    cosine() returns 0.0 for mismatched vector lengths and query() drops
    everything below min_score, so a model swap yields zero matches -- which is
    indistinguishable from a legitimate "no relevant sources". The model then
    answers from its own knowledge while the corpus is silently disconnected.
    That silence is the failure this guard exists to convert into a named
    error."""
    recorded_dims = store.meta("embedding_dimensions")
    if recorded_dims is None:
        return  # empty or pre-contract corpus with nothing measurable
    if str(query_dims) != recorded_dims:
        raise CorpusModelMismatch(
            f"RAG index was built with {store.meta('embedding_model')}/"
            f"{recorded_dims}d, but the active model "
            f"({oc.EMBED_MODEL}) produces {query_dims}d. Reindex required."
        )
    recorded_model = store.meta("embedding_model")
    if recorded_model and recorded_model != "unknown" and recorded_model != oc.EMBED_MODEL:
        raise CorpusModelMismatch(
            f"RAG index was built with {recorded_model}, but the active model "
            f"is {oc.EMBED_MODEL}. Same dimension does not mean the same vector "
            f"space. Reindex required."
        )


async def query(
    store: DocStore,
    q: str,
    top_k: int = 4,
    synthesize: bool = True,
    model: str | None = None,
    source: str | None = None,
    min_score: float = 0.3,
) -> dict:
    """Retrieve the top_k most relevant chunks, but only ones that clear
    min_score first -- without this, a query with no genuinely relevant
    content still forces top_k chunks into the context (even ones with a
    near-zero cosine score), which can lead the model to answer from noise
    instead of correctly saying it doesn't know. Filtering happens before the
    top_k cut, not after, so a good min_score can return fewer than top_k
    matches (including zero) rather than padding with irrelevant ones.

    Sources the user switched off are excluded here, at retrieval — not by
    deleting anything. A switched-off source therefore cannot reach the model
    through RAG, but its chunks survive and the switch is reversible.
    """
    q_emb = await oc.embed(q)
    assert_corpus_matches_active_model(store, len(q_emb))
    scored = [
        {"id": doc_id, "text": text, "source": src,
         "chunk_index": chunk_index, "score": cosine(q_emb, emb)}
        for doc_id, text, src, chunk_index, emb in store.all(source=source, include_disabled=False)
    ]
    scored = [m for m in scored if m["score"] >= min_score]
    scored.sort(key=lambda x: x["score"], reverse=True)
    matches = scored[:top_k]

    result: dict = {"matches": matches}
    if synthesize:
        if matches:
            context = "\n\n".join(f"[{m['source'] or m['id']}] {m['text']}" for m in matches)
            messages = [
                {
                    "role": "system",
                    "content": "Answer using ONLY the provided context. "
                               "If the answer is not in the context, say you don't know.",
                },
                {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {q}"},
            ]
            result["answer"] = await oc.chat(messages, model=model)
        else:
            # No chunk cleared min_score -> there is no grounded context to
            # answer from. Return an explicit, deterministic "don't know"
            # here rather than letting matches=[] fall through: without this
            # the caller got no answer field and silently degraded to a
            # context-free chat, which is why the phone answered "hej" with a
            # generic greeting while desktop (with context) said "I don't
            # know" -- same query, divergent behavior. Now both clients get
            # the same honest reply, in the query's language where trivial.
            result["answer"] = "Jeg kan ikke finde noget relevant i kilderne til at besvare det. / I don't have relevant context to answer that."
    return result
