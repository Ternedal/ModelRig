"""ADR-DC-087 strict base-synchronization preflight.

Consumes one live PASS ADR-DC-086 required-status evaluation whose canonical
policy requires strict status checks. The read helper observes the exact current
``main`` tip, compares that immutable tip to the exact reviewed head, then reads
``main`` again. A receipt is issued only when the base tip stayed stable and
GitHub's compare graph proves the exact head contains that current base.

This is evidence only. Review-thread policy, fresh status/review observation,
full branch policy, merge readiness and all mutation authority remain separate.
"""
from __future__ import annotations

import hashlib
import os
import weakref
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .github_read import ReadOnlyTransport, UrllibReadOnlyTransport
from . import improvement_pilot_exact_task_pr_required_status_evaluation as evaluation_boundary
from .improvement_pilot_exact_task_pr_required_status_evaluation import (
    PilotExactTaskPrRequiredStatusEvaluation,
)
from ._improvement_pilot_exact_task_pr_strict_base_sync_preflight_support import (
    PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_SCHEMA,
    PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_AUTHORITY,
    PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_SCOPE,
    PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_MAX_DURATION_SECONDS,
    PilotExactTaskPrStrictBaseSyncPreflightError,
    _REPOSITORY,
    _BASE_BRANCH,
    _MAX_COMPARE_COMMITS,
    _COMPARE_STATUSES,
    _canonical,
    _hex64,
    _hex40,
    _utc,
    _now_utc_seconds,
    _main_url,
    _compare_url,
    _read_main_tip,
    _read_compare,
)


def _require_live_evaluation(
    value: Any,
) -> PilotExactTaskPrRequiredStatusEvaluation:
    if type(value) is not PilotExactTaskPrRequiredStatusEvaluation:
        raise PilotExactTaskPrStrictBaseSyncPreflightError(
            "exact live ADR-DC-086 required-status evaluation is required"
        )
    try:
        replayed = PilotExactTaskPrRequiredStatusEvaluation.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPrStrictBaseSyncPreflightError(
            "ADR-DC-086 replay validation failed"
        ) from exc
    live = evaluation_boundary._get_live_pr_required_status_evaluation_inputs(value)
    if (
        replayed != value
        or replayed.sha256 != value.sha256
        or value.evaluation_authenticated is not True
        or live is None
        or value.repository != _REPOSITORY
        or value.evaluation_result != "PASS"
        or value.required_status_checks_evaluated is not True
        or value.required_status_checks_passed is not True
        or value.strict_required_status_checks_policy is not True
        or value.strict_base_sync_preflight_required is not True
        or value.branch_policy_fully_evaluated is not False
        or value.review_threads_preflight_required is not True
        or value.fresh_review_reobservation_required is not True
        or value.fresh_merge_transaction_revalidation_required is not True
        or value.merge_readiness_authorized is not False
        or value.merge_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskPrStrictBaseSyncPreflightError(
            "strict base-sync preflight requires one live PASS strict ADR-DC-086 evaluation"
        )
    return value


_live_records: dict[
    int,
    tuple[
        int,
        str,
        weakref.ReferenceType[Any],
        weakref.ReferenceType[PilotExactTaskPrRequiredStatusEvaluation],
    ],
] = {}


def _mark_authenticated(
    result: Any,
    evaluation: PilotExactTaskPrRequiredStatusEvaluation,
) -> None:
    key = id(result)

    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)

    _live_records[key] = (
        os.getpid(),
        result.sha256,
        weakref.ref(result, cleanup),
        weakref.ref(evaluation),
    )


def _get_live_pr_strict_base_sync_preflight_inputs(
    result: Any,
) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(result))
    if entry is None:
        return None
    pid, digest, result_ref, evaluation_ref = entry
    evaluation = evaluation_ref()
    if (
        pid != os.getpid()
        or result_ref() is not result
        or evaluation is None
        or evaluation.evaluation_authenticated is not True
        or evaluation.sha256 != result.required_status_evaluation_sha256
        or evaluation.required_status_policy_sha256
        != result.required_status_policy_sha256
        or evaluation.status_check_observation_sha256
        != result.status_check_observation_sha256
        or evaluation.predicted_commit_sha != result.predicted_commit_sha
        or result.sha256 != digest
    ):
        return None
    return MappingProxyType({"required_status_evaluation": evaluation})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrStrictBaseSyncPreflight:
    required_status_evaluation_sha256: str
    required_status_policy_sha256: str
    status_check_observation_sha256: str
    repository: str
    pull_request_number: int
    predicted_commit_sha: str
    base_branch: str
    first_base_tip_sha: str
    second_base_tip_sha: str
    main_branch_request_url_sha256: str
    compare_request_url_sha256: str
    first_main_body_sha256: str
    first_main_etag_sha256: str
    compare_body_sha256: str
    compare_etag_sha256: str
    second_main_body_sha256: str
    second_main_etag_sha256: str
    compare_status: str
    ahead_by: int
    behind_by: int
    total_commits: int
    base_commit_sha: str
    merge_base_sha: str
    first_observed_at_utc: str
    second_observed_at_utc: str
    source_status_evaluation_verified: bool = True
    source_required_status_pass_verified: bool = True
    strict_policy_verified: bool = True
    stable_base_tip_verified: bool = True
    compare_exact_head_bound: bool = True
    merge_base_equals_current_base: bool = True
    head_contains_current_base: bool = True
    credential_free_reads: bool = True
    fixed_github_api_origin: bool = True
    redirects_forbidden: bool = True
    response_bounded: bool = True
    observation_duration_bounded: bool = True
    strict_base_sync_evaluated: bool = True
    strict_base_sync_passed: bool = True
    required_status_checks_passed: bool = True
    branch_policy_fully_evaluated: bool = False
    review_threads_preflight_required: bool = True
    fresh_review_reobservation_required: bool = True
    fresh_required_status_reobservation_before_merge_required: bool = True
    fresh_merge_transaction_revalidation_required: bool = True
    merge_readiness_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_AUTHORITY
    observation_scope: str = PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_SCOPE
    schema: str = PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_AUTHORITY
            or self.observation_scope
            != PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_SCOPE
        ):
            raise PilotExactTaskPrStrictBaseSyncPreflightError(
                "strict base-sync schema/authority/scope unsupported"
            )
        for name in (
            "required_status_evaluation_sha256",
            "required_status_policy_sha256",
            "status_check_observation_sha256",
            "main_branch_request_url_sha256",
            "compare_request_url_sha256",
            "first_main_body_sha256",
            "first_main_etag_sha256",
            "compare_body_sha256",
            "compare_etag_sha256",
            "second_main_body_sha256",
            "second_main_etag_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in (
            "predicted_commit_sha",
            "first_base_tip_sha",
            "second_base_tip_sha",
            "base_commit_sha",
            "merge_base_sha",
        ):
            _hex40(getattr(self, name), name=name)
        first = _utc(self.first_observed_at_utc, name="first_observed_at_utc")
        second = _utc(self.second_observed_at_utc, name="second_observed_at_utc")
        if (
            second < first
            or (second - first).total_seconds()
            > PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_MAX_DURATION_SECONDS
        ):
            raise PilotExactTaskPrStrictBaseSyncPreflightError(
                "strict base-sync observation duration is invalid"
            )
        if (
            isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
        ):
            raise PilotExactTaskPrStrictBaseSyncPreflightError(
                "pull_request_number is invalid"
            )
        for name in ("ahead_by", "behind_by", "total_commits"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value <= _MAX_COMPARE_COMMITS
            ):
                raise PilotExactTaskPrStrictBaseSyncPreflightError(
                    f"{name} is invalid"
                )
        if (
            self.repository != _REPOSITORY
            or self.base_branch != _BASE_BRANCH
            or self.first_base_tip_sha != self.second_base_tip_sha
            or self.base_commit_sha != self.first_base_tip_sha
            or self.merge_base_sha != self.first_base_tip_sha
            or self.behind_by != 0
            or self.total_commits != self.ahead_by
            or self.compare_status not in _COMPARE_STATUSES
            or (
                self.compare_status == "identical"
                and (
                    self.predicted_commit_sha != self.first_base_tip_sha
                    or self.ahead_by != 0
                )
            )
            or (
                self.compare_status == "ahead"
                and (
                    self.predicted_commit_sha == self.first_base_tip_sha
                    or self.ahead_by < 1
                )
            )
            or self.main_branch_request_url_sha256
            != hashlib.sha256(_main_url().encode("utf-8")).hexdigest()
            or self.compare_request_url_sha256
            != hashlib.sha256(
                _compare_url(
                    self.first_base_tip_sha,
                    self.predicted_commit_sha,
                ).encode("utf-8")
            ).hexdigest()
        ):
            raise PilotExactTaskPrStrictBaseSyncPreflightError(
                "strict base-sync exact target/graph binding is invalid"
            )
        required_true = (
            "source_status_evaluation_verified",
            "source_required_status_pass_verified",
            "strict_policy_verified",
            "stable_base_tip_verified",
            "compare_exact_head_bound",
            "merge_base_equals_current_base",
            "head_contains_current_base",
            "credential_free_reads",
            "fixed_github_api_origin",
            "redirects_forbidden",
            "response_bounded",
            "observation_duration_bounded",
            "strict_base_sync_evaluated",
            "strict_base_sync_passed",
            "required_status_checks_passed",
            "review_threads_preflight_required",
            "fresh_review_reobservation_required",
            "fresh_required_status_reobservation_before_merge_required",
            "fresh_merge_transaction_revalidation_required",
        )
        forced_false = (
            "branch_policy_fully_evaluated",
            "merge_readiness_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrStrictBaseSyncPreflightError(
                "strict base-sync evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrStrictBaseSyncPreflightError(
                "strict base-sync preflight widened authority"
            )

    @property
    def preflight_authenticated(self) -> bool:
        return _get_live_pr_strict_base_sync_preflight_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(
        cls,
        value: Any,
    ) -> "PilotExactTaskPrStrictBaseSyncPreflight":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrStrictBaseSyncPreflightError(
                "strict base-sync preflight must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrStrictBaseSyncPreflightError(
                "strict base-sync preflight fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _observe_verified_pilot_exact_task_pr_strict_base_sync_preflight(
    *,
    required_status_evaluation: PilotExactTaskPrRequiredStatusEvaluation,
    transport: ReadOnlyTransport,
    now_provider: Any,
) -> PilotExactTaskPrStrictBaseSyncPreflight:
    checked = _require_live_evaluation(required_status_evaluation)

    first_at = now_provider()
    _utc(first_at, name="first_observed_at_utc")
    first = _read_main_tip(transport=transport)

    compared = _read_compare(
        base_sha=str(first["tip_sha"]),
        head_sha=checked.predicted_commit_sha,
        transport=transport,
    )

    second = _read_main_tip(transport=transport)
    second_at = now_provider()
    first_dt = _utc(first_at, name="first_observed_at_utc")
    second_dt = _utc(second_at, name="second_observed_at_utc")
    if (
        second_dt < first_dt
        or (second_dt - first_dt).total_seconds()
        > PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_MAX_DURATION_SECONDS
        or first["tip_sha"] != second["tip_sha"]
    ):
        raise PilotExactTaskPrStrictBaseSyncPreflightError(
            "current main tip drifted or observation window exceeded"
        )

    result = PilotExactTaskPrStrictBaseSyncPreflight(
        required_status_evaluation_sha256=checked.sha256,
        required_status_policy_sha256=checked.required_status_policy_sha256,
        status_check_observation_sha256=checked.status_check_observation_sha256,
        repository=checked.repository,
        pull_request_number=checked.pull_request_number,
        predicted_commit_sha=checked.predicted_commit_sha,
        base_branch=_BASE_BRANCH,
        first_base_tip_sha=str(first["tip_sha"]),
        second_base_tip_sha=str(second["tip_sha"]),
        main_branch_request_url_sha256=str(first["request_url_sha256"]),
        compare_request_url_sha256=str(compared["request_url_sha256"]),
        first_main_body_sha256=str(first["response_body_sha256"]),
        first_main_etag_sha256=str(first["response_etag_sha256"]),
        compare_body_sha256=str(compared["response_body_sha256"]),
        compare_etag_sha256=str(compared["response_etag_sha256"]),
        second_main_body_sha256=str(second["response_body_sha256"]),
        second_main_etag_sha256=str(second["response_etag_sha256"]),
        compare_status=str(compared["status"]),
        ahead_by=int(compared["ahead_by"]),
        behind_by=int(compared["behind_by"]),
        total_commits=int(compared["total_commits"]),
        base_commit_sha=str(compared["base_commit_sha"]),
        merge_base_sha=str(compared["merge_base_sha"]),
        first_observed_at_utc=first_at,
        second_observed_at_utc=second_at,
    )
    _mark_authenticated(result, checked)
    if result.preflight_authenticated is not True:
        raise PilotExactTaskPrStrictBaseSyncPreflightError(
            "strict base-sync preflight lost live provenance"
        )
    return result


def observe_pilot_exact_task_pr_strict_base_sync_preflight(
    required_status_evaluation: PilotExactTaskPrRequiredStatusEvaluation,
) -> PilotExactTaskPrStrictBaseSyncPreflight:
    """Prove strict current-base ancestry only; never grant merge authority."""
    return _observe_verified_pilot_exact_task_pr_strict_base_sync_preflight(
        required_status_evaluation=required_status_evaluation,
        transport=UrllibReadOnlyTransport(),
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_SCHEMA",
    "PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_AUTHORITY",
    "PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_SCOPE",
    "PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_MAX_DURATION_SECONDS",
    "PilotExactTaskPrStrictBaseSyncPreflightError",
    "PilotExactTaskPrStrictBaseSyncPreflight",
    "observe_pilot_exact_task_pr_strict_base_sync_preflight",
]
