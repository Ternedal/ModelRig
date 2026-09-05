"""Read source as CODE, not as text.

Every gate in this repo that asserts "this file contains X" is a substring
test, and a commented-out line is still in the file. Measured on 2026-09-04:
commenting out `AgentStartPolicy.verdictForPlan(` left the Agent 3 dormancy
gate green at 41/41 with the start unguarded, and four mutations of the Unity
renderer left 50 of 50 contracts green while it applied unvalidated frames
over an unauthenticated request.

`code_of` removes comments before the check runs. String literals are
respected, because "http://..." is not a comment, and a `#` inside a Python
string is not either.
"""

from __future__ import annotations

from pathlib import Path

_C_LIKE = {".cs", ".kt", ".java", ".go", ".js", ".ts", ".kts"}
_HASH = {".py", ".ps1", ".sh", ".yml", ".yaml", ".toml"}


def strip_comments(text: str, suffix: str) -> str:
    """Source with comments removed. Unknown suffixes are returned unchanged."""
    if suffix in _C_LIKE:
        return _strip(text, line_marks=("//",), block=("/*", "*/"), verbatim=True)
    if suffix in _HASH:
        return _strip(text, line_marks=("#",), block=None, verbatim=False)
    return text


def code_of(path: Path) -> str:
    return strip_comments(path.read_text(encoding="utf-8"), path.suffix)


def _strip(text: str, *, line_marks: tuple[str, ...], block: tuple[str, str] | None,
           verbatim: bool) -> str:
    out: list[str] = []
    i, n = 0, len(text)
    in_str = in_char = in_verbatim = False
    quote = ""
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_str:
            out.append(c)
            if c == "\\" and not in_verbatim:
                if i + 1 < n:
                    out.append(nxt)
                i += 2
                continue
            if c == quote:
                if in_verbatim and nxt == quote:
                    out.append(nxt)
                    i += 2
                    continue
                in_str = in_verbatim = False
            i += 1
            continue
        if in_char:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(nxt)
                i += 2
                continue
            if c == "'":
                in_char = False
            i += 1
            continue
        if verbatim and c == "@" and nxt == '"':
            in_str = in_verbatim = True
            quote = '"'
            out.append(c); out.append(nxt)
            i += 2
            continue
        if c in ('"', "'"):
            # Python triple quotes: keep the whole literal, comments inside it
            # are not comments.
            if text[i:i + 3] in ('"""', "'''"):
                close = text.find(text[i:i + 3], i + 3)
                end = n if close == -1 else close + 3
                out.append(text[i:end])
                i = end
                continue
            if c == "'" and not verbatim:
                in_str, quote = True, c
            elif c == "'":
                in_char = True
            else:
                in_str, quote = True, c
            out.append(c)
            i += 1
            continue
        if block and text.startswith(block[0], i):
            end = text.find(block[1], i + len(block[0]))
            i = n if end == -1 else end + len(block[1])
            continue
        if any(text.startswith(m, i) for m in line_marks):
            while i < n and text[i] != "\n":
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)
