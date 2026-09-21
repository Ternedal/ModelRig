"""Strict provenance adapter for RSI improvement evidence.

Agent 3's model-eval report does not carry a Git commit SHA.  It does carry the
worker's code_sha256 fingerprint specifically so evidence cannot be confused
between different code trees that happen to share a version.  Keep those two
identities separate: code_sha256 comes from the measured rig; base_sha comes
from repository authority supplied by the operator/caller.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from .improvement_proposal import (
    AGENT3_EVAL_SCHEMA,
    ImprovementProposalError,
    build_agent3_improvement_brief,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def build_verified_agent3_improvement_brief(
    report: Mapping[str, Any],
    *,
    repository: str,
    base_sha: str,
) -> dict[str, Any]:
    """Build a brief only when the eval names the exact measured code identity."""

    if not isinstance(report, Mapping):
        raise ImprovementProposalError("report must be an object")
    if report.get("schema") != AGENT3_EVAL_SCHEMA:
        raise ImprovementProposalError(
            f"report schema must be {AGENT3_EVAL_SCHEMA}"
        )
    backend = report.get("backend")
    if not isinstance(backend, Mapping):
        raise ImprovementProposalError("report.backend must be an object")
    code_sha256 = backend.get("code_sha256")
    if not isinstance(code_sha256, str) or _SHA256.fullmatch(code_sha256) is None:
        raise ImprovementProposalError(
            "report.backend.code_sha256 must be a lowercase SHA-256"
        )
    version = backend.get("version")
    if not isinstance(version, str) or not version or version.strip() != version:
        raise ImprovementProposalError(
            "report.backend.version must be a non-empty canonical string"
        )

    brief = build_agent3_improvement_brief(
        report,
        repository=repository,
        base_sha=base_sha,
    )
    # These are evidence identity, not repository authority.  The report digest
    # already binds them cryptographically; surfacing them in the brief makes
    # the model/reviewer see which measured code produced the gap.
    return {
        **brief,
        "source_code_sha256": code_sha256,
        "source_version": version,
        "base_sha_provenance": "repository-authority-external-to-eval",
    }
