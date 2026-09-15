"""ADR-DC-065 exact one-shot GraphQL ready-for-review transaction.

Consumes one live ADR-DC-064 GraphQL node identity. The exact still-draft PR is
freshly revalidated, the host-pinned ready broker is freshly hashed, and a
durable transaction-start marker is committed before one broker invocation of
GitHub's markPullRequestReadyForReview mutation. ModelRig never receives a
credential. A successful mutation is then verified with a separate credential-
free REST readback. Any ambiguous failure after the start marker fails closed
and cannot be automatically retried with the same ready nonce.
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
from . import _improvement_pilot_exact_task_pr_ready_for_review_credential_capability_production_boundary as broker_boundary
from .bounded_subprocess import BoundedSubprocessError, run_bounded_subprocess
from .durable_publication import DurablePublicationError, create_once_file
from . import improvement_pilot_exact_task_pr_ready_for_review_credential_capability as capability_boundary
from . import improvement_pilot_exact_task_pr_ready_for_review_node_identity as node_boundary
from .improvement_pilot_exact_task_pr_ready_for_review_node_identity import (
    PILOT_EXACT_TASK_PR_READY_NODE_IDENTITY_AUTHORITY,
    PilotExactTaskPrReadyNodeIdentity,
)

PILOT_EXACT_TASK_PR_READY_TRANSACTION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-ready-for-review-transaction/v1"
)
PILOT_EXACT_TASK_PR_READY_TRANSACTION_AUTHORITY = (
    "completed-one-dc-l16-exact-pr-ready-for-review-only"
)
PILOT_EXACT_TASK_PR_READY_TRANSACTION_LEDGER_SCOPE = (
    "canonical-host-pr-ready-for-review-transaction-v1"
)
PILOT_EXACT_TASK_PR_READY_BROKER_REQUEST_SCHEMA = (
    "kaliv-rsi-pilot-exact-task-pr-ready-for-review-broker-request/v1"
)
PILOT_EXACT_TASK_PR_READY_BROKER_RESPONSE_SCHEMA = (
    "kaliv-rsi-pilot-exact-task-pr-ready-for-review-broker-response/v1"
)
PILOT_EXACT_TASK_PR_READY_GRAPHQL_MUTATION = "markPullRequestReadyForReview"
PILOT_EXACT_TASK_PR_READY_TRANSACTION_MAX_NODE_IDENTITY_AGE_SECONDS = 60
PILOT_EXACT_TASK_PR_READY_READBACK_API_VERSION = "2022-11-28"

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_NODE_ID = re.compile(r"^[A-Za-z0-9_+/=-]{8,256}$")
_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_MAX_BROKER_REQUEST_BYTES = 128 * 1024
_MAX_BROKER_OUTPUT_BYTES = 64 * 1024
_MAX_READBACK_BYTES = 256 * 1024
_BROKER_TIMEOUT_SECONDS = 60
_READBACK_TIMEOUT_SECONDS = 20
_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-pr-ready-for-review-transaction-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-pr-ready-for-review-transaction-ledger-v1"
)


class PilotExactTaskPrReadyTransactionError(ValueError):
    """The exact ready-for-review transaction is stale, replayed or unsafe."""


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
        raise PilotExactTaskPrReadyTransactionError(
            "ready-for-review transaction is not canonical JSON"
        ) from exc


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return _canonical(value).encode("utf-8")


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrReadyTransactionError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrReadyTransactionError(f"{name} is invalid")
    return value


def _node_id(value: Any) -> str:
    if not isinstance(value, str) or value.strip() != value or _NODE_ID.fullmatch(value) is None:
        raise PilotExactTaskPrReadyTransactionError("GraphQL pull-request node id is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrReadyTransactionError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskPrReadyTransactionError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


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
        raise PilotExactTaskPrReadyTransactionError(
            "ready transaction ledger root is unsafe"
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
        raise PilotExactTaskPrReadyTransactionError(
            "canonical ready transaction ledger is not host controlled"
        ) from exc
    raise PilotExactTaskPrReadyTransactionError(
        "ready transaction platform is unsupported"
    )


def _require_live_identity(
    value: Any,
) -> tuple[PilotExactTaskPrReadyNodeIdentity, Any, Any, Mapping[str, str], Any]:
    if type(value) is not PilotExactTaskPrReadyNodeIdentity:
        raise PilotExactTaskPrReadyTransactionError(
            "exact ADR-DC-064 GraphQL node identity is required"
        )
    try:
        replayed = PilotExactTaskPrReadyNodeIdentity.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrReadyTransactionError(
            "ADR-DC-064 node identity replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrReadyTransactionError(
            "ADR-DC-064 node identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_PR_READY_NODE_IDENTITY_AUTHORITY
        or value.identity_authenticated is not True
        or value.credential_free_rest_read is not True
        or value.exact_pr_state_reverified is not True
        or value.graphql_pull_request_node_identity_verified is not True
        or value.graphql_ready_for_review_mutation_required is not True
        or value.ready_for_review_authorization_consumed is not True
        or value.ready_for_review_slot_reserved is not True
        or value.ready_for_review_authorized is not False
        or value.ready_for_review_performed is not False
        or value.reviewer_mutation_authorized is not False
        or value.label_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskPrReadyTransactionError(
            "ready transaction requires one live inert ADR-DC-064 identity"
        )
    identity_inputs = node_boundary._get_live_pr_ready_node_identity_inputs(value)
    capability = None if identity_inputs is None else identity_inputs.get(
        "ready_credential_capability"
    )
    if (
        capability is None
        or getattr(capability, "capability_authenticated", None) is not True
        or capability.sha256 != value.ready_credential_capability_sha256
    ):
        raise PilotExactTaskPrReadyTransactionError(
            "ADR-DC-064 lost live ADR-DC-063 capability provenance"
        )
    cap_inputs = capability_boundary._get_live_pr_ready_credential_capability_inputs(
        capability
    )
    descriptor = None if cap_inputs is None else cap_inputs.get(
        "credential_broker_descriptor"
    )
    if not isinstance(descriptor, Mapping):
        raise PilotExactTaskPrReadyTransactionError(
            "ADR-DC-063 live broker descriptor is unavailable"
        )
    try:
        _capability, _observation, _reservation, requirements = (
            node_boundary._require_live_capability(capability)
        )
    except Exception as exc:
        raise PilotExactTaskPrReadyTransactionError(
            "ADR-DC-063 live state provenance is unavailable"
        ) from exc
    if (
        capability.pull_request_number != value.pull_request_number
        or capability.predicted_commit_sha != value.predicted_commit_sha
        or capability.ready_for_review_nonce_sha256 != value.ready_for_review_nonce_sha256
        or requirements.review_handoff_plan_sha256 != value.review_handoff_plan_sha256
    ):
        raise PilotExactTaskPrReadyTransactionError(
            "ready transaction provenance binding mismatch"
        )
    return value, capability, requirements, MappingProxyType(dict(descriptor)), _observation


def _require_transaction_window(identity: PilotExactTaskPrReadyNodeIdentity, *, at_utc: str) -> None:
    at = _utc(at_utc, name="ready transaction time")
    observed = _utc(identity.observed_at_utc, name="node identity observed_at_utc")
    if at < observed or (at - observed).total_seconds() > PILOT_EXACT_TASK_PR_READY_TRANSACTION_MAX_NODE_IDENTITY_AGE_SECONDS:
        raise PilotExactTaskPrReadyTransactionError(
            "ADR-DC-064 node identity is too old for ready mutation"
        )


def _fresh_exact_draft_state(
    *,
    identity: PilotExactTaskPrReadyNodeIdentity,
    capability: Any,
    requirements: Any,
    reader: Callable[..., Mapping[str, Any]],
) -> Mapping[str, Any]:
    try:
        evidence = node_boundary._validate_reader_evidence(
            reader(
                ready_credential_capability=capability,
                review_handoff_requirements=requirements,
            ),
            capability=capability,
        )
    except Exception as exc:
        raise PilotExactTaskPrReadyTransactionError(
            "fresh exact draft revalidation failed immediately before ready mutation"
        ) from exc
    if (
        evidence["pull_request_node_id"] != identity.pull_request_node_id
        or evidence["pull_request_node_id_sha256"] != identity.pull_request_node_id_sha256
        or evidence["observed_updated_at_utc"] != identity.observed_updated_at_utc
    ):
        raise PilotExactTaskPrReadyTransactionError(
            "fresh PR/node state drifted before ready mutation"
        )
    return evidence


def _fresh_broker_binary(
    descriptor: Mapping[str, str],
    *,
    require_host_control: bool,
) -> Path:
    path_text = descriptor.get("broker_executable_path")
    if not isinstance(path_text, str) or not path_text:
        raise PilotExactTaskPrReadyTransactionError(
            "live ready credential-broker path is unavailable"
        )
    path = Path(path_text)
    try:
        payload = broker_boundary._read_broker_bytes(
            path,
            require_host_control=require_host_control,
        )
    except Exception as exc:
        raise PilotExactTaskPrReadyTransactionError(
            "ready credential-broker binary could not be freshly verified"
        ) from exc
    if hashlib.sha256(payload).hexdigest() != descriptor.get("broker_executable_sha256"):
        raise PilotExactTaskPrReadyTransactionError(
            "ready credential-broker binary changed after ADR-DC-063"
        )
    if _path_sha256(path) != descriptor.get("broker_executable_path_sha256"):
        raise PilotExactTaskPrReadyTransactionError(
            "ready credential-broker path identity changed after ADR-DC-063"
        )
    return path


def _broker_request(identity: PilotExactTaskPrReadyNodeIdentity) -> Mapping[str, Any]:
    request = {
        "schema": PILOT_EXACT_TASK_PR_READY_BROKER_REQUEST_SCHEMA,
        "operation": "mark-pull-request-ready-for-review",
        "graphql_mutation": PILOT_EXACT_TASK_PR_READY_GRAPHQL_MUTATION,
        "api_origin": "https://api.github.com/graphql",
        "repository": identity.repository,
        "pull_request_number": identity.pull_request_number,
        "pull_request_id": identity.pull_request_node_id,
        "pull_request_id_sha256": identity.pull_request_node_id_sha256,
        "head_sha": identity.predicted_commit_sha,
        "review_handoff_plan_sha256": identity.review_handoff_plan_sha256,
        "ready_for_review_nonce_sha256": identity.ready_for_review_nonce_sha256,
    }
    payload = _canonical_bytes(request)
    if not payload or len(payload) > _MAX_BROKER_REQUEST_BYTES:
        raise PilotExactTaskPrReadyTransactionError(
            "exact ready broker request exceeds byte bound"
        )
    return MappingProxyType(request)


def _validate_broker_response(
    payload: bytes,
    *,
    request_sha256: str,
    identity: PilotExactTaskPrReadyNodeIdentity,
) -> Mapping[str, Any]:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_BROKER_OUTPUT_BYTES:
        raise PilotExactTaskPrReadyTransactionError(
            "ready credential-broker response is missing or oversized"
        )
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrReadyTransactionError(
            "ready credential-broker response is not UTF-8 JSON"
        ) from exc
    expected = {
        "schema",
        "status",
        "graphql_mutation",
        "request_sha256",
        "ready_for_review_nonce_sha256",
        "repository",
        "pull_request_number",
        "pull_request_id",
        "pull_request_id_sha256",
        "head_sha",
        "is_draft",
        "updated_at_utc",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PilotExactTaskPrReadyTransactionError(
            "ready credential-broker response fields mismatch"
        )
    updated = value.get("updated_at_utc")
    _utc(updated, name="broker updated_at_utc")
    if (
        value.get("schema") != PILOT_EXACT_TASK_PR_READY_BROKER_RESPONSE_SCHEMA
        or value.get("status") != "ready-for-review"
        or value.get("graphql_mutation") != PILOT_EXACT_TASK_PR_READY_GRAPHQL_MUTATION
        or value.get("request_sha256") != request_sha256
        or value.get("ready_for_review_nonce_sha256") != identity.ready_for_review_nonce_sha256
        or value.get("repository") != identity.repository
        or value.get("pull_request_number") != identity.pull_request_number
        or value.get("pull_request_id") != identity.pull_request_node_id
        or value.get("pull_request_id_sha256") != identity.pull_request_node_id_sha256
        or value.get("head_sha") != identity.predicted_commit_sha
        or value.get("is_draft") is not False
        or _utc(updated, name="broker updated_at_utc") < _utc(identity.observed_updated_at_utc, name="pre-ready updated_at_utc")
    ):
        raise PilotExactTaskPrReadyTransactionError(
            "ready credential-broker response does not match exact authorized PR"
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
    identity: PilotExactTaskPrReadyNodeIdentity,
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
        raise PilotExactTaskPrReadyTransactionError(
            "ready broker environment unexpectedly contains credential-shaped keys"
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
        raise PilotExactTaskPrReadyTransactionError(
            "bounded ready credential-broker process failed"
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
        raise PilotExactTaskPrReadyTransactionError(
            "ready credential-broker did not complete cleanly and silently"
        )
    return result, _validate_broker_response(
        result.stdout.prefix,
        request_sha256=request_sha256,
        identity=identity,
    )


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _read_ready_pr(
    *,
    identity: PilotExactTaskPrReadyNodeIdentity,
    requirements: Any,
    expected_updated_at_utc: str,
) -> Mapping[str, Any]:
    url = identity.pull_request_api_url
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": PILOT_EXACT_TASK_PR_READY_READBACK_API_VERSION,
            "User-Agent": "ModelRig-DevControl-ADR-DC-065",
        },
    )
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(request, timeout=_READBACK_TIMEOUT_SECONDS) as response:
            status = getattr(response, "status", None)
            headers = {str(k).lower(): str(v).strip() for k, v in response.headers.items()}
            payload = response.read(_MAX_READBACK_BYTES + 1)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PilotExactTaskPrReadyTransactionError(
            "fixed-origin ready PR readback failed"
        ) from exc
    if status != 200 or len(payload) > _MAX_READBACK_BYTES:
        raise PilotExactTaskPrReadyTransactionError(
            "ready PR readback status/size is unsafe"
        )
    lowered_headers = {name.lower() for name in request.headers}
    if "authorization" in lowered_headers or "cookie" in lowered_headers:
        raise PilotExactTaskPrReadyTransactionError(
            "ready PR readback must remain credential free"
        )
    try:
        document = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrReadyTransactionError(
            "ready PR readback is not UTF-8 JSON"
        ) from exc
    if not isinstance(document, Mapping):
        raise PilotExactTaskPrReadyTransactionError("ready PR readback must be an object")
    head = document.get("head")
    base = document.get("base")
    head_repo = None if not isinstance(head, Mapping) else head.get("repo")
    base_repo = None if not isinstance(base, Mapping) else base.get("repo")
    node = document.get("node_id")
    if (
        document.get("number") != identity.pull_request_number
        or document.get("node_id") != identity.pull_request_node_id
        or document.get("url") != identity.pull_request_api_url
        or document.get("html_url") != identity.pull_request_html_url
        or document.get("state") != "open"
        or document.get("closed_at") is not None
        or document.get("merged_at") is not None
        or document.get("draft") is not False
        or document.get("title") != requirements.pr_title
        or document.get("body") != requirements.pr_body
        or document.get("maintainer_can_modify") is not False
        or document.get("updated_at") != expected_updated_at_utc
        or not isinstance(head, Mapping)
        or head.get("ref") != identity.head_branch
        or head.get("sha") != identity.predicted_commit_sha
        or not isinstance(head_repo, Mapping)
        or head_repo.get("full_name") != identity.repository
        or not isinstance(base, Mapping)
        or base.get("ref") != identity.base_branch
        or not isinstance(base_repo, Mapping)
        or base_repo.get("full_name") != identity.repository
        or _node_id(node) != identity.pull_request_node_id
    ):
        raise PilotExactTaskPrReadyTransactionError(
            "post-ready PR does not exactly match authorized identity/state"
        )
    etag = headers.get("etag", "")
    if len(etag) > 512 or "\r" in etag or "\n" in etag or "\x00" in etag:
        raise PilotExactTaskPrReadyTransactionError("ready PR readback ETag is invalid")
    return MappingProxyType(
        {
            "response_body_sha256": hashlib.sha256(payload).hexdigest(),
            "response_etag_sha256": hashlib.sha256(etag.encode("utf-8")).hexdigest(),
            "pull_request_node_id_sha256": hashlib.sha256(node.encode("utf-8")).hexdigest(),
            "updated_at_utc": expected_updated_at_utc,
        }
    )


def _validate_readback_evidence(value: Any, *, identity: PilotExactTaskPrReadyNodeIdentity, expected_updated_at_utc: str) -> Mapping[str, Any]:
    expected = {
        "response_body_sha256",
        "response_etag_sha256",
        "pull_request_node_id_sha256",
        "updated_at_utc",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PilotExactTaskPrReadyTransactionError("ready readback evidence fields mismatch")
    result = dict(value)
    for name in ("response_body_sha256", "response_etag_sha256", "pull_request_node_id_sha256"):
        _hex64(result.get(name), name=name)
    if (
        result["pull_request_node_id_sha256"] != identity.pull_request_node_id_sha256
        or result.get("updated_at_utc") != expected_updated_at_utc
    ):
        raise PilotExactTaskPrReadyTransactionError("ready readback evidence identity mismatch")
    return MappingProxyType(result)


@dataclass(frozen=True, slots=True)
class _PilotExactTaskPrReadyTransactionStart:
    ledger_root_path_sha256: str
    transaction_key_sha256: str
    node_identity_sha256: str
    ready_credential_capability_sha256: str
    ready_state_observation_sha256: str
    ready_for_review_reservation_sha256: str
    review_handoff_requirements_sha256: str
    ready_for_review_nonce_sha256: str
    pull_request_node_id_sha256: str
    predicted_commit_sha: str
    broker_request_sha256: str
    broker_policy_sha256: str
    broker_executable_path_sha256: str
    broker_executable_sha256: str
    repository: str
    pull_request_number: int
    started_at_utc: str
    authority: str = "started-one-dc-l16-exact-pr-ready-for-review-only"
    schema: str = "kaliv-rsi-dc-l16-exact-task-pr-ready-for-review-transaction-start/v1"

    def __post_init__(self) -> None:
        for name in (
            "ledger_root_path_sha256", "transaction_key_sha256", "node_identity_sha256",
            "ready_credential_capability_sha256", "ready_state_observation_sha256",
            "ready_for_review_reservation_sha256", "review_handoff_requirements_sha256",
            "ready_for_review_nonce_sha256", "pull_request_node_id_sha256", "broker_request_sha256",
            "broker_policy_sha256", "broker_executable_path_sha256", "broker_executable_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _utc(self.started_at_utc, name="started_at_utc")
        if self.transaction_key_sha256 != self.ready_for_review_nonce_sha256 or self.repository != "Ternedal/ModelRig" or self.pull_request_number < 1:
            raise PilotExactTaskPrReadyTransactionError("ready transaction-start binding is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class _PilotExactTaskPrReadyTransactionLedger:
    def __init__(self, root: Path) -> None:
        self.root = _require_safe_ledger_root(Path(root))
        self.root_sha256 = _path_sha256(self.root)

    def _start_path(self, nonce_sha256: str) -> Path:
        return self.root / f"{_hex64(nonce_sha256, name='ready_for_review_nonce_sha256')}.start.json"

    def _final_path(self, nonce_sha256: str) -> Path:
        return self.root / f"{_hex64(nonce_sha256, name='ready_for_review_nonce_sha256')}.json"

    def begin(self, start: _PilotExactTaskPrReadyTransactionStart) -> tuple[Path, bytes]:
        if start.ledger_root_path_sha256 != self.root_sha256 or start.transaction_key_sha256 != start.ready_for_review_nonce_sha256:
            raise PilotExactTaskPrReadyTransactionError("ready transaction-start does not belong to ledger")
        start_path = self._start_path(start.ready_for_review_nonce_sha256)
        final_path = self._final_path(start.ready_for_review_nonce_sha256)
        if start_path.exists() or final_path.exists():
            raise PilotExactTaskPrReadyTransactionError("ready nonce already has transaction state")
        payload = start.canonical_json().encode("utf-8")
        try:
            create_once_file(start_path, payload, mode=0o600)
        except (FileExistsError, DurablePublicationError, OSError) as exc:
            raise PilotExactTaskPrReadyTransactionError("ready transaction-start could not be committed") from exc
        if _read_bound_file(start_path) != payload:
            raise PilotExactTaskPrReadyTransactionError("ready transaction-start readback failed")
        return start_path, payload

    def finish(self, receipt: "PilotExactTaskPrReadyTransaction") -> tuple[Path, bytes]:
        if receipt.ledger_root_path_sha256 != self.root_sha256 or receipt.transaction_key_sha256 != receipt.ready_for_review_nonce_sha256:
            raise PilotExactTaskPrReadyTransactionError("ready transaction receipt does not belong to ledger")
        if not self._start_path(receipt.ready_for_review_nonce_sha256).is_file():
            raise PilotExactTaskPrReadyTransactionError("ready transaction lacks durable start marker")
        final_path = self._final_path(receipt.ready_for_review_nonce_sha256)
        payload = receipt.canonical_json().encode("utf-8")
        try:
            create_once_file(final_path, payload, mode=0o600)
        except (FileExistsError, DurablePublicationError, OSError) as exc:
            raise PilotExactTaskPrReadyTransactionError("ready transaction receipt could not be committed") from exc
        if _read_bound_file(final_path) != payload:
            raise PilotExactTaskPrReadyTransactionError("ready transaction receipt readback failed")
        return final_path, payload


_live_records: dict[int, tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[PilotExactTaskPrReadyNodeIdentity], Path, bytes, Path, bytes]] = {}


def _mark_pr_ready_transaction_authenticated(receipt: Any, identity: PilotExactTaskPrReadyNodeIdentity, *, start_path: Path, start_payload: bytes, final_path: Path, final_payload: bytes) -> None:
    key = id(receipt)
    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)
    _live_records[key] = (
        os.getpid(), receipt.sha256, weakref.ref(receipt, cleanup), weakref.ref(identity),
        start_path, start_payload, final_path, final_payload,
    )


def _get_live_pr_ready_transaction_inputs(receipt: Any) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(receipt))
    if entry is None:
        return None
    pid, digest, receipt_ref, identity_ref, start_path, start_payload, final_path, final_payload = entry
    identity = identity_ref()
    if (
        pid != os.getpid() or receipt_ref() is not receipt or identity is None
        or identity.identity_authenticated is not True
        or identity.sha256 != receipt.node_identity_sha256
        or receipt.sha256 != digest
        or _read_bound_file(start_path) != start_payload
        or _read_bound_file(final_path) != final_payload
    ):
        return None
    return MappingProxyType({"ready_node_identity": identity})


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReadyTransaction:
    ledger_root_path_sha256: str
    transaction_key_sha256: str
    transaction_start_sha256: str
    node_identity_sha256: str
    ready_credential_capability_sha256: str
    ready_state_observation_sha256: str
    ready_for_review_reservation_sha256: str
    review_handoff_requirements_sha256: str
    pr_create_transaction_sha256: str
    predicted_commit_sha: str
    review_handoff_plan_sha256: str
    ready_for_review_nonce_sha256: str
    repository: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_html_url: str
    pull_request_node_id: str
    pull_request_node_id_sha256: str
    base_branch: str
    head_branch: str
    broker_policy_sha256: str
    broker_executable_path_sha256: str
    broker_executable_sha256: str
    broker_request_sha256: str
    broker_stdout_sha256: str
    broker_stderr_sha256: str
    broker_total_output_bytes: int
    prewrite_response_body_sha256: str
    prewrite_response_etag_sha256: str
    post_ready_response_body_sha256: str
    post_ready_response_etag_sha256: str
    pre_ready_updated_at_utc: str
    ready_updated_at_utc: str
    started_at_utc: str
    mutated_at_utc: str
    verified_at_utc: str
    host_transaction_start_committed: bool = True
    ready_for_review_authorization_consumed: bool = True
    ready_for_review_slot_consumed: bool = True
    fresh_pr_state_revalidated_before_ready: bool = True
    exact_graphql_node_identity_revalidated: bool = True
    credential_broker_freshly_verified: bool = True
    credential_broker_invoked_without_secret_exposure: bool = True
    exact_graphql_ready_request_performed: bool = True
    ready_for_review_performed: bool = True
    post_ready_readback_verified: bool = True
    draft_state_cleared_verified: bool = True
    exact_head_sha_verified: bool = True
    exact_base_verified: bool = True
    exact_metadata_verified: bool = True
    credential_material_in_artifact: bool = False
    credential_material_in_process_arguments: bool = False
    credential_material_in_environment: bool = False
    pr_mutation_authorized: bool = False
    pull_request_create_authorized: bool = False
    ready_for_review_authorized: bool = False
    reviewer_mutation_authorized: bool = False
    label_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_READY_TRANSACTION_AUTHORITY
    ledger_scope: str = PILOT_EXACT_TASK_PR_READY_TRANSACTION_LEDGER_SCOPE
    schema: str = PILOT_EXACT_TASK_PR_READY_TRANSACTION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PR_READY_TRANSACTION_SCHEMA or self.authority != PILOT_EXACT_TASK_PR_READY_TRANSACTION_AUTHORITY or self.ledger_scope != PILOT_EXACT_TASK_PR_READY_TRANSACTION_LEDGER_SCOPE:
            raise PilotExactTaskPrReadyTransactionError("ready transaction schema/authority/scope is unsupported")
        for name in (
            "ledger_root_path_sha256", "transaction_key_sha256", "transaction_start_sha256", "node_identity_sha256",
            "ready_credential_capability_sha256", "ready_state_observation_sha256", "ready_for_review_reservation_sha256",
            "review_handoff_requirements_sha256", "pr_create_transaction_sha256", "review_handoff_plan_sha256",
            "ready_for_review_nonce_sha256", "pull_request_node_id_sha256", "broker_policy_sha256",
            "broker_executable_path_sha256", "broker_executable_sha256", "broker_request_sha256",
            "broker_stdout_sha256", "broker_stderr_sha256", "prewrite_response_body_sha256",
            "prewrite_response_etag_sha256", "post_ready_response_body_sha256", "post_ready_response_etag_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _node_id(self.pull_request_node_id)
        if self.pull_request_node_id_sha256 != hashlib.sha256(self.pull_request_node_id.encode("utf-8")).hexdigest():
            raise PilotExactTaskPrReadyTransactionError("ready transaction node id digest mismatch")
        pre = _utc(self.pre_ready_updated_at_utc, name="pre_ready_updated_at_utc")
        ready = _utc(self.ready_updated_at_utc, name="ready_updated_at_utc")
        started = _utc(self.started_at_utc, name="started_at_utc")
        mutated = _utc(self.mutated_at_utc, name="mutated_at_utc")
        verified = _utc(self.verified_at_utc, name="verified_at_utc")
        if ready < pre or mutated < started or verified < mutated:
            raise PilotExactTaskPrReadyTransactionError("ready transaction timestamps are invalid")
        if (
            self.transaction_key_sha256 != self.ready_for_review_nonce_sha256
            or self.repository != "Ternedal/ModelRig" or self.base_branch != "main"
            or _HEAD.fullmatch(self.head_branch) is None
            or self.pull_request_number < 1
            or self.pull_request_api_url != f"https://api.github.com/repos/Ternedal/ModelRig/pulls/{self.pull_request_number}"
            or self.pull_request_html_url != f"https://github.com/Ternedal/ModelRig/pull/{self.pull_request_number}"
            or isinstance(self.broker_total_output_bytes, bool) or not isinstance(self.broker_total_output_bytes, int)
            or self.broker_total_output_bytes < 1 or self.broker_total_output_bytes > _MAX_BROKER_OUTPUT_BYTES
        ):
            raise PilotExactTaskPrReadyTransactionError("ready transaction target/output binding is invalid")
        required_true = (
            "host_transaction_start_committed", "ready_for_review_authorization_consumed", "ready_for_review_slot_consumed",
            "fresh_pr_state_revalidated_before_ready", "exact_graphql_node_identity_revalidated",
            "credential_broker_freshly_verified", "credential_broker_invoked_without_secret_exposure",
            "exact_graphql_ready_request_performed", "ready_for_review_performed", "post_ready_readback_verified",
            "draft_state_cleared_verified", "exact_head_sha_verified", "exact_base_verified", "exact_metadata_verified",
        )
        forced_false = (
            "credential_material_in_artifact", "credential_material_in_process_arguments", "credential_material_in_environment",
            "pr_mutation_authorized", "pull_request_create_authorized", "ready_for_review_authorized",
            "reviewer_mutation_authorized", "label_mutation_authorized", "merge_authorized", "release_authorized",
            "deploy_authorized", "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrReadyTransactionError("ready transaction evidence is incomplete")
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReadyTransactionError("ready transaction retains forbidden authority")

    @property
    def transaction_authenticated(self) -> bool:
        return _get_live_pr_ready_transaction_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrReadyTransaction":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReadyTransactionError("ready transaction must be an object")
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReadyTransactionError("ready transaction fields mismatch")
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _execute_verified_pilot_exact_task_pr_ready_for_review(
    *,
    ready_node_identity: PilotExactTaskPrReadyNodeIdentity,
    ledger: _PilotExactTaskPrReadyTransactionLedger,
    state_reader: Callable[..., Mapping[str, Any]],
    subprocess_runner: Callable[..., Any],
    readback_reader: Callable[..., Mapping[str, Any]],
    now_provider: Callable[[], str],
    broker_host_control_required: bool,
) -> PilotExactTaskPrReadyTransaction:
    identity, capability, requirements, descriptor, _observation = _require_live_identity(ready_node_identity)
    transaction_at = now_provider()
    _require_transaction_window(identity, at_utc=transaction_at)
    fresh = _fresh_exact_draft_state(
        identity=identity,
        capability=capability,
        requirements=requirements,
        reader=state_reader,
    )
    broker_path = _fresh_broker_binary(
        descriptor,
        require_host_control=broker_host_control_required,
    )
    request = _broker_request(identity)
    request_payload = _canonical_bytes(request)
    request_sha256 = hashlib.sha256(request_payload).hexdigest()
    started_at = now_provider()
    _require_transaction_window(identity, at_utc=started_at)
    start = _PilotExactTaskPrReadyTransactionStart(
        ledger_root_path_sha256=ledger.root_sha256,
        transaction_key_sha256=identity.ready_for_review_nonce_sha256,
        node_identity_sha256=identity.sha256,
        ready_credential_capability_sha256=capability.sha256,
        ready_state_observation_sha256=identity.ready_state_observation_sha256,
        ready_for_review_reservation_sha256=identity.ready_for_review_reservation_sha256,
        review_handoff_requirements_sha256=identity.review_handoff_requirements_sha256,
        ready_for_review_nonce_sha256=identity.ready_for_review_nonce_sha256,
        pull_request_node_id_sha256=identity.pull_request_node_id_sha256,
        predicted_commit_sha=identity.predicted_commit_sha,
        broker_request_sha256=request_sha256,
        broker_policy_sha256=capability.broker_policy_sha256,
        broker_executable_path_sha256=capability.broker_executable_path_sha256,
        broker_executable_sha256=capability.broker_executable_sha256,
        repository=identity.repository,
        pull_request_number=identity.pull_request_number,
        started_at_utc=started_at,
    )
    start_path, start_payload = ledger.begin(start)
    broker_result, broker_response = _invoke_broker(
        broker_path=broker_path,
        protocol=capability.credential_protocol,
        request_payload=request_payload,
        request_sha256=request_sha256,
        identity=identity,
        subprocess_runner=subprocess_runner,
    )
    mutated_at = now_provider()
    if _utc(mutated_at, name="mutated_at_utc") < _utc(started_at, name="started_at_utc"):
        raise PilotExactTaskPrReadyTransactionError("ready mutation time predates start")
    readback = _validate_readback_evidence(
        readback_reader(
            identity=identity,
            requirements=requirements,
            expected_updated_at_utc=broker_response["updated_at_utc"],
        ),
        identity=identity,
        expected_updated_at_utc=broker_response["updated_at_utc"],
    )
    verified_at = now_provider()
    receipt = PilotExactTaskPrReadyTransaction(
        ledger_root_path_sha256=ledger.root_sha256,
        transaction_key_sha256=identity.ready_for_review_nonce_sha256,
        transaction_start_sha256=start.sha256,
        node_identity_sha256=identity.sha256,
        ready_credential_capability_sha256=capability.sha256,
        ready_state_observation_sha256=identity.ready_state_observation_sha256,
        ready_for_review_reservation_sha256=identity.ready_for_review_reservation_sha256,
        review_handoff_requirements_sha256=identity.review_handoff_requirements_sha256,
        pr_create_transaction_sha256=identity.pr_create_transaction_sha256,
        predicted_commit_sha=identity.predicted_commit_sha,
        review_handoff_plan_sha256=identity.review_handoff_plan_sha256,
        ready_for_review_nonce_sha256=identity.ready_for_review_nonce_sha256,
        repository=identity.repository,
        pull_request_number=identity.pull_request_number,
        pull_request_api_url=identity.pull_request_api_url,
        pull_request_html_url=identity.pull_request_html_url,
        pull_request_node_id=identity.pull_request_node_id,
        pull_request_node_id_sha256=identity.pull_request_node_id_sha256,
        base_branch=identity.base_branch,
        head_branch=identity.head_branch,
        broker_policy_sha256=capability.broker_policy_sha256,
        broker_executable_path_sha256=capability.broker_executable_path_sha256,
        broker_executable_sha256=capability.broker_executable_sha256,
        broker_request_sha256=request_sha256,
        broker_stdout_sha256=broker_result.stdout.sha256,
        broker_stderr_sha256=broker_result.stderr.sha256,
        broker_total_output_bytes=broker_result.total_output_bytes,
        prewrite_response_body_sha256=fresh["response_body_sha256"],
        prewrite_response_etag_sha256=fresh["response_etag_sha256"],
        post_ready_response_body_sha256=readback["response_body_sha256"],
        post_ready_response_etag_sha256=readback["response_etag_sha256"],
        pre_ready_updated_at_utc=identity.observed_updated_at_utc,
        ready_updated_at_utc=broker_response["updated_at_utc"],
        started_at_utc=started_at,
        mutated_at_utc=mutated_at,
        verified_at_utc=verified_at,
    )
    final_path, final_payload = ledger.finish(receipt)
    _mark_pr_ready_transaction_authenticated(
        receipt,
        identity,
        start_path=start_path,
        start_payload=start_payload,
        final_path=final_path,
        final_payload=final_payload,
    )
    if receipt.transaction_authenticated is not True:
        raise PilotExactTaskPrReadyTransactionError(
            "ready transaction lost durable live provenance"
        )
    return receipt


def execute_pilot_exact_task_pr_ready_for_review(
    ready_node_identity: PilotExactTaskPrReadyNodeIdentity,
) -> PilotExactTaskPrReadyTransaction:
    """Execute one exact ready transition through the host-pinned GraphQL broker."""
    return _execute_verified_pilot_exact_task_pr_ready_for_review(
        ready_node_identity=ready_node_identity,
        ledger=_PilotExactTaskPrReadyTransactionLedger(_canonical_ledger_root()),
        state_reader=node_boundary._read_exact_pr_node_identity,
        subprocess_runner=run_bounded_subprocess,
        readback_reader=_read_ready_pr,
        now_provider=_now_utc_seconds,
        broker_host_control_required=True,
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_READY_TRANSACTION_SCHEMA",
    "PILOT_EXACT_TASK_PR_READY_TRANSACTION_AUTHORITY",
    "PILOT_EXACT_TASK_PR_READY_TRANSACTION_LEDGER_SCOPE",
    "PILOT_EXACT_TASK_PR_READY_BROKER_REQUEST_SCHEMA",
    "PILOT_EXACT_TASK_PR_READY_BROKER_RESPONSE_SCHEMA",
    "PILOT_EXACT_TASK_PR_READY_GRAPHQL_MUTATION",
    "PilotExactTaskPrReadyTransactionError",
    "PilotExactTaskPrReadyTransaction",
    "execute_pilot_exact_task_pr_ready_for_review",
]
