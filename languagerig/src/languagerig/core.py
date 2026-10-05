"""Small local workspace and provenance primitives; no model/network imports."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


class LanguageRigError(ValueError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace("\xad", "").replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u200b", "")
    return "\n".join(" ".join(line.split()) for line in text.splitlines()).strip()


def write_json(path: Path, value: object) -> None:
    """Atomic replacement, including on Windows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def jsonl(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise LanguageRigError(f"{path.name}:{line_number}: invalid JSON") from exc
            if not isinstance(row, dict):
                raise LanguageRigError(f"{path.name}:{line_number}: expected an object")
            yield row


def write_jsonl(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")


def init_workspace(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for name in ("books", "datasets", "runs", "exports"):
        (path / name).mkdir(exist_ok=True)
    if not (path / "project.json").exists():
        write_json(path / "project.json", {
            "format": "languagerig-project/v1", "created_at": now(), "seed": 42,
        })


def books(workspace: Path) -> list[dict]:
    if not (workspace / "project.json").is_file():
        raise LanguageRigError("Workspace not initialized; run init first.")
    return [read_json(path) for path in sorted((workspace / "books").glob("*/book.json"))]


def book_path(workspace: Path, source_id: str) -> Path:
    if len(source_id) != 64 or any(c not in "0123456789abcdef" for c in source_id):
        raise LanguageRigError("Source ID must be the full SHA-256 shown by inventory.")
    path = workspace / "books" / source_id / "book.json"
    if not path.is_file():
        raise LanguageRigError("Unknown source ID.")
    return path


def label_book(workspace: Path, source_id: str, **changes) -> dict:
    path = book_path(workspace, source_id)
    row = read_json(path)
    for key, value in changes.items():
        if value is not None:
            row[key] = value
    write_json(path, row)
    return {key: value for key, value in row.items() if key != "sections"}
