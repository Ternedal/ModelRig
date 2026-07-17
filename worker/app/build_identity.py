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


def _hash_source_tree() -> str:
    """Fingerprint every module this worker could import.

    Sorted by path so the result is an identity, not an accident of filesystem
    order. Both the path and the content go in: moving a file changes what runs
    even when no byte of it changed.
    """
    h = hashlib.sha256()
    for path in sorted(_APP.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(_APP).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(hashlib.sha256(path.read_bytes()).digest())
    return h.hexdigest()


def _hash_frozen_binary() -> str:
    """A PyInstaller build has no source tree -- the exe IS the code."""
    exe = Path(sys.executable)
    h = hashlib.sha256()
    with exe.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def code_fingerprint() -> str:
    """Stable identity of the code this process is running.

    Cached: it cannot change without a restart, and a running process that
    reports a different fingerprint than it started with would be lying either
    before or after.
    """
    global _cached
    if _cached is None:
        _cached = (_hash_frozen_binary() if getattr(sys, "frozen", False)
                   else _hash_source_tree())
    return _cached


def describe() -> dict:
    """What /health publishes so a report can bind to code instead of a label."""
    return {
        "code_sha256": code_fingerprint(),
        "frozen": bool(getattr(sys, "frozen", False)),
    }
