"""ADR-DC-086 evaluate the synthesized required-status policy against exact-head evidence."""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from . import improvement_pilot_exact_task_pr_required_status_policy as policy_boundary
from . import improvement_pilot_exact_task_pr_status_check_observation as status_boundary
from .improvement_pilot_exact_task_pr_required_status_policy import (
    PilotExactTaskPrRequiredStatusPolicy,
)
from .improvement_pilot_exact_task_pr_status_check_observation import (
    PilotExactTaskPrStatusCheckObservation,
)

SCHEMA = "kaliv-rsi-dc-l16-exact-task-pr-required-status-evaluation/v1"
AUTHORITY = "evaluated-one-dc-l16-exact-required-status-policy-only"
_REPOSITORY = "Ternedal/ModelRig"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class PilotExactTaskPrRequiredStatusEvaluationError(ValueError):
    pass


def _canon(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _hex(value: Any, *, length: int, name: str) -> str:
    pattern = _HEX40 if length == 40 else _HEX64
    if (
        not isinstance(value, str)
        or pattern.fullmatch(value) is None
        or value == "0" * length
    ):
        raise PilotExactTaskPrRequiredStatusEvaluationError(f"{name} is invalid")
    return value


def _sources(policy: Any, status: Any):
    if (
        type(policy) is not PilotExactTaskPrRequiredStatusPolicy
        or type(status) is not PilotExactTaskPrStatusCheckObservation
    ):
        raise PilotExactTaskPrRequiredStatusEvaluationError(
            "live ADR-DC-085 policy and ADR-DC-081 status evidence required"
        )
    policy_replay = PilotExactTaskPrRequiredStatusPolicy.from_mapping(policy.to_dict())
    status_replay = PilotExactTaskPrStatusCheckObservation.from_mapping(status.to_dict())
    policy_live = policy_boundary._get_live_pr_required_status_policy_inputs(policy)
    status_live = status_boundary._get_live_pr_status_check_observation_inputs(status)
    if (
        policy_replay != policy
        or status_replay != status
        or policy.policy_authenticated is not True
        or policy.synthesis_result != "SUPPORTED"
        or policy.required_status_checks_evaluated is not False
        or status.observation_authenticated is not True
        or policy_live is None
        or status_live is None
        or status.sha256 != policy.status_check_observation_sha256
        or status.repository != policy.repository
        or status.pull_request_number != policy.pull_request_number
        or status.predicted_commit_sha != policy.predicted_commit_sha
        or policy.merge_authorized is not False
        or status.merge_authorized is not False
    ):
        raise PilotExactTaskPrRequiredStatusEvaluationError(
            "status evaluation source provenance invalid"
        )
    return (
        tuple(policy_live["required_checks"]),
        tuple(status_live["check_runs"]),
        tuple(status_live["legacy_statuses"]),
    )


def _latest_checks(rows):
    rows = tuple(rows)
    if not rows:
        return None, False
    stamped = []
    for row in rows:
        completed = row.get("completed_at_utc", "")
        started = row.get("started_at_utc", "")
        timestamp = completed if row.get("status") == "completed" else started
        if not isinstance(timestamp, str) or not timestamp:
            return None, True
        stamped.append((timestamp, row))
    latest = max(timestamp for timestamp, _row in stamped)
    winners = [row for timestamp, row in stamped if timestamp == latest]
    if len(winners) != 1:
        return None, True
    return winners[0], False


def _latest_legacy(rows):
    rows = tuple(rows)
    if not rows:
        return None, False
    stamps = [row.get("updated_at_utc", "") for row in rows]
    if any(not isinstance(value, str) or not value for value in stamps):
        return None, True
    latest = max(stamps)
    winners = [row for row in rows if row.get("updated_at_utc") == latest]
    if len(winners) != 1:
        return None, True
    return winners[0], False


def _check_outcome(rows):
    latest, ambiguous = _latest_checks(rows)
    if ambiguous:
        return "UNSUPPORTED"
    if latest is None:
        return "MISSING"
    if latest.get("status") != "completed":
        return "PENDING"
    return "SATISFIED" if latest.get("conclusion") == "success" else "FAILING"


def _one_requirement(context: str, app_id: int | None, checks, legacy):
    if app_id == -1:
        return "UNSUPPORTED"
    if app_id is not None:
        return _check_outcome(
            row
            for row in checks
            if row.get("name") == context and row.get("app_id") == app_id
        )
    check_rows = tuple(row for row in checks if row.get("name") == context)
    legacy_rows = tuple(row for row in legacy if row.get("context") == context)
    if check_rows and legacy_rows:
        return "UNSUPPORTED"
    if check_rows:
        return _check_outcome(check_rows)
    if legacy_rows:
        latest, ambiguous = _latest_legacy(legacy_rows)
        if ambiguous or latest is None:
            return "UNSUPPORTED"
        state = latest.get("state")
        if state == "success":
            return "SATISFIED"
        if state == "pending":
            return "PENDING"
        return "FAILING"
    return "MISSING"


_live = {}


def _get_live_pr_required_status_evaluation_inputs(value: Any):
    row = _live.get(id(value))
    if row is None:
        return None
    pid, digest, ref, policy_ref, status_ref = row
    policy = policy_ref()
    status = status_ref()
    if (
        pid != os.getpid()
        or ref() is not value
        or policy is None
        or status is None
        or value.sha256 != digest
        or policy.policy_authenticated is not True
        or status.observation_authenticated is not True
        or policy.sha256 != value.required_status_policy_sha256
        or status.sha256 != value.status_check_observation_sha256
        or status.second_combined_evidence_sha256 != value.status_evidence_sha256
    ):
        return None
    return MappingProxyType(
        {
            "required_status_policy": policy,
            "status_check_observation": status,
        }
    )


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrRequiredStatusEvaluation:
    required_status_policy_sha256: str
    status_check_observation_sha256: str
    repository: str
    pull_request_number: int
    predicted_commit_sha: str
    status_evidence_sha256: str
    required_check_count: int
    satisfied_check_count: int
    missing_check_count: int
    pending_check_count: int
    failing_check_count: int
    unsupported_check_count: int
    strict_required_status_checks_policy: bool
    evaluation_result: str
    source_policy_verified: bool = True
    source_status_observation_verified: bool = True
    exact_head_status_evidence_verified: bool = True
    unsupported_semantics_fail_closed: bool = True
    required_status_checks_evaluated: bool = True
    required_status_checks_passed: bool = False
    strict_base_sync_preflight_required: bool = False
    branch_policy_fully_evaluated: bool = False
    review_threads_preflight_required: bool = True
    fresh_review_reobservation_required: bool = True
    fresh_merge_transaction_revalidation_required: bool = True
    merge_readiness_authorized: bool = False
    merge_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = AUTHORITY
    schema: str = SCHEMA

    def __post_init__(self):
        if (
            self.schema != SCHEMA
            or self.authority != AUTHORITY
            or self.evaluation_result not in {"PASS", "BLOCKED", "UNSUPPORTED"}
        ):
            raise PilotExactTaskPrRequiredStatusEvaluationError(
                "invalid status evaluation receipt"
            )
        for name in (
            "required_status_policy_sha256",
            "status_check_observation_sha256",
            "status_evidence_sha256",
        ):
            _hex(getattr(self, name), length=64, name=name)
        _hex(self.predicted_commit_sha, length=40, name="predicted_commit_sha")
        if (
            self.repository != _REPOSITORY
            or isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or isinstance(self.required_check_count, bool)
            or not isinstance(self.required_check_count, int)
            or self.required_check_count < 0
        ):
            raise PilotExactTaskPrRequiredStatusEvaluationError(
                "status evaluation target identity is invalid"
            )
        counts = (
            self.satisfied_check_count,
            self.missing_check_count,
            self.pending_check_count,
            self.failing_check_count,
            self.unsupported_check_count,
        )
        if (
            any(
                isinstance(item, bool) or not isinstance(item, int) or item < 0
                for item in counts
            )
            or sum(counts) != self.required_check_count
        ):
            raise PilotExactTaskPrRequiredStatusEvaluationError(
                "status evaluation counts inconsistent"
            )
        for name in (
            "strict_required_status_checks_policy",
            "source_policy_verified",
            "source_status_observation_verified",
            "exact_head_status_evidence_verified",
            "unsupported_semantics_fail_closed",
            "required_status_checks_evaluated",
            "required_status_checks_passed",
            "strict_base_sync_preflight_required",
            "branch_policy_fully_evaluated",
            "review_threads_preflight_required",
            "fresh_review_reobservation_required",
            "fresh_merge_transaction_revalidation_required",
            "merge_readiness_authorized",
            "merge_authorized",
            "production_activation_authorized",
        ):
            if not isinstance(getattr(self, name), bool):
                raise PilotExactTaskPrRequiredStatusEvaluationError(
                    f"{name} must be boolean"
                )
        if (
            self.strict_base_sync_preflight_required
            is not self.strict_required_status_checks_policy
        ):
            raise PilotExactTaskPrRequiredStatusEvaluationError(
                "strict base-sync requirement drifted"
            )
        if self.evaluation_result == "PASS" and (
            self.required_status_checks_passed is not True
            or any(counts[1:])
            or self.required_status_checks_evaluated is not True
        ):
            raise PilotExactTaskPrRequiredStatusEvaluationError(
                "passing status evaluation contains blockers"
            )
        if self.evaluation_result == "UNSUPPORTED" and (
            self.unsupported_check_count < 1
            or self.required_status_checks_evaluated is not False
        ):
            raise PilotExactTaskPrRequiredStatusEvaluationError(
                "unsupported status semantics misclassified"
            )
        if self.evaluation_result == "BLOCKED" and (
            self.required_status_checks_evaluated is not True
            or not any(counts[1:4])
            or self.unsupported_check_count != 0
        ):
            raise PilotExactTaskPrRequiredStatusEvaluationError(
                "blocked status evaluation is inconsistent"
            )
        if (
            self.evaluation_result != "PASS"
            and self.required_status_checks_passed is not False
        ):
            raise PilotExactTaskPrRequiredStatusEvaluationError(
                "nonpassing status evaluation marked passed"
            )
        if (
            self.source_policy_verified is not True
            or self.source_status_observation_verified is not True
            or self.exact_head_status_evidence_verified is not True
            or self.unsupported_semantics_fail_closed is not True
            or self.branch_policy_fully_evaluated is not False
            or self.review_threads_preflight_required is not True
            or self.fresh_review_reobservation_required is not True
            or self.fresh_merge_transaction_revalidation_required is not True
            or self.merge_readiness_authorized is not False
            or self.merge_authorized is not False
            or self.production_activation_authorized is not False
        ):
            raise PilotExactTaskPrRequiredStatusEvaluationError(
                "status evaluation widened authority"
            )

    @property
    def evaluation_authenticated(self):
        return _get_live_pr_required_status_evaluation_inputs(self) is not None

    @property
    def sha256(self):
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()

    def to_dict(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    def canonical_json(self):
        return _canon(self.to_dict())

    @classmethod
    def from_mapping(cls, value):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskPrRequiredStatusEvaluationError("fields mismatch")
        return cls(**dict(value))


def evaluate_pilot_exact_task_pr_required_status(
    policy: PilotExactTaskPrRequiredStatusPolicy,
    status: PilotExactTaskPrStatusCheckObservation,
):
    required, checks, legacy = _sources(policy, status)
    outcomes = [
        _one_requirement(context, app_id, checks, legacy)
        for context, app_id in required
    ]
    counts = {
        name: outcomes.count(name)
        for name in ("SATISFIED", "MISSING", "PENDING", "FAILING", "UNSUPPORTED")
    }
    if counts["UNSUPPORTED"]:
        result = "UNSUPPORTED"
    elif counts["MISSING"] or counts["PENDING"] or counts["FAILING"]:
        result = "BLOCKED"
    else:
        result = "PASS"
    evaluated = result != "UNSUPPORTED"
    passed = result == "PASS"
    out = PilotExactTaskPrRequiredStatusEvaluation(
        policy.sha256,
        status.sha256,
        policy.repository,
        policy.pull_request_number,
        policy.predicted_commit_sha,
        status.second_combined_evidence_sha256,
        len(required),
        counts["SATISFIED"],
        counts["MISSING"],
        counts["PENDING"],
        counts["FAILING"],
        counts["UNSUPPORTED"],
        policy.strict_required_status_checks_policy,
        result,
        required_status_checks_evaluated=evaluated,
        required_status_checks_passed=passed,
        strict_base_sync_preflight_required=bool(
            policy.strict_required_status_checks_policy
        ),
    )
    key = id(out)

    def cleanup(_):
        _live.pop(key, None)

    _live[key] = (
        os.getpid(),
        out.sha256,
        weakref.ref(out, cleanup),
        weakref.ref(policy),
        weakref.ref(status),
    )
    if out.evaluation_authenticated is not True:
        raise PilotExactTaskPrRequiredStatusEvaluationError(
            "status evaluation lost provenance"
        )
    return out


__all__ = [
    "PilotExactTaskPrRequiredStatusEvaluationError",
    "PilotExactTaskPrRequiredStatusEvaluation",
    "evaluate_pilot_exact_task_pr_required_status",
]
