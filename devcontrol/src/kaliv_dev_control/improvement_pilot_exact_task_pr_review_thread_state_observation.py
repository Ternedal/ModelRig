"""ADR-DC-083 exact reviewDecision + review-thread state observation.

Consumes one fresh live ADR-DC-082 host-pinned GraphQL read capability. The
observer invokes only the capability's hash-pinned broker protocol, sends the
fixed query digest plus exact PR/head variables over stdin, and never loads a
GitHub credential. The complete bounded reviewThreads inventory is observed
twice and must remain identical.

This is evidence only. It does not evaluate required status checks, branch
policy, review-thread policy, or merge readiness and grants no mutation
authority.
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

from . import _improvement_pilot_exact_task_pr_status_review_thread_credential_capability_production_boundary as _broker_boundary
from . import improvement_pilot_exact_task_pr_status_review_thread_credential_capability as capability_boundary
from .bounded_subprocess import BoundedSubprocessError, run_bounded_subprocess
from .improvement_pilot_exact_task_pr_status_review_thread_credential_capability import (
    PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_CREDENTIAL_CAPABILITY_AUTHORITY,
    PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_CREDENTIAL_PROTOCOL,
    PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_GRAPHQL_ENDPOINT,
    PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_GRAPHQL_OPERATION,
    PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_GRAPHQL_QUERY,
    PilotExactTaskPrStatusReviewThreadCredentialCapability,
)

PILOT_EXACT_TASK_PR_REVIEW_THREAD_STATE_OBSERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-review-thread-state-observation/v1"
)
PILOT_EXACT_TASK_PR_REVIEW_THREAD_STATE_OBSERVATION_AUTHORITY = (
    "observed-one-dc-l16-exact-pr-review-decision-thread-state-only"
)
PILOT_EXACT_TASK_PR_REVIEW_THREAD_STATE_OBSERVATION_SCOPE = (
    "brokered-stable-exact-pr-review-decision-thread-read-only-v1"
)
PILOT_EXACT_TASK_PR_REVIEW_THREAD_BROKER_REQUEST_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-review-thread-read-broker-request/v1"
)
PILOT_EXACT_TASK_PR_REVIEW_THREAD_BROKER_RESPONSE_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-review-thread-read-broker-response/v1"
)
PILOT_EXACT_TASK_PR_REVIEW_THREAD_STATE_MAX_CAPABILITY_AGE_SECONDS = 10

_REPOSITORY = "Ternedal/ModelRig"
_MAX_PAGES = 10
_PAGE_SIZE = 100
_MAX_OUTPUT_BYTES = 512 * 1024
_MAX_REQUEST_BYTES = 64 * 1024
_BROKER_TIMEOUT_SECONDS = 60
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_REVIEW_DECISIONS = frozenset({"NONE", "APPROVED", "CHANGES_REQUESTED", "REVIEW_REQUIRED"})


class PilotExactTaskPrReviewThreadStateObservationError(ValueError):
    """Review-thread evidence is stale, drifted, incomplete, or unsafe."""


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "review-thread evidence is not canonical JSON"
        ) from exc


def _canonical_bytes(value: Any) -> bytes:
    return _canonical(value).encode("utf-8")


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskPrReviewThreadStateObservationError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskPrReviewThreadStateObservationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrReviewThreadStateObservationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrReviewThreadStateObservationError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _path_sha256(path: Path) -> str:
    return hashlib.sha256(
        os.fsencode(os.path.abspath(os.fspath(path)))
    ).hexdigest()


def _broker_environment() -> dict[str, str]:
    environment = {"LANG": "C", "LC_ALL": "C"}
    if os.name == "nt":
        for name in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
            value = os.environ.get(name)
            if value and "\0" not in value:
                environment[name] = value
    if any(
        marker in key.upper()
        for key in environment
        for marker in ("TOKEN", "PASSWORD", "AUTHORIZATION", "BEARER", "COOKIE")
    ):
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "review-thread broker environment contains credential-shaped keys"
        )
    return environment


def _require_live_capability(
    value: Any,
) -> tuple[
    PilotExactTaskPrStatusReviewThreadCredentialCapability,
    Any,
    Mapping[str, str],
]:
    if type(value) is not PilotExactTaskPrStatusReviewThreadCredentialCapability:
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "exact live ADR-DC-082 review-thread credential capability is required"
        )
    try:
        replayed = (
            PilotExactTaskPrStatusReviewThreadCredentialCapability.from_mapping(
                value.to_dict()
            )
        )
    except Exception as exc:
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "ADR-DC-082 capability replay validation failed"
        ) from exc
    live = (
        capability_boundary
        ._get_live_pr_status_review_thread_credential_capability_inputs(value)
    )
    source = None if live is None else live.get("status_check_observation")
    descriptor = None if live is None else live.get("credential_broker_descriptor")
    required_true = (
        "status_check_observation_verified",
        "source_merge_preflight_verified",
        "source_approved_review_verified",
        "source_exact_head_status_inventory_verified",
        "source_status_policy_not_evaluated",
        "source_required_status_checks_not_evaluated",
        "source_review_threads_required",
        "source_branch_policy_required",
        "source_fresh_review_reobservation_required",
        "source_fresh_merge_transaction_revalidation_required",
        "review_thread_credential_capability_materialized",
        "read_broker_host_pinned",
        "read_broker_binary_verified",
        "credential_secret_not_loaded",
        "credential_broker_owns_https",
        "review_decision_read_only",
        "review_threads_read_only",
        "graphql_queries_only",
        "graphql_mutations_forbidden",
        "graphql_introspection_forbidden",
        "redirect_following_forbidden",
        "rest_review_read_forbidden",
        "other_repository_reads_forbidden",
        "review_submission_write_forbidden",
        "review_dismissal_write_forbidden",
        "review_thread_mutation_forbidden",
        "reviewer_request_write_forbidden",
        "pull_request_create_forbidden",
        "pull_request_metadata_write_forbidden",
        "ready_for_review_write_forbidden",
        "label_write_forbidden",
        "merge_write_forbidden",
        "repository_contents_write_forbidden",
        "administration_write_forbidden",
        "release_write_forbidden",
        "deployment_write_forbidden",
        "review_thread_state_observation_required",
        "required_status_checks_evaluation_still_required",
        "branch_policy_still_required",
        "fresh_review_reobservation_still_required",
        "fresh_merge_transaction_revalidation_still_required",
    )
    forced_false = (
        "credential_material_in_artifact",
        "credential_material_in_process_arguments",
        "credential_material_in_environment",
        "nonce_reusable",
        "reviewer_mutation_authorized",
        "review_submission_authorized",
        "review_thread_mutation_authorized",
        "merge_readiness_authorized",
        "label_mutation_authorized",
        "merge_authorized",
        "release_authorized",
        "deploy_authorized",
        "production_activation_authorized",
    )
    if (
        replayed != value
        or replayed.sha256 != value.sha256
        or value.authority
        != PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_CREDENTIAL_CAPABILITY_AUTHORITY
        or value.capability_authenticated is not True
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
        or value.repository != _REPOSITORY
        or value.base_branch != "main"
        or _HEAD.fullmatch(value.head_branch) is None
        or value.credential_protocol
        != PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_CREDENTIAL_PROTOCOL
        or value.graphql_operation
        != PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_GRAPHQL_OPERATION
        or value.graphql_endpoint
        != PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_GRAPHQL_ENDPOINT
        or value.graphql_query_sha256
        != _sha256_text(PILOT_EXACT_TASK_PR_STATUS_REVIEW_THREAD_GRAPHQL_QUERY)
        or source is None
        or getattr(source, "observation_authenticated", None) is not True
        or source.sha256 != value.status_check_observation_sha256
        or descriptor is None
        or not isinstance(descriptor, Mapping)
    ):
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "ADR-DC-083 requires one live inert ADR-DC-082 capability"
        )
    checked = capability_boundary._descriptor(descriptor)
    if (
        checked["broker_policy_sha256"] != value.broker_policy_sha256
        or checked["broker_executable_path_sha256"]
        != value.broker_executable_path_sha256
        or checked["broker_executable_sha256"] != value.broker_executable_sha256
        or checked["graphql_query_sha256"] != value.graphql_query_sha256
    ):
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "live broker descriptor drifted from ADR-DC-082 capability"
        )
    return value, source, checked


def _require_capability_window(
    capability: PilotExactTaskPrStatusReviewThreadCredentialCapability,
    *,
    at_utc: str,
) -> None:
    at = _utc(at_utc, name="review-thread observation time")
    materialized = _utc(
        capability.materialized_at_utc,
        name="ADR-DC-082 materialized_at_utc",
    )
    if (
        at < materialized
        or (at - materialized).total_seconds()
        > PILOT_EXACT_TASK_PR_REVIEW_THREAD_STATE_MAX_CAPABILITY_AGE_SECONDS
    ):
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "ADR-DC-082 capability is too old for review-thread observation"
        )


def _reverify_broker(
    *,
    capability: PilotExactTaskPrStatusReviewThreadCredentialCapability,
    descriptor: Mapping[str, str],
    require_host_control: bool,
) -> Path:
    path = Path(descriptor["broker_executable_path"])
    if (
        not path.is_absolute()
        or _path_sha256(path) != capability.broker_executable_path_sha256
    ):
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "review-thread broker path drifted from capability"
        )
    try:
        payload = _broker_boundary._read_broker_bytes(
            path,
            require_host_control=require_host_control,
        )
    except Exception as exc:
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "review-thread broker binary could not be reverified"
        ) from exc
    if hashlib.sha256(payload).hexdigest() != capability.broker_executable_sha256:
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "review-thread broker binary hash drifted from capability"
        )
    return path


def _request(
    capability: PilotExactTaskPrStatusReviewThreadCredentialCapability,
    *,
    cursor: str | None,
) -> Mapping[str, Any]:
    owner, name = capability.repository.split("/", 1)
    request = {
        "schema": PILOT_EXACT_TASK_PR_REVIEW_THREAD_BROKER_REQUEST_SCHEMA,
        "operation": capability.graphql_operation,
        "graphql_endpoint": capability.graphql_endpoint,
        "graphql_query_sha256": capability.graphql_query_sha256,
        "review_thread_credential_capability_sha256": capability.sha256,
        "repository": capability.repository,
        "pull_request_number": capability.pull_request_number,
        "pull_request_node_id_sha256": capability.pull_request_node_id_sha256,
        "head_sha": capability.predicted_commit_sha,
        "variables": {
            "owner": owner,
            "name": name,
            "number": capability.pull_request_number,
            "threadsCursor": cursor,
        },
    }
    payload = _canonical_bytes(request)
    if not payload or len(payload) > _MAX_REQUEST_BYTES:
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "review-thread broker request exceeds bound"
        )
    return MappingProxyType(request)


def _invoke(
    *,
    capability: PilotExactTaskPrStatusReviewThreadCredentialCapability,
    broker_path: Path,
    request: Mapping[str, Any],
    subprocess_runner: Callable[..., Any],
) -> tuple[Mapping[str, Any], str, str]:
    request_payload = _canonical_bytes(dict(request))
    request_sha256 = hashlib.sha256(request_payload).hexdigest()
    command = (
        os.fspath(broker_path),
        "--protocol",
        capability.credential_protocol,
        "--request-stdin-json",
        "--response-stdout-json",
    )
    try:
        result = subprocess_runner(
            command,
            cwd=broker_path.parent,
            env=_broker_environment(),
            stdin_bytes=request_payload,
            timeout_seconds=_BROKER_TIMEOUT_SECONDS,
            max_output_bytes=_MAX_OUTPUT_BYTES,
            stdout_prefix_bytes=_MAX_OUTPUT_BYTES,
            stderr_prefix_bytes=_MAX_OUTPUT_BYTES,
        )
    except BoundedSubprocessError as exc:
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "bounded review-thread read broker failed"
        ) from exc
    if (
        result.returncode != 0
        or result.output_limit_exceeded
        or result.timed_out
        or result.stdout.truncated
        or result.stderr.truncated
        or result.stderr.total_bytes != 0
        or result.stdout.total_bytes != len(result.stdout.prefix)
        or not result.stdout.prefix
    ):
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "review-thread read broker did not complete cleanly"
        )
    payload = bytes(result.stdout.prefix)
    if len(payload) > _MAX_OUTPUT_BYTES:
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "review-thread broker response exceeds bound"
        )
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "review-thread broker response is not UTF-8 JSON"
        ) from exc
    expected = {
        "schema",
        "operation",
        "request_sha256",
        "review_thread_credential_capability_sha256",
        "data",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "review-thread broker response fields mismatch"
        )
    if (
        value.get("schema")
        != PILOT_EXACT_TASK_PR_REVIEW_THREAD_BROKER_RESPONSE_SCHEMA
        or value.get("operation") != capability.graphql_operation
        or value.get("request_sha256") != request_sha256
        or value.get("review_thread_credential_capability_sha256")
        != capability.sha256
        or not isinstance(value.get("data"), Mapping)
    ):
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "review-thread broker response is not bound to exact request/capability"
        )
    return (
        MappingProxyType(dict(value["data"])),
        request_sha256,
        hashlib.sha256(payload).hexdigest(),
    )


def _thread_row(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "id",
        "isResolved",
        "isOutdated",
        "path",
    }:
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "review-thread row fields mismatch"
        )
    node_id = value.get("id")
    path = value.get("path")
    if (
        not isinstance(node_id, str)
        or not node_id
        or len(node_id.encode("utf-8")) > 1024
        or not isinstance(path, str)
        or not path
        or len(path.encode("utf-8")) > 4096
        or "\0" in path
        or "\r" in path
        or "\n" in path
        or path.startswith("/")
        or not isinstance(value.get("isResolved"), bool)
        or not isinstance(value.get("isOutdated"), bool)
    ):
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "review-thread row is invalid"
        )
    return MappingProxyType(
        {
            "thread_node_id_sha256": hashlib.sha256(
                node_id.encode("utf-8")
            ).hexdigest(),
            "path": path,
            "is_resolved": value["isResolved"],
            "is_outdated": value["isOutdated"],
        }
    )


def _page(
    *,
    capability: PilotExactTaskPrStatusReviewThreadCredentialCapability,
    data: Mapping[str, Any],
) -> tuple[str, tuple[Mapping[str, Any], ...], bool, str | None]:
    repository = data.get("repository")
    pr = repository.get("pullRequest") if isinstance(repository, Mapping) else None
    if not isinstance(repository, Mapping) or not isinstance(pr, Mapping):
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "GraphQL broker did not return exact pull request"
        )
    node_id = pr.get("id")
    decision = pr.get("reviewDecision")
    normalized_decision = "NONE" if decision is None else decision
    connection = pr.get("reviewThreads")
    if (
        not isinstance(node_id, str)
        or not node_id
        or hashlib.sha256(node_id.encode("utf-8")).hexdigest()
        != capability.pull_request_node_id_sha256
        or pr.get("number") != capability.pull_request_number
        or pr.get("state") != "OPEN"
        or pr.get("isDraft") is not False
        or pr.get("baseRefName") != capability.base_branch
        or pr.get("headRefName") != capability.head_branch
        or pr.get("headRefOid") != capability.predicted_commit_sha
        or normalized_decision not in _REVIEW_DECISIONS
        or not isinstance(connection, Mapping)
    ):
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "GraphQL pull-request identity/state drifted from capability"
        )
    if set(connection) != {"nodes", "pageInfo"}:
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "reviewThreads connection fields mismatch"
        )
    nodes = connection.get("nodes")
    page_info = connection.get("pageInfo")
    if (
        not isinstance(nodes, list)
        or len(nodes) > _PAGE_SIZE
        or not isinstance(page_info, Mapping)
        or set(page_info) != {"hasNextPage", "endCursor"}
        or not isinstance(page_info.get("hasNextPage"), bool)
    ):
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "reviewThreads pagination shape is invalid"
        )
    has_next = page_info["hasNextPage"]
    cursor = page_info.get("endCursor")
    if has_next and (not isinstance(cursor, str) or not cursor or len(cursor) > 4096):
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "reviewThreads next cursor is invalid"
        )
    if not has_next and cursor is not None and not isinstance(cursor, str):
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "reviewThreads final cursor is invalid"
        )
    return (
        normalized_decision,
        tuple(_thread_row(item) for item in nodes),
        has_next,
        cursor,
    )


def _snapshot(
    *,
    capability: PilotExactTaskPrStatusReviewThreadCredentialCapability,
    descriptor: Mapping[str, str],
    subprocess_runner: Callable[..., Any],
    require_host_control: bool,
) -> Mapping[str, Any]:
    broker_path = _reverify_broker(
        capability=capability,
        descriptor=descriptor,
        require_host_control=require_host_control,
    )
    rows: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    evidence: list[Mapping[str, Any]] = []
    cursor: str | None = None
    decision: str | None = None
    seen_cursors: set[str] = set()

    for page in range(1, _MAX_PAGES + 1):
        request = _request(capability, cursor=cursor)
        data, request_sha256, response_sha256 = _invoke(
            capability=capability,
            broker_path=broker_path,
            request=request,
            subprocess_runner=subprocess_runner,
        )
        current_decision, page_rows, has_next, next_cursor = _page(
            capability=capability,
            data=data,
        )
        if decision is None:
            decision = current_decision
        elif current_decision != decision:
            raise PilotExactTaskPrReviewThreadStateObservationError(
                "reviewDecision drifted during thread pagination"
            )
        for row in page_rows:
            identity = str(row["thread_node_id_sha256"])
            if identity in seen:
                raise PilotExactTaskPrReviewThreadStateObservationError(
                    "duplicate review-thread identity across pagination"
                )
            seen.add(identity)
            rows.append(row)
        evidence.append(
            MappingProxyType(
                {
                    "page": page,
                    "request_sha256": request_sha256,
                    "response_sha256": response_sha256,
                    "row_count": len(page_rows),
                    "cursor_sha256": hashlib.sha256(
                        ("" if cursor is None else cursor).encode("utf-8")
                    ).hexdigest(),
                }
            )
        )
        if not has_next:
            break
        if next_cursor is None or next_cursor in seen_cursors or next_cursor == cursor:
            raise PilotExactTaskPrReviewThreadStateObservationError(
                "reviewThreads cursor did not make progress"
            )
        seen_cursors.add(next_cursor)
        cursor = next_cursor
        if page == _MAX_PAGES:
            raise PilotExactTaskPrReviewThreadStateObservationError(
                "reviewThreads inventory completeness is not provable within page bound"
            )
    else:
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "reviewThreads pagination exceeded bounded limit"
        )

    if decision is None:
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "reviewDecision was not observed"
        )
    normalized = tuple(
        sorted(rows, key=lambda item: str(item["thread_node_id_sha256"]))
    )
    inventory_sha256 = hashlib.sha256(
        _canonical_bytes([dict(item) for item in normalized])
    ).hexdigest()
    evidence_sha256 = hashlib.sha256(
        _canonical_bytes([dict(item) for item in evidence])
    ).hexdigest()
    unresolved = sum(1 for item in normalized if not item["is_resolved"])
    unresolved_outdated = sum(
        1
        for item in normalized
        if not item["is_resolved"] and item["is_outdated"]
    )
    return MappingProxyType(
        {
            "review_decision": decision,
            "thread_rows": normalized,
            "thread_inventory_sha256": inventory_sha256,
            "broker_evidence_sha256": evidence_sha256,
            "thread_count": len(normalized),
            "unresolved_thread_count": unresolved,
            "unresolved_outdated_thread_count": unresolved_outdated,
            "thread_page_count": len(evidence),
        }
    )


_live_records: dict[
    int,
    tuple[
        int,
        str,
        weakref.ReferenceType[Any],
        weakref.ReferenceType[
            PilotExactTaskPrStatusReviewThreadCredentialCapability
        ],
        tuple[Mapping[str, Any], ...],
    ],
] = {}


def _mark_authenticated(
    result: Any,
    capability: PilotExactTaskPrStatusReviewThreadCredentialCapability,
    thread_rows: tuple[Mapping[str, Any], ...],
) -> None:
    key = id(result)

    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)

    _live_records[key] = (
        os.getpid(),
        result.sha256,
        weakref.ref(result, cleanup),
        weakref.ref(capability),
        thread_rows,
    )


def _get_live_pr_review_thread_state_observation_inputs(
    result: Any,
) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(result))
    if entry is None:
        return None
    pid, digest, result_ref, capability_ref, rows = entry
    capability = capability_ref()
    if (
        pid != os.getpid()
        or result_ref() is not result
        or capability is None
        or capability.capability_authenticated is not True
        or capability.sha256 != result.review_thread_credential_capability_sha256
        or hashlib.sha256(
            _canonical_bytes([dict(item) for item in rows])
        ).hexdigest()
        != result.review_threads_inventory_sha256
        or result.sha256 != digest
    ):
        return None
    return MappingProxyType(
        {
            "review_thread_credential_capability": capability,
            "review_threads": rows,
        }
    )


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReviewThreadStateObservation:
    review_thread_credential_capability_sha256: str
    status_check_observation_sha256: str
    merge_preflight_sha256: str
    review_disposition_sha256: str
    submitted_review_observation_sha256: str
    review_observation_checkpoint_sha256: str
    reviewer_handoff_requirements_sha256: str
    repository: str
    pull_request_number: int
    pull_request_node_id_sha256: str
    base_branch: str
    head_branch: str
    predicted_commit_sha: str
    check_runs_inventory_sha256: str
    legacy_statuses_inventory_sha256: str
    status_combined_evidence_sha256: str
    broker_policy_sha256: str
    broker_executable_path_sha256: str
    broker_executable_sha256: str
    graphql_query_sha256: str
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
    source_status_check_observation_verified: bool = True
    source_approved_review_preflight_verified: bool = True
    source_status_policy_not_evaluated: bool = True
    source_required_status_checks_not_evaluated: bool = True
    fresh_capability_age_verified: bool = True
    broker_binary_reverified: bool = True
    graphql_fixed_query_verified: bool = True
    exact_pr_identity_revalidated: bool = True
    exact_head_revalidated: bool = True
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
    required_status_checks_evaluation_still_required: bool = True
    branch_policy_still_required: bool = True
    fresh_review_reobservation_still_required: bool = True
    fresh_merge_transaction_revalidation_still_required: bool = True
    review_thread_policy_evaluated: bool = False
    required_status_checks_evaluated: bool = False
    status_policy_evaluated: bool = False
    credential_material_in_artifact: bool = False
    credential_material_in_process_arguments: bool = False
    credential_material_in_environment: bool = False
    reviewer_mutation_authorized: bool = False
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    label_mutation_authorized: bool = False
    merge_readiness_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_REVIEW_THREAD_STATE_OBSERVATION_AUTHORITY
    observation_scope: str = PILOT_EXACT_TASK_PR_REVIEW_THREAD_STATE_OBSERVATION_SCOPE
    schema: str = PILOT_EXACT_TASK_PR_REVIEW_THREAD_STATE_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PR_REVIEW_THREAD_STATE_OBSERVATION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PR_REVIEW_THREAD_STATE_OBSERVATION_AUTHORITY
            or self.observation_scope
            != PILOT_EXACT_TASK_PR_REVIEW_THREAD_STATE_OBSERVATION_SCOPE
        ):
            raise PilotExactTaskPrReviewThreadStateObservationError(
                "review-thread observation schema/authority/scope unsupported"
            )
        for name in (
            "review_thread_credential_capability_sha256",
            "status_check_observation_sha256",
            "merge_preflight_sha256",
            "review_disposition_sha256",
            "submitted_review_observation_sha256",
            "review_observation_checkpoint_sha256",
            "reviewer_handoff_requirements_sha256",
            "pull_request_node_id_sha256",
            "check_runs_inventory_sha256",
            "legacy_statuses_inventory_sha256",
            "status_combined_evidence_sha256",
            "broker_policy_sha256",
            "broker_executable_path_sha256",
            "broker_executable_sha256",
            "graphql_query_sha256",
            "first_review_threads_inventory_sha256",
            "second_review_threads_inventory_sha256",
            "review_threads_inventory_sha256",
            "first_broker_evidence_sha256",
            "second_broker_evidence_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        first = _utc(self.first_observed_at_utc, name="first_observed_at_utc")
        second = _utc(self.second_observed_at_utc, name="second_observed_at_utc")
        if second < first:
            raise PilotExactTaskPrReviewThreadStateObservationError(
                "review-thread observation clock moved backwards"
            )
        if (
            self.repository != _REPOSITORY
            or self.base_branch != "main"
            or _HEAD.fullmatch(self.head_branch) is None
            or isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.github_review_decision not in _REVIEW_DECISIONS
            or self.first_review_threads_inventory_sha256
            != self.second_review_threads_inventory_sha256
            or self.review_threads_inventory_sha256
            != self.first_review_threads_inventory_sha256
            or self.first_broker_evidence_sha256
            != self.second_broker_evidence_sha256
        ):
            raise PilotExactTaskPrReviewThreadStateObservationError(
                "review-thread observation exact target/evidence binding invalid"
            )
        for name in (
            "review_thread_count",
            "unresolved_review_thread_count",
            "unresolved_outdated_review_thread_count",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value <= _PAGE_SIZE * _MAX_PAGES
            ):
                raise PilotExactTaskPrReviewThreadStateObservationError(
                    f"{name} is invalid"
                )
        if (
            self.unresolved_review_thread_count > self.review_thread_count
            or self.unresolved_outdated_review_thread_count
            > self.unresolved_review_thread_count
            or isinstance(self.review_thread_page_count, bool)
            or not isinstance(self.review_thread_page_count, int)
            or not 1 <= self.review_thread_page_count <= _MAX_PAGES
        ):
            raise PilotExactTaskPrReviewThreadStateObservationError(
                "review-thread counts/pages are inconsistent"
            )
        required_true = (
            "source_capability_verified",
            "source_status_check_observation_verified",
            "source_approved_review_preflight_verified",
            "source_status_policy_not_evaluated",
            "source_required_status_checks_not_evaluated",
            "fresh_capability_age_verified",
            "broker_binary_reverified",
            "graphql_fixed_query_verified",
            "exact_pr_identity_revalidated",
            "exact_head_revalidated",
            "review_decision_observed",
            "review_threads_observed",
            "review_thread_inventory_complete",
            "stable_double_observation_verified",
            "credential_secret_not_loaded",
            "credential_broker_owns_https",
            "bounded_broker_process",
            "broker_stderr_empty",
            "pagination_bounded",
            "review_thread_state_observation_completed",
            "required_status_checks_evaluation_still_required",
            "branch_policy_still_required",
            "fresh_review_reobservation_still_required",
            "fresh_merge_transaction_revalidation_still_required",
        )
        forced_false = (
            "review_thread_policy_evaluated",
            "required_status_checks_evaluated",
            "status_policy_evaluated",
            "credential_material_in_artifact",
            "credential_material_in_process_arguments",
            "credential_material_in_environment",
            "reviewer_mutation_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "label_mutation_authorized",
            "merge_readiness_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrReviewThreadStateObservationError(
                "review-thread observation evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReviewThreadStateObservationError(
                "review-thread observation cannot evaluate policy or grant authority"
            )

    @property
    def observation_authenticated(self) -> bool:
        return _get_live_pr_review_thread_state_observation_inputs(self) is not None

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
        cls, value: Any
    ) -> "PilotExactTaskPrReviewThreadStateObservation":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReviewThreadStateObservationError(
                "review-thread observation must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReviewThreadStateObservationError(
                "review-thread observation fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _observe_verified_pilot_exact_task_pr_review_thread_state(
    *,
    review_thread_credential_capability: PilotExactTaskPrStatusReviewThreadCredentialCapability,
    subprocess_runner: Callable[..., Any],
    now_provider: Callable[[], str],
    broker_host_control_required: bool,
) -> PilotExactTaskPrReviewThreadStateObservation:
    capability, source, descriptor = _require_live_capability(
        review_thread_credential_capability
    )

    first_at = now_provider()
    _require_capability_window(capability, at_utc=first_at)
    first = _snapshot(
        capability=capability,
        descriptor=descriptor,
        subprocess_runner=subprocess_runner,
        require_host_control=broker_host_control_required,
    )

    second_at = now_provider()
    _require_capability_window(capability, at_utc=second_at)
    if _utc(second_at, name="second_observed_at_utc") < _utc(
        first_at, name="first_observed_at_utc"
    ):
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "clock moved backwards during review-thread observation"
        )
    second = _snapshot(
        capability=capability,
        descriptor=descriptor,
        subprocess_runner=subprocess_runner,
        require_host_control=broker_host_control_required,
    )

    stable_keys = (
        "review_decision",
        "thread_inventory_sha256",
        "broker_evidence_sha256",
        "thread_count",
        "unresolved_thread_count",
        "unresolved_outdated_thread_count",
        "thread_page_count",
    )
    if any(first[key] != second[key] for key in stable_keys):
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "reviewDecision/reviewThreads changed between complete observations"
        )

    result = PilotExactTaskPrReviewThreadStateObservation(
        review_thread_credential_capability_sha256=capability.sha256,
        status_check_observation_sha256=capability.status_check_observation_sha256,
        merge_preflight_sha256=capability.merge_preflight_sha256,
        review_disposition_sha256=capability.review_disposition_sha256,
        submitted_review_observation_sha256=capability.submitted_review_observation_sha256,
        review_observation_checkpoint_sha256=capability.review_observation_checkpoint_sha256,
        reviewer_handoff_requirements_sha256=capability.reviewer_handoff_requirements_sha256,
        repository=capability.repository,
        pull_request_number=capability.pull_request_number,
        pull_request_node_id_sha256=capability.pull_request_node_id_sha256,
        base_branch=capability.base_branch,
        head_branch=capability.head_branch,
        predicted_commit_sha=capability.predicted_commit_sha,
        check_runs_inventory_sha256=capability.check_runs_inventory_sha256,
        legacy_statuses_inventory_sha256=capability.legacy_statuses_inventory_sha256,
        status_combined_evidence_sha256=capability.status_combined_evidence_sha256,
        broker_policy_sha256=capability.broker_policy_sha256,
        broker_executable_path_sha256=capability.broker_executable_path_sha256,
        broker_executable_sha256=capability.broker_executable_sha256,
        graphql_query_sha256=capability.graphql_query_sha256,
        first_review_threads_inventory_sha256=str(
            first["thread_inventory_sha256"]
        ),
        second_review_threads_inventory_sha256=str(
            second["thread_inventory_sha256"]
        ),
        review_threads_inventory_sha256=str(first["thread_inventory_sha256"]),
        first_broker_evidence_sha256=str(first["broker_evidence_sha256"]),
        second_broker_evidence_sha256=str(second["broker_evidence_sha256"]),
        github_review_decision=str(first["review_decision"]),
        review_thread_count=int(first["thread_count"]),
        unresolved_review_thread_count=int(first["unresolved_thread_count"]),
        unresolved_outdated_review_thread_count=int(
            first["unresolved_outdated_thread_count"]
        ),
        review_thread_page_count=int(first["thread_page_count"]),
        first_observed_at_utc=first_at,
        second_observed_at_utc=second_at,
    )
    _mark_authenticated(result, capability, tuple(first["thread_rows"]))
    if result.observation_authenticated is not True:
        raise PilotExactTaskPrReviewThreadStateObservationError(
            "review-thread observation lost live provenance"
        )
    return result


def observe_pilot_exact_task_pr_review_thread_state(
    review_thread_credential_capability: PilotExactTaskPrStatusReviewThreadCredentialCapability,
) -> PilotExactTaskPrReviewThreadStateObservation:
    """Observe exact reviewDecision/reviewThreads only; never evaluate or mutate."""
    return _observe_verified_pilot_exact_task_pr_review_thread_state(
        review_thread_credential_capability=review_thread_credential_capability,
        subprocess_runner=run_bounded_subprocess,
        now_provider=_now_utc_seconds,
        broker_host_control_required=True,
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_REVIEW_THREAD_STATE_OBSERVATION_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEW_THREAD_STATE_OBSERVATION_AUTHORITY",
    "PILOT_EXACT_TASK_PR_REVIEW_THREAD_STATE_OBSERVATION_SCOPE",
    "PILOT_EXACT_TASK_PR_REVIEW_THREAD_BROKER_REQUEST_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEW_THREAD_BROKER_RESPONSE_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEW_THREAD_STATE_MAX_CAPABILITY_AGE_SECONDS",
    "PilotExactTaskPrReviewThreadStateObservationError",
    "PilotExactTaskPrReviewThreadStateObservation",
    "observe_pilot_exact_task_pr_review_thread_state",
]
