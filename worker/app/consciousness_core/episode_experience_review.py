"""C30-I trusted review boundary from episode closure evidence to C7 evaluation.

This module never invents a synthetic cognitive cycle for a multi-cycle episode.
A reviewer may bind one real C7 ExperienceCandidate to bounded C30-H closure
reference evidence. The existing C7 handoff policy remains authoritative and no
Memory 4 write is performed here.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .episode_closure_evidence import (
    EpisodeClosureEvidence,
    episode_closure_evidence_ref,
)
from .experience import (
    ExperienceCandidate,
    MemoryHandoffDecision,
    plan_memory_handoff,
)


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
ReviewDisposition = Literal["NO_REVIEW", "TRUSTED_REVIEW_REQUIRED"]
ReviewDecision = Literal["APPROVE", "REJECT"]
ReviewAuthority = Literal["operator_explicit", "trusted_semantic_review"]


class EpisodeExperienceReviewError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class EpisodeExperienceReviewPlan(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-experience-review-plan/v1"
    ]
    closure_evidence_ref: NonEmptyRef
    closed_episode_ref: NonEmptyRef
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_revision: Annotated[
        str,
        Field(pattern=r"^person-r[0-9]{4,}$"),
    ]
    disposition: ReviewDisposition
    retained_moment_count: Annotated[int, Field(ge=0, le=128, strict=True)]
    participant_refs: Annotated[list[NonEmptyRef], Field(max_length=32)]
    active_goal_refs: Annotated[list[NonEmptyRef], Field(max_length=64)]
    salient_source_refs: Annotated[list[NonEmptyRef], Field(max_length=16)]
    raw_text_available: Literal[False]
    raw_chain_of_thought_available: Literal[False]
    completed_turn_authority_available: Literal[False]
    synthetic_cycle_allowed: Literal[False]
    candidate_created: Literal[False]
    memory4_called: Literal[False]
    durable_memory_write_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_disposition(self) -> "EpisodeExperienceReviewPlan":
        expected = (
            "NO_REVIEW"
            if self.retained_moment_count == 0
            else "TRUSTED_REVIEW_REQUIRED"
        )
        if self.disposition != expected:
            raise ValueError("episode experience review disposition is invalid")
        return self


class TrustedEpisodeExperienceReview(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/trusted-episode-experience-review/v1"
    ]
    review_id: Annotated[
        str,
        Field(pattern=r"^erev-[a-f0-9]{32}$"),
    ]
    closure_evidence_ref: NonEmptyRef
    decision: ReviewDecision
    authority: ReviewAuthority
    reviewer_source_ref: NonEmptyRef
    reviewed_candidate_ref: NonEmptyRef | None
    raw_text_asserted_from_closure_evidence: Literal[False]
    completed_turn_authority_asserted: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "TrustedEpisodeExperienceReview":
        if self.decision == "APPROVE":
            if self.reviewed_candidate_ref is None:
                raise ValueError("APPROVE review requires candidate binding")
        elif self.reviewed_candidate_ref is not None:
            raise ValueError("REJECT review cannot bind a candidate")
        return self


class EpisodeExperienceCandidateEvaluation(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-experience-candidate-evaluation/v1"
    ]
    closure_evidence_ref: NonEmptyRef
    review_ref: NonEmptyRef
    accepted_for_c7_evaluation: bool
    candidate_ref: NonEmptyRef | None
    c7_handoff: MemoryHandoffDecision | None
    candidate_persisted: Literal[False]
    memory4_called: Literal[False]
    completed_turn_authority_granted: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "EpisodeExperienceCandidateEvaluation":
        if self.accepted_for_c7_evaluation:
            if self.candidate_ref is None or self.c7_handoff is None:
                raise ValueError(
                    "accepted episode candidate evaluation is incomplete"
                )
            if self.c7_handoff.status != "trusted_review_required":
                raise ValueError(
                    "episode-derived candidate cannot gain automatic C7 write authority"
                )
        elif self.candidate_ref is not None or self.c7_handoff is not None:
            raise ValueError(
                "rejected episode candidate evaluation cannot retain candidate/handoff"
            )
        return self


def _canonical_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def trusted_episode_experience_review_ref(
    review: TrustedEpisodeExperienceReview,
) -> str:
    if not isinstance(review, TrustedEpisodeExperienceReview):
        raise TypeError("review must be TrustedEpisodeExperienceReview")
    return "episode-experience-review:" + _digest(review)


def experience_candidate_ref(candidate: ExperienceCandidate) -> str:
    if not isinstance(candidate, ExperienceCandidate):
        raise TypeError("candidate must be ExperienceCandidate")
    return f"experience:{candidate.experience_id}"


def _validate_evidence(
    evidence: EpisodeClosureEvidence | Mapping[str, Any],
) -> EpisodeClosureEvidence:
    try:
        return (
            evidence
            if isinstance(evidence, EpisodeClosureEvidence)
            else EpisodeClosureEvidence.model_validate(evidence)
        )
    except ValidationError as exc:
        raise EpisodeExperienceReviewError(
            "invalid episode closure evidence"
        ) from exc


def plan_episode_experience_review(
    evidence: EpisodeClosureEvidence | Mapping[str, Any],
) -> EpisodeExperienceReviewPlan:
    """Plan review without creating a C7 candidate or invoking Memory 4."""
    value = _validate_evidence(evidence)
    retained = value.retained_moment_count
    return EpisodeExperienceReviewPlan(
        schema=(
            "kaliv-consciousness-core/"
            "episode-experience-review-plan/v1"
        ),
        closure_evidence_ref=episode_closure_evidence_ref(value),
        closed_episode_ref=value.closed_episode_ref,
        self_id=value.self_id,
        person_revision=value.person_revision,
        disposition=(
            "NO_REVIEW"
            if retained == 0
            else "TRUSTED_REVIEW_REQUIRED"
        ),
        retained_moment_count=retained,
        participant_refs=list(value.participant_refs),
        active_goal_refs=list(value.active_goal_refs),
        salient_source_refs=list(value.salient_source_refs),
        raw_text_available=False,
        raw_chain_of_thought_available=False,
        completed_turn_authority_available=False,
        synthetic_cycle_allowed=False,
        candidate_created=False,
        memory4_called=False,
        durable_memory_write_authority=False,
        production_activation=False,
    )


def evaluate_reviewed_episode_candidate(
    evidence: EpisodeClosureEvidence | Mapping[str, Any],
    review: TrustedEpisodeExperienceReview | Mapping[str, Any],
    candidate: ExperienceCandidate | Mapping[str, Any] | None = None,
) -> EpisodeExperienceCandidateEvaluation:
    """Admit a reviewer-bound real C7 candidate without persisting it."""
    value = _validate_evidence(evidence)
    try:
        trusted = (
            review
            if isinstance(review, TrustedEpisodeExperienceReview)
            else TrustedEpisodeExperienceReview.model_validate(review)
        )
        item = (
            None
            if candidate is None
            else candidate
            if isinstance(candidate, ExperienceCandidate)
            else ExperienceCandidate.model_validate(candidate)
        )
    except ValidationError as exc:
        raise EpisodeExperienceReviewError(
            "invalid episode experience review input"
        ) from exc

    evidence_ref = episode_closure_evidence_ref(value)
    if trusted.closure_evidence_ref != evidence_ref:
        raise EpisodeExperienceReviewError(
            "review belongs to another episode closure evidence object"
        )
    review_ref = trusted_episode_experience_review_ref(trusted)

    if trusted.decision == "REJECT":
        if item is not None:
            raise EpisodeExperienceReviewError(
                "rejected review cannot carry an ExperienceCandidate"
            )
        return EpisodeExperienceCandidateEvaluation(
            schema=(
                "kaliv-consciousness-core/"
                "episode-experience-candidate-evaluation/v1"
            ),
            closure_evidence_ref=evidence_ref,
            review_ref=review_ref,
            accepted_for_c7_evaluation=False,
            candidate_ref=None,
            c7_handoff=None,
            candidate_persisted=False,
            memory4_called=False,
            completed_turn_authority_granted=False,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )

    if value.memory_review_disposition == "NO_MOMENTS":
        raise EpisodeExperienceReviewError(
            "empty episode closure cannot approve an experience candidate"
        )
    if item is None:
        raise EpisodeExperienceReviewError(
            "approved review requires a real ExperienceCandidate"
        )

    item_ref = experience_candidate_ref(item)
    if trusted.reviewed_candidate_ref != item_ref:
        raise EpisodeExperienceReviewError(
            "review candidate binding mismatch"
        )
    if item.self_id != value.self_id:
        raise EpisodeExperienceReviewError(
            "ExperienceCandidate belongs to another self"
        )
    if item.person_revision != value.person_revision:
        raise EpisodeExperienceReviewError(
            "ExperienceCandidate belongs to another Person Revision"
        )
    if item.event_ref != value.closed_episode_ref:
        raise EpisodeExperienceReviewError(
            "ExperienceCandidate event_ref must bind the closed episode"
        )
    if evidence_ref not in item.source_refs:
        raise EpisodeExperienceReviewError(
            "ExperienceCandidate must include closure evidence provenance"
        )
    if not set(item.participant_refs).issubset(value.participant_refs):
        raise EpisodeExperienceReviewError(
            "ExperienceCandidate introduces unobserved episode participants"
        )
    if not set(item.active_goal_refs).issubset(value.active_goal_refs):
        raise EpisodeExperienceReviewError(
            "ExperienceCandidate introduces unobserved episode goals"
        )

    # C30-H deliberately discarded raw turn text. C30-I must not launder that
    # structural evidence back into the privileged C7 completed-turn path.
    if item.kind == "USER_STATED_FACT":
        raise EpisodeExperienceReviewError(
            "episode closure evidence cannot reconstruct USER_STATED_FACT"
        )
    if item.completed_turn_source_ref is not None:
        raise EpisodeExperienceReviewError(
            "episode closure review cannot assert completed-turn authority"
        )
    if item.provenance_kind not in {"inferred", "shared_event"}:
        raise EpisodeExperienceReviewError(
            "episode closure review cannot promote source provenance"
        )

    handoff = plan_memory_handoff(item)
    if handoff.status != "trusted_review_required":
        raise EpisodeExperienceReviewError(
            "episode-derived candidate unexpectedly gained C7 write authority"
        )

    return EpisodeExperienceCandidateEvaluation(
        schema=(
            "kaliv-consciousness-core/"
            "episode-experience-candidate-evaluation/v1"
        ),
        closure_evidence_ref=evidence_ref,
        review_ref=review_ref,
        accepted_for_c7_evaluation=True,
        candidate_ref=item_ref,
        c7_handoff=handoff,
        candidate_persisted=False,
        memory4_called=False,
        completed_turn_authority_granted=False,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        production_activation=False,
    )
