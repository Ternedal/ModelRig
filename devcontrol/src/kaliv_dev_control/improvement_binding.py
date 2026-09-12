"""Bind a model-authored RSI proposal back to the exact evidence brief.

The proposal contract is intentionally non-authorizing.  This module adds the
second half of that boundary: a syntactically valid proposal is still rejected
unless it refers to the same repository, code SHA, evidence digest and observed
finding ids as the brief that was shown to the model.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from .improvement_proposal import (
    BRIEF_SCHEMA,
    ImprovementProposal,
    ImprovementProposalError,
)


def validate_proposal_against_brief(
    proposal: ImprovementProposal,
    brief: Mapping[str, Any],
) -> ImprovementProposal:
    if not isinstance(proposal, ImprovementProposal):
        raise ImprovementProposalError("proposal must be an ImprovementProposal")
    if not isinstance(brief, Mapping):
        raise ImprovementProposalError("brief must be an object")
    if brief.get("schema") != BRIEF_SCHEMA:
        raise ImprovementProposalError(f"brief schema must be {BRIEF_SCHEMA}")
    if brief.get("authority") != "evidence-only":
        raise ImprovementProposalError("brief authority must remain evidence-only")

    bindings = (
        ("repository", proposal.repository),
        ("base_sha", proposal.base_sha),
        ("source_schema", proposal.source_schema),
        ("evidence_sha256", proposal.evidence_sha256),
    )
    for name, proposed in bindings:
        if brief.get(name) != proposed:
            raise ImprovementProposalError(
                f"proposal {name} is not bound to the supplied brief"
            )

    findings = brief.get("findings")
    if not isinstance(findings, list) or not findings:
        raise ImprovementProposalError("brief has no observed findings to improve")
    available: set[str] = set()
    for index, finding in enumerate(findings):
        if not isinstance(finding, Mapping):
            raise ImprovementProposalError(f"brief.findings[{index}] must be an object")
        finding_id = finding.get("finding_id")
        if not isinstance(finding_id, str) or not finding_id:
            raise ImprovementProposalError(
                f"brief.findings[{index}] is missing finding_id"
            )
        available.add(finding_id)

    unknown = sorted(set(proposal.finding_ids) - available)
    if unknown:
        raise ImprovementProposalError(
            "proposal references findings absent from the supplied brief: "
            + ", ".join(unknown)
        )
    if proposal.source_schema not in proposal.required_evals:
        raise ImprovementProposalError(
            "required_evals must include the source eval schema for regression proof"
        )
    return proposal


def proposal_from_model_json(
    text: str,
    *,
    brief: Mapping[str, Any],
) -> ImprovementProposal:
    """Parse strict model JSON and bind it to the brief in one fail-closed step."""

    proposal = ImprovementProposal.from_json(text)
    return validate_proposal_against_brief(proposal, brief)


def canonical_bound_proposal_json(
    text: str,
    *,
    brief: Mapping[str, Any],
) -> str:
    """Return canonical JSON only after evidence binding succeeds."""

    proposal = proposal_from_model_json(text, brief=brief)
    return proposal.canonical_json()
