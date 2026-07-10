"""RAG HTML ingest — text extraction with the standard library only.

Unlike PDF/DOCX/PPTX this needs NO third-party package. html.parser is in the
stdlib, so HTML ingest is always available and the endpoint never returns 501.
That is a deliberate choice: pulling in beautifulsoup/lxml would buy prettier
extraction at the cost of another optional dependency to install on the rig,
and saved web pages are the one format Anders can produce without any tooling
(Ctrl+S in a browser).

What we do:
  - drop <script>, <style>, <noscript>, <template>, <svg> -- markup, not prose
  - drop <nav>, <header>, <footer>, <aside> -- site chrome repeats on every
    page and would pollute every chunk with the same navigation text
  - treat block-level tags as paragraph breaks, so the RAG chunker sees the
    document's real structure instead of one giant run-on line
  - unescape entities (&aelig; -> æ), which matters for Danish text
  - keep <title> as the first line: it is usually the best one-line summary

Known limits, stated rather than hidden: this is text extraction, not
rendering. Content injected by JavaScript is not in the saved HTML and cannot
be recovered here. Tables become pipe-joined rows, losing column alignment.
"""
from __future__ import annotations

import html as _html
import re
from html.parser import HTMLParser

# Tags whose *contents* are never prose.
_DROP_CONTENT = {"script", "style", "noscript", "template", "svg", "head"}
# Site chrome: real text, but the same text on every page.
_DROP_CHROME = {"nav", "header", "footer", "aside"}
# Tags that end a paragraph.
_BLOCK = {
    "p", "div", "br", "li", "tr", "section", "article", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6", "pre", "table", "ul", "ol",
}
# Cells are inline, but two adjacent cells must not fuse into one word
# ("A" + "B" -> "AB"). Separate them like rag_docx does with its tables.
_CELL = {"td", "th"}


def is_available() -> bool:
    """Always True: html.parser ships with Python. Kept for endpoint symmetry."""
    return True


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title: str = ""
        self._skip_depth = 0
        self._skip_tag: str | None = None
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if self._skip_depth:
            if tag == self._skip_tag:
                self._skip_depth += 1
            return
        if tag in _DROP_CONTENT or tag in _DROP_CHROME:
            self._skip_tag = tag
            self._skip_depth = 1
            return
        if tag == "title":
            self._in_title = True
        if tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._skip_depth:
            if tag == self._skip_tag:
                self._skip_depth -= 1
                if self._skip_depth == 0:
                    self._skip_tag = None
            return
        if tag == "title":
            self._in_title = False
        if tag in _CELL:
            self.parts.append(" | ")
        if tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        # <title> lives inside <head>, which we skip; capture it before that.
        if self._in_title:
            self.title += data
            return
        if self._skip_depth:
            return
        if data.strip():
            self.parts.append(data)


def extract_text(html_bytes: bytes) -> dict:
    """Extract text from HTML bytes.

    Returns {text, title, chars}. Raises RuntimeError (surfaced as 400) if the
    bytes cannot be decoded as text at all.
    """
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            raw = html_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise RuntimeError("could not decode HTML as text (utf-8/cp1252/latin-1)")

    # <title> is inside <head>, which _DROP_CONTENT skips; grab it up front.
    m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
    title = _html.unescape(m.group(1)).strip() if m else ""

    p = _Extractor()
    try:
        p.feed(raw)
        p.close()
    except Exception as e:
        raise RuntimeError(f"could not parse HTML: {e}") from e

    body = "".join(p.parts)
    # Collapse runs of whitespace within a line, and runs of blank lines.
    lines = [re.sub(r"[ \t\u00a0]+", " ", ln).strip() for ln in body.split("\n")]
    # A row ends with a dangling separator from its last cell.
    lines = [re.sub(r"\s*\|\s*$", "", ln).strip() for ln in lines]
    text = "\n\n".join(ln for ln in lines if ln)
    if title:
        text = f"{title}\n\n{text}" if text else title
    text = text.strip()
    return {"text": text, "title": title, "chars": len(text)}
