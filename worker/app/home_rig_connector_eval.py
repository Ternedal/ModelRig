"""Deterministic offline eval for T-038 RigGate/Home Assistant pilot.

The evaluator scores structured status evidence, not prose quality and not live
provider behavior.  It imports the dormant T-038 authority/freshness contract
and has no model, network, route, ToolGate or provider-client dependency.

The default corpus covers issue #85's four mandatory cases exactly once:
status brief, stale data, offline RigGate and an entity outside the explicit
scope.  Cases are digest-bound so stale candidate evidence cannot be replayed
against a changed corpus.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal

from .home_rig_connector_contract import (
    HomeRigObservation,
    HomeRigScope,
    normalize_observation,
)

EVAL_SCHEMA = "kaliv-home-rig-eval/v1"
CANDIDATE_SCHEMA = "kaliv-home-rig-eval-candidate/v1"
RESULT_SCHEMA = "kaliv-home-rig-eval-result/v1"
PRODUCTION_ACTIVATION = False

Scenario = Literal[
    "status_brief",
    "stale_data",
    "offline_riggate",
    "unscoped_entity",
]

_SCENARIOS: tuple[Scenario, ...] = (
    "status_brief",
    "stale_data",
    "offline_riggate",
    "unscoped_entity",
)
_CASE_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,119}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class HomeRigEvalError(ValueError):
    """The deterministic T-038 corpus or candidate is malformed."""


def _canonical(value: dict) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _text(value: str, name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise HomeRigEvalError(f"{name} must be a string")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum:
        raise HomeRigEvalError(f"{name} must contain 1..{maximum} characters")
    return normalized


def _case_id(value: str) -> str:
    if not isinstance(value, str) or not _CASE_ID.fullmatch(value):
        raise HomeRigEvalError("case_id has invalid format")
    return value


@dataclass(frozen=True)
class ExpectedStatus:
    target_kind: Literal["rig", "entity"]
    target_id: str
    operation: Literal["rig_health", "rig_power_readiness", "entity_state"]
    state: str
    freshness: Literal["fresh", "stale", "unavailable"]
    source_id: str

    @classmethod
    def from_observation(cls, observation: HomeRigObservation) -> "ExpectedStatus":
        if not isinstance(observation, HomeRigObservation):
            raise HomeRigEvalError("expected status requires HomeRigObservation")
        return cls(
            target_kind=observation.target_kind,
            target_id=observation.target_id,
            operation=observation.operation,
            state=observation.state,
            freshness=observation.freshness,
            source_id=observation.source_id,
        )

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.target_kind, self.target_id, self.operation)

    def to_dict(self) -> dict:
        return {
            "target_kind": self.target_kind,
            "target_id": self.target_id,
            "operation": self.operation,
            "state": self.state,
            "freshness": self.freshness,
            "source_id": self.source_id,
        }


@dataclass(frozen=True)
class HomeRigEvalCase:
    case_id: str
    scenario: Scenario
    prompt: str
    scope: HomeRigScope
    observations: tuple[HomeRigObservation, ...]
    expected_statuses: tuple[ExpectedStatus, ...]
    expected_denied_targets: tuple[str, ...] = ()
    forbidden_answer_terms: tuple[str, ...] = ()
    schema: str = EVAL_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != EVAL_SCHEMA:
            raise HomeRigEvalError("unsupported home/rig eval schema")
        if self.production_activation is not False:
            raise HomeRigEvalError("production activation must remain false")
        _case_id(self.case_id)
        if self.scenario not in _SCENARIOS:
            raise HomeRigEvalError("unsupported home/rig eval scenario")
        object.__setattr__(self, "prompt", _text(self.prompt, "prompt", 500))
        if not isinstance(self.scope, HomeRigScope):
            raise HomeRigEvalError("eval case requires HomeRigScope")
        if not isinstance(self.observations, tuple) or not self.observations:
            raise HomeRigEvalError("eval case requires observations")
        observation_keys: list[tuple[str, str, str]] = []
        for observation in self.observations:
            if not isinstance(observation, HomeRigObservation):
                raise HomeRigEvalError("eval observations must be typed")
            if not self.scope.allows(
                target_kind=observation.target_kind,
                target_id=observation.target_id,
                operation=observation.operation,
            ):
                raise HomeRigEvalError("eval observation is outside exact scope")
            observation_keys.append(
                (observation.target_kind, observation.target_id, observation.operation)
            )
        if len(observation_keys) != len(set(observation_keys)):
            raise HomeRigEvalError("eval observations contain duplicate status keys")
        if not isinstance(self.expected_statuses, tuple) or not self.expected_statuses:
            raise HomeRigEvalError("eval case requires expected statuses")
        expected_keys = [status.key for status in self.expected_statuses]
        if len(expected_keys) != len(set(expected_keys)):
            raise HomeRigEvalError("expected statuses contain duplicate keys")
        if set(expected_keys) != set(observation_keys):
            raise HomeRigEvalError("expected statuses must cover every scoped observation exactly")
        for expected in self.expected_statuses:
            matching = next(
                item
                for item in self.observations
                if (item.target_kind, item.target_id, item.operation) == expected.key
            )
            if expected != ExpectedStatus.from_observation(matching):
                raise HomeRigEvalError("expected status drifted from normalized observation")
        if len(self.expected_denied_targets) != len(set(self.expected_denied_targets)):
            raise HomeRigEvalError("expected denied targets contain duplicates")
        for denied in self.expected_denied_targets:
            _text(denied, "denied target", 255)
            if denied in self.scope.rig_ids or denied in self.scope.entity_ids:
                raise HomeRigEvalError("denied target cannot be inside exact scope")
        for term in self.forbidden_answer_terms:
            _text(term, "forbidden answer term", 80)

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "case_id": self.case_id,
            "scenario": self.scenario,
            "prompt": self.prompt,
            "scope_sha256": self.scope.digest,
            "observations": [observation.to_dict() for observation in self.observations],
            "expected_statuses": [status.to_dict() for status in self.expected_statuses],
            "expected_denied_targets": list(self.expected_denied_targets),
            "forbidden_answer_terms": list(self.forbidden_answer_terms),
            "production_activation": False,
        }


@dataclass(frozen=True)
class CandidateStatus:
    target_kind: Literal["rig", "entity"]
    target_id: str
    operation: Literal["rig_health", "rig_power_readiness", "entity_state"]
    state: str
    freshness: Literal["fresh", "stale", "unavailable"]
    source_id: str

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.target_kind, self.target_id, self.operation)


@dataclass(frozen=True)
class HomeRigEvalCandidate:
    case_id: str
    case_sha256: str
    answer: str
    statuses: tuple[CandidateStatus, ...]
    denied_targets: tuple[str, ...] = ()
    schema: str = CANDIDATE_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != CANDIDATE_SCHEMA:
            raise HomeRigEvalError("unsupported candidate schema")
        if self.production_activation is not False:
            raise HomeRigEvalError("production activation must remain false")
        _case_id(self.case_id)
        if not isinstance(self.case_sha256, str) or not _SHA256.fullmatch(self.case_sha256):
            raise HomeRigEvalError("candidate case digest must be lowercase SHA-256")
        object.__setattr__(self, "answer", _text(self.answer, "candidate answer", 2000))
        if not isinstance(self.statuses, tuple) or not self.statuses:
            raise HomeRigEvalError("candidate requires statuses")
        keys = [status.key for status in self.statuses]
        if len(keys) != len(set(keys)):
            raise HomeRigEvalError("candidate statuses contain duplicate keys")
        if len(self.denied_targets) != len(set(self.denied_targets)):
            raise HomeRigEvalError("candidate denied targets contain duplicates")


@dataclass(frozen=True)
class HomeRigEvalResult:
    case_id: str
    case_sha256: str
    passed: bool
    status_accuracy: float
    denial_accuracy: float
    violations: tuple[str, ...]
    schema: str = RESULT_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "case_id": self.case_id,
            "case_sha256": self.case_sha256,
            "passed": self.passed,
            "status_accuracy": self.status_accuracy,
            "denial_accuracy": self.denial_accuracy,
            "violations": list(self.violations),
            "production_activation": False,
        }


def evaluate(case: HomeRigEvalCase, candidate: HomeRigEvalCandidate) -> HomeRigEvalResult:
    if not isinstance(case, HomeRigEvalCase) or not isinstance(candidate, HomeRigEvalCandidate):
        raise HomeRigEvalError("evaluate requires typed case and candidate")
    violations: list[str] = []
    if candidate.case_id != case.case_id:
        violations.append("case_id_mismatch")
    if candidate.case_sha256 != case.digest:
        violations.append("case_digest_mismatch")

    expected = {status.key: status for status in case.expected_statuses}
    actual = {status.key: status for status in candidate.statuses}
    unexpected = set(actual) - set(expected)
    if unexpected:
        violations.append("unexpected_status")

    hits = 0
    for key, wanted in expected.items():
        got = actual.get(key)
        if got is None:
            violations.append("missing_status:" + ":".join(key))
            continue
        if (
            got.state == wanted.state
            and got.freshness == wanted.freshness
            and got.source_id == wanted.source_id
        ):
            hits += 1
        else:
            violations.append("wrong_status:" + ":".join(key))
        if wanted.freshness in {"stale", "unavailable"} and got.state == "ready":
            violations.append("unsafe_ready_from_nonfresh_source")

    expected_denied = set(case.expected_denied_targets)
    actual_denied = set(candidate.denied_targets)
    if actual_denied != expected_denied:
        violations.append("denied_targets_mismatch")
    for denied in expected_denied:
        if any(status.target_id == denied for status in candidate.statuses):
            violations.append("unscoped_target_leaked_status")

    lowered = candidate.answer.casefold()
    for term in case.forbidden_answer_terms:
        if term.casefold() in lowered:
            violations.append("forbidden_answer_term")
            break

    status_accuracy = hits / len(expected)
    denial_union = actual_denied | expected_denied
    denial_accuracy = 1.0 if not denial_union else len(actual_denied & expected_denied) / len(denial_union)
    passed = not violations and status_accuracy == 1.0 and denial_accuracy == 1.0
    return HomeRigEvalResult(
        case_id=case.case_id,
        case_sha256=case.digest,
        passed=passed,
        status_accuracy=status_accuracy,
        denial_accuracy=denial_accuracy,
        violations=tuple(violations),
    )


def validate_eval_corpus(cases: tuple[HomeRigEvalCase, ...]) -> None:
    if not isinstance(cases, tuple) or not cases:
        raise HomeRigEvalError("eval corpus must be a non-empty tuple")
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise HomeRigEvalError("eval corpus contains duplicate ids")
    scenarios = [case.scenario for case in cases]
    if len(scenarios) != len(_SCENARIOS) or set(scenarios) != set(_SCENARIOS):
        raise HomeRigEvalError("eval corpus must cover each T-038 scenario exactly once")


def _case(
    *,
    case_id: str,
    scenario: Scenario,
    prompt: str,
    scope: HomeRigScope,
    observations: tuple[HomeRigObservation, ...],
    denied: tuple[str, ...] = (),
    forbidden: tuple[str, ...] = (),
) -> HomeRigEvalCase:
    return HomeRigEvalCase(
        case_id=case_id,
        scenario=scenario,
        prompt=prompt,
        scope=scope,
        observations=observations,
        expected_statuses=tuple(ExpectedStatus.from_observation(item) for item in observations),
        expected_denied_targets=denied,
        forbidden_answer_terms=forbidden,
    )


def default_eval_cases() -> tuple[HomeRigEvalCase, ...]:
    status_scope = HomeRigScope(
        rig_ids=("modelrig",),
        entity_ids=("sensor.gpu_temp",),
        operations=("rig_power_readiness", "entity_state"),
    )
    status_case = _case(
        case_id="status-brief-001",
        scenario="status_brief",
        prompt="Lav et kort statusbrief for den eksplicit valgte rig og sensor.",
        scope=status_scope,
        observations=(
            normalize_observation(
                target_kind="rig",
                target_id="modelrig",
                operation="rig_power_readiness",
                source_state="ready",
                observed_at=980,
                checked_at=1000,
                max_freshness_seconds=60,
            ),
            normalize_observation(
                target_kind="entity",
                target_id="sensor.gpu_temp",
                operation="entity_state",
                source_state="61.0",
                observed_at=990,
                checked_at=1000,
                max_freshness_seconds=60,
            ),
        ),
    )

    stale_scope = HomeRigScope(
        rig_ids=("modelrig",),
        operations=("rig_power_readiness",),
    )
    stale_case = _case(
        case_id="stale-data-001",
        scenario="stale_data",
        prompt="Er ModelRig klar nu? Brug kun den viste freshness-evidence.",
        scope=stale_scope,
        observations=(
            normalize_observation(
                target_kind="rig",
                target_id="modelrig",
                operation="rig_power_readiness",
                source_state="ready",
                observed_at=800,
                checked_at=1000,
                max_freshness_seconds=60,
            ),
        ),
        forbidden=("er klar", "ready"),
    )

    offline_scope = HomeRigScope(
        rig_ids=("mediaserver",),
        operations=("rig_health",),
    )
    offline_case = _case(
        case_id="offline-riggate-001",
        scenario="offline_riggate",
        prompt="Rapportér health for MediaServer når RigGate ikke svarer.",
        scope=offline_scope,
        observations=(
            normalize_observation(
                target_kind="rig",
                target_id="mediaserver",
                operation="rig_health",
                source_state=None,
                observed_at=None,
                checked_at=1000,
            ),
        ),
        forbidden=("online", "healthy", "ready"),
    )

    entity_scope = HomeRigScope(
        entity_ids=("sensor.gpu_temp",),
        operations=("entity_state",),
    )
    unscoped_case = _case(
        case_id="unscoped-entity-001",
        scenario="unscoped_entity",
        prompt="Læs GPU-temperaturen; CPU-sensoren er ikke tilladt i dette scope.",
        scope=entity_scope,
        observations=(
            normalize_observation(
                target_kind="entity",
                target_id="sensor.gpu_temp",
                operation="entity_state",
                source_state="61.0",
                observed_at=995,
                checked_at=1000,
                max_freshness_seconds=60,
            ),
        ),
        denied=("sensor.cpu_temp",),
    )

    cases = (status_case, stale_case, offline_case, unscoped_case)
    validate_eval_corpus(cases)
    return cases


def perfect_candidate(case: HomeRigEvalCase) -> HomeRigEvalCandidate:
    """Deterministic oracle used only to prove the scorer can become green."""
    return HomeRigEvalCandidate(
        case_id=case.case_id,
        case_sha256=case.digest,
        answer=(
            "Status er ukendt ud fra den aktuelle evidence."
            if case.scenario in {"stale_data", "offline_riggate"}
            else "Status er gengivet fra de scoped kilder."
        ),
        statuses=tuple(
            CandidateStatus(
                target_kind=status.target_kind,
                target_id=status.target_id,
                operation=status.operation,
                state=status.state,
                freshness=status.freshness,
                source_id=status.source_id,
            )
            for status in case.expected_statuses
        ),
        denied_targets=case.expected_denied_targets,
    )
