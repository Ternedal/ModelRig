"""Hardened public ADR-DC-075 one-shot reviewer-write transaction.

The large implementation module contains the durable receipt/ledger model and
closed helper seams. This public facade deliberately tightens the production
mutation sequence: exact PR revalidation -> durable start marker -> final broker
rehash -> exactly one broker invocation -> independent fixed-origin readback.
Everything after the durable marker is non-retriable.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from . import _improvement_pilot_exact_task_pr_reviewer_write_transaction_impl as _implementation
from . import _improvement_pilot_exact_task_pr_reviewer_write_credential_capability_production_boundary as _write_broker_boundary
from .bounded_subprocess import BoundedSubprocessError, run_bounded_subprocess
from .github_read import GitHubReadError, UrllibReadOnlyTransport
from .improvement_pilot_exact_task_pr_reviewer_write_credential_capability import (
    PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_OPERATION,
    PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_PROTOCOL,
    PILOT_EXACT_TASK_PR_REVIEWER_WRITE_REQUEST_PATH_TEMPLATE,
    PilotExactTaskPrReviewerWriteCredentialCapability,
)

PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_SCHEMA
)
PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_AUTHORITY = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_AUTHORITY
)
PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_LEDGER_SCOPE = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_LEDGER_SCOPE
)
PILOT_EXACT_TASK_PR_REVIEWER_WRITE_BROKER_REQUEST_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_WRITE_BROKER_REQUEST_SCHEMA
)
PILOT_EXACT_TASK_PR_REVIEWER_WRITE_BROKER_RESPONSE_SCHEMA = (
    _implementation.PILOT_EXACT_TASK_PR_REVIEWER_WRITE_BROKER_RESPONSE_SCHEMA
)
PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_MAX_CAPABILITY_AGE_SECONDS = 10
PILOT_EXACT_TASK_PR_REVIEWER_WRITE_API_VERSION = "2022-11-28"

PilotExactTaskPrReviewerWriteTransactionError = (
    _implementation.PilotExactTaskPrReviewerWriteTransactionError
)
PilotExactTaskPrReviewerWriteTransaction = (
    _implementation.PilotExactTaskPrReviewerWriteTransaction
)
_TransactionLedger = _implementation._TransactionLedger
_require_live_capability = _implementation._require_live_capability
_get_live_pr_reviewer_write_transaction_inputs = (
    _implementation._get_live_pr_reviewer_write_transaction_inputs
)

_MAX_BROKER_REQUEST_BYTES = 128 * 1024
_MAX_BROKER_OUTPUT_BYTES = 64 * 1024
_MAX_READBACK_BYTES = 256 * 1024
_BROKER_TIMEOUT_SECONDS = 60
_READBACK_TIMEOUT_SECONDS = 20


def _require_transaction_window(
    capability: PilotExactTaskPrReviewerWriteCredentialCapability,
    *,
    at_utc: str,
) -> None:
    at = _implementation._utc(at_utc, name="reviewer-write transaction time")
    materialized = _implementation._utc(
        capability.materialized_at_utc,
        name="write capability materialized_at_utc",
    )
    if (
        at < materialized
        or (at - materialized).total_seconds()
        > PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_MAX_CAPABILITY_AGE_SECONDS
    ):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "ADR-DC-074 write capability is too old for reviewer mutation"
        )


def _broker_request(
    capability: PilotExactTaskPrReviewerWriteCredentialCapability,
    descriptor: Mapping[str, str],
) -> Mapping[str, Any]:
    template = descriptor.get("request_path_template")
    if template != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_REQUEST_PATH_TEMPLATE:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer-write broker request path template drifted"
        )
    if hashlib.sha256(template.encode("utf-8")).hexdigest() != capability.request_path_template_sha256:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer-write broker request path hash drifted"
        )
    request_path = template.format(pull_request_number=capability.pull_request_number)
    request = {
        "schema": PILOT_EXACT_TASK_PR_REVIEWER_WRITE_BROKER_REQUEST_SCHEMA,
        "operation": PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_OPERATION,
        "api_origin": "https://api.github.com",
        "request_path": request_path,
        "repository": capability.repository,
        "pull_request_number": capability.pull_request_number,
        "head_sha": capability.predicted_commit_sha,
        "reviewer_login": capability.reviewer_login,
        "reviewer_user_id": capability.reviewer_user_id,
        "reviewer_node_id_sha256": capability.reviewer_user_node_id_sha256,
        "reviewer_request_nonce_sha256": capability.reviewer_request_nonce_sha256,
        "reviewer_write_credential_capability_sha256": capability.sha256,
        "reviewers": [capability.reviewer_login],
        "team_reviewers": [],
    }
    payload = _implementation._canonical_bytes(request)
    if not payload or len(payload) > _MAX_BROKER_REQUEST_BYTES:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer-write broker request exceeds byte bound"
        )
    return MappingProxyType(request)


def _validate_broker_response(
    payload: bytes,
    *,
    request_sha256: str,
    capability: PilotExactTaskPrReviewerWriteCredentialCapability,
) -> Mapping[str, Any]:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_BROKER_OUTPUT_BYTES:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer-write broker response is missing or oversized"
        )
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer-write broker response is not UTF-8 JSON"
        ) from exc
    expected = {
        "schema",
        "status",
        "operation",
        "request_sha256",
        "reviewer_write_credential_capability_sha256",
        "repository",
        "pull_request_number",
        "head_sha",
        "reviewer_login",
        "reviewer_user_id",
        "reviewer_request_nonce_sha256",
        "requested_reviewer_count",
        "requested_team_count",
        "updated_at_utc",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer-write broker response fields mismatch"
        )
    _implementation._utc(value.get("updated_at_utc"), name="broker updated_at_utc")
    if (
        value.get("schema") != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_BROKER_RESPONSE_SCHEMA
        or value.get("status") != "reviewer-requested"
        or value.get("operation") != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_OPERATION
        or value.get("request_sha256") != request_sha256
        or value.get("reviewer_write_credential_capability_sha256") != capability.sha256
        or value.get("repository") != capability.repository
        or value.get("pull_request_number") != capability.pull_request_number
        or value.get("head_sha") != capability.predicted_commit_sha
        or value.get("reviewer_login") != capability.reviewer_login
        or value.get("reviewer_user_id") != capability.reviewer_user_id
        or value.get("reviewer_request_nonce_sha256") != capability.reviewer_request_nonce_sha256
        or value.get("requested_reviewer_count") != 1
        or value.get("requested_team_count") != 0
    ):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer-write broker response does not match exact capability/request"
        )
    return MappingProxyType(dict(value))


def _invoke_broker(
    *,
    broker_path: Path,
    request_payload: bytes,
    request_sha256: str,
    capability: PilotExactTaskPrReviewerWriteCredentialCapability,
    subprocess_runner: Callable[..., Any],
) -> tuple[Any, Mapping[str, Any]]:
    command = (
        os.fspath(broker_path),
        "--protocol",
        PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_PROTOCOL,
        "--request-stdin-json",
        "--response-stdout-json",
    )
    environment = _implementation._broker_environment()
    if any(
        marker in key.upper()
        for key in environment
        for marker in ("TOKEN", "PASSWORD", "AUTHORIZATION", "BEARER")
    ):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer-write broker environment contains credential-shaped keys"
        )
    try:
        result = subprocess_runner(
            command,
            cwd=broker_path.parent,
            env=environment,
            stdin_bytes=request_payload,
            timeout_seconds=_BROKER_TIMEOUT_SECONDS,
            max_output_bytes=_MAX_BROKER_OUTPUT_BYTES,
            stdout_prefix_bytes=_MAX_BROKER_OUTPUT_BYTES,
            stderr_prefix_bytes=_MAX_BROKER_OUTPUT_BYTES,
        )
    except BoundedSubprocessError as exc:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "bounded reviewer-write broker process failed"
        ) from exc
    if (
        result.returncode != 0
        or result.output_limit_exceeded
        or result.timed_out
        or result.stdout.truncated
        or result.stderr.truncated
        or result.stderr.total_bytes != 0
        or result.stdout.total_bytes != len(result.stdout.prefix)
    ):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer-write broker did not complete cleanly"
        )
    response = _validate_broker_response(
        result.stdout.prefix,
        request_sha256=request_sha256,
        capability=capability,
    )
    return result, response


def _validate_post_request_document(
    *,
    document: Mapping[str, Any],
    headers: Mapping[str, str],
    payload: bytes,
    capability: PilotExactTaskPrReviewerWriteCredentialCapability,
    requirements: Any,
    expected_updated_at_utc: str,
) -> Mapping[str, Any]:
    head = document.get("head")
    base = document.get("base")
    author = document.get("user")
    head_repo = None if not isinstance(head, Mapping) else head.get("repo")
    base_repo = None if not isinstance(base, Mapping) else base.get("repo")
    reviewers = document.get("requested_reviewers")
    teams = document.get("requested_teams")
    node_id = document.get("node_id")
    if (
        not isinstance(reviewers, list)
        or len(reviewers) != 1
        or not isinstance(reviewers[0], Mapping)
        or reviewers[0].get("login") != capability.reviewer_login
        or reviewers[0].get("id") != capability.reviewer_user_id
        or reviewers[0].get("type") != "User"
        or not isinstance(teams, list)
        or teams
    ):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "post-request reviewer set is not exactly the pinned individual"
        )
    reviewer_node = reviewers[0].get("node_id")
    if (
        not isinstance(reviewer_node, str)
        or not reviewer_node
        or hashlib.sha256(reviewer_node.encode("utf-8")).hexdigest()
        != capability.reviewer_user_node_id_sha256
    ):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "post-request reviewer immutable node identity is missing or changed"
        )
    if (
        document.get("number") != capability.pull_request_number
        or document.get("url") != capability.pull_request_api_url
        or document.get("html_url") != capability.pull_request_html_url
        or not isinstance(node_id, str)
        or not node_id
        or hashlib.sha256(node_id.encode("utf-8")).hexdigest()
        != capability.pull_request_node_id_sha256
        or document.get("state") != "open"
        or document.get("closed_at") is not None
        or document.get("merged_at") is not None
        or document.get("draft") is not False
        or document.get("title") != requirements.pr_title
        or document.get("body") != requirements.pr_body
        or document.get("maintainer_can_modify") is not False
        or document.get("updated_at") != expected_updated_at_utc
        or not isinstance(author, Mapping)
        or author.get("login") != capability.pull_request_author_login
        or author.get("id") != capability.pull_request_author_user_id
        or not isinstance(head, Mapping)
        or head.get("ref") != capability.head_branch
        or head.get("sha") != capability.predicted_commit_sha
        or not isinstance(head_repo, Mapping)
        or head_repo.get("full_name") != capability.repository
        or not isinstance(base, Mapping)
        or base.get("ref") != capability.base_branch
        or not isinstance(base_repo, Mapping)
        or base_repo.get("full_name") != capability.repository
    ):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "post-request PR drifted from exact authorized state"
        )
    etag = str(headers.get("etag", ""))
    if len(etag) > 512 or any(marker in etag for marker in ("\r", "\n", "\x00")):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer post-request ETag is invalid"
        )
    return MappingProxyType(
        {
            "response_body_sha256": hashlib.sha256(payload).hexdigest(),
            "response_etag_sha256": hashlib.sha256(etag.encode("utf-8")).hexdigest(),
            "updated_at_utc": expected_updated_at_utc,
            "requested_reviewer_count": 1,
            "requested_team_count": 0,
        }
    )


def _read_post_request_pr(
    *,
    capability: PilotExactTaskPrReviewerWriteCredentialCapability,
    requirements: Any,
    expected_updated_at_utc: str,
    transport: Any | None = None,
) -> Mapping[str, Any]:
    reader = UrllibReadOnlyTransport() if transport is None else transport
    try:
        response = reader.get(
            capability.pull_request_api_url,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": PILOT_EXACT_TASK_PR_REVIEWER_WRITE_API_VERSION,
                "User-Agent": "ModelRig-DevControl-ADR-DC-075",
            },
            timeout_seconds=_READBACK_TIMEOUT_SECONDS,
            max_bytes=_MAX_READBACK_BYTES,
        )
    except (GitHubReadError, TimeoutError, OSError) as exc:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer post-request fixed-origin readback failed"
        ) from exc
    if response.status != 200 or len(response.body) > _MAX_READBACK_BYTES:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer post-request readback status/size is unsafe"
        )
    content_type = str(response.headers.get("content-type", "")).lower()
    if content_type and not (
        content_type.startswith("application/json")
        or content_type.startswith("application/vnd.github+json")
    ):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer post-request readback content type is unsafe"
        )
    try:
        document = json.loads(response.body.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer post-request readback is not UTF-8 JSON"
        ) from exc
    if not isinstance(document, Mapping):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer post-request readback must be an object"
        )
    return _validate_post_request_document(
        document=document,
        headers=response.headers,
        payload=response.body,
        capability=capability,
        requirements=requirements,
        expected_updated_at_utc=expected_updated_at_utc,
    )


def _execute_verified_pilot_exact_task_pr_reviewer_write(
    *,
    reviewer_write_credential_capability: PilotExactTaskPrReviewerWriteCredentialCapability,
    ledger: _TransactionLedger,
    pr_state_reader: Callable[..., Mapping[str, Any]],
    subprocess_runner: Callable[..., Any],
    readback_reader: Callable[..., Mapping[str, Any]],
    now_provider: Callable[[], str],
    broker_host_control_required: bool,
) -> PilotExactTaskPrReviewerWriteTransaction:
    (
        capability,
        preflight,
        precondition,
        reservation,
        target,
        requirements,
        descriptor,
    ) = _require_live_capability(reviewer_write_credential_capability)

    transaction_at = now_provider()
    _require_transaction_window(capability, at_utc=transaction_at)
    fresh = _implementation._fresh_exact_pr_state(
        precondition=precondition,
        reservation=reservation,
        target=target,
        requirements=requirements,
        reader=pr_state_reader,
    )
    if (
        fresh["pull_request_author_login"] != capability.pull_request_author_login
        or fresh["pull_request_author_user_id"] != capability.pull_request_author_user_id
    ):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "pull-request author identity drifted before reviewer write"
        )

    request = _broker_request(capability, descriptor)
    request_payload = _implementation._canonical_bytes(request)
    request_sha256 = hashlib.sha256(request_payload).hexdigest()
    started_at = now_provider()
    _require_transaction_window(capability, at_utc=started_at)

    start = _implementation._TransactionStart(
        ledger_root_path_sha256=ledger.root_sha256,
        transaction_key_sha256=capability.reviewer_request_nonce_sha256,
        reviewer_write_credential_capability_sha256=capability.sha256,
        reviewer_request_preflight_sha256=capability.reviewer_request_preflight_sha256,
        reviewer_request_nonce_sha256=capability.reviewer_request_nonce_sha256,
        predicted_commit_sha=capability.predicted_commit_sha,
        broker_request_sha256=request_sha256,
        broker_policy_sha256=capability.broker_policy_sha256,
        broker_executable_path_sha256=capability.broker_executable_path_sha256,
        broker_executable_sha256=capability.broker_executable_sha256,
        repository=capability.repository,
        pull_request_number=capability.pull_request_number,
        reviewer_login=capability.reviewer_login,
        reviewer_user_id=capability.reviewer_user_id,
        started_at_utc=started_at,
    )
    start_path, start_payload = ledger.begin(start)

    # No operation beyond this durable point may be automatically retried.
    broker_path = _implementation._fresh_broker_binary(
        descriptor,
        require_host_control=broker_host_control_required,
    )
    # Re-read via the ADR-074 hardened primitive as an independent final check.
    try:
        broker_bytes = _write_broker_boundary._read_broker_bytes(
            broker_path,
            require_host_control=broker_host_control_required,
        )
    except Exception as exc:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "final reviewer-write broker verification failed after transaction burn"
        ) from exc
    if (
        hashlib.sha256(broker_bytes).hexdigest() != capability.broker_executable_sha256
        or _implementation._path_sha256(broker_path) != capability.broker_executable_path_sha256
    ):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer-write broker changed after durable transaction burn"
        )

    broker_result, broker_response = _invoke_broker(
        broker_path=broker_path,
        request_payload=request_payload,
        request_sha256=request_sha256,
        capability=capability,
        subprocess_runner=subprocess_runner,
    )
    mutated_at = now_provider()
    if _implementation._utc(mutated_at, name="mutated_at_utc") < _implementation._utc(
        started_at,
        name="started_at_utc",
    ):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "clock moved backwards after reviewer write"
        )

    readback = _implementation._validate_readback(
        readback_reader(
            capability=capability,
            requirements=requirements,
            expected_updated_at_utc=broker_response["updated_at_utc"],
        ),
        expected_updated_at_utc=broker_response["updated_at_utc"],
    )
    verified_at = now_provider()
    if _implementation._utc(verified_at, name="verified_at_utc") < _implementation._utc(
        mutated_at,
        name="mutated_at_utc",
    ):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "clock moved backwards during reviewer readback"
        )

    receipt = PilotExactTaskPrReviewerWriteTransaction(
        ledger_root_path_sha256=ledger.root_sha256,
        transaction_key_sha256=capability.reviewer_request_nonce_sha256,
        transaction_start_sha256=start.sha256,
        reviewer_write_credential_capability_sha256=capability.sha256,
        reviewer_request_preflight_sha256=capability.reviewer_request_preflight_sha256,
        reviewer_requestability_precondition_sha256=capability.reviewer_requestability_precondition_sha256,
        reviewer_request_credential_capability_sha256=capability.reviewer_request_credential_capability_sha256,
        reviewer_identity_observation_sha256=capability.reviewer_identity_observation_sha256,
        reviewer_request_reservation_sha256=capability.reviewer_request_reservation_sha256,
        reviewer_target_attestation_sha256=capability.reviewer_target_attestation_sha256,
        reviewer_handoff_requirements_sha256=capability.reviewer_handoff_requirements_sha256,
        reviewer_target_policy_sha256=capability.reviewer_target_policy_sha256,
        reviewer_target_policy_epoch=capability.reviewer_target_policy_epoch,
        reviewer_request_nonce_sha256=capability.reviewer_request_nonce_sha256,
        repository=capability.repository,
        pull_request_number=capability.pull_request_number,
        pull_request_api_url=capability.pull_request_api_url,
        pull_request_html_url=capability.pull_request_html_url,
        pull_request_node_id_sha256=capability.pull_request_node_id_sha256,
        base_branch=capability.base_branch,
        head_branch=capability.head_branch,
        predicted_commit_sha=capability.predicted_commit_sha,
        reviewer_login=capability.reviewer_login,
        reviewer_user_id=capability.reviewer_user_id,
        reviewer_user_node_id_sha256=capability.reviewer_user_node_id_sha256,
        pull_request_author_login=capability.pull_request_author_login,
        pull_request_author_user_id=capability.pull_request_author_user_id,
        broker_policy_sha256=capability.broker_policy_sha256,
        broker_executable_path_sha256=capability.broker_executable_path_sha256,
        broker_executable_sha256=capability.broker_executable_sha256,
        broker_request_sha256=request_sha256,
        broker_stdout_sha256=broker_result.stdout.sha256,
        broker_stderr_sha256=broker_result.stderr.sha256,
        broker_total_output_bytes=broker_result.total_output_bytes,
        prewrite_pr_response_body_sha256=str(fresh["pr_response_body_sha256"]),
        prewrite_pr_response_etag_sha256=str(fresh["pr_response_etag_sha256"]),
        post_request_response_body_sha256=str(readback["response_body_sha256"]),
        post_request_response_etag_sha256=str(readback["response_etag_sha256"]),
        capability_materialized_at_utc=capability.materialized_at_utc,
        prewrite_updated_at_utc=str(fresh["observed_updated_at_utc"]),
        requested_updated_at_utc=str(broker_response["updated_at_utc"]),
        started_at_utc=started_at,
        mutated_at_utc=mutated_at,
        verified_at_utc=verified_at,
    )
    final_path, final_payload = ledger.finish(receipt)
    _implementation._mark_authenticated(
        receipt,
        capability,
        start_path=start_path,
        start_payload=start_payload,
        final_path=final_path,
        final_payload=final_payload,
    )
    if receipt.transaction_authenticated is not True:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer-write transaction lost durable live provenance"
        )
    return receipt


def execute_pilot_exact_task_pr_reviewer_write(
    reviewer_write_credential_capability: PilotExactTaskPrReviewerWriteCredentialCapability,
) -> PilotExactTaskPrReviewerWriteTransaction:
    """Execute one exact pinned reviewer request, at most once."""
    return _execute_verified_pilot_exact_task_pr_reviewer_write(
        reviewer_write_credential_capability=reviewer_write_credential_capability,
        ledger=_TransactionLedger(_implementation._canonical_ledger_root()),
        pr_state_reader=_implementation.identity_boundary._read_exact_ready_pr_state,
        subprocess_runner=run_bounded_subprocess,
        readback_reader=_read_post_request_pr,
        now_provider=_implementation._now_utc_seconds,
        broker_host_control_required=True,
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_AUTHORITY",
    "PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_LEDGER_SCOPE",
    "PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_MAX_CAPABILITY_AGE_SECONDS",
    "PilotExactTaskPrReviewerWriteTransactionError",
    "PilotExactTaskPrReviewerWriteTransaction",
    "execute_pilot_exact_task_pr_reviewer_write",
]
