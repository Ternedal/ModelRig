"""What code is this worker actually running? (F-508)

A validation report says "I tested a rig calling itself 1.58.78". The gate then
compares that string to the VERSION file and calls it evidence. Two different
trees can carry the same semver -- every commit that does not bump does exactly
that -- so the gate proves the rig agreed about a NUMBER, not that it ran this
software. The report is the gate to everything else; a gate that checks a label
is a gate.

The harness cannot hash the rig's files: it talks to it over HTTP. So the
binding has to come from where the truth is -- the worker reports its own code
identity, the report carries it, and the gate compares it to the tree it is
being asked to bless.

Scope is behaviour, on purpose. Hashing every file would invalidate physical
evidence on a README typo, and a check that cries wolf is a check that gets
waived. What is hashed is what runs on the rig: the worker's own modules. Tests
and documents do not execute there.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

_APP = Path(__file__).resolve().parent
_cached: str | None = None


# Written by scripts/stamp_build_identity.py immediately before PyInstaller
# packs the worker, and EXCLUDED from the hash below -- otherwise stamping the
# tree would change the tree it just measured.
_STAMP = _APP / "_build_stamp.py"


def _canonical_bytes(path: "Path") -> bytes:
    """The bytes of a source file with line endings normalized to LF (F-726).

    The fingerprint used to hash raw bytes, and Git rewrites line endings on
    checkout: with core.autocrlf=true on Windows, a file lands as CRLF; the same
    file on the Linux CI runner and in a plain source checkout lands as LF. Byte-
    identical logical source, two different hashes -- so the code-identity gate
    that stands between here and physical validation (F-607, F-701) would report
    validated_code_mismatch on the rig for a file nobody changed.

    Normalizing CRLF and lone CR to LF before hashing makes the fingerprint a
    property of the source, not of the checkout that produced it. A committed
    .gitattributes keeps the working tree consistent too; this is the second
    line, so a file that slips through with the wrong ending still hashes right.
    """
    return path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _hash_source_tree() -> str:
    """Fingerprint every module this worker could import.

    Sorted by path so the result is an identity, not an accident of filesystem
    order. Both the path and the content go in: moving a file changes what runs
    even when no byte of it changed.
    """
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
    """What a packed worker reports (F-607).

    This used to hash the exe, and that made the whole binding useless: the
    readiness page runs from a source checkout and computes a tree hash, the
    appliance runs frozen and computed a binary hash, and the two are hashes of
    DIFFERENT THINGS. They can never be equal, so code_match on the real Windows
    appliance was False forever -- physical validation, the gate everything else
    waits behind, could not be passed. I shipped that, having written
    `"frozen": bool` into describe() an hour earlier: I knew there were two
    modes and never asked whether they could be compared.

    The identity we want is of the CODE, not of the packaging. So the build
    stamps the source-tree fingerprint in before packing, and a frozen worker
    reports what it was built FROM. Same code, same answer, either side.

    No stamp is fail-loud on purpose: a packed worker that cannot say what it
    was built from cannot take part in physical evidence, and quietly falling
    back to an exe hash is exactly how this was broken in the first place.
    """
    try:
        from ._build_stamp import CODE_SHA256  # type: ignore[attr-defined]
    except ImportError as exc:  # pragma: no cover - only on a mis-built exe
        raise RuntimeError(
            "denne pakkede worker har intet build-stempel: den kan ikke sige "
            "hvilken kode den er bygget af, og kan derfor ikke indgå i fysisk "
            "validering (kør scripts/stamp_build_identity.py før PyInstaller)"
        ) from exc
    return CODE_SHA256


def code_fingerprint() -> str:
    """Stable identity of the code this process is running.

    Cached: it cannot change without a restart, and a running process that
    reports a different fingerprint than it started with would be lying either
    before or after.
    """
    global _cached
    if _cached is None:
        _cached = (_frozen_identity() if getattr(sys, "frozen", False)
                   else _hash_source_tree())
    return _cached


def describe() -> dict:
    """What /health publishes so a report can bind to code instead of a label."""
    return {
        "code_sha256": code_fingerprint(),
        "frozen": bool(getattr(sys, "frozen", False)),
    }
