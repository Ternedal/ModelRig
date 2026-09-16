"""What code is this worker actually running? (F-508).

The source fingerprint remains the compatibility identity used by the existing
physical-validation chain. A packed worker additionally reports the exact Git
commit stamped at pack time plus the SHA-256 of the executable artifact that is
currently running. Those extra fields are additive: existing callers that only
consume ``code_sha256`` and ``frozen`` keep the same contract.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

_APP = Path(__file__).resolve().parent
_REPO = _APP.parents[1]
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UNSET = object()
_cached: str | None = None
_commit_cached: str | None | object = _UNSET
_artifact_cached: str | None | object = _UNSET


# Written by scripts/stamp_build_identity.py immediately before PyInstaller
# packs the worker, and EXCLUDED from the source hash below.
_STAMP = _APP / "_build_stamp.py"


def _canonical_bytes(path: "Path") -> bytes:
    """The bytes of a source file with line endings normalized to LF (F-726)."""
    return path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _hash_source_tree() -> str:
    """Fingerprint every worker module that can execute on the rig."""
    h = hashlib.sha256()
    for path in sorted(_APP.rglob("*.py")):
        if "__pycache__" in path.parts or path.name == "_build_stamp.py":
            continue
        rel = path.relative_to(_APP).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(hashlib.sha256(_canonical_bytes(path)).digest())
    return h.hexdigest()


def _frozen_identity() -> str:
    """Source identity stamped into a correctly packed worker (F-607)."""
    try:
        from ._build_stamp import CODE_SHA256  # type: ignore[attr-defined]
    except ImportError as exc:  # pragma: no cover - only on a mis-built exe
        raise RuntimeError(
            "denne pakkede worker har intet build-stempel: den kan ikke sige "
            "hvilken kode den er bygget af, og kan derfor ikke indgå i fysisk "
            "validering (kør scripts/stamp_build_identity.py før PyInstaller)"
        ) from exc
    if not isinstance(CODE_SHA256, str) or _HEX64.fullmatch(CODE_SHA256) is None:
        raise RuntimeError("worker build-stemplets CODE_SHA256 er ugyldigt")
    return CODE_SHA256


def _frozen_commit() -> str:
    """Exact Git commit stamped into the packed worker at build time."""
    try:
        from ._build_stamp import COMMIT_SHA  # type: ignore[attr-defined]
    except ImportError as exc:  # pragma: no cover - only on a mis-built exe
        raise RuntimeError(
            "denne pakkede worker mangler commit-identitet i build-stemplet"
        ) from exc
    if not isinstance(COMMIT_SHA, str) or _HEX40.fullmatch(COMMIT_SHA) is None:
        raise RuntimeError("worker build-stemplets COMMIT_SHA er ugyldigt")
    return COMMIT_SHA


def _source_commit() -> str | None:
    """Best-effort source-checkout commit for non-frozen developer runtimes."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_REPO,
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip().lower()
    return value if _HEX40.fullmatch(value) is not None else None


def code_fingerprint() -> str:
    """Stable identity of the worker code this process is running."""
    global _cached
    if _cached is None:
        _cached = (
            _frozen_identity()
            if getattr(sys, "frozen", False)
            else _hash_source_tree()
        )
    return _cached


def commit_identity() -> str | None:
    """Commit identity of this runtime; packed workers must always have one."""
    global _commit_cached
    if _commit_cached is _UNSET:
        _commit_cached = (
            _frozen_commit() if getattr(sys, "frozen", False) else _source_commit()
        )
    value = _commit_cached
    return value if isinstance(value, str) else None


def artifact_fingerprint() -> str | None:
    """SHA-256 of the packed executable currently running.

    Source-mode Python has no single immutable artifact, so it reports ``None``.
    A frozen PyInstaller process is one executable and is hashed once per process.
    """
    global _artifact_cached
    if _artifact_cached is _UNSET:
        if not getattr(sys, "frozen", False):
            _artifact_cached = None
        else:
            try:
                executable = Path(sys.executable).resolve(strict=True)
                h = hashlib.sha256()
                with executable.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        h.update(chunk)
                _artifact_cached = h.hexdigest()
            except OSError as exc:  # pragma: no cover - physical runtime only
                raise RuntimeError("worker executable kunne ikke hashes") from exc
    value = _artifact_cached
    if value is not None and (
        not isinstance(value, str) or _HEX64.fullmatch(value) is None
    ):
        raise RuntimeError("worker artifact SHA-256 er ugyldig")
    return value if isinstance(value, str) else None


def describe() -> dict:
    """Build identity published through ``/health/full``.

    ``code_sha256`` and ``frozen`` are the established fields. ``commit_sha``
    and ``artifact_sha256`` add immutable build/runtime identity for ADR-DC-084.
    """
    return {
        "code_sha256": code_fingerprint(),
        "commit_sha": commit_identity(),
        "artifact_sha256": artifact_fingerprint(),
        "frozen": bool(getattr(sys, "frozen", False)),
    }
