#!/usr/bin/env python3
"""Regression coverage for PyMuPDF document ownership.

The production dependency is optional, so these tests install a tiny fake fitz
module in sys.modules. That exercises the real extraction code without requiring
PyMuPDF or a generated PDF fixture.
"""
from __future__ import annotations

import sys

from app import rag_pdf


passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    print(f"  {'PASS' if condition else 'FAIL'}: {name}")
    passed += bool(condition)
    failed += not condition


class FakePage:
    def __init__(self, text: str = "", error: Exception | None = None) -> None:
        self.text = text
        self.error = error

    def get_text(self, mode: str) -> str:
        if mode != "text":
            raise AssertionError(f"unexpected extraction mode: {mode}")
        if self.error is not None:
            raise self.error
        return self.text


class FakeDocument:
    def __init__(
        self,
        pages: list[FakePage],
        *,
        encrypted: bool = False,
        authenticate_result: bool = True,
        authenticate_error: Exception | None = None,
    ) -> None:
        self._pages = pages
        self.is_encrypted = encrypted
        self.authenticate_result = authenticate_result
        self.authenticate_error = authenticate_error
        self.close_count = 0

    @property
    def page_count(self) -> int:
        return len(self._pages)

    def authenticate(self, password: str) -> bool:
        if password != "":
            raise AssertionError("only empty-password unlock is expected")
        if self.authenticate_error is not None:
            raise self.authenticate_error
        return self.authenticate_result

    def __iter__(self):
        return iter(self._pages)

    def close(self) -> None:
        self.close_count += 1


class FakeFitz:
    def __init__(self, document: FakeDocument | None = None, open_error: Exception | None = None) -> None:
        self.document = document
        self.open_error = open_error
        self.open_calls = 0

    def open(self, *, stream: bytes, filetype: str) -> FakeDocument:
        self.open_calls += 1
        if stream != b"pdf-bytes" or filetype != "pdf":
            raise AssertionError("extract_text changed the fitz.open contract")
        if self.open_error is not None:
            raise self.open_error
        if self.document is None:
            raise AssertionError("fake document missing")
        return self.document


def run_with(fake_fitz: FakeFitz):
    previous = sys.modules.get("fitz")
    sys.modules["fitz"] = fake_fitz
    try:
        return rag_pdf.extract_text(b"pdf-bytes")
    finally:
        if previous is None:
            sys.modules.pop("fitz", None)
        else:
            sys.modules["fitz"] = previous


# Success closes once and keeps the existing extraction result shape.
doc = FakeDocument([
    FakePage("  første side  "),
    FakePage(""),
    FakePage("anden side"),
])
result = run_with(FakeFitz(doc))
check(result == {
    "text": "første side\n\nanden side",
    "pages": 3,
    "chars": len("første side\n\nanden side"),
}, "successful extraction preserves text/pages/chars")
check(doc.close_count == 1, "successful extraction closes the document exactly once")


# A password-protected document used to close through a one-off branch. The
# shared finally must retain that behaviour without a second close.
locked = FakeDocument([], encrypted=True, authenticate_result=False)
try:
    run_with(FakeFitz(locked))
    locked_error = ""
except RuntimeError as exc:
    locked_error = str(exc)
check("password-protected" in locked_error, "locked PDF keeps its explicit error")
check(locked.close_count == 1, "locked PDF closes exactly once")


# The actual leak: page.get_text raised after fitz.open had returned, and the old
# manual close at the bottom was never reached.
broken_page = FakeDocument([
    FakePage("first"),
    FakePage(error=ValueError("broken page tree")),
])
try:
    run_with(FakeFitz(broken_page))
    extraction_error = ""
except RuntimeError as exc:
    extraction_error = str(exc)
check(
    extraction_error == "could not extract PDF text: broken page tree",
    "page failures are normalized to the endpoint RuntimeError contract",
)
check(broken_page.close_count == 1, "page extraction failure still closes the document")


# Authentication itself can fail in a malformed encrypted document. It owns the
# same handle and must follow the same finally path.
broken_auth = FakeDocument(
    [],
    encrypted=True,
    authenticate_error=ValueError("damaged encryption dictionary"),
)
try:
    run_with(FakeFitz(broken_auth))
    auth_error = ""
except RuntimeError as exc:
    auth_error = str(exc)
check(
    auth_error == "could not extract PDF text: damaged encryption dictionary",
    "authentication failures are normalized",
)
check(broken_auth.close_count == 1, "authentication failure still closes the document")


# If open itself fails, no document was acquired and therefore nothing is closed.
try:
    run_with(FakeFitz(open_error=ValueError("not a PDF")))
    open_error = ""
except RuntimeError as exc:
    open_error = str(exc)
check(open_error == "could not open PDF: not a PDF", "open failure keeps its existing error contract")


print(f"\n===== RAG PDF LIFECYCLE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
