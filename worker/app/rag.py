"""RAG orchestration: embed, brute-force cosine retrieval, optional synthesis."""
from __future__ import annotations

import math

from . import ollama_client as oc
from .store import DocStore


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
    """Split text into overlapping chunks, preferring whitespace break points.

    Overlap preserves context across chunk boundaries so a fact split mid-way is
    still retrievable. Short text passes through as a single chunk.
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
        if end < n:  # try to break on whitespace within the window's back half
            brk = max(text.rfind(" ", start + overlap, end),
                      text.rfind("\n", start + overlap, end))
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
                 chunk_size: int = 800, overlap: int = 150) -> int:
    """Chunk each document, embed every chunk, store it. Returns chunks added."""
    added = 0
    for d in documents:
        source = d.get("source")
        for idx, piece in enumerate(chunk_text(d.get("text") or "", chunk_size, overlap)):
            emb = await oc.embed(piece)
            store.add(piece, emb, source, idx)
            added += 1
    return added


async def query(
    store: DocStore,
    q: str,
    top_k: int = 4,
    synthesize: bool = True,
    model: str | None = None,
) -> dict:
    q_emb = await oc.embed(q)
    scored = [
        {"id": doc_id, "text": text, "source": source,
         "chunk_index": chunk_index, "score": cosine(q_emb, emb)}
        for doc_id, text, source, chunk_index, emb in store.all()
    ]
    scored.sort(key=lambda x: x["score"], reverse=True)
    matches = scored[:top_k]

    result: dict = {"matches": matches}
    if synthesize and matches:
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
    return result
