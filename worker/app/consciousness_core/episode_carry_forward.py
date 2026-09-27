"""C31-E bounded episode carry-forward policy.

Closed/reviewed episode evidence may influence a later workspace only through
explicit reference candidates. This seam never writes Memory4, persists episode
contents, resumes goals, or grants execution/model authority.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .episode_closure_evidence import EpisodeClosureEvidence, episode_closure_evidence_ref
from .episode_experience_review import TrustedEpisodeExperienceReview, trusted_episode_experience_review_ref
from .cycle import WorkspaceCandidate


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
CandidateId = Annotated[str, Field(pattern=r"^wc-[a-f0-9]{32}$")]
UnitInterval = Annotated[float, Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False)]


class EpisodeCarryForwardError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False)


class EpisodeCarryForwardPlan(StrictModel):
    schema: Literal["kaliv-consciousness-core/episode-carry-forward-plan/v1"]
    closure_evidence_ref: NonEmptyRef
    review_ref: NonEmptyRef | None
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    disposition: Literal["OMIT", "ADMIT_REFERENCE"]
    candidate: WorkspaceCandidate | None
    durable_memory_candidate_ref: NonEmptyRef | None
    reference_only: Literal[True]
    automatic_goal_resume: Literal[False]
    episode_contents_persisted: Literal[False]
    memory4_called: Literal[False]
    durable_memory_write_authority: Literal[False]
    identity_authority: Literal[False]
    persistent_state_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    model_authority: Literal[False]
    raw_text_included: Literal[False]
    raw_chain_of_thought_included: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "EpisodeCarryForwardPlan":
        if self.disposition == "ADMIT_REFERENCE" and self.candidate is None:
            raise ValueError("admitted carry-forward requires candidate")
        if self.disposition == "OMIT" and self.candidate is not None:
            raise ValueError("omitted carry-forward cannot carry candidate")
        if self.review_ref is None and self.durable_memory_candidate_ref is not None:
            raise ValueError("durable candidate ref requires reviewed evidence")
        return self


def _canonical_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _candidate_id(seed: Mapping[str, Any]) -> str:
    return "wc-" + hashlib.sha256(_canonical_json(seed)).hexdigest()[:32]


def plan_episode_carry_forward(
    closure_evidence: EpisodeClosureEvidence | Mapping[str, Any],
    *,
    review: TrustedEpisodeExperienceReview | Mapping[str, Any] | None = None,
    salience: float = 0.55,
) -> EpisodeCarryForwardPlan:
    """Create at most one bounded later-attention candidate from explicit refs."""
    try:
        evidence = (
            closure_evidence
            if isinstance(closure_evidence, EpisodeClosureEvidence)
            else EpisodeClosureEvidence.model_validate(closure_evidence)
        )
        reviewed = (
            None
            if review is None
            else review
            if isinstance(review, TrustedEpisodeExperienceReview)
            else TrustedEpisodeExperienceReview.model_validate(review)
        )
    except ValidationError as exc:
        raise EpisodeCarryForwardError("invalid episode carry-forward input") from exc

    if not isinstance(salience, float) or not 0.0 <= salience <= 1.0:
        raise EpisodeCarryForwardError("salience must be a float between 0 and 1")

    closure_ref = episode_closure_evidence_ref(evidence)
    review_ref = None
    durable_candidate_ref = None
    if reviewed is not None:
        if reviewed.closure_evidence_ref != closure_ref:
            raise EpisodeCarryForwardError("review belongs to another closure evidence")
        review_ref = trusted_episode_experience_review_ref(reviewed)
        if reviewed.decision == "APPROVE":
            durable_candidate_ref = reviewed.reviewed_candidate_ref

    admit = evidence.total_moment_count > 0 and (
        reviewed is None or reviewed.decision == "APPROVE"
    )
    candidate = None
    if admit:
        source_ref = review_ref or closure_ref
        candidate = WorkspaceCandidate(
            candidate_id=_candidate_id({
                "closure_evidence_ref": closure_ref,
                "review_ref": review_ref,
                "source_ref": source_ref,
            }),
            kind="memory",
            salience=salience,
            summary=(
                "Reference-only prior episode context is available for bounded "
                "attention; Memory4 remains authoritative for durable memory."
            ),
            source_ref=source_ref,
        )

    return EpisodeCarryForwardPlan(
        schema="kaliv-consciousness-core/episode-carry-forward-plan/v1",
        closure_evidence_ref=closure_ref,
        review_ref=review_ref,
        self_id=evidence.self_id,
        person_revision=evidence.person_revision,
        disposition="ADMIT_REFERENCE" if admit else "OMIT",
        candidate=candidate,
        durable_memory_candidate_ref=durable_candidate_ref,
        reference_only=True,
        automatic_goal_resume=False,
        episode_contents_persisted=False,
        memory4_called=False,
        durable_memory_write_authority=False,
        identity_authority=False,
        persistent_state_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        model_authority=False,
        raw_text_included=False,
        raw_chain_of_thought_included=False,
        production_activation=False,
    )
