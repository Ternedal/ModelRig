"""ADR-DC-075 exact one-shot reviewer-write transaction.

Consumes one exact live ADR-DC-074 write-only reviewer credential capability,
freshly revalidates the exact ready pull request, freshly verifies the pinned
write broker, durably commits a create-once transaction-start marker, and only
then invokes the broker once for the exact pinned individual reviewer. A
separate credential-free REST readback must prove the exact reviewer set.
Ambiguous failures remain burned and are never automatically retried.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from . import _improvement_pilot_exact_task_pr_reviewer_write_credential_capability_production_boundary as broker_boundary
from . import improvement_pilot_exact_task_pr_reviewer_identity_observation as identity_boundary
from . import improvement_pilot_exact_task_pr_reviewer_request_preflight as preflight_boundary
from . import improvement_pilot_exact_task_pr_reviewer_write_credential_capability as capability_boundary
from .bounded_subprocess import BoundedSubprocessError, run_bounded_subprocess
from .durable_publication import DurablePublicationError, create_once_file
from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
    _require_host_controlled_ledger_root,
)
from .improvement_pilot_exact_task_pr_reviewer_write_credential_capability import (
    PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_CAPABILITY_AUTHORITY,
    PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_OPERATION,
    PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_PROTOCOL,
    PilotExactTaskPrReviewerWriteCredentialCapability,
)

PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-reviewer-write-transaction/v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_AUTHORITY = (
    "completed-one-dc-l16-exact-pr-individual-reviewer-request-only"
)
PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_LEDGER_SCOPE = (
    "canonical-host-pr-reviewer-write-transaction-v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_WRITE_BROKER_REQUEST_SCHEMA = (
    "kaliv-rsi-pilot-exact-task-pr-reviewer-write-broker-request/v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_WRITE_BROKER_RESPONSE_SCHEMA = (
    "kaliv-rsi-pilot-exact-task-pr-reviewer-write-broker-response/v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_WRITE_MAX_CAPABILITY_AGE_SECONDS = 15
PILOT_EXACT_TASK_PR_REVIEWER_WRITE_API_VERSION = "2022-11-28"

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_MAX_BROKER_REQUEST_BYTES = 128 * 1024
_MAX_BROKER_OUTPUT_BYTES = 64 * 1024
_MAX_READBACK_BYTES = 256 * 1024
_BROKER_TIMEOUT_SECONDS = 60
_READBACK_TIMEOUT_SECONDS = 20
_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-pr-reviewer-write-transaction-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-pr-reviewer-write-transaction-ledger-v1"
)


class PilotExactTaskPrReviewerWriteTransactionError(ValueError):
    """Exact reviewer write is stale, replayed, ambiguous, or unsafe."""


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer-write transaction is not canonical JSON"
        ) from exc


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return _canonical(value).encode("utf-8")


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrReviewerWriteTransactionError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrReviewerWriteTransactionError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrReviewerWriteTransactionError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _path_sha256(path: Path) -> str:
    return hashlib.sha256(os.fsencode(os.path.abspath(os.fspath(path)))).hexdigest()


def _read_bound_file(path: Path) -> bytes | None:
    candidate = Path(path)
    if not candidate.is_absolute() or candidate.is_symlink():
        return None
    try:
        payload = candidate.read_bytes()
    except OSError:
        return None
    if not payload or len(payload) > _MAX_ARTIFACT_BYTES:
        return None
    return payload


def _require_safe_ledger_root(path: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute() or not candidate.is_dir() or candidate.is_symlink():
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer-write transaction ledger root is unsafe"
        )
    return candidate


def _canonical_ledger_root() -> Path:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            return _require_host_controlled_ledger_root(_POSIX_LEDGER)
        if os.name == "nt":
            return _require_host_controlled_ledger_root(_WINDOWS_LEDGER)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "canonical reviewer-write transaction ledger is not host controlled"
        ) from exc
    raise PilotExactTaskPrReviewerWriteTransactionError(
        "reviewer-write transaction platform is unsupported"
    )


def _require_live_capability(
    value: Any,
) -> tuple[PilotExactTaskPrReviewerWriteCredentialCapability, Any, Any, Any, Any, Any, Mapping[str, str]]:
    if type(value) is not PilotExactTaskPrReviewerWriteCredentialCapability:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "exact ADR-DC-074 reviewer-write credential capability is required"
        )
    try:
        replayed = PilotExactTaskPrReviewerWriteCredentialCapability.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "ADR-DC-074 capability replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "ADR-DC-074 capability identity mismatch"
        )
    required_true = (
        "reviewer_request_authorization_consumed",
        "reviewer_request_slot_reserved",
        "reviewer_identity_verified",
        "reviewer_requestability_precondition_verified",
        "fresh_exact_pr_state_revalidated",
        "no_requested_reviewers_verified",
        "reviewer_not_pr_author_verified",
        "reviewer_write_credential_capability_materialized",
        "write_broker_host_pinned",
        "write_broker_binary_verified",
        "credential_secret_not_loaded",
        "credential_broker_owns_https",
        "individual_reviewer_write_only",
        "team_reviewers_forbidden",
        "collaborator_permission_read_forbidden",
        "other_repository_reads_forbidden",
        "pull_request_create_forbidden",
        "pull_request_metadata_write_forbidden",
        "ready_for_review_write_forbidden",
        "label_write_forbidden",
        "merge_write_forbidden",
        "repository_contents_write_forbidden",
        "administration_write_forbidden",
        "release_write_forbidden",
        "deployment_write_forbidden",
        "redirect_following_forbidden",
        "one_shot_reviewer_request_transaction_required",
        "post_request_readback_verification_required",
    )
    forced_false = (
        "credential_material_in_artifact",
        "credential_material_in_process_arguments",
        "credential_material_in_environment",
        "reviewer_mutation_authorized",
        "reviewer_request_performed",
        "label_mutation_authorized",
        "merge_authorized",
        "release_authorized",
        "deploy_authorized",
        "production_activation_authorized",
    )
    if (
        value.authority
        != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_CAPABILITY_AUTHORITY
        or value.capability_authenticated is not True
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
        or value.credential_protocol != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_PROTOCOL
        or value.credential_operation != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_OPERATION
        or value.repository != "Ternedal/ModelRig"
        or value.base_branch != "main"
        or _HEAD.fullmatch(value.head_branch) is None
    ):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "transaction requires one live inert ADR-DC-074 capability"
        )

    cap_inputs = (
        capability_boundary._get_live_pr_reviewer_write_credential_capability_inputs(
            value
        )
    )
    preflight = None if cap_inputs is None else cap_inputs.get("reviewer_request_preflight")
    descriptor = None if cap_inputs is None else cap_inputs.get(
        "credential_broker_descriptor"
    )
    if (
        preflight is None
        or getattr(preflight, "observation_authenticated", None) is not True
        or preflight.sha256 != value.reviewer_request_preflight_sha256
        or not isinstance(descriptor, Mapping)
    ):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "ADR-DC-074 lost live preflight/broker provenance"
        )

    preflight_inputs = preflight_boundary._get_live_pr_reviewer_request_preflight_inputs(
        preflight
    )
    precondition = None if preflight_inputs is None else preflight_inputs.get(
        "reviewer_requestability_precondition"
    )
    if precondition is None or getattr(precondition, "observation_authenticated", None) is not True:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "ADR-DC-073 lost live ADR-DC-072 provenance"
        )
    try:
        _precondition, identity, reservation, target, requirements = (
            preflight_boundary._require_live_precondition(precondition)
        )
    except Exception as exc:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer-write transaction lost live ADR-DC-072/070/069 provenance"
        ) from exc

    if (
        precondition.sha256 != value.reviewer_requestability_precondition_sha256
        or preflight.reviewer_request_nonce_sha256 != value.reviewer_request_nonce_sha256
        or preflight.pull_request_number != value.pull_request_number
        or preflight.predicted_commit_sha != value.predicted_commit_sha
        or preflight.reviewer_login != value.reviewer_login
        or preflight.reviewer_user_id != value.reviewer_user_id
        or preflight.reviewer_user_node_id_sha256 != value.reviewer_user_node_id_sha256
        or preflight.pull_request_author_login != value.pull_request_author_login
        or preflight.pull_request_author_user_id != value.pull_request_author_user_id
        or reservation.sha256 != value.reviewer_request_reservation_sha256
        or target.sha256 != value.reviewer_target_attestation_sha256
        or requirements.sha256 != value.reviewer_handoff_requirements_sha256
        or descriptor.get("broker_policy_sha256") != value.broker_policy_sha256
        or descriptor.get("broker_executable_path_sha256")
        != value.broker_executable_path_sha256
        or descriptor.get("broker_executable_sha256") != value.broker_executable_sha256
        or descriptor.get("credential_protocol") != value.credential_protocol
        or descriptor.get("operation") != value.credential_operation
    ):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "ADR-DC-074 exact reviewer/PR/broker provenance mismatch"
        )
    return value, preflight, precondition, reservation, target, requirements, MappingProxyType(dict(descriptor))


def _require_transaction_window(
    capability: PilotExactTaskPrReviewerWriteCredentialCapability,
    *,
    at_utc: str,
) -> None:
    at = _utc(at_utc, name="reviewer-write transaction time")
    materialized = _utc(
        capability.materialized_at_utc,
        name="write capability materialized_at_utc",
    )
    if (
        at < materialized
        or (at - materialized).total_seconds()
        > PILOT_EXACT_TASK_PR_REVIEWER_WRITE_MAX_CAPABILITY_AGE_SECONDS
    ):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "ADR-DC-074 write capability is too old for mutation"
        )


def _fresh_exact_pr_state(
    *,
    precondition: Any,
    reservation: Any,
    target: Any,
    requirements: Any,
    reader: Callable[..., Mapping[str, Any]],
) -> Mapping[str, Any]:
    try:
        return preflight_boundary._validate_pr_evidence(
            reader(
                reservation_receipt=reservation,
                reviewer_target=target,
                reviewer_handoff_requirements=requirements,
            ),
            precondition=precondition,
            target=target,
        )
    except Exception as exc:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "fresh exact PR revalidation failed immediately before reviewer write"
        ) from exc


def _fresh_broker_binary(
    descriptor: Mapping[str, str],
    *,
    require_host_control: bool,
) -> Path:
    path_text = descriptor.get("broker_executable_path")
    if not isinstance(path_text, str) or not path_text:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "live reviewer-write broker path is unavailable"
        )
    path = Path(path_text)
    try:
        payload = broker_boundary._read_broker_bytes(
            path,
            require_host_control=require_host_control,
        )
    except Exception as exc:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer-write broker could not be freshly verified"
        ) from exc
    if (
        hashlib.sha256(payload).hexdigest()
        != descriptor.get("broker_executable_sha256")
        or _path_sha256(path) != descriptor.get("broker_executable_path_sha256")
    ):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer-write broker changed after ADR-DC-074"
        )
    return path


def _broker_request(
    capability: PilotExactTaskPrReviewerWriteCredentialCapability,
) -> Mapping[str, Any]:
    request_url = f"{capability.pull_request_api_url}/requested_reviewers"
    request = {
        "schema": PILOT_EXACT_TASK_PR_REVIEWER_WRITE_BROKER_REQUEST_SCHEMA,
        "operation": PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_OPERATION,
        "api_origin": "https://api.github.com",
        "request_reviewers_api_url": request_url,
        "repository": capability.repository,
        "pull_request_number": capability.pull_request_number,
        "head_sha": capability.predicted_commit_sha,
        "reviewer_login": capability.reviewer_login,
        "reviewer_user_id": capability.reviewer_user_id,
        "reviewer_node_id_sha256": capability.reviewer_user_node_id_sha256,
        "reviewer_request_nonce_sha256": capability.reviewer_request_nonce_sha256,
        "reviewers": [capability.reviewer_login],
        "team_reviewers": [],
    }
    payload = _canonical_bytes(request)
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
    if (
        not isinstance(payload, bytes)
        or not payload
        or len(payload) > _MAX_BROKER_OUTPUT_BYTES
    ):
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
    updated = value.get("updated_at_utc")
    _utc(updated, name="reviewer-write broker updated_at_utc")
    if (
        value.get("schema") != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_BROKER_RESPONSE_SCHEMA
        or value.get("status") != "reviewer-requested"
        or value.get("operation") != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_CREDENTIAL_OPERATION
        or value.get("request_sha256") != request_sha256
        or value.get("repository") != capability.repository
        or value.get("pull_request_number") != capability.pull_request_number
        or value.get("head_sha") != capability.predicted_commit_sha
        or value.get("reviewer_login") != capability.reviewer_login
        or value.get("reviewer_user_id") != capability.reviewer_user_id
        or value.get("reviewer_request_nonce_sha256")
        != capability.reviewer_request_nonce_sha256
        or value.get("requested_reviewer_count") != 1
        or value.get("requested_team_count") != 0
    ):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer-write broker response does not match exact request"
        )
    return MappingProxyType(dict(value))


def _broker_environment() -> dict[str, str]:
    environment = {"LANG": "C", "LC_ALL": "C"}
    if os.name == "nt":
        for name in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
            value = os.environ.get(name)
            if value and "\0" not in value:
                environment[name] = value
    return environment


def _invoke_broker(
    *,
    broker_path: Path,
    protocol: str,
    request_payload: bytes,
    request_sha256: str,
    capability: PilotExactTaskPrReviewerWriteCredentialCapability,
    subprocess_runner: Callable[..., Any],
) -> tuple[Any, Mapping[str, Any]]:
    command = (
        os.fspath(broker_path),
        "--protocol",
        protocol,
        "--request-stdin-json",
        "--response-stdout-json",
    )
    environment = _broker_environment()
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
    return result, _validate_broker_response(
        result.stdout.prefix,
        request_sha256=request_sha256,
        capability=capability,
    )


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _read_post_request_pr(
    *,
    capability: PilotExactTaskPrReviewerWriteCredentialCapability,
    requirements: Any,
    expected_updated_at_utc: str,
) -> Mapping[str, Any]:
    request = urllib.request.Request(
        capability.pull_request_api_url,
        method="GET",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": PILOT_EXACT_TASK_PR_REVIEWER_WRITE_API_VERSION,
            "User-Agent": "ModelRig-DevControl-ADR-DC-075",
        },
    )
    lowered = {str(name).lower() for name in request.headers}
    if "authorization" in lowered or "cookie" in lowered:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer post-request readback must remain credential free"
        )
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(request, timeout=_READBACK_TIMEOUT_SECONDS) as response:
            status = getattr(response, "status", None)
            headers = {
                str(k).lower(): str(v).strip()
                for k, v in response.headers.items()
            }
            payload = response.read(_MAX_READBACK_BYTES + 1)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer post-request readback failed"
        ) from exc
    if status != 200 or len(payload) > _MAX_READBACK_BYTES:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer post-request readback status/size is unsafe"
        )
    try:
        document = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer post-request readback is not UTF-8 JSON"
        ) from exc
    if not isinstance(document, Mapping):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer post-request readback must be an object"
        )

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
        or not isinstance(teams, list)
        or teams
    ):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "post-request reviewer set is not exactly the pinned individual"
        )
    reviewer_node = reviewers[0].get("node_id")
    if (
        isinstance(reviewer_node, str)
        and reviewer_node
        and hashlib.sha256(reviewer_node.encode("utf-8")).hexdigest()
        != capability.reviewer_user_node_id_sha256
    ):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "post-request reviewer node identity changed"
        )
    if (
        document.get("number") != capability.pull_request_number
        or document.get("url") != capability.pull_request_api_url
        or document.get("html_url") != capability.pull_request_html_url
        or not isinstance(node_id, str)
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
    etag = headers.get("etag", "")
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


def _validate_readback(
    value: Any,
    *,
    expected_updated_at_utc: str,
) -> Mapping[str, Any]:
    expected = {
        "response_body_sha256",
        "response_etag_sha256",
        "updated_at_utc",
        "requested_reviewer_count",
        "requested_team_count",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer readback evidence fields mismatch"
        )
    result = dict(value)
    _hex64(result.get("response_body_sha256"), name="response_body_sha256")
    _hex64(result.get("response_etag_sha256"), name="response_etag_sha256")
    if (
        result.get("updated_at_utc") != expected_updated_at_utc
        or result.get("requested_reviewer_count") != 1
        or result.get("requested_team_count") != 0
    ):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "reviewer readback evidence does not match exact request"
        )
    _utc(result["updated_at_utc"], name="post-request updated_at_utc")
    return MappingProxyType(result)


@dataclass(frozen=True, slots=True)
class _TransactionStart:
    ledger_root_path_sha256: str
    transaction_key_sha256: str
    reviewer_write_credential_capability_sha256: str
    reviewer_request_preflight_sha256: str
    reviewer_request_nonce_sha256: str
    predicted_commit_sha: str
    broker_request_sha256: str
    broker_policy_sha256: str
    broker_executable_path_sha256: str
    broker_executable_sha256: str
    repository: str
    pull_request_number: int
    reviewer_login: str
    reviewer_user_id: int
    started_at_utc: str
    authority: str = "started-one-dc-l16-exact-pr-individual-reviewer-write-only"
    schema: str = "kaliv-rsi-dc-l16-exact-task-pr-reviewer-write-transaction-start/v1"

    def __post_init__(self) -> None:
        for name in (
            "ledger_root_path_sha256",
            "transaction_key_sha256",
            "reviewer_write_credential_capability_sha256",
            "reviewer_request_preflight_sha256",
            "reviewer_request_nonce_sha256",
            "broker_request_sha256",
            "broker_policy_sha256",
            "broker_executable_path_sha256",
            "broker_executable_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _utc(self.started_at_utc, name="started_at_utc")
        if (
            self.transaction_key_sha256 != self.reviewer_request_nonce_sha256
            or self.repository != "Ternedal/ModelRig"
            or isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or not isinstance(self.reviewer_login, str)
            or _LOGIN.fullmatch(self.reviewer_login) is None
            or isinstance(self.reviewer_user_id, bool)
            or not isinstance(self.reviewer_user_id, int)
            or self.reviewer_user_id < 1
        ):
            raise PilotExactTaskPrReviewerWriteTransactionError(
                "reviewer-write transaction-start binding is invalid"
            )

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class _TransactionLedger:
    def __init__(self, root: Path) -> None:
        self.root = _require_safe_ledger_root(Path(root))
        self.root_sha256 = _path_sha256(self.root)

    def _start_path(self, nonce: str) -> Path:
        return self.root / f"{_hex64(nonce, name='reviewer_request_nonce_sha256')}.start.json"

    def _final_path(self, nonce: str) -> Path:
        return self.root / f"{_hex64(nonce, name='reviewer_request_nonce_sha256')}.json"

    def begin(self, start: _TransactionStart) -> tuple[Path, bytes]:
        if start.ledger_root_path_sha256 != self.root_sha256:
            raise PilotExactTaskPrReviewerWriteTransactionError(
                "reviewer-write transaction-start does not belong to ledger"
            )
        start_path = self._start_path(start.reviewer_request_nonce_sha256)
        final_path = self._final_path(start.reviewer_request_nonce_sha256)
        if start_path.exists() or final_path.exists():
            raise PilotExactTaskPrReviewerWriteTransactionError(
                "reviewer nonce already has transaction state"
            )
        payload = start.canonical_json().encode("utf-8")
        try:
            create_once_file(start_path, payload, mode=0o600)
        except (FileExistsError, DurablePublicationError, OSError) as exc:
            raise PilotExactTaskPrReviewerWriteTransactionError(
                "reviewer-write transaction-start could not be committed"
            ) from exc
        if _read_bound_file(start_path) != payload:
            raise PilotExactTaskPrReviewerWriteTransactionError(
                "reviewer-write transaction-start readback failed"
            )
        return start_path, payload

    def finish(self, receipt: "PilotExactTaskPrReviewerWriteTransaction") -> tuple[Path, bytes]:
        if receipt.ledger_root_path_sha256 != self.root_sha256:
            raise PilotExactTaskPrReviewerWriteTransactionError(
                "reviewer-write transaction receipt does not belong to ledger"
            )
        if not self._start_path(receipt.reviewer_request_nonce_sha256).is_file():
            raise PilotExactTaskPrReviewerWriteTransactionError(
                "reviewer-write transaction lacks durable start marker"
            )
        final_path = self._final_path(receipt.reviewer_request_nonce_sha256)
        payload = receipt.canonical_json().encode("utf-8")
        try:
            create_once_file(final_path, payload, mode=0o600)
        except (FileExistsError, DurablePublicationError, OSError) as exc:
            raise PilotExactTaskPrReviewerWriteTransactionError(
                "reviewer-write transaction receipt could not be committed"
            ) from exc
        if _read_bound_file(final_path) != payload:
            raise PilotExactTaskPrReviewerWriteTransactionError(
                "reviewer-write transaction receipt readback failed"
            )
        return final_path, payload


_live_records: dict[
    int,
    tuple[
        int,
        str,
        weakref.ReferenceType[Any],
        weakref.ReferenceType[PilotExactTaskPrReviewerWriteCredentialCapability],
        Path,
        bytes,
        Path,
        bytes,
    ],
] = {}


def _mark_authenticated(
    receipt: Any,
    capability: PilotExactTaskPrReviewerWriteCredentialCapability,
    *,
    start_path: Path,
    start_payload: bytes,
    final_path: Path,
    final_payload: bytes,
) -> None:
    key = id(receipt)

    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)

    _live_records[key] = (
        os.getpid(),
        receipt.sha256,
        weakref.ref(receipt, cleanup),
        weakref.ref(capability),
        start_path,
        start_payload,
        final_path,
        final_payload,
    )


def _get_live_pr_reviewer_write_transaction_inputs(receipt: Any) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(receipt))
    if entry is None:
        return None
    (
        pid,
        digest,
        receipt_ref,
        capability_ref,
        start_path,
        start_payload,
        final_path,
        final_payload,
    ) = entry
    capability = capability_ref()
    if (
        pid != os.getpid()
        or receipt_ref() is not receipt
        or capability is None
        or capability.capability_authenticated is not True
        or capability.sha256 != receipt.reviewer_write_credential_capability_sha256
        or receipt.sha256 != digest
        or _read_bound_file(start_path) != start_payload
        or _read_bound_file(final_path) != final_payload
    ):
        return None
    return MappingProxyType({"reviewer_write_credential_capability": capability})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReviewerWriteTransaction:
    ledger_root_path_sha256: str
    transaction_key_sha256: str
    transaction_start_sha256: str
    reviewer_write_credential_capability_sha256: str
    reviewer_request_preflight_sha256: str
    reviewer_requestability_precondition_sha256: str
    reviewer_request_credential_capability_sha256: str
    reviewer_identity_observation_sha256: str
    reviewer_request_reservation_sha256: str
    reviewer_target_attestation_sha256: str
    reviewer_handoff_requirements_sha256: str
    reviewer_target_policy_sha256: str
    reviewer_target_policy_epoch: int
    reviewer_request_nonce_sha256: str
    repository: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_html_url: str
    pull_request_node_id_sha256: str
    base_branch: str
    head_branch: str
    predicted_commit_sha: str
    reviewer_login: str
    reviewer_user_id: int
    reviewer_user_node_id_sha256: str
    pull_request_author_login: str
    pull_request_author_user_id: int
    broker_policy_sha256: str
    broker_executable_path_sha256: str
    broker_executable_sha256: str
    broker_request_sha256: str
    broker_stdout_sha256: str
    broker_stderr_sha256: str
    broker_total_output_bytes: int
    prewrite_pr_response_body_sha256: str
    prewrite_pr_response_etag_sha256: str
    post_request_response_body_sha256: str
    post_request_response_etag_sha256: str
    capability_materialized_at_utc: str
    prewrite_updated_at_utc: str
    requested_updated_at_utc: str
    started_at_utc: str
    mutated_at_utc: str
    verified_at_utc: str
    host_transaction_start_committed: bool = True
    reviewer_request_authorization_consumed: bool = True
    reviewer_request_slot_consumed: bool = True
    reviewer_requestability_revalidated: bool = True
    fresh_pr_state_revalidated_before_reviewer_request: bool = True
    no_prior_requested_reviewers_reverified: bool = True
    reviewer_not_pr_author_reverified: bool = True
    write_broker_freshly_verified: bool = True
    credential_broker_invoked_without_secret_exposure: bool = True
    exact_individual_reviewer_request_performed: bool = True
    reviewer_request_performed: bool = True
    post_reviewer_request_readback_verified: bool = True
    exact_reviewer_set_verified: bool = True
    team_reviewers_absent_verified: bool = True
    credential_material_in_artifact: bool = False
    credential_material_in_process_arguments: bool = False
    credential_material_in_environment: bool = False
    nonce_reusable: bool = False
    reviewer_mutation_authorized: bool = False
    label_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_AUTHORITY
    ledger_scope: str = PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_LEDGER_SCOPE
    schema: str = PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_SCHEMA
            or self.authority != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_AUTHORITY
            or self.ledger_scope != PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_LEDGER_SCOPE
        ):
            raise PilotExactTaskPrReviewerWriteTransactionError(
                "reviewer-write transaction schema/authority/scope unsupported"
            )
        for name in (
            "ledger_root_path_sha256",
            "transaction_key_sha256",
            "transaction_start_sha256",
            "reviewer_write_credential_capability_sha256",
            "reviewer_request_preflight_sha256",
            "reviewer_requestability_precondition_sha256",
            "reviewer_request_credential_capability_sha256",
            "reviewer_identity_observation_sha256",
            "reviewer_request_reservation_sha256",
            "reviewer_target_attestation_sha256",
            "reviewer_handoff_requirements_sha256",
            "reviewer_target_policy_sha256",
            "reviewer_request_nonce_sha256",
            "pull_request_node_id_sha256",
            "reviewer_user_node_id_sha256",
            "broker_policy_sha256",
            "broker_executable_path_sha256",
            "broker_executable_sha256",
            "broker_request_sha256",
            "broker_stdout_sha256",
            "broker_stderr_sha256",
            "prewrite_pr_response_body_sha256",
            "prewrite_pr_response_etag_sha256",
            "post_request_response_body_sha256",
            "post_request_response_etag_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        for name in (
            "capability_materialized_at_utc",
            "prewrite_updated_at_utc",
            "requested_updated_at_utc",
            "started_at_utc",
            "mutated_at_utc",
            "verified_at_utc",
        ):
            _utc(getattr(self, name), name=name)
        if (
            self.transaction_key_sha256 != self.reviewer_request_nonce_sha256
            or self.repository != "Ternedal/ModelRig"
            or self.base_branch != "main"
            or _HEAD.fullmatch(self.head_branch) is None
            or isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or isinstance(self.reviewer_user_id, bool)
            or not isinstance(self.reviewer_user_id, int)
            or self.reviewer_user_id < 1
            or not isinstance(self.reviewer_login, str)
            or _LOGIN.fullmatch(self.reviewer_login) is None
            or isinstance(self.pull_request_author_user_id, bool)
            or not isinstance(self.pull_request_author_user_id, int)
            or self.pull_request_author_user_id < 1
            or self.pull_request_author_user_id == self.reviewer_user_id
            or self.pull_request_author_login.lower() == self.reviewer_login.lower()
            or isinstance(self.broker_total_output_bytes, bool)
            or not isinstance(self.broker_total_output_bytes, int)
            or self.broker_total_output_bytes < 1
            or self.broker_total_output_bytes > _MAX_BROKER_OUTPUT_BYTES
        ):
            raise PilotExactTaskPrReviewerWriteTransactionError(
                "reviewer-write transaction target/output binding invalid"
            )
        required_true = (
            "host_transaction_start_committed",
            "reviewer_request_authorization_consumed",
            "reviewer_request_slot_consumed",
            "reviewer_requestability_revalidated",
            "fresh_pr_state_revalidated_before_reviewer_request",
            "no_prior_requested_reviewers_reverified",
            "reviewer_not_pr_author_reverified",
            "write_broker_freshly_verified",
            "credential_broker_invoked_without_secret_exposure",
            "exact_individual_reviewer_request_performed",
            "reviewer_request_performed",
            "post_reviewer_request_readback_verified",
            "exact_reviewer_set_verified",
            "team_reviewers_absent_verified",
        )
        forced_false = (
            "credential_material_in_artifact",
            "credential_material_in_process_arguments",
            "credential_material_in_environment",
            "nonce_reusable",
            "reviewer_mutation_authorized",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrReviewerWriteTransactionError(
                "reviewer-write transaction evidence incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReviewerWriteTransactionError(
                "reviewer-write transaction retains forbidden authority"
            )

    @property
    def transaction_authenticated(self) -> bool:
        return _get_live_pr_reviewer_write_transaction_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrReviewerWriteTransaction":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReviewerWriteTransactionError(
                "reviewer-write transaction must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReviewerWriteTransactionError(
                "reviewer-write transaction fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


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
    fresh = _fresh_exact_pr_state(
        precondition=precondition,
        reservation=reservation,
        target=target,
        requirements=requirements,
        reader=pr_state_reader,
    )
    if (
        fresh["pull_request_author_login"] != capability.pull_request_author_login
        or fresh["pull_request_author_user_id"]
        != capability.pull_request_author_user_id
    ):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "pull-request author identity drifted before reviewer write"
        )
    broker_path = _fresh_broker_binary(
        descriptor,
        require_host_control=broker_host_control_required,
    )
    request = _broker_request(capability)
    request_payload = _canonical_bytes(request)
    request_sha256 = hashlib.sha256(request_payload).hexdigest()

    started_at = now_provider()
    _require_transaction_window(capability, at_utc=started_at)
    start = _TransactionStart(
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

    broker_result, broker_response = _invoke_broker(
        broker_path=broker_path,
        protocol=capability.credential_protocol,
        request_payload=request_payload,
        request_sha256=request_sha256,
        capability=capability,
        subprocess_runner=subprocess_runner,
    )
    mutated_at = now_provider()
    if _utc(mutated_at, name="mutated_at_utc") < _utc(
        started_at,
        name="started_at_utc",
    ):
        raise PilotExactTaskPrReviewerWriteTransactionError(
            "clock moved backwards after reviewer write"
        )
    readback = _validate_readback(
        readback_reader(
            capability=capability,
            requirements=requirements,
            expected_updated_at_utc=broker_response["updated_at_utc"],
        ),
        expected_updated_at_utc=broker_response["updated_at_utc"],
    )
    verified_at = now_provider()
    if _utc(verified_at, name="verified_at_utc") < _utc(
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
    _mark_authenticated(
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
    """Execute one exact pinned individual reviewer request, at most once."""
    return _execute_verified_pilot_exact_task_pr_reviewer_write(
        reviewer_write_credential_capability=reviewer_write_credential_capability,
        ledger=_TransactionLedger(_canonical_ledger_root()),
        pr_state_reader=identity_boundary._read_exact_ready_pr_state,
        subprocess_runner=run_bounded_subprocess,
        readback_reader=_read_post_request_pr,
        now_provider=_now_utc_seconds,
        broker_host_control_required=True,
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_AUTHORITY",
    "PILOT_EXACT_TASK_PR_REVIEWER_WRITE_TRANSACTION_LEDGER_SCOPE",
    "PILOT_EXACT_TASK_PR_REVIEWER_WRITE_BROKER_REQUEST_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEWER_WRITE_BROKER_RESPONSE_SCHEMA",
    "PilotExactTaskPrReviewerWriteTransactionError",
    "PilotExactTaskPrReviewerWriteTransaction",
    "execute_pilot_exact_task_pr_reviewer_write",
]
