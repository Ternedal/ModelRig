"""EPUB spine extraction and text-PDF extraction, preserving source locations."""
from __future__ import annotations

import math
import posixpath
import re
import xml.etree.ElementTree as ET
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from zipfile import BadZipFile, ZipFile

from .core import LanguageRigError, books, digest, file_digest, normalise, now, write_json

MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_PAGES = 3000


def _xml(content: bytes) -> ET.Element:
    if re.search(br"<!\s*(DOCTYPE|ENTITY)\b", content, re.I):
        raise LanguageRigError("DTD/entity declarations are not supported in EPUB metadata.")
    return ET.fromstring(content)


def _member(archive: ZipFile, name: str) -> bytes:
    info = archive.getinfo(name)
    if info.file_size > MAX_MEMBER_BYTES:
        raise LanguageRigError("EPUB member exceeds the import size limit.")
    with archive.open(info) as stream:
        data = stream.read(MAX_MEMBER_BYTES + 1)
    if len(data) > MAX_MEMBER_BYTES:
        raise LanguageRigError("EPUB member exceeds the import size limit.")
    return data


def _relative(base: str, href: str) -> str:
    url = urlsplit(href)
    if url.scheme or url.netloc:
        raise LanguageRigError("EPUB spine points to an external resource.")
    name = posixpath.normpath(posixpath.join(posixpath.dirname(base), unquote(url.path)))
    if name.startswith(("../", "/")) or name == "..":
        raise LanguageRigError("EPUB spine points outside the archive.")
    return name


class ChapterParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.heading: list[str] = []
        self.title = ""
        self.stack: list[tuple[str, bool, bool]] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        ignored = (bool(self.stack and self.stack[-1][1])
                   or tag in ("script", "style", "nav", "head")
                   or "hidden" in attributes
                   or attributes.get("aria-hidden") == "true")
        heading = bool(self.stack and self.stack[-1][2]) or tag in ("h1", "h2")
        if tag in ("br", "hr"):
            if not ignored:
                self.parts.append("\n")
            return
        if tag in ("meta", "link", "img", "input", "source", "wbr"):
            return
        self.stack.append((tag, ignored, heading))
        if not ignored and tag in ("p", "div", "section", "li", "h1", "h2", "h3", "tr"):
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                _, ignored, heading = self.stack[i]
                del self.stack[i:]
                if not ignored and tag in ("p", "div", "section", "li", "h1", "h2", "h3", "tr"):
                    self.parts.append("\n")
                if heading and tag in ("h1", "h2") and not self.title:
                    self.title = normalise("".join(self.heading))
                return

    def handle_data(self, data):
        if self.stack and self.stack[-1][1]:
            return
        self.parts.append(data)
        if self.stack and self.stack[-1][2] and not self.title:
            self.heading.append(data)


def extract_epub(path: Path) -> dict:
    with ZipFile(path) as archive:
        infos = archive.infolist()
        if len({i.filename for i in infos}) != len(infos):
            raise LanguageRigError("EPUB contains duplicate archive member names.")
        if sum(i.file_size for i in infos) > MAX_ARCHIVE_BYTES:
            raise LanguageRigError("EPUB uncompressed size exceeds the import limit.")
        container = _xml(_member(archive, "META-INF/container.xml"))
        rootfiles = container.findall(".//{*}rootfile")
        if not rootfiles:
            raise LanguageRigError("EPUB has no package rootfile.")
        package_name = _relative("", rootfiles[0].attrib["full-path"])
        package = _xml(_member(archive, package_name))
        metadata = package.find("{*}metadata")
        def values(tag):
            return [normalise("".join(e.itertext())) for e in metadata.findall("{*}" + tag)] if metadata is not None else []
        title = next(iter(values("title")), path.stem)
        language = next(iter(values("language")), "unknown").lower().split("-")[0]
        manifest = {item.attrib["id"]: item for item in package.findall("./{*}manifest/{*}item")}
        encrypted = set()
        if "META-INF/encryption.xml" in archive.namelist():
            encryption = _xml(_member(archive, "META-INF/encryption.xml"))
            encrypted = {unquote(e.attrib.get("URI", "")) for e in encryption.findall(".//{*}CipherReference")}
        sections = []
        for ref in package.findall("./{*}spine/{*}itemref"):
            if ref.attrib.get("linear", "yes") == "no":
                continue
            item = manifest.get(ref.attrib.get("idref"))
            if item is None:
                raise LanguageRigError("EPUB spine references a missing manifest item.")
            if "nav" in item.attrib.get("properties", "").split():
                continue
            if item.attrib.get("media-type") not in ("application/xhtml+xml", "text/html"):
                continue
            name = _relative(package_name, item.attrib["href"])
            if name in encrypted:
                raise LanguageRigError("Encrypted EPUB text is not supported.")
            parser = ChapterParser()
            parser.feed(_member(archive, name).decode("utf-8-sig"))
            text = normalise("".join(parser.parts))
            if text:
                sections.append({"location": name, "title": parser.title or f"Kapitel {len(sections) + 1}", "text": text})
        return {"title": title, "authors": values("creator"), "language": language,
                "subjects": values("subject"), "sections": sections, "warnings": []}


def extract_pdf(path: Path) -> dict:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise LanguageRigError("PDF import needs pypdf; install the languagerig package.") from exc
    reader = PdfReader(path)
    if reader.is_encrypted and not reader.decrypt(""):
        raise LanguageRigError("Password-protected PDF is not supported.")
    if len(reader.pages) > MAX_PAGES:
        raise LanguageRigError("PDF exceeds the page limit.")
    pages = [normalise(page.extract_text() or "") for page in reader.pages]
    edge_counts = Counter()
    nonempty = [page for page in pages if page]
    for page in nonempty:
        lines = page.splitlines()
        edge_counts.update(set([lines[0], lines[-1]]))
    repeated = {line for line, count in edge_counts.items()
                if count >= max(3, math.ceil(len(nonempty) * 0.6)) and len(line) < 150}
    sections = []
    for number, text in enumerate(pages, 1):
        lines = text.splitlines()
        if lines and lines[0] in repeated:
            lines = lines[1:]
        if lines and lines[-1] in repeated:
            lines = lines[:-1]
        text = normalise("\n".join(lines))
        if text:
            sections.append({"location": f"page:{number}", "title": f"Side {number}", "text": text})
    warnings = []
    if len(nonempty) < len(pages):
        warnings.append(f"pdf_pages_without_text:{len(pages) - len(nonempty)}")
    if not nonempty or len(nonempty) < len(pages) * 0.8:
        warnings.append("ocr_or_manual_review_required")
    metadata = reader.metadata
    return {"title": str(metadata.title or path.stem) if metadata else path.stem,
            "authors": [str(metadata.author)] if metadata and metadata.author else [],
            "language": "unknown", "subjects": [], "sections": sections, "warnings": warnings}


def import_books(workspace: Path, source: Path, *, genre="unknown", language=None,
                 topics=None, training_allowed=False) -> dict:
    existing = books(workspace)
    known = {book["source_id"]: book for book in existing}
    content_ids = {book["content_sha256"]: book["source_id"] for book in existing}
    candidates = [source] if source.is_file() else sorted(
        p for p in source.rglob("*") if p.is_file() and p.suffix.lower() in (".epub", ".pdf"))
    if not source.exists():
        raise LanguageRigError("Input file/directory does not exist.")
    result = {"imported": [], "skipped": [], "errors": []}
    for path in candidates:
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                raise LanguageRigError("Book exceeds the file size limit.")
            suffix = path.suffix.lower()
            if suffix not in (".epub", ".pdf"):
                raise LanguageRigError("Expected EPUB or PDF.")
            source_id = file_digest(path)
            if source_id in known:
                result["skipped"].append({"file": path.name, "source_id": source_id, "reason": "already_imported"})
                continue
            extracted = extract_epub(path) if suffix == ".epub" else extract_pdf(path)
            text = "\n\n".join(section["text"] for section in extracted["sections"])
            if not text:
                raise LanguageRigError("No readable text; OCR/encrypted content is not imported.")
            if len(text) < 200:
                extracted["warnings"].append("very_short_text")
            if text.count("\ufffd") / len(text) > 0.01:
                extracted["warnings"].append("text_encoding_review_required")
            content_id = digest(" ".join(text.split()))
            work_key = normalise(extracted["title"] + " " + " ".join(extracted["authors"])).casefold()
            work_key = re.sub(r"[\W_]+", " ", work_key).strip()
            review = any("required" in warning or warning == "very_short_text" for warning in extracted["warnings"])
            row = {**extracted, "format": "languagerig-book/v1", "source_id": source_id,
                   "original_name": path.name, "content_sha256": content_id,
                   "work_id": "auto:" + digest(work_key), "genre": genre,
                   "language": language or extracted["language"], "topics": topics or [],
                   "training_allowed": bool(training_allowed), "quality_accepted": not review,
                   "duplicate_of": content_ids.get(content_id), "imported_at": now()}
            write_json(workspace / "books" / source_id / "book.json", row)
            known[source_id] = row
            content_ids.setdefault(content_id, source_id)
            result["imported"].append({key: value for key, value in row.items() if key != "sections"})
        except Exception as exc:
            # Parser libraries expose different malformed/encrypted-document
            # exceptions. Report the failed file and continue the import batch.
            result["errors"].append({"file": path.name, "error": str(exc)})
    return result
