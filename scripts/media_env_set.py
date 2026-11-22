#!/usr/bin/env python3
"""Set a few KEY=VALUE lines in an env file without disturbing anything else in it.

    python scripts/media_env_set.py --file C:\\Rig\\ModelRig\\modelrig.env KEY=VALUE [KEY=VALUE ...]

For the rig's modelrig.env (#2479 review): rewriting the whole file from a shell
(``Set-Content -Encoding ascii``) loses every non-ASCII byte in it, and a backup under a fixed
name is overwritten by the second run, so "roll back" stops meaning "back to the original".

What this does instead:
- Every line that is not one of the named keys keeps its exact bytes: the file's encoding is
  never interpreted, so it cannot be damaged. (UTF-16 with a byte-order mark is decoded and
  written back as the same UTF-16; without a mark it is refused rather than guessed.)
- Existing ``KEY=`` lines for the named keys are removed and one new line per key is appended,
  with the file's own line ending.
- A backup is made first under a name that does not exist yet (``<file>.bak-<UTC time>``,
  created exclusively) -- an earlier backup is never overwritten.
- The new content is written to a temporary file beside the original, read back and checked
  (each key exactly once with its value, every other line unchanged and in order), and only
  then moved into place in one step. On any failure the original is untouched.

Keys are ``[A-Z][A-Z0-9_]*``; values are printable ASCII without line breaks. Nothing else is
accepted, so what is appended is the same bytes in every encoding this handles.
Exit: 0 written (or nothing to change), 2 refused (bad argument, unreadable or UTF-16 without
a mark), 1 failed. Standard library only.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

KEY = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
VALUE = re.compile(r"[\x20-\x7e]{0,2000}")
UTF16 = {b"\xff\xfe": "utf-16-le", b"\xfe\xff": "utf-16-be"}


class Refused(Exception):
    pass


def parse_pairs(items: list[str]) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not KEY.fullmatch(key) or not VALUE.fullmatch(value) or value != value.strip():
            raise Refused(f"not a KEY=VALUE this tool sets: {item[:60]!r}")
        if key in pairs:
            raise Refused(f"{key} is given twice")
        pairs[key] = value
    if not pairs:
        raise Refused("no KEY=VALUE given")
    return pairs


def _split(data: bytes, newline: bytes) -> list[bytes]:
    """Lines with their endings kept, so joining them gives the same bytes back."""
    lines = data.split(newline)
    out = [line + newline for line in lines[:-1]]
    if lines[-1]:
        out.append(lines[-1])
    return out


def rewrite(data: bytes, pairs: dict[str, str]) -> bytes:
    """The file's bytes with the keys set. Pure: the encoding rules live here, the file handling
    in ``apply``."""
    mark = data[:2] if data[:2] in UTF16 else b""
    if mark:
        codec = UTF16[mark]
        try:
            text = data[2:].decode(codec)
        except UnicodeDecodeError:
            raise Refused("the file has a UTF-16 mark but is not valid UTF-16") from None
        body = rewrite(text.encode("utf-8"), pairs).decode("utf-8")
        return mark + body.encode(codec)
    if b"\x00" in data:
        raise Refused("the file contains NUL bytes (UTF-16 without a byte-order mark?): not guessed at")
    bom = b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b""
    rest = data[len(bom):]
    newline = b"\r\n" if rest.count(b"\r\n") * 2 >= rest.count(b"\n") and b"\r\n" in rest else b"\n"
    heads = tuple(key.encode("ascii") + b"=" for key in pairs)
    kept = [line for line in _split(rest, b"\n") if not line.lstrip(b" \t").startswith(heads)]
    if kept and not kept[-1].endswith(b"\n"):
        kept[-1] += newline
    added = [f"{key}={value}".encode("ascii") + newline for key, value in pairs.items()]
    return bom + b"".join(kept) + b"".join(added)


def verify(before: bytes, after: bytes, pairs: dict[str, str]) -> None:
    """What was written is what was meant: each key once, with its value; all else untouched."""
    def text_lines(data: bytes) -> list[bytes]:
        if data[:2] in UTF16:
            data = data[2:].decode(UTF16[data[:2]]).encode("utf-8")
        elif data.startswith(b"\xef\xbb\xbf"):
            data = data[3:]
        return [line.rstrip(b"\r") for line in data.split(b"\n")]

    heads = {key: key.encode("ascii") + b"=" for key in pairs}

    def others(lines: list[bytes]) -> list[bytes]:
        kept = [line for line in lines if not line.lstrip(b" \t").startswith(tuple(heads.values()))]
        while kept and kept[-1] == b"":
            kept.pop()
        return kept
    new = text_lines(after)
    for key, value in pairs.items():
        found = [line for line in new if line.lstrip(b" \t").startswith(heads[key])]
        if found != [heads[key] + value.encode("ascii")]:
            raise RuntimeError(f"verification failed for {key}")
    if others(text_lines(before)) != others(new):
        raise RuntimeError("verification failed: a line that was not asked for changed")


def backup_path(path: Path, stamp: str) -> Path:
    for attempt in range(1000):
        candidate = path.with_name(f"{path.name}.bak-{stamp}" + (f"-{attempt}" if attempt else ""))
        try:
            with open(candidate, "xb"):
                return candidate
        except FileExistsError:
            continue
    raise RuntimeError("no free backup name")


def apply(path: Path, pairs: dict[str, str], *, stamp: str | None = None) -> tuple[Path | None, bool]:
    """``(backup, changed)``. Nothing is written when the file already says what is asked."""
    if path.is_symlink() or not path.is_file():
        raise Refused(f"not a regular file: {path}")
    before = path.read_bytes()
    after = rewrite(before, pairs)
    verify(before, after, pairs)
    if after == before:
        return None, False
    backup = backup_path(path, stamp or time.strftime("%Y%m%d-%H%M%S", time.gmtime()))
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        backup.write_bytes(before)
        if backup.read_bytes() != before:
            raise RuntimeError("the backup does not match the original")
        with open(temporary, "xb") as handle:
            handle.write(after)
            handle.flush()
            os.fsync(handle.fileno())
        verify(before, temporary.read_bytes(), pairs)
        if path.read_bytes() != before:
            raise RuntimeError("the file changed while it was being edited; nothing was replaced")
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    return backup, True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", required=True)
    parser.add_argument("pairs", nargs="+", metavar="KEY=VALUE")
    args = parser.parse_args(argv)
    try:
        pairs = parse_pairs(args.pairs)
        backup, changed = apply(Path(args.file), pairs)
    except Refused as exc:
        print(f"AFVIST: {exc}", file=sys.stderr)
        return 2
    except (OSError, RuntimeError) as exc:
        print(f"FEJL: {exc} - filen er ikke aendret", file=sys.stderr)
        return 1
    for key, value in pairs.items():
        print(f"{key}={value}")
    print(f"BACKUP {backup}" if changed else "UAENDRET: filen sagde det allerede")
    return 0


if __name__ == "__main__":
    sys.exit(main())
