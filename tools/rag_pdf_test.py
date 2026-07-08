#!/usr/bin/env python3
"""RAG PDF ingest — test recipe for the rig.

Unlike the Voice tests, PDF extraction is fully verifiable in the container and
was proven there (PyMuPDF extracts Danish text correctly). This recipe lets you
confirm the FULL round trip on the rig, where Ollama is running: extract ->
chunk -> embed -> store -> query.

PREREQUISITES (on the rig):
    pip install pymupdf
    # Ollama running with the embedding model:  ollama pull nomic-embed-text

RUN (point at any PDF, or omit to generate a small Danish test PDF):
    python tools/rag_pdf_test.py                 # generates + tests a sample
    python tools/rag_pdf_test.py my_document.pdf # tests your own PDF

WHAT IT PROVES:
    - PyMuPDF extracts text from the PDF (pages, chars).
    - The text ingests into the RAG index (chunks embedded + stored).
    - A query over the ingested content returns a relevant answer.

REPORT BACK: pages/chars extracted, chunks added, and whether the query answer
is grounded in the PDF.
"""
import base64
import sys


def main() -> int:
    sys.path.insert(0, "worker")
    from app import rag_pdf

    if not rag_pdf.is_available():
        print("PyMuPDF not installed. Run: pip install pymupdf")
        return 1

    # Get PDF bytes: user's file, or generate a small Danish sample.
    if len(sys.argv) > 1:
        path = sys.argv[1]
        with open(path, "rb") as f:
            pdf_bytes = f.read()
        print(f"using {path}")
    else:
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100),
                         "ModelRig er en selvhostet LLM-platform.\n"
                         "Rig-maskinen har en RTX 3060 GPU med 12 GB VRAM.\n"
                         "Alva er Android-appen; motoren hedder ModelRig.\n"
                         "Voice bruger faster-whisper til ASR og Piper til TTS.",
                         fontsize=12)
        pdf_bytes = doc.tobytes()
        doc.close()
        print("using a generated Danish sample PDF")

    # 1. Extract (pure, no Ollama).
    extracted = rag_pdf.extract_text(pdf_bytes)
    print(f"\nEXTRACTED: {extracted['pages']} page(s), {extracted['chars']} chars")
    print("--- first 300 chars ---")
    print(extracted["text"][:300])

    # 2. Ingest via the running worker (needs Ollama for embeddings).
    import urllib.request, json
    b64 = base64.b64encode(pdf_bytes).decode()
    body = json.dumps({"pdf_base64": b64, "source": "pdf_test"}).encode()
    req = urllib.request.Request("http://127.0.0.1:8099/rag/ingest/pdf",
                                 data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            result = json.loads(r.read())
        print(f"\nINGESTED: {result['chunks_added']} chunks, {result['total']} total in index")
    except Exception as e:
        print(f"\nINGEST via worker failed: {e}")
        print("(is the worker running on :8099 and Ollama on :11434?)")
        return 1

    # 3. Query it.
    q = "Hvilken GPU har rig-maskinen?"
    body = json.dumps({"query": q, "top_k": 3}).encode()
    req = urllib.request.Request("http://127.0.0.1:8099/rag/query",
                                 data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            ans = json.loads(r.read())
        print(f"\nQUERY: {q}")
        print("ANSWER:", ans.get("answer", ans))
    except Exception as e:
        print(f"\nQUERY failed: {e}")
        return 1
    print("\nIf the answer mentions the RTX 3060, the full PDF->RAG chain works.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
