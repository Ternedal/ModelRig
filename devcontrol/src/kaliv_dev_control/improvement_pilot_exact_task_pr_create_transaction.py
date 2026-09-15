"""ADR-DC-058 exact one-shot draft pull-request create transaction.

Consumes one live ADR-DC-057 host-pinned PR credential capability. The exact
head/base is freshly re-observed as having no open PR, the pinned credential
broker is freshly re-hashed, and a durable create-once transaction-start marker
is committed before the broker is invoked. The broker owns credential retrieval
and HTTPS; ModelRig never receives a GitHub secret. A successful create is then
verified through a separate credential-free fixed-origin GitHub GET.

Any failure after the start marker is durable leaves the nonce burned for
explicit recovery rather than automatically retrying an ambiguous POST.
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

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
    _require_host_controlled_ledger_root,
)
from . import _improvement_pilot_exact_task_pr_credential_capability_production_boundary as broker_boundary
from .bounded_subprocess import BoundedSubprocessError, run_bounded_subprocess
from .durable_publication import DurablePublicationError, create_once_file
from . import improvement_pilot_exact_task_pr_credential_capability as capability_boundary
from .improvement_pilot_exact_task_pr_credential_capability import (
    PILOT_EXACT_TASK_PR_CREDENTIAL_CAPABILITY_AUTHORITY,
    PilotExactTaskPrCredentialCapability,
)
from . import improvement_pilot_exact_task_pr_mutation_reservation as reservation_boundary
from . import improvement_pilot_exact_task_pr_state_observation as observation_boundary

PILOT_EXACT_TASK_PR_CREATE_TRANSACTION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-create-transaction/v1"
)
PILOT_EXACT_TASK_PR_CREATE_TRANSACTION_AUTHORITY = (
    "completed-one-dc-l16-exact-draft-pr-create-only"
)
PILOT_EXACT_TASK_PR_CREATE_TRANSACTION_LEDGER_SCOPE = (
    "canonical-host-pr-create-transaction-v1"
)
PILOT_EXACT_TASK_PR_CREATE_BROKER_REQUEST_SCHEMA = (
    "kaliv-rsi-pilot-exact-task-pr-create-broker-request/v1"
)
PILOT_EXACT_TASK_PR_CREATE_BROKER_RESPONSE_SCHEMA = (
    "kaliv-rsi-pilot-exact-task-pr-create-broker-response/v1"
)
PILOT_EXACT_TASK_PR_CREATE_TRANSACTION_MAX_CAPABILITY_AGE_SECONDS = 60
PILOT_EXACT_TASK_PR_CREATE_TRANSACTION_ORIGIN = "https://api.github.com"
PILOT_EXACT_TASK_PR_CREATE_TRANSACTION_API_VERSION = "2022-11-28"

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_MAX_BROKER_REQUEST_BYTES = 128 * 1024
_MAX_BROKER_OUTPUT_BYTES = 64 * 1024
_MAX_READBACK_BYTES = 256 * 1024
_BROKER_TIMEOUT_SECONDS = 60
_READBACK_TIMEOUT_SECONDS = 20
_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-pr-create-transaction-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-pr-create-transaction-ledger-v1"
)


class PilotExactTaskPrCreateTransactionError(ValueError):
    """The exact draft-PR transaction is stale, replayed, drifted, or unsafe."""


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
        raise PilotExactTaskPrCreateTransactionError(
            "PR create transaction is not canonical JSON"
        ) from exc


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return _canonical(value).encode("utf-8")


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskPrCreateTransactionError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskPrCreateTransactionError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrCreateTransactionError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrCreateTransactionError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _path_sha256(path: Path) -> str:
    return hashlib.sha256(
        os.fsencode(os.path.abspath(os.fspath(path)))
    ).hexdigest()


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
    if (
        not candidate.is_absolute()
        or not candidate.is_dir()
        or candidate.is_symlink()
    ):
        raise PilotExactTaskPrCreateTransactionError(
            "PR create transaction ledger root is unsafe"
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
        raise PilotExactTaskPrCreateTransactionError(
            "canonical PR create transaction ledger is not host controlled"
        ) from exc
    raise PilotExactTaskPrCreateTransactionError(
        "PR create transaction platform is unsupported"
    )


def _require_live_capability(
    value: Any,
) -> tuple[
    PilotExactTaskPrCredentialCapability,
    Any,
    Any,
    Any,
    Mapping[str, str],
]:
    if type(value) is not PilotExactTaskPrCredentialCapability:
        raise PilotExactTaskPrCreateTransactionError(
            "exact ADR-DC-057 PR credential capability is required"
        )
    try:
        replayed = PilotExactTaskPrCredentialCapability.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPrCreateTransactionError(
            "ADR-DC-057 capability replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrCreateTransactionError(
            "ADR-DC-057 capability identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_PR_CREDENTIAL_CAPABILITY_AUTHORITY
        or value.capability_authenticated is not True
        or value.pr_mutation_slot_reserved is not True
        or value.no_existing_open_pr_verified is not True
        or value.credential_broker_host_pinned is not True
        or value.credential_broker_binary_verified is not True
        or value.credential_secret_not_loaded is not True
        or value.credential_broker_owns_https is not True
        or value.credential_material_in_artifact is not False
        or value.credential_material_in_process_arguments is not False
        or value.credential_material_in_environment is not False
        or value.one_shot_draft_pr_create_required is not True
        or value.fresh_pr_state_revalidation_before_create_required is not True
        or value.post_create_readback_verification_required is not True
        or value.maintainer_can_modify is not False
        or value.pr_mutation_authorized is not False
        or value.pull_request_create_authorized is not False
        or value.pull_request_created is not False
        or value.ready_for_review_authorized is not False
        or value.reviewer_mutation_authorized is not False
        or value.label_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.repository != "Ternedal/ModelRig"
        or value.base_branch != "main"
        or _HEAD.fullmatch(value.head_branch) is None
    ):
        raise PilotExactTaskPrCreateTransactionError(
            "PR create transaction requires one live inert ADR-DC-057 capability"
        )

    cap_inputs = capability_boundary._get_live_pr_credential_capability_inputs(
        value
    )
    if cap_inputs is None:
        raise PilotExactTaskPrCreateTransactionError(
            "ADR-DC-057 live capability provenance is unavailable"
        )
    supplied_observation = cap_inputs.get("pr_state_observation")
    descriptor = cap_inputs.get("credential_broker_descriptor")
    if (
        supplied_observation is None
        or getattr(supplied_observation, "observation_authenticated", None) is not True
        or getattr(supplied_observation, "sha256", None)
        != value.pr_state_observation_sha256
        or not isinstance(descriptor, Mapping)
        or descriptor.get("broker_policy_sha256") != value.broker_policy_sha256
        or descriptor.get("broker_executable_path_sha256")
        != value.broker_executable_path_sha256
        or descriptor.get("broker_executable_sha256")
        != value.broker_executable_sha256
    ):
        raise PilotExactTaskPrCreateTransactionError(
            "ADR-DC-057 lost exact live observation/broker provenance"
        )

    observation_inputs = observation_boundary._get_live_pr_state_observation_inputs(
        supplied_observation
    )
    reservation = None if observation_inputs is None else observation_inputs.get(
        "pr_mutation_reservation"
    )
    if (
        reservation is None
        or getattr(reservation, "reservation_authenticated", None) is not True
        or getattr(reservation, "sha256", None)
        != value.pr_mutation_reservation_sha256
    ):
        raise PilotExactTaskPrCreateTransactionError(
            "ADR-DC-056 live reservation provenance is unavailable"
        )
    reservation_inputs = reservation_boundary._get_live_pr_mutation_reservation_inputs(
        reservation
    )
    requirements = None if reservation_inputs is None else reservation_inputs.get(
        "pr_mutation_requirements"
    )
    if (
        requirements is None
        or getattr(requirements, "requirements_authenticated", None) is not True
        or getattr(requirements, "sha256", None)
        != value.pr_mutation_requirements_sha256
        or getattr(requirements, "remote_write_transaction_sha256", None)
        != value.remote_write_transaction_sha256
        or getattr(requirements, "predicted_commit_sha", None)
        != value.predicted_commit_sha
        or getattr(requirements, "pr_plan_sha256", None) != value.pr_plan_sha256
        or getattr(requirements, "repository", None) != value.repository
        or getattr(requirements, "base_branch", None) != value.base_branch
        or getattr(requirements, "head_branch", None) != value.head_branch
    ):
        raise PilotExactTaskPrCreateTransactionError(
            "ADR-DC-055 live deterministic PR requirements are unavailable"
        )
    return value, supplied_observation, reservation, requirements, MappingProxyType(dict(descriptor))


def _require_transaction_window(
    capability: PilotExactTaskPrCredentialCapability,
    *,
    at_utc: str,
) -> None:
    at = _utc(at_utc, name="PR transaction time")
    materialized = _utc(
        capability.materialized_at_utc,
        name="capability materialized_at_utc",
    )
    if at < materialized:
        raise PilotExactTaskPrCreateTransactionError(
            "system clock moved backwards after ADR-DC-057 capability"
        )
    if (
        at - materialized
    ).total_seconds() > PILOT_EXACT_TASK_PR_CREATE_TRANSACTION_MAX_CAPABILITY_AGE_SECONDS:
        raise PilotExactTaskPrCreateTransactionError(
            "ADR-DC-057 credential capability is too old for PR create"
        )


def _fresh_pr_absence(
    *,
    supplied_observation: Any,
    reservation: Any,
    reader: Callable[..., Mapping[str, Any]],
    now_provider: Callable[[], str],
) -> Any:
    try:
        fresh = observation_boundary._observe_verified_pilot_exact_task_pr_state(
            pr_mutation_reservation=reservation,
            reader=reader,
            now_provider=now_provider,
        )
    except Exception as exc:
        raise PilotExactTaskPrCreateTransactionError(
            "fresh zero-open-PR revalidation failed immediately before create"
        ) from exc
    identity_fields = (
        "pr_mutation_reservation_sha256",
        "pr_mutation_requirements_sha256",
        "remote_write_transaction_sha256",
        "predicted_commit_sha",
        "pr_plan_sha256",
        "pr_mutation_nonce_sha256",
        "repository",
        "base_branch",
        "head_branch",
        "request_url_sha256",
        "open_pr_match_count",
        "reservation_revalidated",
        "fixed_origin_github_read",
        "credential_free_read",
        "redirects_forbidden",
        "response_bounded",
        "no_existing_open_pr_verified",
        "create_new_draft_pull_request_required",
        "fresh_pr_state_revalidation_before_create_required",
        "maintainer_can_modify",
        "pr_mutation_authorized",
        "pull_request_create_authorized",
        "pull_request_created",
        "ready_for_review_authorized",
        "reviewer_mutation_authorized",
        "label_mutation_authorized",
        "merge_authorized",
        "release_authorized",
        "deploy_authorized",
        "production_activation_authorized",
    )
    if any(
        getattr(fresh, name) != getattr(supplied_observation, name)
        for name in identity_fields
    ):
        raise PilotExactTaskPrCreateTransactionError(
            "fresh PR-state target/safety semantics drifted before create"
        )
    if fresh.observation_authenticated is not True or fresh.open_pr_match_count != 0:
        raise PilotExactTaskPrCreateTransactionError(
            "fresh PR-state evidence is not live zero-open-PR proof"
        )
    return fresh


def _fresh_broker_binary(
    descriptor: Mapping[str, str],
    *,
    require_host_control: bool,
) -> Path:
    path_text = descriptor.get("broker_executable_path")
    if not isinstance(path_text, str) or not path_text:
        raise PilotExactTaskPrCreateTransactionError(
            "live PR credential-broker path is unavailable"
        )
    path = Path(path_text)
    try:
        payload = broker_boundary._read_broker_bytes(
            path,
            require_host_control=require_host_control,
        )
    except Exception as exc:
        raise PilotExactTaskPrCreateTransactionError(
            "PR credential-broker binary could not be freshly verified"
        ) from exc
    if hashlib.sha256(payload).hexdigest() != descriptor.get(
        "broker_executable_sha256"
    ):
        raise PilotExactTaskPrCreateTransactionError(
            "PR credential-broker binary changed after ADR-DC-057"
        )
    if _path_sha256(path) != descriptor.get("broker_executable_path_sha256"):
        raise PilotExactTaskPrCreateTransactionError(
            "PR credential-broker path identity changed after ADR-DC-057"
        )
    return path


def _broker_request(
    *,
    capability: PilotExactTaskPrCredentialCapability,
    requirements: Any,
) -> Mapping[str, Any]:
    request = {
        "schema": PILOT_EXACT_TASK_PR_CREATE_BROKER_REQUEST_SCHEMA,
        "operation": "create-draft-pull-request",
        "api_origin": PILOT_EXACT_TASK_PR_CREATE_TRANSACTION_ORIGIN,
        "repository": capability.repository,
        "base_branch": capability.base_branch,
        "head_branch": capability.head_branch,
        "head_sha": capability.predicted_commit_sha,
        "title": requirements.pr_title,
        "body": requirements.pr_body,
        "draft": True,
        "maintainer_can_modify": False,
        "pr_plan_sha256": capability.pr_plan_sha256,
        "pr_mutation_nonce_sha256": capability.pr_mutation_nonce_sha256,
    }
    payload = _canonical_bytes(request)
    if not payload or len(payload) > _MAX_BROKER_REQUEST_BYTES:
        raise PilotExactTaskPrCreateTransactionError(
            "exact PR broker request exceeds byte bound"
        )
    return MappingProxyType(request)


def _validate_broker_response(
    payload: bytes,
    *,
    request_sha256: str,
    capability: PilotExactTaskPrCredentialCapability,
) -> Mapping[str, Any]:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_BROKER_OUTPUT_BYTES:
        raise PilotExactTaskPrCreateTransactionError(
            "PR credential-broker response is missing or oversized"
        )
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrCreateTransactionError(
            "PR credential-broker response is not UTF-8 JSON"
        ) from exc
    expected_fields = {
        "schema",
        "status",
        "http_status",
        "request_sha256",
        "pr_mutation_nonce_sha256",
        "pull_request_number",
        "api_url",
        "html_url",
        "repository",
        "base_ref",
        "head_ref",
        "head_sha",
        "draft",
        "maintainer_can_modify",
    }
    if not isinstance(value, Mapping) or set(value) != expected_fields:
        raise PilotExactTaskPrCreateTransactionError(
            "PR credential-broker response fields mismatch"
        )
    number = value.get("pull_request_number")
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise PilotExactTaskPrCreateTransactionError(
            "PR credential-broker response number is invalid"
        )
    api_url = (
        f"https://api.github.com/repos/Ternedal/ModelRig/pulls/{number}"
    )
    html_url = f"https://github.com/Ternedal/ModelRig/pull/{number}"
    if (
        value.get("schema") != PILOT_EXACT_TASK_PR_CREATE_BROKER_RESPONSE_SCHEMA
        or value.get("status") != "created"
        or value.get("http_status") != 201
        or value.get("request_sha256") != request_sha256
        or value.get("pr_mutation_nonce_sha256")
        != capability.pr_mutation_nonce_sha256
        or value.get("api_url") != api_url
        or value.get("html_url") != html_url
        or value.get("repository") != capability.repository
        or value.get("base_ref") != capability.base_branch
        or value.get("head_ref") != capability.head_branch
        or value.get("head_sha") != capability.predicted_commit_sha
        or value.get("draft") is not True
        or value.get("maintainer_can_modify") is not False
    ):
        raise PilotExactTaskPrCreateTransactionError(
            "PR credential-broker response does not match exact draft plan"
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
    capability: PilotExactTaskPrCredentialCapability,
    request_payload: bytes,
    request_sha256: str,
    subprocess_runner: Callable[..., Any],
) -> tuple[Any, Mapping[str, Any]]:
    command = (
        os.fspath(broker_path),
        "--protocol",
        capability.credential_protocol,
        "--request-stdin-json",
        "--response-stdout-json",
    )
    environment = _broker_environment()
    if any(
        marker in key.upper()
        for key in environment
        for marker in ("TOKEN", "PASSWORD", "AUTHORIZATION", "BEARER")
    ):
        raise PilotExactTaskPrCreateTransactionError(
            "PR broker environment unexpectedly contains credential-shaped keys"
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
        raise PilotExactTaskPrCreateTransactionError(
            "bounded PR credential-broker process failed"
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
        raise PilotExactTaskPrCreateTransactionError(
            "PR credential-broker did not complete cleanly and silently"
        )
    response = _validate_broker_response(
        result.stdout.prefix,
        request_sha256=request_sha256,
        capability=capability,
    )
    return result, response


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _read_created_pr(
    *,
    pull_request_number: int,
    capability: PilotExactTaskPrCredentialCapability,
    requirements: Any,
) -> Mapping[str, Any]:
    if (
        isinstance(pull_request_number, bool)
        or not isinstance(pull_request_number, int)
        or pull_request_number < 1
    ):
        raise PilotExactTaskPrCreateTransactionError("PR readback number is invalid")
    url = (
        f"{PILOT_EXACT_TASK_PR_CREATE_TRANSACTION_ORIGIN}/repos/"
        f"Ternedal/ModelRig/pulls/{pull_request_number}"
    )
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": PILOT_EXACT_TASK_PR_CREATE_TRANSACTION_API_VERSION,
            "User-Agent": "ModelRig-DevControl-ADR-DC-058",
        },
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
        raise PilotExactTaskPrCreateTransactionError(
            "fixed-origin created-PR readback failed"
        ) from exc
    if status != 200:
        raise PilotExactTaskPrCreateTransactionError(
            "created-PR readback returned a non-success status"
        )
    if len(payload) > _MAX_READBACK_BYTES:
        raise PilotExactTaskPrCreateTransactionError(
            "created-PR readback exceeded byte ceiling"
        )
    lowered_request_headers = {name.lower() for name in request.headers}
    if "authorization" in lowered_request_headers or "cookie" in lowered_request_headers:
        raise PilotExactTaskPrCreateTransactionError(
            "created-PR readback must remain credential free"
        )
    try:
        document = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrCreateTransactionError(
            "created-PR readback is not UTF-8 JSON"
        ) from exc
    if not isinstance(document, Mapping):
        raise PilotExactTaskPrCreateTransactionError(
            "created-PR readback must be a JSON object"
        )
    head = document.get("head")
    base = document.get("base")
    head_repo = None if not isinstance(head, Mapping) else head.get("repo")
    base_repo = None if not isinstance(base, Mapping) else base.get("repo")
    api_url = (
        f"https://api.github.com/repos/Ternedal/ModelRig/pulls/"
        f"{pull_request_number}"
    )
    html_url = f"https://github.com/Ternedal/ModelRig/pull/{pull_request_number}"
    if (
        document.get("number") != pull_request_number
        or document.get("url") != api_url
        or document.get("html_url") != html_url
        or document.get("state") != "open"
        or document.get("draft") is not True
        or document.get("title") != requirements.pr_title
        or document.get("body") != requirements.pr_body
        or document.get("maintainer_can_modify") is not False
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
        raise PilotExactTaskPrCreateTransactionError(
            "created PR does not exactly match the authorized draft plan"
        )
    etag = headers.get("etag", "")
    if len(etag) > 512 or "\r" in etag or "\n" in etag or "\x00" in etag:
        raise PilotExactTaskPrCreateTransactionError(
            "created-PR readback ETag is invalid"
        )
    return MappingProxyType(
        {
            "response_body_sha256": hashlib.sha256(payload).hexdigest(),
            "response_etag_sha256": hashlib.sha256(
                etag.encode("utf-8")
            ).hexdigest(),
            "pull_request_number": pull_request_number,
            "api_url": api_url,
            "html_url": html_url,
        }
    )


def _validate_readback_evidence(
    value: Any,
    *,
    pull_request_number: int,
) -> Mapping[str, Any]:
    expected = {
        "response_body_sha256",
        "response_etag_sha256",
        "pull_request_number",
        "api_url",
        "html_url",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PilotExactTaskPrCreateTransactionError(
            "created-PR readback evidence fields mismatch"
        )
    result = dict(value)
    _hex64(result.get("response_body_sha256"), name="response_body_sha256")
    _hex64(result.get("response_etag_sha256"), name="response_etag_sha256")
    if result.get("pull_request_number") != pull_request_number:
        raise PilotExactTaskPrCreateTransactionError(
            "created-PR readback number mismatch"
        )
    if result.get("api_url") != (
        f"https://api.github.com/repos/Ternedal/ModelRig/pulls/{pull_request_number}"
    ) or result.get("html_url") != (
        f"https://github.com/Ternedal/ModelRig/pull/{pull_request_number}"
    ):
        raise PilotExactTaskPrCreateTransactionError(
            "created-PR readback URL mismatch"
        )
    return MappingProxyType(result)


@dataclass(frozen=True, slots=True)
class _PilotExactTaskPrCreateTransactionStart:
    ledger_root_path_sha256: str
    transaction_key_sha256: str
    pr_credential_capability_sha256: str
    fresh_pr_state_observation_sha256: str
    pr_mutation_reservation_sha256: str
    pr_mutation_requirements_sha256: str
    pr_plan_sha256: str
    pr_mutation_nonce_sha256: str
    predicted_commit_sha: str
    broker_request_sha256: str
    broker_policy_sha256: str
    broker_executable_path_sha256: str
    broker_executable_sha256: str
    repository: str
    base_branch: str
    head_branch: str
    started_at_utc: str
    authority: str = "started-one-dc-l16-exact-draft-pr-create-only"
    schema: str = "kaliv-rsi-dc-l16-exact-task-pr-create-transaction-start/v1"

    def __post_init__(self) -> None:
        for name in (
            "ledger_root_path_sha256",
            "transaction_key_sha256",
            "pr_credential_capability_sha256",
            "fresh_pr_state_observation_sha256",
            "pr_mutation_reservation_sha256",
            "pr_mutation_requirements_sha256",
            "pr_plan_sha256",
            "pr_mutation_nonce_sha256",
            "broker_request_sha256",
            "broker_policy_sha256",
            "broker_executable_path_sha256",
            "broker_executable_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _utc(self.started_at_utc, name="started_at_utc")
        if (
            self.transaction_key_sha256 != self.pr_mutation_nonce_sha256
            or self.repository != "Ternedal/ModelRig"
            or self.base_branch != "main"
            or _HEAD.fullmatch(self.head_branch) is None
        ):
            raise PilotExactTaskPrCreateTransactionError(
                "PR transaction-start target binding is invalid"
            )

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class _PilotExactTaskPrCreateTransactionLedger:
    def __init__(self, root: Path) -> None:
        self.root = _require_safe_ledger_root(Path(root))
        self.root_sha256 = _path_sha256(self.root)

    def _start_path(self, nonce_sha256: str) -> Path:
        return self.root / (
            f"{_hex64(nonce_sha256, name='pr_mutation_nonce_sha256')}.start.json"
        )

    def _final_path(self, nonce_sha256: str) -> Path:
        return self.root / (
            f"{_hex64(nonce_sha256, name='pr_mutation_nonce_sha256')}.json"
        )

    def begin(
        self,
        start: _PilotExactTaskPrCreateTransactionStart,
    ) -> tuple[Path, bytes]:
        if (
            type(start) is not _PilotExactTaskPrCreateTransactionStart
            or start.ledger_root_path_sha256 != self.root_sha256
            or start.transaction_key_sha256 != start.pr_mutation_nonce_sha256
        ):
            raise PilotExactTaskPrCreateTransactionError(
                "PR transaction-start does not belong to this ledger"
            )
        start_path = self._start_path(start.pr_mutation_nonce_sha256)
        final_path = self._final_path(start.pr_mutation_nonce_sha256)
        if start_path.exists() or final_path.exists():
            raise PilotExactTaskPrCreateTransactionError(
                "PR-mutation nonce already has transaction state"
            )
        payload = start.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PilotExactTaskPrCreateTransactionError(
                "PR transaction-start exceeds byte bound"
            )
        try:
            create_once_file(start_path, payload, mode=0o600)
        except (FileExistsError, DurablePublicationError, OSError) as exc:
            raise PilotExactTaskPrCreateTransactionError(
                "PR transaction-start could not be committed create-once"
            ) from exc
        if _read_bound_file(start_path) != payload:
            raise PilotExactTaskPrCreateTransactionError(
                "PR transaction-start could not be read back exactly"
            )
        return start_path, payload

    def finish(
        self,
        receipt: "PilotExactTaskPrCreateTransaction",
    ) -> tuple[Path, bytes]:
        if (
            type(receipt) is not PilotExactTaskPrCreateTransaction
            or receipt.ledger_root_path_sha256 != self.root_sha256
            or receipt.transaction_key_sha256 != receipt.pr_mutation_nonce_sha256
        ):
            raise PilotExactTaskPrCreateTransactionError(
                "PR transaction receipt does not belong to this ledger"
            )
        final_path = self._final_path(receipt.pr_mutation_nonce_sha256)
        if not self._start_path(receipt.pr_mutation_nonce_sha256).is_file():
            raise PilotExactTaskPrCreateTransactionError(
                "PR transaction finalization lacks durable start marker"
            )
        payload = receipt.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PilotExactTaskPrCreateTransactionError(
                "PR transaction receipt exceeds byte bound"
            )
        try:
            create_once_file(final_path, payload, mode=0o600)
        except (FileExistsError, DurablePublicationError, OSError) as exc:
            raise PilotExactTaskPrCreateTransactionError(
                "PR transaction receipt could not be committed create-once"
            ) from exc
        if _read_bound_file(final_path) != payload:
            raise PilotExactTaskPrCreateTransactionError(
                "PR transaction receipt could not be read back exactly"
            )
        return final_path, payload


_live_records: dict[
    int,
    tuple[
        int,
        str,
        weakref.ReferenceType[Any],
        weakref.ReferenceType[PilotExactTaskPrCredentialCapability],
        Path,
        bytes,
        Path,
        bytes,
    ],
] = {}


def _mark_pr_create_transaction_authenticated(
    receipt: Any,
    capability: PilotExactTaskPrCredentialCapability,
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


def _get_live_pr_create_transaction_inputs(receipt: Any) -> Mapping[str, Any] | None:
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
        or capability.sha256 != receipt.pr_credential_capability_sha256
        or receipt.sha256 != digest
        or _read_bound_file(start_path) != start_payload
        or _read_bound_file(final_path) != final_payload
    ):
        return None
    return MappingProxyType({"pr_credential_capability": capability})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrCreateTransaction:
    ledger_root_path_sha256: str
    transaction_key_sha256: str
    transaction_start_sha256: str
    pr_credential_capability_sha256: str
    fresh_pr_state_observation_sha256: str
    pr_mutation_reservation_sha256: str
    pr_mutation_requirements_sha256: str
    remote_write_transaction_sha256: str
    predicted_commit_sha: str
    pr_plan_sha256: str
    pr_mutation_nonce_sha256: str
    repository: str
    base_branch: str
    head_branch: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_html_url: str
    broker_request_sha256: str
    broker_policy_sha256: str
    broker_executable_path_sha256: str
    broker_executable_sha256: str
    broker_stdout_sha256: str
    broker_stderr_sha256: str
    broker_total_output_bytes: int
    readback_body_sha256: str
    readback_etag_sha256: str
    started_at_utc: str
    created_at_utc: str
    verified_at_utc: str
    host_transaction_start_committed: bool = True
    pr_mutation_slot_consumed: bool = True
    fresh_pr_state_revalidated_before_create: bool = True
    no_existing_open_pr_reverified: bool = True
    credential_broker_freshly_verified: bool = True
    credential_broker_invoked_without_secret_exposure: bool = True
    exact_draft_pr_request_performed: bool = True
    pull_request_created: bool = True
    draft_pull_request_created: bool = True
    post_create_readback_verified: bool = True
    draft_state_verified: bool = True
    exact_head_sha_verified: bool = True
    exact_base_verified: bool = True
    exact_metadata_verified: bool = True
    credential_material_in_artifact: bool = False
    credential_material_in_process_arguments: bool = False
    credential_material_in_environment: bool = False
    maintainer_can_modify: bool = False
    pr_mutation_authorized: bool = False
    pull_request_create_authorized: bool = False
    ready_for_review_authorized: bool = False
    reviewer_mutation_authorized: bool = False
    label_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_CREATE_TRANSACTION_AUTHORITY
    ledger_scope: str = PILOT_EXACT_TASK_PR_CREATE_TRANSACTION_LEDGER_SCOPE
    schema: str = PILOT_EXACT_TASK_PR_CREATE_TRANSACTION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PR_CREATE_TRANSACTION_SCHEMA
            or self.authority != PILOT_EXACT_TASK_PR_CREATE_TRANSACTION_AUTHORITY
            or self.ledger_scope
            != PILOT_EXACT_TASK_PR_CREATE_TRANSACTION_LEDGER_SCOPE
        ):
            raise PilotExactTaskPrCreateTransactionError(
                "PR create transaction schema/authority/scope is unsupported"
            )
        for name in (
            "ledger_root_path_sha256",
            "transaction_key_sha256",
            "transaction_start_sha256",
            "pr_credential_capability_sha256",
            "fresh_pr_state_observation_sha256",
            "pr_mutation_reservation_sha256",
            "pr_mutation_requirements_sha256",
            "remote_write_transaction_sha256",
            "pr_plan_sha256",
            "pr_mutation_nonce_sha256",
            "broker_request_sha256",
            "broker_policy_sha256",
            "broker_executable_path_sha256",
            "broker_executable_sha256",
            "broker_stdout_sha256",
            "broker_stderr_sha256",
            "readback_body_sha256",
            "readback_etag_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        if (
            self.transaction_key_sha256 != self.pr_mutation_nonce_sha256
            or self.repository != "Ternedal/ModelRig"
            or self.base_branch != "main"
            or _HEAD.fullmatch(self.head_branch) is None
            or isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"https://api.github.com/repos/Ternedal/ModelRig/pulls/{self.pull_request_number}"
            or self.pull_request_html_url
            != f"https://github.com/Ternedal/ModelRig/pull/{self.pull_request_number}"
            or isinstance(self.broker_total_output_bytes, bool)
            or not isinstance(self.broker_total_output_bytes, int)
            or self.broker_total_output_bytes < 1
            or self.broker_total_output_bytes > _MAX_BROKER_OUTPUT_BYTES
        ):
            raise PilotExactTaskPrCreateTransactionError(
                "PR create transaction binding is invalid"
            )
        started = _utc(self.started_at_utc, name="started_at_utc")
        created = _utc(self.created_at_utc, name="created_at_utc")
        verified = _utc(self.verified_at_utc, name="verified_at_utc")
        if created < started or verified < created:
            raise PilotExactTaskPrCreateTransactionError(
                "PR create transaction timestamps are not monotonic"
            )
        required_true = (
            "host_transaction_start_committed",
            "pr_mutation_slot_consumed",
            "fresh_pr_state_revalidated_before_create",
            "no_existing_open_pr_reverified",
            "credential_broker_freshly_verified",
            "credential_broker_invoked_without_secret_exposure",
            "exact_draft_pr_request_performed",
            "pull_request_created",
            "draft_pull_request_created",
            "post_create_readback_verified",
            "draft_state_verified",
            "exact_head_sha_verified",
            "exact_base_verified",
            "exact_metadata_verified",
        )
        forced_false = (
            "credential_material_in_artifact",
            "credential_material_in_process_arguments",
            "credential_material_in_environment",
            "maintainer_can_modify",
            "pr_mutation_authorized",
            "pull_request_create_authorized",
            "ready_for_review_authorized",
            "reviewer_mutation_authorized",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrCreateTransactionError(
                "PR create transaction evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrCreateTransactionError(
                "completed PR create transaction cannot retain mutation authority"
            )

    @property
    def transaction_authenticated(self) -> bool:
        return _get_live_pr_create_transaction_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrCreateTransaction":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrCreateTransactionError(
                "PR create transaction must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrCreateTransactionError(
                "PR create transaction fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _execute_verified_pilot_exact_task_pr_create(
    *,
    pr_credential_capability: PilotExactTaskPrCredentialCapability,
    ledger: _PilotExactTaskPrCreateTransactionLedger,
    state_reader: Callable[..., Mapping[str, Any]],
    subprocess_runner: Callable[..., Any],
    readback_reader: Callable[..., Mapping[str, Any]],
    now_provider: Callable[[], str],
    broker_host_control_required: bool,
) -> PilotExactTaskPrCreateTransaction:
    (
        capability,
        supplied_observation,
        reservation,
        requirements,
        descriptor,
    ) = _require_live_capability(pr_credential_capability)
    if not isinstance(ledger, _PilotExactTaskPrCreateTransactionLedger):
        raise PilotExactTaskPrCreateTransactionError(
            "exact PR create transaction ledger is required"
        )

    preflight_at = now_provider()
    _require_transaction_window(capability, at_utc=preflight_at)
    fresh_observation = _fresh_pr_absence(
        supplied_observation=supplied_observation,
        reservation=reservation,
        reader=state_reader,
        now_provider=now_provider,
    )
    broker_path = _fresh_broker_binary(
        descriptor,
        require_host_control=broker_host_control_required,
    )
    request = _broker_request(capability=capability, requirements=requirements)
    request_payload = _canonical_bytes(request)
    request_sha256 = hashlib.sha256(request_payload).hexdigest()

    started_at = now_provider()
    _require_transaction_window(capability, at_utc=started_at)
    start = _PilotExactTaskPrCreateTransactionStart(
        ledger_root_path_sha256=ledger.root_sha256,
        transaction_key_sha256=capability.pr_mutation_nonce_sha256,
        pr_credential_capability_sha256=capability.sha256,
        fresh_pr_state_observation_sha256=fresh_observation.sha256,
        pr_mutation_reservation_sha256=capability.pr_mutation_reservation_sha256,
        pr_mutation_requirements_sha256=capability.pr_mutation_requirements_sha256,
        pr_plan_sha256=capability.pr_plan_sha256,
        pr_mutation_nonce_sha256=capability.pr_mutation_nonce_sha256,
        predicted_commit_sha=capability.predicted_commit_sha,
        broker_request_sha256=request_sha256,
        broker_policy_sha256=capability.broker_policy_sha256,
        broker_executable_path_sha256=capability.broker_executable_path_sha256,
        broker_executable_sha256=capability.broker_executable_sha256,
        repository=capability.repository,
        base_branch=capability.base_branch,
        head_branch=capability.head_branch,
        started_at_utc=started_at,
    )
    start_path, start_payload = ledger.begin(start)

    result, broker_response = _invoke_broker(
        broker_path=broker_path,
        capability=capability,
        request_payload=request_payload,
        request_sha256=request_sha256,
        subprocess_runner=subprocess_runner,
    )
    created_at = now_provider()
    number = broker_response["pull_request_number"]
    readback = _validate_readback_evidence(
        readback_reader(
            pull_request_number=number,
            capability=capability,
            requirements=requirements,
        ),
        pull_request_number=number,
    )
    verified_at = now_provider()
    _require_transaction_window(capability, at_utc=verified_at)

    receipt = PilotExactTaskPrCreateTransaction(
        ledger_root_path_sha256=ledger.root_sha256,
        transaction_key_sha256=capability.pr_mutation_nonce_sha256,
        transaction_start_sha256=start.sha256,
        pr_credential_capability_sha256=capability.sha256,
        fresh_pr_state_observation_sha256=fresh_observation.sha256,
        pr_mutation_reservation_sha256=capability.pr_mutation_reservation_sha256,
        pr_mutation_requirements_sha256=capability.pr_mutation_requirements_sha256,
        remote_write_transaction_sha256=capability.remote_write_transaction_sha256,
        predicted_commit_sha=capability.predicted_commit_sha,
        pr_plan_sha256=capability.pr_plan_sha256,
        pr_mutation_nonce_sha256=capability.pr_mutation_nonce_sha256,
        repository=capability.repository,
        base_branch=capability.base_branch,
        head_branch=capability.head_branch,
        pull_request_number=number,
        pull_request_api_url=broker_response["api_url"],
        pull_request_html_url=broker_response["html_url"],
        broker_request_sha256=request_sha256,
        broker_policy_sha256=capability.broker_policy_sha256,
        broker_executable_path_sha256=capability.broker_executable_path_sha256,
        broker_executable_sha256=capability.broker_executable_sha256,
        broker_stdout_sha256=result.stdout.sha256,
        broker_stderr_sha256=result.stderr.sha256,
        broker_total_output_bytes=result.total_output_bytes,
        readback_body_sha256=readback["response_body_sha256"],
        readback_etag_sha256=readback["response_etag_sha256"],
        started_at_utc=started_at,
        created_at_utc=created_at,
        verified_at_utc=verified_at,
    )
    final_path, final_payload = ledger.finish(receipt)
    _mark_pr_create_transaction_authenticated(
        receipt,
        capability,
        start_path=start_path,
        start_payload=start_payload,
        final_path=final_path,
        final_payload=final_payload,
    )
    if receipt.transaction_authenticated is not True:
        raise PilotExactTaskPrCreateTransactionError(
            "PR create transaction lost durable live capability provenance"
        )
    return receipt


def execute_pilot_exact_task_pr_create(
    pr_credential_capability: PilotExactTaskPrCredentialCapability,
) -> PilotExactTaskPrCreateTransaction:
    """Create one exact draft PR through the host-pinned broker, then verify it."""
    try:
        _require_elevated_operator()
    except PhysicalHostStateError as exc:
        raise PilotExactTaskPrCreateTransactionError(
            "PR create transaction requires an elevated host operator"
        ) from exc
    ledger = _PilotExactTaskPrCreateTransactionLedger(_canonical_ledger_root())
    return _execute_verified_pilot_exact_task_pr_create(
        pr_credential_capability=pr_credential_capability,
        ledger=ledger,
        state_reader=observation_boundary._read_public_open_pr_state,
        subprocess_runner=run_bounded_subprocess,
        readback_reader=_read_created_pr,
        now_provider=_now_utc_seconds,
        broker_host_control_required=True,
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_CREATE_TRANSACTION_SCHEMA",
    "PILOT_EXACT_TASK_PR_CREATE_TRANSACTION_AUTHORITY",
    "PILOT_EXACT_TASK_PR_CREATE_TRANSACTION_LEDGER_SCOPE",
    "PILOT_EXACT_TASK_PR_CREATE_TRANSACTION_MAX_CAPABILITY_AGE_SECONDS",
    "PilotExactTaskPrCreateTransactionError",
    "PilotExactTaskPrCreateTransaction",
    "execute_pilot_exact_task_pr_create",
]
