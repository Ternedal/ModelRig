#!/usr/bin/env python3
"""Fail-closed loader for the tracked physical-candidate branch pointer."""
from __future__ import annotations

import re
from pathlib import Path

POINTER_NAME = "CANDIDATE_BRANCH"
MAX_BYTES = 256


class CandidateBranchError(RuntimeError):
    pass


def load_candidate_branch(root: Path, version: str) -> str:
    """Return the exact tracked candidate branch for *version*.

    Replacement freezes cannot safely hardcode an old branch in several shims.
    The pointer is committed to main before the named candidate branch is
    created, so every operator and retained validator consumes one authority.
    """
    path = root.resolve() / POINTER_NAME
    if not path.is_file() or path.is_symlink():
        raise CandidateBranchError(f"{POINTER_NAME} is missing or irregular")
    body = path.read_bytes()
    if not body or len(body) > MAX_BYTES:
        raise CandidateBranchError(f"{POINTER_NAME} has invalid size")
    try:
        branch = body.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise CandidateBranchError(f"{POINTER_NAME} is not UTF-8") from exc
    expected = re.compile(
        rf"agent/unified-candidate-{re.escape(version)}(?:-r[1-9][0-9]*)?"
    )
    if expected.fullmatch(branch) is None:
        raise CandidateBranchError(
            f"{POINTER_NAME} does not name a valid {version} candidate branch: {branch!r}"
        )
    return branch
