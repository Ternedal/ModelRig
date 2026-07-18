#!/usr/bin/env python3
"""Regression coverage for PyMuPDF document ownership.

PyMuPDF is optional, so the test installs a real ModuleType named ``fitz`` in
``sys.modules``. That exercises the production import and extraction code without
adding the optional dependency or generating a PDF fixture.
"""
from __future__ import annotations

import sys
from types import ModuleType

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
    ) -> None:
        self._pages = pages
        self.is_encrypted = encrypted
        self.authenticate_result = authenticate_result
        self.close_count = 0

    @property
    def page_count(self) -> int:
        return len(self._pages)

    def authenticate(self, password: str) -> bool:
        if password != "":
            raise AssertionError("only empty-password unlock is expected")
        return self.authenticate_result

    def __iter__(self):
        return iter(self._pages)

    def close(self) -> None:
        self.close_count += 1


def run_with(document: FakeDocument):
    fake_fitz = ModuleType("fitz")

    def fake_open(*, stream: bytes, filetype: str) -> FakeDocument:
        if stream != b"pdf-bytes" or filetype != "pdf":
            raise AssertionError("extract_text changed the fitz.open contract")
        return document

    fake_fitz.open = fake_open
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
result = run_with(doc)
expected_text = "første side\n\nanden side"
check(
    result == {"text": expected_text, "pages": 3, "chars": len(expected_text)},
    "successful extraction preserves text/pages/chars",
)
check(doc.close_count == 1, "successful extraction closes the document exactly once")


# Password rejection already had an explicit error. The shared finally must keep
# that contract while ensuring there is no branch-specific double close.
locked = FakeDocument([], encrypted=True, authenticate_result=False)
try:
    run_with(locked)
    locked_error = ""
except RuntimeError as exc:
    locked_error = str(exc)
check("password-protected" in locked_error, "locked PDF keeps its explicit error")
check(locked.close_count == 1, "locked PDF closes exactly once")


# The actual leak: page.get_text raised after fitz.open returned, so the previous
# manual close at the bottom was never reached.
broken_page = FakeDocument([
    FakePage("first"),
    FakePage(error=ValueError("broken page tree")),
])
try:
    run_with(broken_page)
    extraction_error = ""
except RuntimeError as exc:
    extraction_error = str(exc)
check(
    extraction_error == "could not extract PDF text: broken page tree",
    "page failures are normalized to the endpoint RuntimeError contract",
)
check(broken_page.close_count == 1, "page extraction failure still closes the document")


print(f"\n===== RAG PDF LIFECYCLE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
