"""ADR-DC-090 strict-synced reviewDecision + review-thread state observation.

Consumes one fresh live ADR-DC-089 host-pinned read capability, reverifies the
pinned broker binary, executes only the fixed GraphQL query through a bounded
subprocess, and requires two identical complete review-thread inventories.
This is read evidence only: review/thread policy and merge readiness remain
separate later gates.
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

from . import _improvement_pilot_exact_task_pr_strict_synced_review_thread_read_capability_production_boundary as _broker_boundary
from . import improvement_pilot_exact_task_pr_strict_synced_review_thread_read_capability as capability_boundary
from .bounded_subprocess import BoundedSubprocessError, run_bounded_subprocess
from .improvement_pilot_exact_task_pr_strict_synced_review_thread_read_capability import (
    PilotExactTaskPrStrictSyncedReviewThreadReadCapability,
)

SCHEMA = "kaliv-rsi-dc-l16-exact-task-pr-strict-synced-review-thread-state-observation/v1"
AUTHORITY = "observed-one-dc-l16-strict-synced-review-decision-thread-state-only"
OBSERVATION_SCOPE = "brokered-stable-strict-synced-review-decision-thread-read-only-v1"
REQUEST_SCHEMA = "kaliv-rsi-dc-l16-strict-synced-review-thread-read-broker-request/v1"
RESPONSE_SCHEMA = "kaliv-rsi-dc-l16-strict-synced-review-thread-read-broker-response/v1"
MAX_CAPABILITY_AGE_SECONDS = 10
MAX_OBSERVATION_WINDOW_SECONDS = 30
_REPOSITORY = "Ternedal/ModelRig"
_MAX_PAGES = 10
_PAGE_SIZE = 100
_MAX_OUTPUT_BYTES = 512 * 1024
_MAX_REQUEST_BYTES = 64 * 1024
_BROKER_TIMEOUT_SECONDS = 60
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_REVIEW_DECISIONS = frozenset({"NONE", "APPROVED", "CHANGES_REQUESTED", "REVIEW_REQUIRED"})


class PilotExactTaskPrStrictSyncedReviewThreadStateObservationError(ValueError):
    pass


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("evidence is not canonical JSON") from exc


def _canonical_bytes(value: Any) -> bytes:
    return _canonical(value).encode("utf-8")


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError(f"{name} invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError(f"{name} invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError(f"{name} invalid")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError(f"{name} invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _path_sha256(path: Path) -> str:
    return hashlib.sha256(os.fsencode(os.path.abspath(os.fspath(path)))).hexdigest()


def _broker_environment() -> dict[str, str]:
    environment = {"LANG": "C", "LC_ALL": "C"}
    if os.name == "nt":
        for name in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
            value = os.environ.get(name)
            if value and "\0" not in value:
                environment[name] = value
    if any(marker in key.upper() for key in environment for marker in ("TOKEN", "PASSWORD", "AUTHORIZATION", "BEARER", "COOKIE")):
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("broker environment contains credential-shaped keys")
    return environment


def _require_live_capability(
    value: Any,
) -> tuple[PilotExactTaskPrStrictSyncedReviewThreadReadCapability, Any, Mapping[str, str]]:
    if type(value) is not PilotExactTaskPrStrictSyncedReviewThreadReadCapability:
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("live ADR-DC-089 capability required")
    try:
        replay = PilotExactTaskPrStrictSyncedReviewThreadReadCapability.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("ADR-DC-089 replay validation failed") from exc
    live = capability_boundary._get_live_pr_strict_synced_review_thread_read_capability_inputs(value)
    strict = None if live is None else live.get("strict_base_sync_preflight")
    descriptor = None if live is None else live.get("broker_descriptor")
    required_true = (
        "source_strict_sync_verified", "source_review_thread_requirements_verified",
        "source_status_checks_passed", "source_strict_base_sync_passed", "fresh_source_age_verified",
        "review_thread_read_capability_materialized", "read_broker_host_pinned", "read_broker_binary_verified",
        "credential_secret_not_loaded", "credential_broker_owns_https", "graphql_query_only",
        "graphql_mutations_forbidden", "graphql_introspection_forbidden", "other_repository_reads_forbidden",
        "review_thread_state_observation_required", "fresh_required_status_reobservation_before_merge_required",
        "fresh_review_reobservation_required", "fresh_merge_transaction_revalidation_required",
    )
    forced_false = (
        "branch_policy_fully_evaluated", "credential_material_in_artifact",
        "credential_material_in_process_arguments", "credential_material_in_environment",
        "review_thread_mutation_authorized", "merge_readiness_authorized", "merge_authorized",
        "production_activation_authorized",
    )
    if (
        replay != value or replay.sha256 != value.sha256 or value.capability_authenticated is not True
        or live is None or strict is None or descriptor is None
        or getattr(strict, "preflight_authenticated", None) is not True
        or strict.sha256 != value.strict_base_sync_preflight_sha256
        or value.repository != _REPOSITORY
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
    ):
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("ADR-DC-089 provenance/authority invalid")
    checked = capability_boundary._descriptor(
        descriptor,
        expected_operation=value.graphql_operation,
        expected_query_sha256=value.graphql_query_sha256,
    )
    if (
        checked["broker_policy_sha256"] != value.broker_policy_sha256
        or checked["broker_executable_path_sha256"] != value.broker_executable_path_sha256
        or checked["broker_executable_sha256"] != value.broker_executable_sha256
        or checked["credential_protocol"] != value.credential_protocol
        or checked["graphql_operation"] != value.graphql_operation
        or checked["graphql_query_sha256"] != value.graphql_query_sha256
    ):
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("live ADR-DC-089 broker descriptor drifted")
    return value, strict, checked


def _require_capability_window(
    capability: PilotExactTaskPrStrictSyncedReviewThreadReadCapability,
    *,
    at_utc: str,
) -> None:
    at = _utc(at_utc, name="observation start")
    materialized = _utc(capability.materialized_at_utc, name="ADR-DC-089 materialized_at_utc")
    if at < materialized or (at - materialized).total_seconds() > MAX_CAPABILITY_AGE_SECONDS:
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("ADR-DC-089 capability is stale")


def _reverify_broker(
    *,
    capability: PilotExactTaskPrStrictSyncedReviewThreadReadCapability,
    descriptor: Mapping[str, str],
    require_host_control: bool,
) -> Path:
    path = Path(descriptor["broker_executable_path"])
    if not path.is_absolute() or _path_sha256(path) != capability.broker_executable_path_sha256:
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("broker path drifted")
    try:
        payload = _broker_boundary._read_broker_bytes(path, require_host_control=require_host_control)
    except Exception as exc:
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("broker binary could not be reverified") from exc
    if hashlib.sha256(payload).hexdigest() != capability.broker_executable_sha256:
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("broker binary hash drifted")
    return path


def _request(
    capability: PilotExactTaskPrStrictSyncedReviewThreadReadCapability,
    *,
    cursor: str | None,
) -> Mapping[str, Any]:
    owner, name = capability.repository.split("/", 1)
    request = {
        "schema": REQUEST_SCHEMA,
        "operation": capability.graphql_operation,
        "graphql_endpoint": capability.graphql_endpoint,
        "graphql_query_sha256": capability.graphql_query_sha256,
        "strict_synced_review_thread_read_capability_sha256": capability.sha256,
        "strict_base_sync_preflight_sha256": capability.strict_base_sync_preflight_sha256,
        "repository": capability.repository,
        "pull_request_number": capability.pull_request_number,
        "head_sha": capability.predicted_commit_sha,
        "strict_base_tip_sha": capability.strict_base_tip_sha,
        "variables": {
            "owner": owner,
            "name": name,
            "number": capability.pull_request_number,
            "threadsCursor": cursor,
        },
    }
    payload = _canonical_bytes(request)
    if not payload or len(payload) > _MAX_REQUEST_BYTES:
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("broker request exceeds bound")
    return MappingProxyType(request)


def _invoke(
    *,
    capability: PilotExactTaskPrStrictSyncedReviewThreadReadCapability,
    broker_path: Path,
    request: Mapping[str, Any],
    subprocess_runner: Callable[..., Any],
) -> tuple[Mapping[str, Any], str, str]:
    request_payload = _canonical_bytes(dict(request))
    request_sha256 = hashlib.sha256(request_payload).hexdigest()
    command = (
        os.fspath(broker_path), "--protocol", capability.credential_protocol,
        "--request-stdin-json", "--response-stdout-json",
    )
    try:
        result = subprocess_runner(
            command, cwd=broker_path.parent, env=_broker_environment(), stdin_bytes=request_payload,
            timeout_seconds=_BROKER_TIMEOUT_SECONDS, max_output_bytes=_MAX_OUTPUT_BYTES,
            stdout_prefix_bytes=_MAX_OUTPUT_BYTES, stderr_prefix_bytes=_MAX_OUTPUT_BYTES,
        )
    except BoundedSubprocessError as exc:
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("bounded broker failed") from exc
    if (
        result.returncode != 0 or result.output_limit_exceeded or result.timed_out
        or result.stdout.truncated or result.stderr.truncated or result.stderr.total_bytes != 0
        or result.stdout.total_bytes != len(result.stdout.prefix) or not result.stdout.prefix
    ):
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("broker did not complete cleanly")
    payload = bytes(result.stdout.prefix)
    if len(payload) > _MAX_OUTPUT_BYTES:
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("broker response exceeds bound")
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("broker response is not UTF-8 JSON") from exc
    expected = {"schema", "operation", "request_sha256", "strict_synced_review_thread_read_capability_sha256", "data"}
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("broker response fields mismatch")
    if (
        value.get("schema") != RESPONSE_SCHEMA or value.get("operation") != capability.graphql_operation
        or value.get("request_sha256") != request_sha256
        or value.get("strict_synced_review_thread_read_capability_sha256") != capability.sha256
        or not isinstance(value.get("data"), Mapping)
    ):
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("broker response not bound to exact request/capability")
    return MappingProxyType(dict(value["data"])), request_sha256, hashlib.sha256(payload).hexdigest()


def _thread_row(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"id", "isResolved", "isOutdated", "path"}:
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("thread row fields mismatch")
    node_id = value.get("id")
    path = value.get("path")
    if (
        not isinstance(node_id, str) or not node_id or len(node_id.encode("utf-8")) > 1024
        or not isinstance(path, str) or not path or len(path.encode("utf-8")) > 4096
        or "\0" in path or "\r" in path or "\n" in path or path.startswith("/")
        or not isinstance(value.get("isResolved"), bool) or not isinstance(value.get("isOutdated"), bool)
    ):
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("thread row invalid")
    return MappingProxyType({
        "thread_node_id_sha256": hashlib.sha256(node_id.encode("utf-8")).hexdigest(),
        "path": path, "is_resolved": value["isResolved"], "is_outdated": value["isOutdated"],
    })


def _page(
    *,
    capability: PilotExactTaskPrStrictSyncedReviewThreadReadCapability,
    data: Mapping[str, Any],
) -> tuple[str, str, str, tuple[Mapping[str, Any], ...], bool, str | None]:
    repository = data.get("repository")
    pr = repository.get("pullRequest") if isinstance(repository, Mapping) else None
    if not isinstance(repository, Mapping) or not isinstance(pr, Mapping):
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("GraphQL did not return exact pull request")
    node_id = pr.get("id")
    head_ref_name = pr.get("headRefName")
    decision = pr.get("reviewDecision")
    normalized_decision = "NONE" if decision is None else decision
    connection = pr.get("reviewThreads")
    if (
        not isinstance(node_id, str) or not node_id or len(node_id.encode("utf-8")) > 1024
        or pr.get("number") != capability.pull_request_number or pr.get("state") != "OPEN"
        or pr.get("isDraft") is not False or pr.get("baseRefName") != "main"
        or not isinstance(head_ref_name, str) or not head_ref_name or len(head_ref_name.encode("utf-8")) > 512
        or "\0" in head_ref_name or "\r" in head_ref_name or "\n" in head_ref_name
        or pr.get("headRefOid") != capability.predicted_commit_sha
        or normalized_decision not in _REVIEW_DECISIONS or not isinstance(connection, Mapping)
    ):
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("GraphQL PR identity/state drifted")
    if set(connection) != {"nodes", "pageInfo"}:
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("reviewThreads connection fields mismatch")
    nodes = connection.get("nodes")
    page_info = connection.get("pageInfo")
    if (
        not isinstance(nodes, list) or len(nodes) > _PAGE_SIZE or not isinstance(page_info, Mapping)
        or set(page_info) != {"hasNextPage", "endCursor"} or not isinstance(page_info.get("hasNextPage"), bool)
    ):
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("reviewThreads pagination invalid")
    has_next = page_info["hasNextPage"]
    cursor = page_info.get("endCursor")
    if has_next and (not isinstance(cursor, str) or not cursor or len(cursor) > 4096):
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("next cursor invalid")
    if not has_next and cursor is not None and not isinstance(cursor, str):
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("final cursor invalid")
    return (
        hashlib.sha256(node_id.encode("utf-8")).hexdigest(), head_ref_name, normalized_decision,
        tuple(_thread_row(item) for item in nodes), has_next, cursor,
    )


def _snapshot(
    *,
    capability: PilotExactTaskPrStrictSyncedReviewThreadReadCapability,
    descriptor: Mapping[str, str],
    subprocess_runner: Callable[..., Any],
    require_host_control: bool,
) -> Mapping[str, Any]:
    broker_path = _reverify_broker(capability=capability, descriptor=descriptor, require_host_control=require_host_control)
    rows: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    evidence: list[Mapping[str, Any]] = []
    cursor: str | None = None
    decision: str | None = None
    pr_node_id_sha256: str | None = None
    head_ref_name: str | None = None
    seen_cursors: set[str] = set()
    for page in range(1, _MAX_PAGES + 1):
        request = _request(capability, cursor=cursor)
        data, request_sha256, response_sha256 = _invoke(
            capability=capability, broker_path=broker_path, request=request, subprocess_runner=subprocess_runner,
        )
        current_node, current_head, current_decision, page_rows, has_next, next_cursor = _page(
            capability=capability, data=data,
        )
        if pr_node_id_sha256 is None:
            pr_node_id_sha256, head_ref_name, decision = current_node, current_head, current_decision
        elif current_node != pr_node_id_sha256 or current_head != head_ref_name or current_decision != decision:
            raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("PR/reviewDecision drifted during pagination")
        for row in page_rows:
            identity = str(row["thread_node_id_sha256"])
            if identity in seen:
                raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("duplicate thread identity")
            seen.add(identity)
            rows.append(row)
        evidence.append(MappingProxyType({
            "page": page, "request_sha256": request_sha256, "response_sha256": response_sha256,
            "row_count": len(page_rows),
            "cursor_sha256": hashlib.sha256(("" if cursor is None else cursor).encode("utf-8")).hexdigest(),
        }))
        if not has_next:
            break
        if next_cursor is None or next_cursor == cursor or next_cursor in seen_cursors:
            raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("cursor did not progress")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
        if page == _MAX_PAGES:
            raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("inventory completeness not provable")
    if pr_node_id_sha256 is None or head_ref_name is None or decision is None:
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("review-thread snapshot incomplete")
    normalized = tuple(sorted(rows, key=lambda item: str(item["thread_node_id_sha256"])))
    inventory_sha256 = hashlib.sha256(_canonical_bytes([dict(item) for item in normalized])).hexdigest()
    evidence_sha256 = hashlib.sha256(_canonical_bytes([dict(item) for item in evidence])).hexdigest()
    unresolved = sum(1 for item in normalized if not item["is_resolved"])
    unresolved_outdated = sum(1 for item in normalized if not item["is_resolved"] and item["is_outdated"])
    return MappingProxyType({
        "pull_request_node_id_sha256": pr_node_id_sha256, "head_ref_name": head_ref_name,
        "review_decision": decision, "thread_rows": normalized, "thread_inventory_sha256": inventory_sha256,
        "broker_evidence_sha256": evidence_sha256, "thread_count": len(normalized),
        "unresolved_thread_count": unresolved, "unresolved_outdated_thread_count": unresolved_outdated,
        "thread_page_count": len(evidence),
    })


_live_records: dict[int, tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[Any], tuple[Mapping[str, Any], ...]]] = {}


def _mark_authenticated(
    result: Any,
    capability: PilotExactTaskPrStrictSyncedReviewThreadReadCapability,
    thread_rows: tuple[Mapping[str, Any], ...],
) -> None:
    key = id(result)
    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)
    _live_records[key] = (os.getpid(), result.sha256, weakref.ref(result, cleanup), weakref.ref(capability), thread_rows)


def _get_live_pr_strict_synced_review_thread_state_observation_inputs(result: Any) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(result))
    if entry is None:
        return None
    pid, digest, result_ref, capability_ref, rows = entry
    capability = capability_ref()
    if (
        pid != os.getpid() or result_ref() is not result or capability is None
        or capability.capability_authenticated is not True
        or capability.sha256 != result.review_thread_read_capability_sha256
        or hashlib.sha256(_canonical_bytes([dict(item) for item in rows])).hexdigest() != result.review_threads_inventory_sha256
        or result.sha256 != digest
    ):
        return None
    return MappingProxyType({"review_thread_read_capability": capability, "review_threads": rows})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrStrictSyncedReviewThreadStateObservation:
    review_thread_read_capability_sha256: str
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
    credential_protocol: str
    pull_request_node_id_sha256: str
    head_ref_name: str
    first_review_threads_inventory_sha256: str
    second_review_threads_inventory_sha256: str
    review_threads_inventory_sha256: str
    first_broker_evidence_sha256: str
    second_broker_evidence_sha256: str
    github_review_decision: str
    review_thread_count: int
    unresolved_review_thread_count: int
    unresolved_outdated_review_thread_count: int
    review_thread_page_count: int
    first_observed_at_utc: str
    second_observed_at_utc: str
    source_capability_verified: bool = True
    source_strict_sync_verified: bool = True
    source_status_checks_passed: bool = True
    source_strict_base_sync_passed: bool = True
    fresh_capability_age_verified: bool = True
    broker_binary_reverified: bool = True
    graphql_fixed_query_verified: bool = True
    exact_repository_pr_head_revalidated: bool = True
    review_decision_observed: bool = True
    review_threads_observed: bool = True
    review_thread_inventory_complete: bool = True
    stable_double_observation_verified: bool = True
    credential_secret_not_loaded: bool = True
    credential_broker_owns_https: bool = True
    bounded_broker_process: bool = True
    broker_stderr_empty: bool = True
    pagination_bounded: bool = True
    review_thread_state_observation_completed: bool = True
    review_thread_policy_evaluation_required: bool = True
    fresh_required_status_reobservation_before_merge_required: bool = True
    fresh_review_reobservation_required: bool = True
    fresh_merge_transaction_revalidation_required: bool = True
    branch_policy_fully_evaluated: bool = False
    review_thread_policy_evaluated: bool = False
    credential_material_in_artifact: bool = False
    credential_material_in_process_arguments: bool = False
    credential_material_in_environment: bool = False
    review_thread_mutation_authorized: bool = False
    merge_readiness_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = AUTHORITY
    observation_scope: str = OBSERVATION_SCOPE
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        if self.schema != SCHEMA or self.authority != AUTHORITY or self.observation_scope != OBSERVATION_SCOPE:
            raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("schema/authority/scope invalid")
        for name in (
            "review_thread_read_capability_sha256", "strict_base_sync_preflight_sha256",
            "review_thread_read_requirements_sha256", "required_status_evaluation_sha256",
            "required_status_policy_sha256", "ruleset_applicability_sha256", "ruleset_observation_sha256",
            "status_check_observation_sha256", "graphql_query_sha256", "broker_policy_sha256",
            "broker_executable_path_sha256", "broker_executable_sha256", "pull_request_node_id_sha256",
            "first_review_threads_inventory_sha256", "second_review_threads_inventory_sha256",
            "review_threads_inventory_sha256", "first_broker_evidence_sha256", "second_broker_evidence_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("predicted_commit_sha", "strict_base_tip_sha"):
            _hex40(getattr(self, name), name=name)
        first = _utc(self.first_observed_at_utc, name="first_observed_at_utc")
        second = _utc(self.second_observed_at_utc, name="second_observed_at_utc")
        if second < first or (second - first).total_seconds() > MAX_OBSERVATION_WINDOW_SECONDS:
            raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("observation window invalid")
        if (
            self.repository != _REPOSITORY or isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int) or self.pull_request_number < 1
            or not isinstance(self.graphql_operation, str) or not self.graphql_operation
            or not isinstance(self.credential_protocol, str) or not self.credential_protocol
            or not isinstance(self.head_ref_name, str) or not self.head_ref_name
            or len(self.head_ref_name.encode("utf-8")) > 512
            or self.github_review_decision not in _REVIEW_DECISIONS
        ):
            raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("target/observed identity invalid")
        for name in (
            "review_thread_count", "unresolved_review_thread_count", "unresolved_outdated_review_thread_count",
            "review_thread_page_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError(f"{name} invalid")
        if (
            self.review_thread_page_count < 1 or self.review_thread_page_count > _MAX_PAGES
            or self.unresolved_review_thread_count > self.review_thread_count
            or self.unresolved_outdated_review_thread_count > self.unresolved_review_thread_count
            or self.first_review_threads_inventory_sha256 != self.second_review_threads_inventory_sha256
            or self.review_threads_inventory_sha256 != self.first_review_threads_inventory_sha256
        ):
            raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("inventory/count evidence invalid")
        required_true = (
            "source_capability_verified", "source_strict_sync_verified", "source_status_checks_passed",
            "source_strict_base_sync_passed", "fresh_capability_age_verified", "broker_binary_reverified",
            "graphql_fixed_query_verified", "exact_repository_pr_head_revalidated", "review_decision_observed",
            "review_threads_observed", "review_thread_inventory_complete", "stable_double_observation_verified",
            "credential_secret_not_loaded", "credential_broker_owns_https", "bounded_broker_process",
            "broker_stderr_empty", "pagination_bounded", "review_thread_state_observation_completed",
            "review_thread_policy_evaluation_required", "fresh_required_status_reobservation_before_merge_required",
            "fresh_review_reobservation_required", "fresh_merge_transaction_revalidation_required",
        )
        forced_false = (
            "branch_policy_fully_evaluated", "review_thread_policy_evaluated",
            "credential_material_in_artifact", "credential_material_in_process_arguments",
            "credential_material_in_environment", "review_thread_mutation_authorized",
            "merge_readiness_authorized", "merge_authorized", "release_authorized",
            "deploy_authorized", "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true) or any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("evidence/authority invalid")

    @property
    def observation_authenticated(self) -> bool:
        return _get_live_pr_strict_synced_review_thread_state_observation_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrStrictSyncedReviewThreadStateObservation":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("fields mismatch")
        return cls(**dict(value))


def _observe_verified_pilot_exact_task_pr_strict_synced_review_thread_state(
    *,
    review_thread_read_capability: PilotExactTaskPrStrictSyncedReviewThreadReadCapability,
    subprocess_runner: Callable[..., Any],
    now_provider: Callable[[], str],
    require_host_control: bool,
) -> PilotExactTaskPrStrictSyncedReviewThreadStateObservation:
    capability, strict, descriptor = _require_live_capability(review_thread_read_capability)
    first_at = now_provider()
    _require_capability_window(capability, at_utc=first_at)
    first = _snapshot(
        capability=capability, descriptor=descriptor, subprocess_runner=subprocess_runner,
        require_host_control=require_host_control,
    )
    second = _snapshot(
        capability=capability, descriptor=descriptor, subprocess_runner=subprocess_runner,
        require_host_control=require_host_control,
    )
    second_at = now_provider()
    first_dt = _utc(first_at, name="first_observed_at_utc")
    second_dt = _utc(second_at, name="second_observed_at_utc")
    if second_dt < first_dt or (second_dt - first_dt).total_seconds() > MAX_OBSERVATION_WINDOW_SECONDS:
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("observation clock/window invalid")
    stable_keys = (
        "pull_request_node_id_sha256", "head_ref_name", "review_decision", "thread_inventory_sha256",
        "thread_count", "unresolved_thread_count", "unresolved_outdated_thread_count", "thread_page_count",
    )
    if any(first[name] != second[name] for name in stable_keys):
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("double observation drifted")
    result = PilotExactTaskPrStrictSyncedReviewThreadStateObservation(
        capability.sha256, capability.strict_base_sync_preflight_sha256,
        capability.review_thread_read_requirements_sha256, capability.required_status_evaluation_sha256,
        capability.required_status_policy_sha256, capability.ruleset_applicability_sha256,
        capability.ruleset_observation_sha256, capability.status_check_observation_sha256,
        capability.repository, capability.pull_request_number, capability.predicted_commit_sha,
        capability.strict_base_tip_sha, capability.graphql_operation, capability.graphql_query_sha256,
        capability.broker_policy_sha256, capability.broker_executable_path_sha256,
        capability.broker_executable_sha256, capability.credential_protocol,
        first["pull_request_node_id_sha256"], first["head_ref_name"],
        first["thread_inventory_sha256"], second["thread_inventory_sha256"], first["thread_inventory_sha256"],
        first["broker_evidence_sha256"], second["broker_evidence_sha256"], first["review_decision"],
        first["thread_count"], first["unresolved_thread_count"], first["unresolved_outdated_thread_count"],
        first["thread_page_count"], first_at, second_at,
    )
    _mark_authenticated(result, capability, first["thread_rows"])
    if result.observation_authenticated is not True:
        raise PilotExactTaskPrStrictSyncedReviewThreadStateObservationError("observation lost live provenance")
    return result


def observe_pilot_exact_task_pr_strict_synced_review_thread_state(
    review_thread_read_capability: PilotExactTaskPrStrictSyncedReviewThreadReadCapability,
) -> PilotExactTaskPrStrictSyncedReviewThreadStateObservation:
    return _observe_verified_pilot_exact_task_pr_strict_synced_review_thread_state(
        review_thread_read_capability=review_thread_read_capability,
        subprocess_runner=run_bounded_subprocess, now_provider=_now_utc_seconds, require_host_control=True,
    )


__all__ = [
    "SCHEMA", "AUTHORITY", "OBSERVATION_SCOPE",
    "PilotExactTaskPrStrictSyncedReviewThreadStateObservationError",
    "PilotExactTaskPrStrictSyncedReviewThreadStateObservation",
    "observe_pilot_exact_task_pr_strict_synced_review_thread_state",
]
