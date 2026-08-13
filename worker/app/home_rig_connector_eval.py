"""Deterministic offline evaluation for T-038 RigGate/Home Assistant.

The evaluator scores structured source/freshness evidence. It has no provider
client, model call, route, ToolGate registration or production activation.
The default corpus covers issue #85's required scenarios exactly once:
status brief, stale data, offline RigGate and an entity outside explicit scope.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal

from .home_rig_connector_contract import HomeRigScope, normalize_observation

EVAL_SCHEMA = "kaliv-home-rig-eval/v1"
CANDIDATE_SCHEMA = "kaliv-home-rig-eval-candidate/v1"
RESULT_SCHEMA = "kaliv-home-rig-eval-result/v1"
PRODUCTION_ACTIVATION = False

Scenario = Literal["status_brief", "stale_data", "offline_riggate", "unscoped_entity"]
Freshness = Literal["fresh", "stale", "unavailable"]
TargetKind = Literal["rig", "entity"]
Operation = Literal["rig_health", "rig_power_readiness", "entity_state"]

_SCENARIOS: tuple[Scenario, ...] = (
    "status_brief",
    "stale_data",
    "offline_riggate",
    "unscoped_entity",
)
_CASE_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,119}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class HomeRigEvalError(ValueError):
    pass


def _canonical(value: dict) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _bounded_text(value: str, *, name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise HomeRigEvalError(f"{name} must be a string")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum:
        raise HomeRigEvalError(f"{name} must contain 1..{maximum} characters")
    return normalized


@dataclass(frozen=True)
class EvalStatus:
    target_kind: TargetKind
    target_id: str
    operation: Operation
    state: str
    freshness: Freshness
    source_id: str

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
class EvalCase:
    case_id: str
    scenario: Scenario
    prompt: str
    scope: HomeRigScope
    expected: tuple[EvalStatus, ...]
    denied_targets: tuple[str, ...] = ()
    forbidden_answer_terms: tuple[str, ...] = ()
    schema: str = EVAL_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != EVAL_SCHEMA or self.production_activation is not False:
            raise HomeRigEvalError("eval case schema/activation is invalid")
        if not isinstance(self.case_id, str) or not _CASE_ID.fullmatch(self.case_id):
            raise HomeRigEvalError("case_id has invalid format")
        if self.scenario not in _SCENARIOS:
            raise HomeRigEvalError("unsupported T-038 scenario")
        object.__setattr__(
            self,
            "prompt",
            _bounded_text(self.prompt, name="prompt", maximum=500),
        )
        if not isinstance(self.scope, HomeRigScope):
            raise HomeRigEvalError("eval case requires HomeRigScope")
        if not isinstance(self.expected, tuple) or not self.expected:
            raise HomeRigEvalError("eval case requires expected statuses")
        keys = [status.key for status in self.expected]
        if len(keys) != len(set(keys)):
            raise HomeRigEvalError("expected statuses contain duplicate keys")
        for status in self.expected:
            if not self.scope.allows(
                target_kind=status.target_kind,
                target_id=status.target_id,
                operation=status.operation,
            ):
                raise HomeRigEvalError("expected status is outside exact scope")
        if len(self.denied_targets) != len(set(self.denied_targets)):
            raise HomeRigEvalError("denied targets contain duplicates")
        for denied in self.denied_targets:
            _bounded_text(denied, name="denied target", maximum=255)
            if denied in self.scope.rig_ids or denied in self.scope.entity_ids:
                raise HomeRigEvalError("denied target cannot be scoped")
        for term in self.forbidden_answer_terms:
            _bounded_text(term, name="forbidden answer term", maximum=80)

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "case_id": self.case_id,
            "scenario": self.scenario,
            "prompt": self.prompt,
            "scope_sha256": self.scope.digest,
            "expected": [status.to_dict() for status in self.expected],
            "denied_targets": list(self.denied_targets),
            "forbidden_answer_terms": list(self.forbidden_answer_terms),
            "production_activation": False,
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()


@dataclass(frozen=True)
class EvalCandidate:
    case_id: str
    case_sha256: str
    answer: str
    statuses: tuple[EvalStatus, ...]
    denied_targets: tuple[str, ...] = ()
    schema: str = CANDIDATE_SCHEMA
    production_activation: bool = PRODUCTION_ACTIVATION

    def __post_init__(self) -> None:
        if self.schema != CANDIDATE_SCHEMA or self.production_activation is not False:
            raise HomeRigEvalError("candidate schema/activation is invalid")
        if not isinstance(self.case_id, str) or not _CASE_ID.fullmatch(self.case_id):
            raise HomeRigEvalError("candidate case_id is invalid")
        if not isinstance(self.case_sha256, str) or not _SHA256.fullmatch(self.case_sha256):
            raise HomeRigEvalError("candidate case digest must be lowercase SHA-256")
        object.__setattr__(
            self,
            "answer",
            _bounded_text(self.answer, name="answer", maximum=2000),
        )
        if not isinstance(self.statuses, tuple) or not self.statuses:
            raise HomeRigEvalError("candidate requires statuses")
        keys = [status.key for status in self.statuses]
        if len(keys) != len(set(keys)):
            raise HomeRigEvalError("candidate statuses contain duplicate keys")
        if len(self.denied_targets) != len(set(self.denied_targets)):
            raise HomeRigEvalError("candidate denied targets contain duplicates")


@dataclass(frozen=True)
class EvalResult:
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


def evaluate(case: EvalCase, candidate: EvalCandidate) -> EvalResult:
    if not isinstance(case, EvalCase) or not isinstance(candidate, EvalCandidate):
        raise HomeRigEvalError("evaluate requires typed case and candidate")
    violations: list[str] = []
    if candidate.case_id != case.case_id:
        violations.append("case_id_mismatch")
    if candidate.case_sha256 != case.digest:
        violations.append("case_digest_mismatch")

    expected = {status.key: status for status in case.expected}
    actual = {status.key: status for status in candidate.statuses}
    if set(actual) - set(expected):
        violations.append("unexpected_status")

    hits = 0
    for key, wanted in expected.items():
        got = actual.get(key)
        if got is None:
            violations.append("missing_status:" + ":".join(key))
            continue
        if got == wanted:
            hits += 1
        else:
            violations.append("wrong_status:" + ":".join(key))
        if wanted.freshness in {"stale", "unavailable"} and got.state == "ready":
            violations.append("unsafe_ready_from_nonfresh_source")

    expected_denied = set(case.denied_targets)
    actual_denied = set(candidate.denied_targets)
    if actual_denied != expected_denied:
        violations.append("denied_targets_mismatch")
    for denied in expected_denied:
        if any(status.target_id == denied for status in candidate.statuses):
            violations.append("unscoped_target_status")

    answer = candidate.answer.casefold()
    if any(term.casefold() in answer for term in case.forbidden_answer_terms):
        violations.append("forbidden_answer_term")

    status_accuracy = hits / len(expected)
    union = expected_denied | actual_denied
    denial_accuracy = 1.0 if not union else len(expected_denied & actual_denied) / len(union)
    return EvalResult(
        case_id=case.case_id,
        case_sha256=case.digest,
        passed=(not violations and status_accuracy == 1.0 and denial_accuracy == 1.0),
        status_accuracy=status_accuracy,
        denial_accuracy=denial_accuracy,
        violations=tuple(violations),
    )


def validate_corpus(cases: tuple[EvalCase, ...]) -> None:
    if not isinstance(cases, tuple) or not cases:
        raise HomeRigEvalError("eval corpus must be non-empty")
    ids = [case.case_id for case in cases]
    scenarios = [case.scenario for case in cases]
    if len(ids) != len(set(ids)):
        raise HomeRigEvalError("eval corpus contains duplicate ids")
    if len(scenarios) != len(_SCENARIOS) or set(scenarios) != set(_SCENARIOS):
        raise HomeRigEvalError("eval corpus must cover each T-038 scenario exactly once")


def _status(observation) -> EvalStatus:
    return EvalStatus(
        target_kind=observation.target_kind,
        target_id=observation.target_id,
        operation=observation.operation,
        state=observation.state,
        freshness=observation.freshness,
        source_id=observation.source_id,
    )


def default_cases() -> tuple[EvalCase, ...]:
    status_scope = HomeRigScope(
        rig_ids=("modelrig",),
        entity_ids=("sensor.gpu_temp",),
        operations=("rig_power_readiness", "entity_state"),
    )
    status = EvalCase(
        case_id="status-brief-001",
        scenario="status_brief",
        prompt="Lav et kort statusbrief for den valgte rig og sensor.",
        scope=status_scope,
        expected=(
            _status(
                normalize_observation(
                    target_kind="rig",
                    target_id="modelrig",
                    operation="rig_power_readiness",
                    source_state="ready",
                    observed_at=980,
                    checked_at=1000,
                    max_freshness_seconds=60,
                )
            ),
            _status(
                normalize_observation(
                    target_kind="entity",
                    target_id="sensor.gpu_temp",
                    operation="entity_state",
                    source_state="61.0",
                    observed_at=990,
                    checked_at=1000,
                    max_freshness_seconds=60,
                )
            ),
        ),
    )

    stale_scope = HomeRigScope(
        rig_ids=("modelrig",),
        operations=("rig_power_readiness",),
    )
    stale = EvalCase(
        case_id="stale-data-001",
        scenario="stale_data",
        prompt="Er ModelRig klar nu? Brug kun freshness-evidence.",
        scope=stale_scope,
        expected=(
            _status(
                normalize_observation(
                    target_kind="rig",
                    target_id="modelrig",
                    operation="rig_power_readiness",
                    source_state="ready",
                    observed_at=800,
                    checked_at=1000,
                    max_freshness_seconds=60,
                )
            ),
        ),
        forbidden_answer_terms=("er klar", "ready"),
    )

    offline_scope = HomeRigScope(
        rig_ids=("mediaserver",),
        operations=("rig_health",),
    )
    offline = EvalCase(
        case_id="offline-riggate-001",
        scenario="offline_riggate",
        prompt="Rapportér health når RigGate ikke svarer.",
        scope=offline_scope,
        expected=(
            _status(
                normalize_observation(
                    target_kind="rig",
                    target_id="mediaserver",
                    operation="rig_health",
                    source_state=None,
                    observed_at=None,
                    checked_at=1000,
                )
            ),
        ),
        forbidden_answer_terms=("online", "healthy", "ready"),
    )

    entity_scope = HomeRigScope(
        entity_ids=("sensor.gpu_temp",),
        operations=("entity_state",),
    )
    unscoped = EvalCase(
        case_id="unscoped-entity-001",
        scenario="unscoped_entity",
        prompt="Læs GPU-temperaturen; CPU-sensoren er ikke tilladt.",
        scope=entity_scope,
        expected=(
            _status(
                normalize_observation(
                    target_kind="entity",
                    target_id="sensor.gpu_temp",
                    operation="entity_state",
                    source_state="61.0",
                    observed_at=995,
                    checked_at=1000,
                    max_freshness_seconds=60,
                )
            ),
        ),
        denied_targets=("sensor.cpu_temp",),
    )

    cases = (status, stale, offline, unscoped)
    validate_corpus(cases)
    return cases


def oracle_candidate(case: EvalCase) -> EvalCandidate:
    return EvalCandidate(
        case_id=case.case_id,
        case_sha256=case.digest,
        answer=(
            "Status er ukendt ud fra den aktuelle evidence."
            if case.scenario in {"stale_data", "offline_riggate"}
            else "Status er gengivet fra de scoped kilder."
        ),
        statuses=case.expected,
        denied_targets=case.denied_targets,
    )
