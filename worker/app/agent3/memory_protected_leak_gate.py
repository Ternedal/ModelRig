from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

LEAK_REPORT_SCHEMA = "kaliv-agent3-memory-protected-leak-gate/v1"
MAX_SCAN_BYTES = 64 * 1024 * 1024
_SENSITIVE_SQL_COLUMNS = frozenset(
    {"value", "source_ref", "value_protected", "source_ref_protected"}
)
_FORBIDDEN_RUNTIME_SYMBOLS = (
    "memory_protected_reader",
    "memory_protected_writer",
    "ProtectedMemoryReader",
    "ProtectedMemoryWriter",
)
_RUNTIME_BOUNDARY_FILES = (
    "worker/app/agent3/production_mount.py",
    "worker/app/agent3/planner.py",
    "worker/app/agent3/memory_api.py",
    "worker/app/agent3/outcome_answer.py",
    "worker/app/agent3/outcome_context.py",
)


class ProtectedMemoryLeakGateError(RuntimeError):
    """Leak evidence cannot be evaluated without weakening the boundary."""


@dataclass(frozen=True)
class ProtectedMemoryLeakFinding:
    surface: str
    kind: str
    canary_sha256: str | None = None
    location: str | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canary_map(canaries: Iterable[str]) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for value in canaries:
        if not isinstance(value, str):
            raise ProtectedMemoryLeakGateError("canaries must be strings")
        if len(value) < 12 or len(value) > 20_000:
            raise ProtectedMemoryLeakGateError(
                "canaries must contain between 12 and 20000 characters"
            )
        encoded = value.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        if digest in result:
            raise ProtectedMemoryLeakGateError("canaries must be unique")
        result[digest] = encoded
    if not result:
        raise ProtectedMemoryLeakGateError("at least one canary is required")
    return result


def _surface_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    except (TypeError, ValueError) as exc:
        raise ProtectedMemoryLeakGateError(
            f"surface cannot be rendered safely: {type(exc).__name__}"
        ) from exc
    return rendered.encode("utf-8")


def scan_surface(
    surface: str,
    value: Any,
    *,
    canaries: Iterable[str],
) -> list[ProtectedMemoryLeakFinding]:
    if not isinstance(surface, str) or not surface.strip():
        raise ProtectedMemoryLeakGateError("surface name is required")
    raw = _surface_bytes(value)
    findings: list[ProtectedMemoryLeakFinding] = []
    for digest, encoded in _canary_map(canaries).items():
        if encoded in raw:
            findings.append(
                ProtectedMemoryLeakFinding(
                    surface=surface.strip(),
                    kind="plaintext_canary",
                    canary_sha256=digest,
                    detail="surface contains a protected plaintext canary",
                )
            )
    return findings


def _regular_file(path: Path, *, allow_empty: bool = False) -> bytes:
    if path.is_symlink():
        raise ProtectedMemoryLeakGateError(f"scan path is a symlink: {path}")
    if not path.is_file():
        raise ProtectedMemoryLeakGateError(f"scan path is not a regular file: {path}")
    size = path.stat().st_size
    if size == 0 and allow_empty:
        return b""
    if size <= 0 or size > MAX_SCAN_BYTES:
        raise ProtectedMemoryLeakGateError(
            f"scan path size is outside 1..{MAX_SCAN_BYTES}: {path}"
        )
    return path.read_bytes()


def scan_sqlite_family(
    database: str | Path,
    *,
    canaries: Iterable[str],
    backups: Iterable[str | Path] = (),
) -> list[ProtectedMemoryLeakFinding]:
    db = Path(database)
    candidates: list[tuple[Path, bool]] = [
        (db, False),
        (Path(str(db) + "-wal"), True),
        (Path(str(db) + "-shm"), True),
        (Path(str(db) + "-journal"), True),
        *((Path(value), False) for value in backups),
    ]
    findings: list[ProtectedMemoryLeakFinding] = []
    canary_bytes = _canary_map(canaries)
    seen: set[Path] = set()
    for path, allow_empty in candidates:
        resolved = path.resolve(strict=False)
        if resolved in seen or not path.exists():
            continue
        seen.add(resolved)
        raw = _regular_file(path, allow_empty=allow_empty)
        for digest, encoded in canary_bytes.items():
            if encoded in raw:
                findings.append(
                    ProtectedMemoryLeakFinding(
                        surface="sqlite_family",
                        kind="plaintext_canary",
                        canary_sha256=digest,
                        location=path.name,
                        detail="SQLite database, journal or backup contains plaintext",
                    )
                )
    return findings


def scan_sensitive_schema_objects(
    database: str | Path,
) -> list[ProtectedMemoryLeakFinding]:
    path = Path(database)
    if path.is_symlink() or not path.is_file():
        raise ProtectedMemoryLeakGateError(
            "schema scan requires a regular SQLite database"
        )
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT type,name,sql FROM sqlite_master "
            "WHERE type IN ('index','trigger','view') ORDER BY type,name"
        ).fetchall()
    finally:
        connection.close()
    findings: list[ProtectedMemoryLeakFinding] = []
    for object_type, name, sql in rows:
        if not isinstance(sql, str):
            continue
        tokens = {token.lower() for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", sql)}
        sensitive = sorted(tokens & _SENSITIVE_SQL_COLUMNS)
        if sensitive:
            findings.append(
                ProtectedMemoryLeakFinding(
                    surface="sqlite_schema",
                    kind="sensitive_projection",
                    location=str(name),
                    detail=(
                        f"{object_type} references protected/plaintext value columns: "
                        + ",".join(sensitive)
                    ),
                )
            )
    return findings


def scan_runtime_mounts(
    repository_root: str | Path,
    *,
    files: Iterable[str] = _RUNTIME_BOUNDARY_FILES,
) -> list[ProtectedMemoryLeakFinding]:
    root = Path(repository_root)
    findings: list[ProtectedMemoryLeakFinding] = []
    for relative in files:
        path = root / relative
        raw = _regular_file(path).decode("utf-8", "strict")
        for symbol in _FORBIDDEN_RUNTIME_SYMBOLS:
            if symbol in raw:
                findings.append(
                    ProtectedMemoryLeakFinding(
                        surface="runtime_mounts",
                        kind="implicit_mount",
                        location=relative,
                        detail=(
                            "protected store symbol is present before a dedicated "
                            "authorization/promotion slice: "
                            + symbol
                        ),
                    )
                )
    return findings


def build_leak_report(
    *,
    database: str | Path,
    canaries: Iterable[str],
    surfaces: Mapping[str, Any],
    repository_root: str | Path,
    backups: Iterable[str | Path] = (),
    runtime_files: Iterable[str] = _RUNTIME_BOUNDARY_FILES,
) -> dict[str, Any]:
    canary_values = tuple(canaries)
    canary_digests = sorted(_canary_map(canary_values))
    findings: list[ProtectedMemoryLeakFinding] = []
    for name, value in surfaces.items():
        findings.extend(scan_surface(name, value, canaries=canary_values))
    findings.extend(
        scan_sqlite_family(database, canaries=canary_values, backups=backups)
    )
    findings.extend(scan_sensitive_schema_objects(database))
    findings.extend(scan_runtime_mounts(repository_root, files=runtime_files))
    ordered = sorted(
        findings,
        key=lambda item: (
            item.surface,
            item.kind,
            item.location or "",
            item.canary_sha256 or "",
        ),
    )
    return {
        "schema": LEAK_REPORT_SCHEMA,
        "success": not ordered,
        "canary_sha256s": canary_digests,
        "surfaces_checked": sorted(surfaces),
        "sqlite_family_checked": True,
        "sensitive_schema_objects_checked": True,
        "runtime_mounts_checked": list(runtime_files),
        "findings": [item.to_dict() for item in ordered],
        "production_activation": False,
    }
