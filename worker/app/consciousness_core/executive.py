"""C16 model-independent cognitive executive for Consciousness Core.

The external ThoughtEngine proposes cognition. This module decides what the Core
may accept as bounded cognitive output and what must instead be verified,
re-queried, decomposed, or held. It never executes tools, schedules work, writes
Memory 4, mutates SelfState, or actuates BodyRig/VoiceRig.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .contracts import CandidateIntention, Hypothesis, ThoughtProposal
from .cycle import (
    CognitiveCycleResult,
    CognitiveWorkspace,
    proposal_ref,
    workspace_ref,
)
from .goals import GoalRecord
from .metacognition import (
    MetacognitiveState,
    PredictionRecord,
    prediction_from_proposal,
)


UnitInterval = Annotated[
    float,
    Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False),
]
NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
BoundedText = Annotated[str, Field(min_length=1, max_length=4096)]

AdjudicationDecision = Literal[
    "ACCEPT_COGNITION",
    "VERIFY",
    "REQUERY",
    "DECOMPOSE",
    "HOLD",
]


class CognitiveExecutiveError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class ExecutivePolicy(StrictModel):
    """Model-independent deterministic policy for one C16 adjudication."""

    schema: Literal["kaliv-consciousness-core/executive-policy/v1"] = "kaliv-consciousness-core/executive-policy/v1"
    hold_uncertainty_threshold: UnitInterval = 0.85
    verify_uncertainty_threshold: UnitInterval = 0.45
    verify_task_uncertainty_threshold: UnitInterval = 0.60
    allow_verify_memory_queries: bool = True
    production_activation: Literal[False] = False


class ExecutiveHypothesisCandidate(StrictModel):
    schema: Literal["kaliv-consciousness-core/executive-hypothesis-candidate/v1"]
    candidate_id: Annotated[str, Field(pattern=r"^xhyp-[a-f0-9]{32}$")]
    summary: BoundedText
    model_confidence: UnitInterval
    effective_confidence: UnitInterval
    proposal_ref: NonEmptyRef
    accepted_as_fact: Literal[False]
    production_activation: Literal[False]


class ExecutiveIntentionCandidate(StrictModel):
    schema: Literal["kaliv-consciousness-core/executive-intention-candidate/v1"]
    candidate_id: Annotated[str, Field(pattern=r"^xint-[a-f0-9]{32}$")]
    summary: BoundedText
    model_confidence: UnitInterval
    effective_confidence: UnitInterval
    required_authority: Literal[
        "none",
        "agent3",
        "bodyrig",
        "voicerig",
        "memory4",
        "human_review",
    ]
    active_goal_ref: NonEmptyRef | None
    proposal_ref: NonEmptyRef
    selected: Literal[False]
    dispatched: Literal[False]
    execution_authority: Literal[False]
    production_activation: Literal[False]


class ExecutiveMemoryQueryCandidate(StrictModel):
    schema: Literal["kaliv-consciousness-core/executive-memory-query/v1"]
    query_id: Annotated[str, Field(pattern=r"^xmq-[a-f0-9]{32}$")]
    query: BoundedText
    proposal_ref: NonEmptyRef
    required_authority: Literal["memory4"]
    read_requested: Literal[False]
    durable_write_authority: Literal[False]
    production_activation: Literal[False]


class ExecutiveSemanticIntentCandidate(StrictModel):
    schema: Literal["kaliv-consciousness-core/executive-semantic-intent/v1"]
    intent_id: Annotated[str, Field(pattern=r"^xsem-[a-f0-9]{32}$")]
    channel: Literal["response", "body"]
    semantic_intent: BoundedText
    proposal_ref: NonEmptyRef
    dispatch_authority: Literal[False]
    production_activation: Literal[False]


class AdjudicationReceipt(StrictModel):
    schema: Literal["kaliv-consciousness-core/adjudication-receipt/v1"]
    adjudication_id: Annotated[str, Field(pattern=r"^adj-[a-f0-9]{32}$")]
    cycle_id: Annotated[str, Field(pattern=r"^cycle-[a-f0-9]{32}$")]
    request_id: Annotated[str, Field(pattern=r"^thinkreq-[a-f0-9]{32}$")]
    proposal_ref: NonEmptyRef
    workspace_ref: NonEmptyRef
    metacognitive_state_ref: NonEmptyRef
    policy_ref: NonEmptyRef
    active_goal_ref: NonEmptyRef | None
    decision: AdjudicationDecision
    reasons: Annotated[list[BoundedText], Field(min_length=1, max_length=16)]
    accepted_attention_refs: Annotated[list[NonEmptyRef], Field(max_length=32)]
    rejected_attention_refs: Annotated[list[NonEmptyRef], Field(max_length=32)]
    confidence_ceiling: UnitInterval
    confidence_clipped_count: Annotated[int, Field(ge=0, strict=True)]
    hypothesis_candidate_count: Annotated[int, Field(ge=0, strict=True)]
    intention_candidate_count: Annotated[int, Field(ge=0, strict=True)]
    prediction_candidate_count: Annotated[int, Field(ge=0, strict=True)]
    memory_query_candidate_count: Annotated[int, Field(ge=0, strict=True)]
    semantic_intent_candidate_count: Annotated[int, Field(ge=0, strict=True)]
    self_state_mutation_applied: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    durable_memory_write_authority: Literal[False]
    body_actuation_authority: Literal[False]
    voice_actuation_authority: Literal[False]
    production_activation: Literal[False]


class CognitiveExecutiveResult(StrictModel):
    schema: Literal["kaliv-consciousness-core/executive-result/v1"]
    receipt: AdjudicationReceipt
    hypotheses: Annotated[list[ExecutiveHypothesisCandidate], Field(max_length=32)]
    intentions: Annotated[list[ExecutiveIntentionCandidate], Field(max_length=32)]
    predictions: Annotated[list[PredictionRecord], Field(max_length=32)]
    memory_queries: Annotated[list[ExecutiveMemoryQueryCandidate], Field(max_length=32)]
    semantic_intents: Annotated[
        list[ExecutiveSemanticIntentCandidate],
        Field(max_length=2),
    ]
    production_activation: Literal[False]


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


def _ref(kind: str, value: Any) -> str:
    return f"{kind}:{_digest(value)}"


def metacognitive_state_ref(
    state: MetacognitiveState | Mapping[str, Any],
) -> str:
    parsed = (
        state
        if isinstance(state, MetacognitiveState)
        else MetacognitiveState.model_validate(state)
    )
    return _ref("metacognitive-state", parsed)


def executive_policy_ref(
    policy: ExecutivePolicy | Mapping[str, Any],
) -> str:
    parsed = (
        policy
        if isinstance(policy, ExecutivePolicy)
        else ExecutivePolicy.model_validate(policy)
    )
    return _ref("executive-policy", parsed)


def _effective_confidence(model_confidence: float, ceiling: float) -> float:
    return min(model_confidence, ceiling)


def _hypothesis_candidate(
    item: Hypothesis,
    *,
    index: int,
    proposal_reference: str,
    ceiling: float,
) -> ExecutiveHypothesisCandidate:
    seed = {
        "proposal_ref": proposal_reference,
        "kind": "hypothesis",
        "index": index,
        "summary": item.summary,
    }
    return ExecutiveHypothesisCandidate(
        schema="kaliv-consciousness-core/executive-hypothesis-candidate/v1",
        candidate_id="xhyp-" + _digest(seed)[:32],
        summary=item.summary,
        model_confidence=item.confidence,
        effective_confidence=_effective_confidence(item.confidence, ceiling),
        proposal_ref=proposal_reference,
        accepted_as_fact=False,
        production_activation=False,
    )


def _intention_candidate(
    item: CandidateIntention,
    *,
    index: int,
    proposal_reference: str,
    ceiling: float,
    active_goal_ref: str | None,
) -> ExecutiveIntentionCandidate:
    seed = {
        "proposal_ref": proposal_reference,
        "kind": "intention",
        "index": index,
        "summary": item.summary,
        "authority": item.required_authority,
        "active_goal_ref": active_goal_ref,
    }
    return ExecutiveIntentionCandidate(
        schema="kaliv-consciousness-core/executive-intention-candidate/v1",
        candidate_id="xint-" + _digest(seed)[:32],
        summary=item.summary,
        model_confidence=item.confidence,
        effective_confidence=_effective_confidence(item.confidence, ceiling),
        required_authority=item.required_authority,
        active_goal_ref=active_goal_ref,
        proposal_ref=proposal_reference,
        selected=False,
        dispatched=False,
        execution_authority=False,
        production_activation=False,
    )


def _memory_query_candidate(
    query: str,
    *,
    index: int,
    proposal_reference: str,
) -> ExecutiveMemoryQueryCandidate:
    seed = {
        "proposal_ref": proposal_reference,
        "kind": "memory-query",
        "index": index,
        "query": query,
    }
    return ExecutiveMemoryQueryCandidate(
        schema="kaliv-consciousness-core/executive-memory-query/v1",
        query_id="xmq-" + _digest(seed)[:32],
        query=query,
        proposal_ref=proposal_reference,
        required_authority="memory4",
        read_requested=False,
        durable_write_authority=False,
        production_activation=False,
    )


def _semantic_candidate(
    *,
    channel: Literal["response", "body"],
    semantic_intent: str,
    proposal_reference: str,
) -> ExecutiveSemanticIntentCandidate:
    seed = {
        "proposal_ref": proposal_reference,
        "channel": channel,
        "semantic_intent": semantic_intent,
    }
    return ExecutiveSemanticIntentCandidate(
        schema="kaliv-consciousness-core/executive-semantic-intent/v1",
        intent_id="xsem-" + _digest(seed)[:32],
        channel=channel,
        semantic_intent=semantic_intent,
        proposal_ref=proposal_reference,
        dispatch_authority=False,
        production_activation=False,
    )


def _meaningful_proposal(proposal: ThoughtProposal) -> bool:
    return bool(
        proposal.interpretation.strip()
        or proposal.hypotheses
        or proposal.candidate_intentions
        or proposal.predicted_outcomes
        or proposal.questions
        or proposal.memory_queries
        or proposal.attention_suggestions
        or proposal.response_intent
        or proposal.body_intent
    )


def _validate_active_goal(
    goal: GoalRecord | Mapping[str, Any] | None,
    cycle: CognitiveCycleResult,
) -> GoalRecord | None:
    if goal is None:
        return None
    try:
        parsed = goal if isinstance(goal, GoalRecord) else GoalRecord.model_validate(goal)
    except ValidationError as exc:
        raise CognitiveExecutiveError("invalid active GoalRecord") from exc

    if parsed.status != "active":
        raise CognitiveExecutiveError("executive may bind only an active goal")
    if parsed.self_id != cycle.receipt.self_id:
        raise CognitiveExecutiveError("active goal belongs to another self")
    if parsed.person_revision != cycle.receipt.person_revision:
        raise CognitiveExecutiveError("active goal belongs to another Person Revision")
    return parsed


def _validate_cycle_binding(
    cycle: CognitiveCycleResult,
    workspace: CognitiveWorkspace,
) -> None:
    request = cycle.request
    proposal = cycle.proposal
    receipt = cycle.receipt

    if proposal.request_id != request.request_id:
        raise CognitiveExecutiveError("proposal/request binding mismatch")
    if receipt.request_id != request.request_id:
        raise CognitiveExecutiveError("cycle receipt/request binding mismatch")
    if receipt.cycle_id != request.cycle_id:
        raise CognitiveExecutiveError("cycle receipt belongs to another cycle")
    if workspace.cycle_id != request.cycle_id:
        raise CognitiveExecutiveError("workspace belongs to another cycle")
    if receipt.workspace_ref != workspace_ref(workspace):
        raise CognitiveExecutiveError("cycle receipt is not bound to this workspace")
    if receipt.proposal_ref != proposal_ref(proposal):
        raise CognitiveExecutiveError("cycle receipt is not bound to this proposal")


def _decision(
    *,
    proposal: ThoughtProposal,
    meta: MetacognitiveState,
    policy: ExecutivePolicy,
    rejected_attention_refs: list[str],
) -> tuple[AdjudicationDecision, list[str]]:
    if rejected_attention_refs:
        return (
            "HOLD",
            ["model attention suggestion references material outside the bound workspace"],
        )
    if meta.decomposition_required:
        return (
            "DECOMPOSE",
            ["Core metacognition requires task decomposition before acceptance"],
        )
    if meta.verification_required:
        return (
            "VERIFY",
            ["Core metacognition requires independent verification"],
        )
    if proposal.uncertainty >= policy.hold_uncertainty_threshold:
        return (
            "HOLD",
            ["proposal uncertainty exceeds the Core hold threshold"],
        )
    if not _meaningful_proposal(proposal):
        return (
            "REQUERY",
            ["proposal contains no usable bounded cognitive output"],
        )
    if (
        proposal.uncertainty >= policy.verify_uncertainty_threshold
        or meta.current_task_uncertainty >= policy.verify_task_uncertainty_threshold
    ):
        return (
            "VERIFY",
            ["uncertainty exceeds the Core verification threshold"],
        )
    return (
        "ACCEPT_COGNITION",
        ["proposal satisfies the current model-independent executive policy"],
    )


def adjudicate_cycle(
    cycle: CognitiveCycleResult | Mapping[str, Any],
    *,
    workspace: CognitiveWorkspace | Mapping[str, Any],
    metacognition: MetacognitiveState | Mapping[str, Any],
    active_goal: GoalRecord | Mapping[str, Any] | None = None,
    policy: ExecutivePolicy | Mapping[str, Any] | None = None,
) -> CognitiveExecutiveResult:
    """Adjudicate one C15 result without granting downstream action authority."""
    try:
        cycle_value = (
            cycle
            if isinstance(cycle, CognitiveCycleResult)
            else CognitiveCycleResult.model_validate(cycle)
        )
        workspace_value = (
            workspace
            if isinstance(workspace, CognitiveWorkspace)
            else CognitiveWorkspace.model_validate(workspace)
        )
        meta = (
            metacognition
            if isinstance(metacognition, MetacognitiveState)
            else MetacognitiveState.model_validate(metacognition)
        )
        policy_value = (
            ExecutivePolicy()
            if policy is None
            else policy
            if isinstance(policy, ExecutivePolicy)
            else ExecutivePolicy.model_validate(policy)
        )
    except ValidationError as exc:
        raise CognitiveExecutiveError("invalid C16 executive input") from exc

    _validate_cycle_binding(cycle_value, workspace_value)
    goal = _validate_active_goal(active_goal, cycle_value)

    proposal = cycle_value.proposal
    proposal_reference = proposal_ref(proposal)
    workspace_ids = {item.candidate_id for item in workspace_value.candidates}
    rejected_attention = [
        item for item in proposal.attention_suggestions if item not in workspace_ids
    ]
    accepted_attention = [
        item for item in proposal.attention_suggestions if item in workspace_ids
    ]

    decision, reasons = _decision(
        proposal=proposal,
        meta=meta,
        policy=policy_value,
        rejected_attention_refs=rejected_attention,
    )

    goal_ref = f"goal-record:{goal.goal_id}" if goal is not None else None
    ceiling = meta.confidence_ceiling
    hypotheses: list[ExecutiveHypothesisCandidate] = []
    intentions: list[ExecutiveIntentionCandidate] = []
    predictions: list[PredictionRecord] = []
    memory_queries: list[ExecutiveMemoryQueryCandidate] = []
    semantic_intents: list[ExecutiveSemanticIntentCandidate] = []

    if decision in {"ACCEPT_COGNITION", "VERIFY"}:
        hypotheses = [
            _hypothesis_candidate(
                item,
                index=index,
                proposal_reference=proposal_reference,
                ceiling=ceiling,
            )
            for index, item in enumerate(proposal.hypotheses)
        ]

        for index, item in enumerate(proposal.predicted_outcomes):
            prediction = prediction_from_proposal(
                cycle_value.request,
                proposal,
                outcome_index=index,
                subject_ref=goal_ref or f"cycle:{cycle_value.request.cycle_id}",
                expected_observation_kind="any",
                source_refs=[
                    cycle_value.receipt.proposal_ref,
                    cycle_value.receipt.workspace_ref,
                ],
            )
            if prediction.confidence_before > ceiling:
                prediction = prediction.model_copy(
                    update={"confidence_before": ceiling}
                )
            predictions.append(prediction)

        if decision == "ACCEPT_COGNITION":
            intentions = [
                _intention_candidate(
                    item,
                    index=index,
                    proposal_reference=proposal_reference,
                    ceiling=ceiling,
                    active_goal_ref=goal_ref,
                )
                for index, item in enumerate(proposal.candidate_intentions)
            ]
            memory_queries = [
                _memory_query_candidate(
                    query,
                    index=index,
                    proposal_reference=proposal_reference,
                )
                for index, query in enumerate(proposal.memory_queries)
            ]
            if proposal.response_intent:
                semantic_intents.append(
                    _semantic_candidate(
                        channel="response",
                        semantic_intent=proposal.response_intent,
                        proposal_reference=proposal_reference,
                    )
                )
            if proposal.body_intent:
                semantic_intents.append(
                    _semantic_candidate(
                        channel="body",
                        semantic_intent=proposal.body_intent,
                        proposal_reference=proposal_reference,
                    )
                )
        elif policy_value.allow_verify_memory_queries:
            memory_queries = [
                _memory_query_candidate(
                    query,
                    index=index,
                    proposal_reference=proposal_reference,
                )
                for index, query in enumerate(proposal.memory_queries)
            ]

    clipped_count = sum(
        item.model_confidence > item.effective_confidence
        for item in [*hypotheses, *intentions]
    )
    clipped_count += sum(
        original.confidence > produced.confidence_before
        for original, produced in zip(proposal.predicted_outcomes, predictions)
    )

    meta_ref = metacognitive_state_ref(meta)
    policy_ref = executive_policy_ref(policy_value)
    adjudication_seed = {
        "cycle_id": cycle_value.request.cycle_id,
        "request_id": cycle_value.request.request_id,
        "proposal_ref": proposal_reference,
        "workspace_ref": cycle_value.receipt.workspace_ref,
        "metacognitive_state_ref": meta_ref,
        "policy_ref": policy_ref,
        "active_goal_ref": goal_ref,
        "decision": decision,
        "reasons": reasons,
    }
    receipt = AdjudicationReceipt(
        schema="kaliv-consciousness-core/adjudication-receipt/v1",
        adjudication_id="adj-" + _digest(adjudication_seed)[:32],
        cycle_id=cycle_value.request.cycle_id,
        request_id=cycle_value.request.request_id,
        proposal_ref=proposal_reference,
        workspace_ref=cycle_value.receipt.workspace_ref,
        metacognitive_state_ref=meta_ref,
        policy_ref=policy_ref,
        active_goal_ref=goal_ref,
        decision=decision,
        reasons=reasons,
        accepted_attention_refs=(
            accepted_attention
            if decision in {"ACCEPT_COGNITION", "VERIFY"}
            else []
        ),
        rejected_attention_refs=rejected_attention,
        confidence_ceiling=ceiling,
        confidence_clipped_count=clipped_count,
        hypothesis_candidate_count=len(hypotheses),
        intention_candidate_count=len(intentions),
        prediction_candidate_count=len(predictions),
        memory_query_candidate_count=len(memory_queries),
        semantic_intent_candidate_count=len(semantic_intents),
        self_state_mutation_applied=False,
        execution_authority=False,
        scheduling_authority=False,
        durable_memory_write_authority=False,
        body_actuation_authority=False,
        voice_actuation_authority=False,
        production_activation=False,
    )
    return CognitiveExecutiveResult(
        schema="kaliv-consciousness-core/executive-result/v1",
        receipt=receipt,
        hypotheses=hypotheses,
        intentions=intentions,
        predictions=predictions,
        memory_queries=memory_queries,
        semantic_intents=semantic_intents,
        production_activation=False,
    )
