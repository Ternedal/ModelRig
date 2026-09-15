"""ADR-DC-089 host-pinned review-thread GraphQL read capability.

Consumes one fresh live ADR-DC-088 strict base-sync receipt. The live ADR-088
seam retains ADR-DC-087 review-thread read requirements and the bound status /
ruleset provenance. This boundary attests only a fixed host broker identity; it
does not load credentials, invoke the broker, read GitHub, evaluate thread
policy, or grant mutation/merge authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from . import improvement_pilot_exact_task_pr_strict_base_sync_preflight as sync_boundary
from .improvement_pilot_exact_task_pr_strict_base_sync_preflight import PilotExactTaskPrStrictBaseSyncPreflight

SCHEMA = "kaliv-rsi-dc-l16-exact-task-pr-strict-synced-review-thread-read-capability/v1"
AUTHORITY = "host-attested-one-dc-l16-strict-synced-review-thread-graphql-read-broker-only"
PROTOCOL = "github-strict-synced-review-thread-graphql-read-broker-v1"
SECRET_SOURCE = "host-secret-store-only"
SECRET_TRANSPORT = "broker-owned-https-only"
GRAPHQL_ENDPOINT = "https://api.github.com/graphql"
CREDENTIAL_ACCOUNT = "Ternedal"
MAX_SOURCE_AGE_SECONDS = 15
_REPOSITORY = "Ternedal/ModelRig"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityError(ValueError):
    pass


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityError(f"{name} invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityError(f"{name} invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityError(f"{name} invalid")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityError(f"{name} invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _path_sha256(path: Path) -> str:
    return hashlib.sha256(os.fsencode(os.path.abspath(os.fspath(path)))).hexdigest()


def _require_live_strict_sync(value: Any) -> Mapping[str, Any]:
    if type(value) is not PilotExactTaskPrStrictBaseSyncPreflight:
        raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityError("live ADR-DC-088 strict-sync required")
    try:
        replay = PilotExactTaskPrStrictBaseSyncPreflight.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityError("ADR-DC-088 replay validation failed") from exc
    live = sync_boundary._get_live_pr_strict_base_sync_preflight_inputs(value)
    req = None if live is None else live.get("review_thread_read_requirements")
    evaluation = None if live is None else live.get("required_status_evaluation")
    app = None if live is None else live.get("ruleset_applicability")
    if (
        replay != value
        or replay.sha256 != value.sha256
        or value.preflight_authenticated is not True
        or live is None or req is None or evaluation is None or app is None
        or getattr(req, "requirements_authenticated", None) is not True
        or getattr(evaluation, "evaluation_authenticated", None) is not True
        or getattr(app, "applicability_authenticated", None) is not True
        or value.source_review_thread_requirements_verified is not True
        or value.source_required_status_pass_verified is not True
        or value.review_thread_query_requirements_preserved is not True
        or value.strict_base_sync_evaluated is not True
        or value.strict_base_sync_passed is not True
        or value.required_status_checks_passed is not True
        or value.review_thread_read_capability_required is not True
        or value.review_threads_preflight_required is not True
        or value.fresh_review_reobservation_required is not True
        or value.fresh_required_status_reobservation_before_merge_required is not True
        or value.fresh_merge_transaction_revalidation_required is not True
        or value.branch_policy_fully_evaluated is not False
        or value.merge_readiness_authorized is not False
        or value.merge_authorized is not False
        or value.production_activation_authorized is not False
        or value.repository != _REPOSITORY
        or value.first_base_tip_sha != value.second_base_tip_sha
        or value.review_thread_read_requirements_sha256 != req.sha256
        or value.required_status_evaluation_sha256 != evaluation.sha256
        or value.required_status_policy_sha256 != evaluation.required_status_policy_sha256
        or value.ruleset_applicability_sha256 != app.sha256
        or value.ruleset_observation_sha256 != req.ruleset_observation_sha256
        or value.status_check_observation_sha256 != evaluation.status_check_observation_sha256
        or value.review_thread_graphql_query_sha256 != req.graphql_query_sha256
        or value.predicted_commit_sha != req.predicted_commit_sha
        or value.pull_request_number != req.pull_request_number
    ):
        raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityError("ADR-DC-088 provenance invalid")
    return MappingProxyType({"review_thread_read_requirements": req, "required_status_evaluation": evaluation, "ruleset_applicability": app})


def _require_source_window(strict_sync: PilotExactTaskPrStrictBaseSyncPreflight, *, at_utc: str) -> None:
    _require_live_strict_sync(strict_sync)
    at = _utc(at_utc, name="materialized_at_utc")
    source = _utc(strict_sync.second_observed_at_utc, name="ADR-DC-088 second_observed_at_utc")
    if at < source or (at - source).total_seconds() > MAX_SOURCE_AGE_SECONDS:
        raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityError("ADR-DC-088 source is stale")


def _descriptor(value: Any, *, expected_operation: str, expected_query_sha256: str) -> Mapping[str, str]:
    expected = {
        "broker_policy_sha256", "broker_executable_path", "broker_executable_path_sha256",
        "broker_executable_sha256", "broker_version", "credential_protocol", "graphql_operation",
        "secret_source", "secret_transport", "graphql_endpoint", "credential_account", "graphql_query_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityError("broker descriptor fields mismatch")
    out = {name: value[name] for name in expected}
    if any(not isinstance(item, str) or not item for item in out.values()):
        raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityError("broker descriptor contains invalid text")
    for name in ("broker_policy_sha256", "broker_executable_path_sha256", "broker_executable_sha256", "graphql_query_sha256"):
        _hex64(out[name], name=name)
    path = Path(out["broker_executable_path"])
    if (
        not path.is_absolute()
        or out["broker_executable_path_sha256"] != _path_sha256(path)
        or _VERSION.fullmatch(out["broker_version"]) is None
        or out["credential_protocol"] != PROTOCOL
        or out["graphql_operation"] != expected_operation
        or out["secret_source"] != SECRET_SOURCE
        or out["secret_transport"] != SECRET_TRANSPORT
        or out["graphql_endpoint"] != GRAPHQL_ENDPOINT
        or out["credential_account"] != CREDENTIAL_ACCOUNT
        or out["graphql_query_sha256"] != expected_query_sha256
    ):
        raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityError("broker descriptor semantics unsupported")
    return MappingProxyType(out)


_live: dict[int, tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[Any], Mapping[str, str]]] = {}


def _get_live_pr_strict_synced_review_thread_read_capability_inputs(value: Any) -> Mapping[str, Any] | None:
    row = _live.get(id(value))
    if row is None:
        return None
    pid, digest, ref, strict_ref, descriptor = row
    strict = strict_ref()
    if (
        pid != os.getpid() or ref() is not value or strict is None
        or strict.preflight_authenticated is not True
        or strict.sha256 != value.strict_base_sync_preflight_sha256
        or value.sha256 != digest
        or descriptor.get("broker_policy_sha256") != value.broker_policy_sha256
        or descriptor.get("broker_executable_sha256") != value.broker_executable_sha256
    ):
        return None
    return MappingProxyType({"strict_base_sync_preflight": strict, "broker_descriptor": descriptor})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrStrictSyncedReviewThreadReadCapability:
    strict_base_sync_preflight_sha256: str
    review_thread_read_requirements_sha256: str
    required_status_evaluation_sha256: str
    required_status_policy_sha256: str
    ruleset_applicability_sha256: str
    ruleset_observation_sha256: str
    status_check_observation_sha256: str
    repository: str
    pull_request_number: int
    predicted_commit_sha: str
    strict_base_tip_sha: str
    graphql_operation: str
    graphql_query_sha256: str
    broker_policy_sha256: str
    broker_executable_path_sha256: str
    broker_executable_sha256: str
    broker_version: str
    credential_protocol: str
    secret_source: str
    secret_transport: str
    graphql_endpoint: str
    credential_account_sha256: str
    materialized_at_utc: str
    source_strict_sync_verified: bool = True
    source_review_thread_requirements_verified: bool = True
    source_status_checks_passed: bool = True
    source_strict_base_sync_passed: bool = True
    fresh_source_age_verified: bool = True
    review_thread_read_capability_materialized: bool = True
    read_broker_host_pinned: bool = True
    read_broker_binary_verified: bool = True
    credential_secret_not_loaded: bool = True
    credential_broker_owns_https: bool = True
    graphql_query_only: bool = True
    graphql_mutations_forbidden: bool = True
    graphql_introspection_forbidden: bool = True
    other_repository_reads_forbidden: bool = True
    review_thread_state_observation_required: bool = True
    fresh_required_status_reobservation_before_merge_required: bool = True
    fresh_review_reobservation_required: bool = True
    fresh_merge_transaction_revalidation_required: bool = True
    branch_policy_fully_evaluated: bool = False
    credential_material_in_artifact: bool = False
    credential_material_in_process_arguments: bool = False
    credential_material_in_environment: bool = False
    review_thread_mutation_authorized: bool = False
    merge_readiness_authorized: bool = False
    merge_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = AUTHORITY
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        if self.schema != SCHEMA or self.authority != AUTHORITY:
            raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityError("capability schema/authority invalid")
        for name in (
            "strict_base_sync_preflight_sha256", "review_thread_read_requirements_sha256",
            "required_status_evaluation_sha256", "required_status_policy_sha256", "ruleset_applicability_sha256",
            "ruleset_observation_sha256", "status_check_observation_sha256", "graphql_query_sha256",
            "broker_policy_sha256", "broker_executable_path_sha256", "broker_executable_sha256",
            "credential_account_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("predicted_commit_sha", "strict_base_tip_sha"):
            _hex40(getattr(self, name), name=name)
        _utc(self.materialized_at_utc, name="materialized_at_utc")
        if (
            self.repository != _REPOSITORY
            or isinstance(self.pull_request_number, bool) or not isinstance(self.pull_request_number, int) or self.pull_request_number < 1
            or not isinstance(self.graphql_operation, str) or not self.graphql_operation
            or self.credential_protocol != PROTOCOL or self.secret_source != SECRET_SOURCE
            or self.secret_transport != SECRET_TRANSPORT or self.graphql_endpoint != GRAPHQL_ENDPOINT
            or self.credential_account_sha256 != hashlib.sha256(CREDENTIAL_ACCOUNT.encode("utf-8")).hexdigest()
            or _VERSION.fullmatch(self.broker_version) is None
        ):
            raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityError("capability target/broker identity invalid")
        required_true = (
            "source_strict_sync_verified", "source_review_thread_requirements_verified", "source_status_checks_passed",
            "source_strict_base_sync_passed", "fresh_source_age_verified", "review_thread_read_capability_materialized",
            "read_broker_host_pinned", "read_broker_binary_verified", "credential_secret_not_loaded",
            "credential_broker_owns_https", "graphql_query_only", "graphql_mutations_forbidden",
            "graphql_introspection_forbidden", "other_repository_reads_forbidden", "review_thread_state_observation_required",
            "fresh_required_status_reobservation_before_merge_required", "fresh_review_reobservation_required",
            "fresh_merge_transaction_revalidation_required",
        )
        forced_false = (
            "branch_policy_fully_evaluated", "credential_material_in_artifact", "credential_material_in_process_arguments",
            "credential_material_in_environment", "review_thread_mutation_authorized", "merge_readiness_authorized",
            "merge_authorized", "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true) or any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityError("capability evidence/authority invalid")

    @property
    def capability_authenticated(self) -> bool:
        return _get_live_pr_strict_synced_review_thread_read_capability_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    def canonical_json(self) -> str:
        return _canon(self.to_dict())

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrStrictSyncedReviewThreadReadCapability":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityError("capability fields mismatch")
        return cls(**dict(value))


def _materialize_verified_pilot_exact_task_pr_strict_synced_review_thread_read_capability(
    *, strict_base_sync_preflight: PilotExactTaskPrStrictBaseSyncPreflight,
    broker_descriptor: Mapping[str, str], now_provider: Callable[[], str],
) -> PilotExactTaskPrStrictSyncedReviewThreadReadCapability:
    live = _require_live_strict_sync(strict_base_sync_preflight)
    req = live["review_thread_read_requirements"]
    descriptor = _descriptor(
        broker_descriptor,
        expected_operation=req.graphql_operation,
        expected_query_sha256=strict_base_sync_preflight.review_thread_graphql_query_sha256,
    )
    at = now_provider()
    _require_source_window(strict_base_sync_preflight, at_utc=at)
    result = PilotExactTaskPrStrictSyncedReviewThreadReadCapability(
        strict_base_sync_preflight.sha256,
        strict_base_sync_preflight.review_thread_read_requirements_sha256,
        strict_base_sync_preflight.required_status_evaluation_sha256,
        strict_base_sync_preflight.required_status_policy_sha256,
        strict_base_sync_preflight.ruleset_applicability_sha256,
        strict_base_sync_preflight.ruleset_observation_sha256,
        strict_base_sync_preflight.status_check_observation_sha256,
        strict_base_sync_preflight.repository,
        strict_base_sync_preflight.pull_request_number,
        strict_base_sync_preflight.predicted_commit_sha,
        strict_base_sync_preflight.first_base_tip_sha,
        req.graphql_operation,
        strict_base_sync_preflight.review_thread_graphql_query_sha256,
        descriptor["broker_policy_sha256"], descriptor["broker_executable_path_sha256"],
        descriptor["broker_executable_sha256"], descriptor["broker_version"], descriptor["credential_protocol"],
        descriptor["secret_source"], descriptor["secret_transport"], descriptor["graphql_endpoint"],
        hashlib.sha256(descriptor["credential_account"].encode("utf-8")).hexdigest(), at,
    )
    key = id(result)
    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live.pop(key, None)
    _live[key] = (os.getpid(), result.sha256, weakref.ref(result, cleanup), weakref.ref(strict_base_sync_preflight), descriptor)
    if result.capability_authenticated is not True:
        raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityError("capability lost live provenance")
    return result


def materialize_pilot_exact_task_pr_strict_synced_review_thread_read_capability(
    strict_base_sync_preflight: PilotExactTaskPrStrictBaseSyncPreflight,
) -> PilotExactTaskPrStrictSyncedReviewThreadReadCapability:
    del strict_base_sync_preflight
    raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityError("production capability boundary not installed")


__all__ = [
    "SCHEMA", "AUTHORITY", "PROTOCOL", "SECRET_SOURCE", "SECRET_TRANSPORT", "GRAPHQL_ENDPOINT",
    "CREDENTIAL_ACCOUNT", "MAX_SOURCE_AGE_SECONDS", "PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityError",
    "PilotExactTaskPrStrictSyncedReviewThreadReadCapability",
    "materialize_pilot_exact_task_pr_strict_synced_review_thread_read_capability",
]
