"""RAG PDF ingest — text extraction with PyMuPDF.

Extracts text from an uploaded PDF so it can go through the EXISTING RAG ingest
pipeline (chunk -> embed -> store). No new RAG logic; this is just a text-
extraction layer in front of rag.ingest().

PyMuPDF (imported as `fitz`) chosen over pypdf: much faster, more robust text
extraction on real-world PDFs (better layout handling, fewer empty-string
surprises). It's a reasonably light dependency (a single wheel, no system libs).

OPTIONAL, like the Voice backends: PyMuPDF is NOT a hard worker dependency
(keeps the base "download exe" rig light for users who only ingest text). It's
imported lazily; if it isn't installed, the PDF endpoint returns a clean 501
with install instructions and the rest of the worker is unaffected.

This module IS end-to-end testable without special hardware (unlike Voice) --
create a PDF, extract, ingest, query. See tools/rag_pdf_test.py.
"""
from __future__ import annotations

import logging


def is_available() -> bool:
    """True if PyMuPDF (fitz) can be imported (installed)."""
    try:
        import fitz  # noqa: F401  (PyMuPDF)
        return True
    except Exception as exc:  # noqa: BLE001
        # Fail-closed is right: no PyMuPDF, no PDF-indlæsning. Silence is not.
        #
        # This swallows more than ImportError, and on the rig it will: a broken
        # PyMuPDF wheel, a missing DLL, a CUDA mismatch. All of them arrive here
        # as "unavailable" with no reason, and the person reading the
        # capability list has to guess. F-501 was this exact shape -- an
        # `except Exception` hid an ImportError from a wrong class name for
        # eight releases, and the test passed because it asserted the failing
        # value and got it.
        logging.getLogger(__name__).info(
            "PyMuPDF er ikke tilgængelig (PDF-indlæsning slået fra): %r", exc)
        return False


def extract_text(pdf_bytes: bytes) -> dict:
    """Extract text from PDF bytes.

    Returns {text, pages, chars}. Pages are joined with form-feed-ish newlines
    so a downstream chunker still sees natural breaks, but page boundaries don't
    force a chunk split (the RAG chunker decides that by size/sentence).

    Raises RuntimeError (surfaced as 501/400 by the endpoint) on a missing
    backend or an unreadable/encrypted PDF.
    """
    try:
        import fitz
    except Exception as e:
        raise RuntimeError(
            "PDF ingest needs PyMuPDF. Install it on the rig with: pip install pymupdf"
        ) from e

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        raise RuntimeError(f"could not open PDF: {e}") from e

    if doc.is_encrypted:
        # Try an empty-password unlock (common for "protected" but not truly
        # locked PDFs); if it fails, be honest rather than returning garbage.
        if not doc.authenticate(""):
            doc.close()
            raise RuntimeError("PDF is password-protected; cannot extract text")

    parts: list[str] = []
    for page in doc:
        t = page.get_text("text") or ""
        t = t.strip()
        if t:
            parts.append(t)
    pages = doc.page_count
    doc.close()

    text = "\n\n".join(parts).strip()
    return {"text": text, "pages": pages, "chars": len(text)}
