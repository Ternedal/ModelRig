"""ADR-DC-073 exact one-shot reviewer-request transaction.

Consumes one live ADR-DC-072 requestability preflight, freshly revalidates the
exact ready pull request, freshly hashes the host-pinned reviewer broker, commits
a durable transaction-start marker keyed by the already-consumed reviewer nonce,
and only then asks the broker to request exactly one pinned individual reviewer.
A credential-free REST readback must prove that exact reviewer and no team were
requested. Ambiguous mutation failures remain burned and cannot be retried.
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

from . import _improvement_pilot_exact_task_pr_reviewer_request_credential_capability_production_boundary as broker_boundary
from . import improvement_pilot_exact_task_pr_reviewer_identity_state_observation as state_boundary
from . import improvement_pilot_exact_task_pr_reviewer_requestability_preflight as preflight_boundary
from .bounded_subprocess import BoundedSubprocessError, run_bounded_subprocess
from .durable_publication import DurablePublicationError, create_once_file
from ._improvement_physical_state_host_control import PhysicalHostStateError, _require_elevated_operator, _require_host_controlled_ledger_root
from .improvement_pilot_exact_task_pr_reviewer_requestability_preflight import (
    PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_PREFLIGHT_AUTHORITY,
    PilotExactTaskPrReviewerRequestabilityPreflight,
)

PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_TRANSACTION_SCHEMA = "kaliv-rsi-dc-l16-exact-task-pr-reviewer-request-transaction/v1"
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_TRANSACTION_AUTHORITY = "completed-one-dc-l16-exact-pr-individual-reviewer-request-only"
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_TRANSACTION_LEDGER_SCOPE = "canonical-host-pr-reviewer-request-transaction-v1"
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_BROKER_REQUEST_SCHEMA = "kaliv-rsi-pilot-exact-task-pr-reviewer-request-broker-request/v1"
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_BROKER_RESPONSE_SCHEMA = "kaliv-rsi-pilot-exact-task-pr-reviewer-request-broker-response/v1"
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_OPERATION = "request-exact-reviewer"
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_MAX_PREFLIGHT_AGE_SECONDS = 60
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_API_VERSION = "2022-11-28"

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
_POSIX_LEDGER = Path("/var/lib/modelrig/devcontrol/rsi-pilot-exact-task-pr-reviewer-request-transaction-ledger-v1")
_WINDOWS_LEDGER = Path(r"C:\Program Files\ModelRig\DevControl\state") / "rsi-pilot-exact-task-pr-reviewer-request-transaction-ledger-v1"

class PilotExactTaskPrReviewerRequestTransactionError(ValueError):
    """Exact reviewer request is stale, replayed, ambiguous, or unsafe."""

def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPrReviewerRequestTransactionError("reviewer transaction is not canonical JSON") from exc

def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return _canonical(value).encode("utf-8")

def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrReviewerRequestTransactionError(f"{name} is invalid")
    return value

def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrReviewerRequestTransactionError(f"{name} is invalid")
    return value

def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrReviewerRequestTransactionError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskPrReviewerRequestTransactionError(f"{name} is invalid") from exc

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
        raise PilotExactTaskPrReviewerRequestTransactionError("reviewer transaction ledger root is unsafe")
    return candidate

def _canonical_ledger_root() -> Path:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            return _require_host_controlled_ledger_root(_POSIX_LEDGER)
        if os.name == "nt":
            return _require_host_controlled_ledger_root(_WINDOWS_LEDGER)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskPrReviewerRequestTransactionError("canonical reviewer transaction ledger is not host controlled") from exc
    raise PilotExactTaskPrReviewerRequestTransactionError("reviewer transaction platform is unsupported")

def _require_live_preflight(value: Any):
    if type(value) is not PilotExactTaskPrReviewerRequestabilityPreflight:
        raise PilotExactTaskPrReviewerRequestTransactionError("exact ADR-DC-072 requestability preflight is required")
    try:
        replayed = PilotExactTaskPrReviewerRequestabilityPreflight.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrReviewerRequestTransactionError("ADR-DC-072 replay validation failed") from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPrReviewerRequestTransactionError("ADR-DC-072 preflight identity mismatch")
    if (
        value.authority != PILOT_EXACT_TASK_PR_REVIEWER_REQUESTABILITY_PREFLIGHT_AUTHORITY
        or value.preflight_authenticated is not True
        or value.reviewer_request_authorization_consumed is not True
        or value.reviewer_request_slot_reserved is not True
        or value.reviewer_public_identity_verified is not True
        or value.reviewer_not_pr_author_verified is not True
        or value.credential_broker_freshly_verified is not True
        or value.reviewer_repository_read_access_verified is not True
        or value.reviewer_requestability_verified is not True
        or value.one_shot_reviewer_request_transaction_required is not True
        or value.fresh_pr_state_revalidation_before_reviewer_request_required is not True
        or value.post_reviewer_request_readback_required is not True
        or value.team_reviewers_forbidden is not True
        or value.reviewer_mutation_authorized is not False
        or value.reviewer_request_performed is not False
        or value.label_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskPrReviewerRequestTransactionError("reviewer transaction requires one live inert ADR-DC-072 preflight")
    inputs = preflight_boundary._get_live_pr_reviewer_requestability_preflight_inputs(value)
    capability = None if inputs is None else inputs.get("reviewer_request_credential_capability")
    if capability is None or capability.capability_authenticated is not True or capability.sha256 != value.reviewer_request_credential_capability_sha256:
        raise PilotExactTaskPrReviewerRequestTransactionError("ADR-DC-072 lost live ADR-DC-071 capability provenance")
    cap_inputs = preflight_boundary.capability_boundary._get_live_pr_reviewer_request_credential_capability_inputs(capability)
    observation = None if cap_inputs is None else cap_inputs.get("reviewer_identity_state_observation")
    descriptor = None if cap_inputs is None else cap_inputs.get("credential_broker_descriptor")
    if observation is None or observation.observation_authenticated is not True or observation.sha256 != value.reviewer_identity_state_observation_sha256 or descriptor is None:
        raise PilotExactTaskPrReviewerRequestTransactionError("reviewer transaction lost exact live observation/broker provenance")
    observation_inputs = state_boundary._get_live_pr_reviewer_identity_state_observation_inputs(observation)
    reservation = None if observation_inputs is None else observation_inputs.get("reviewer_request_reservation")
    if reservation is None or reservation.reservation_authenticated is not True or reservation.sha256 != value.reviewer_request_reservation_sha256:
        raise PilotExactTaskPrReviewerRequestTransactionError("reviewer transaction lost exact live reservation provenance")
    target, requirements = state_boundary._require_live_reservation(reservation)[1:]
    if target.sha256 != value.reviewer_target_attestation_sha256 or requirements.sha256 != value.reviewer_handoff_requirements_sha256:
        raise PilotExactTaskPrReviewerRequestTransactionError("reviewer transaction target/requirements provenance mismatch")
    return value, capability, observation, reservation, target, requirements, descriptor

def _require_transaction_window(preflight: PilotExactTaskPrReviewerRequestabilityPreflight, *, at_utc: str) -> None:
    at = _utc(at_utc, name="reviewer transaction time")
    checked = _utc(preflight.checked_at_utc, name="requestability checked_at_utc")
    if at < checked or (at - checked).total_seconds() > PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_MAX_PREFLIGHT_AGE_SECONDS:
        raise PilotExactTaskPrReviewerRequestTransactionError("ADR-DC-072 requestability preflight is too old for mutation")

def _fresh_broker_binary(descriptor: Mapping[str, str], *, require_host_control: bool) -> Path:
    path_text = descriptor.get("broker_executable_path")
    if not isinstance(path_text, str) or not path_text:
        raise PilotExactTaskPrReviewerRequestTransactionError("live reviewer broker path is unavailable")
    path = Path(path_text)
    try:
        payload = broker_boundary._read_broker_bytes(path, require_host_control=require_host_control)
    except Exception as exc:
        raise PilotExactTaskPrReviewerRequestTransactionError("reviewer broker could not be freshly verified") from exc
    if hashlib.sha256(payload).hexdigest() != descriptor.get("broker_executable_sha256") or _path_sha256(path) != descriptor.get("broker_executable_path_sha256"):
        raise PilotExactTaskPrReviewerRequestTransactionError("reviewer broker changed after ADR-DC-071")
    return path

def _validate_pr_evidence(value: Any, *, reservation: Any, target: Any) -> Mapping[str, Any]:
    return state_boundary._validate_pr_evidence(value, receipt=reservation, target=target)

def _fresh_exact_pr_state(*, reservation: Any, target: Any, requirements: Any, reader: Callable[..., Mapping[str, Any]]) -> Mapping[str, Any]:
    return _validate_pr_evidence(reader(reservation_receipt=reservation, reviewer_target=target, reviewer_handoff_requirements=requirements), reservation=reservation, target=target)

def _broker_request(preflight: PilotExactTaskPrReviewerRequestabilityPreflight, *, reservation: Any) -> Mapping[str, Any]:
    request_url = f"{reservation.pull_request_api_url}/requested_reviewers"
    request = {
        "schema": PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_BROKER_REQUEST_SCHEMA,
        "operation": PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_OPERATION,
        "api_origin": "https://api.github.com",
        "request_reviewers_api_url": request_url,
        "repository": preflight.repository,
        "pull_request_number": preflight.pull_request_number,
        "head_sha": preflight.predicted_commit_sha,
        "reviewer_login": preflight.reviewer_login,
        "reviewer_user_id": preflight.reviewer_user_id,
        "reviewer_node_id_sha256": preflight.reviewer_node_id_sha256,
        "reviewer_request_nonce_sha256": preflight.reviewer_request_nonce_sha256,
        "reviewers": [preflight.reviewer_login],
        "team_reviewers": [],
    }
    payload = _canonical_bytes(request)
    if not payload or len(payload) > _MAX_BROKER_REQUEST_BYTES:
        raise PilotExactTaskPrReviewerRequestTransactionError("reviewer broker request exceeds byte bound")
    return MappingProxyType(request)

def _validate_broker_response(payload: bytes, *, request_sha256: str, preflight: PilotExactTaskPrReviewerRequestabilityPreflight) -> Mapping[str, Any]:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_BROKER_OUTPUT_BYTES:
        raise PilotExactTaskPrReviewerRequestTransactionError("reviewer broker response is missing or oversized")
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrReviewerRequestTransactionError("reviewer broker response is not UTF-8 JSON") from exc
    expected = {"schema", "status", "operation", "request_sha256", "repository", "pull_request_number", "head_sha", "reviewer_login", "reviewer_user_id", "reviewer_request_nonce_sha256", "requested_reviewer_count", "requested_team_count", "updated_at_utc"}
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PilotExactTaskPrReviewerRequestTransactionError("reviewer broker response fields mismatch")
    updated = value.get("updated_at_utc")
    _utc(updated, name="reviewer broker updated_at_utc")
    if (
        value.get("schema") != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_BROKER_RESPONSE_SCHEMA
        or value.get("status") != "reviewer-requested"
        or value.get("operation") != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_OPERATION
        or value.get("request_sha256") != request_sha256
        or value.get("repository") != preflight.repository
        or value.get("pull_request_number") != preflight.pull_request_number
        or value.get("head_sha") != preflight.predicted_commit_sha
        or value.get("reviewer_login") != preflight.reviewer_login
        or value.get("reviewer_user_id") != preflight.reviewer_user_id
        or value.get("reviewer_request_nonce_sha256") != preflight.reviewer_request_nonce_sha256
        or value.get("requested_reviewer_count") != 1
        or value.get("requested_team_count") != 0
    ):
        raise PilotExactTaskPrReviewerRequestTransactionError("reviewer broker response does not match exact request")
    return MappingProxyType(dict(value))
def _broker_environment() -> dict[str, str]:
    environment = {"LANG": "C", "LC_ALL": "C"}
    if os.name == "nt":
        for name in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
            value = os.environ.get(name)
            if value and "\0" not in value:
                environment[name] = value
    return environment

def _invoke_broker(*, broker_path: Path, protocol: str, request_payload: bytes, request_sha256: str, preflight: PilotExactTaskPrReviewerRequestabilityPreflight, subprocess_runner: Callable[..., Any]):
    command = (os.fspath(broker_path), "--protocol", protocol, "--request-stdin-json", "--response-stdout-json")
    environment = _broker_environment()
    if any(marker in key.upper() for key in environment for marker in ("TOKEN", "PASSWORD", "AUTHORIZATION", "BEARER")):
        raise PilotExactTaskPrReviewerRequestTransactionError("reviewer broker environment contains credential-shaped keys")
    try:
        result = subprocess_runner(command, cwd=broker_path.parent, env=environment, stdin_bytes=request_payload, timeout_seconds=_BROKER_TIMEOUT_SECONDS, max_output_bytes=_MAX_BROKER_OUTPUT_BYTES, stdout_prefix_bytes=_MAX_BROKER_OUTPUT_BYTES, stderr_prefix_bytes=_MAX_BROKER_OUTPUT_BYTES)
    except BoundedSubprocessError as exc:
        raise PilotExactTaskPrReviewerRequestTransactionError("bounded reviewer broker process failed") from exc
    if result.returncode != 0 or result.output_limit_exceeded or result.timed_out or result.stdout.truncated or result.stderr.truncated or result.stderr.total_bytes != 0 or result.stdout.total_bytes != len(result.stdout.prefix):
        raise PilotExactTaskPrReviewerRequestTransactionError("reviewer broker did not complete cleanly")
    return result, _validate_broker_response(result.stdout.prefix, request_sha256=request_sha256, preflight=preflight)

class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def _read_post_request_pr(*, preflight: PilotExactTaskPrReviewerRequestabilityPreflight, reservation: Any, target: Any, requirements: Any, expected_updated_at_utc: str) -> Mapping[str, Any]:
    request = urllib.request.Request(reservation.pull_request_api_url, method="GET", headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_API_VERSION, "User-Agent": "ModelRig-DevControl-ADR-DC-073"})
    if "authorization" in {str(name).lower() for name in request.headers} or "cookie" in {str(name).lower() for name in request.headers}:
        raise PilotExactTaskPrReviewerRequestTransactionError("reviewer readback must remain credential free")
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(request, timeout=_READBACK_TIMEOUT_SECONDS) as response:
            status = getattr(response, "status", None)
            headers = {str(k).lower(): str(v).strip() for k, v in response.headers.items()}
            payload = response.read(_MAX_READBACK_BYTES + 1)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PilotExactTaskPrReviewerRequestTransactionError("reviewer post-request readback failed") from exc
    if status != 200 or len(payload) > _MAX_READBACK_BYTES:
        raise PilotExactTaskPrReviewerRequestTransactionError("reviewer post-request readback status/size is unsafe")
    try:
        document = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrReviewerRequestTransactionError("reviewer post-request readback is not UTF-8 JSON") from exc
    if not isinstance(document, Mapping):
        raise PilotExactTaskPrReviewerRequestTransactionError("reviewer post-request readback must be an object")
    head, base, author = document.get("head"), document.get("base"), document.get("user")
    head_repo = None if not isinstance(head, Mapping) else head.get("repo")
    base_repo = None if not isinstance(base, Mapping) else base.get("repo")
    reviewers, teams = document.get("requested_reviewers"), document.get("requested_teams")
    if not isinstance(reviewers, list) or len(reviewers) != 1 or not isinstance(reviewers[0], Mapping) or reviewers[0].get("login") != preflight.reviewer_login or reviewers[0].get("id") != preflight.reviewer_user_id or not isinstance(teams, list) or teams:
        raise PilotExactTaskPrReviewerRequestTransactionError("post-request reviewer set is not exactly the pinned individual")
    if (
        document.get("number") != preflight.pull_request_number or document.get("url") != reservation.pull_request_api_url or document.get("html_url") != reservation.pull_request_html_url
        or hashlib.sha256(str(document.get("node_id")).encode("utf-8")).hexdigest() != preflight.pull_request_node_id_sha256
        or document.get("state") != "open" or document.get("closed_at") is not None or document.get("merged_at") is not None or document.get("draft") is not False
        or document.get("title") != requirements.pr_title or document.get("body") != requirements.pr_body or document.get("maintainer_can_modify") is not False
        or document.get("updated_at") != expected_updated_at_utc or not isinstance(author, Mapping) or author.get("id") == preflight.reviewer_user_id
        or not isinstance(head, Mapping) or head.get("ref") != preflight.head_branch or head.get("sha") != preflight.predicted_commit_sha or not isinstance(head_repo, Mapping) or head_repo.get("full_name") != preflight.repository
        or not isinstance(base, Mapping) or base.get("ref") != preflight.base_branch or not isinstance(base_repo, Mapping) or base_repo.get("full_name") != preflight.repository
    ):
        raise PilotExactTaskPrReviewerRequestTransactionError("post-request PR drifted from exact authorized state")
    etag = headers.get("etag", "")
    if len(etag) > 512 or any(marker in etag for marker in ("\r", "\n", "\x00")):
        raise PilotExactTaskPrReviewerRequestTransactionError("reviewer readback ETag is invalid")
    return MappingProxyType({"response_body_sha256": hashlib.sha256(payload).hexdigest(), "response_etag_sha256": hashlib.sha256(etag.encode("utf-8")).hexdigest(), "updated_at_utc": expected_updated_at_utc, "requested_reviewer_count": 1, "requested_team_count": 0})

def _validate_readback(value: Any, *, expected_updated_at_utc: str) -> Mapping[str, Any]:
    expected = {"response_body_sha256", "response_etag_sha256", "updated_at_utc", "requested_reviewer_count", "requested_team_count"}
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PilotExactTaskPrReviewerRequestTransactionError("reviewer readback evidence fields mismatch")
    result = dict(value)
    _hex64(result.get("response_body_sha256"), name="response_body_sha256")
    _hex64(result.get("response_etag_sha256"), name="response_etag_sha256")
    if result.get("updated_at_utc") != expected_updated_at_utc or result.get("requested_reviewer_count") != 1 or result.get("requested_team_count") != 0:
        raise PilotExactTaskPrReviewerRequestTransactionError("reviewer readback evidence does not match exact request")
    _utc(result["updated_at_utc"], name="post-request updated_at_utc")
    return MappingProxyType(result)

@dataclass(frozen=True, slots=True)
class _TransactionStart:
    ledger_root_path_sha256: str
    transaction_key_sha256: str
    requestability_preflight_sha256: str
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
    authority: str = "started-one-dc-l16-exact-pr-individual-reviewer-request-only"
    schema: str = "kaliv-rsi-dc-l16-exact-task-pr-reviewer-request-transaction-start/v1"
    def __post_init__(self):
        for name in ("ledger_root_path_sha256", "transaction_key_sha256", "requestability_preflight_sha256", "reviewer_request_nonce_sha256", "broker_request_sha256", "broker_policy_sha256", "broker_executable_path_sha256", "broker_executable_sha256"):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _utc(self.started_at_utc, name="started_at_utc")
        if self.transaction_key_sha256 != self.reviewer_request_nonce_sha256 or self.repository != "Ternedal/ModelRig" or self.pull_request_number < 1 or not isinstance(self.reviewer_login, str) or _LOGIN.fullmatch(self.reviewer_login) is None or self.reviewer_user_id < 1:
            raise PilotExactTaskPrReviewerRequestTransactionError("reviewer transaction-start binding is invalid")
    def to_dict(self): return {name: getattr(self, name) for name in self.__dataclass_fields__}
    def canonical_json(self): return _canonical(self.to_dict())
    @property
    def sha256(self): return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

class _TransactionLedger:
    def __init__(self, root: Path):
        self.root = _require_safe_ledger_root(Path(root)); self.root_sha256 = _path_sha256(self.root)
    def _start_path(self, nonce): return self.root / f"{_hex64(nonce, name='reviewer_request_nonce_sha256')}.start.json"
    def _final_path(self, nonce): return self.root / f"{_hex64(nonce, name='reviewer_request_nonce_sha256')}.json"
    def begin(self, start: _TransactionStart):
        if start.ledger_root_path_sha256 != self.root_sha256 or self._start_path(start.reviewer_request_nonce_sha256).exists() or self._final_path(start.reviewer_request_nonce_sha256).exists():
            raise PilotExactTaskPrReviewerRequestTransactionError("reviewer nonce already has transaction state")
        path = self._start_path(start.reviewer_request_nonce_sha256); payload = start.canonical_json().encode("utf-8")
        try: create_once_file(path, payload, mode=0o600)
        except (FileExistsError, DurablePublicationError, OSError) as exc: raise PilotExactTaskPrReviewerRequestTransactionError("reviewer transaction-start could not be committed") from exc
        if _read_bound_file(path) != payload: raise PilotExactTaskPrReviewerRequestTransactionError("reviewer transaction-start readback failed")
        return path, payload
    def finish(self, receipt):
        if receipt.ledger_root_path_sha256 != self.root_sha256 or not self._start_path(receipt.reviewer_request_nonce_sha256).is_file(): raise PilotExactTaskPrReviewerRequestTransactionError("reviewer transaction lacks durable start marker")
        path = self._final_path(receipt.reviewer_request_nonce_sha256); payload = receipt.canonical_json().encode("utf-8")
        try: create_once_file(path, payload, mode=0o600)
        except (FileExistsError, DurablePublicationError, OSError) as exc: raise PilotExactTaskPrReviewerRequestTransactionError("reviewer transaction receipt could not be committed") from exc
        if _read_bound_file(path) != payload: raise PilotExactTaskPrReviewerRequestTransactionError("reviewer transaction receipt readback failed")
        return path, payload

_live_records = {}
def _mark_authenticated(receipt, preflight, *, start_path, start_payload, final_path, final_payload):
    key = id(receipt)
    def cleanup(_): _live_records.pop(key, None)
    _live_records[key] = (os.getpid(), receipt.sha256, weakref.ref(receipt, cleanup), weakref.ref(preflight), start_path, start_payload, final_path, final_payload)
def _get_live_pr_reviewer_request_transaction_inputs(receipt):
    entry = _live_records.get(id(receipt))
    if entry is None: return None
    pid, digest, receipt_ref, preflight_ref, start_path, start_payload, final_path, final_payload = entry; preflight = preflight_ref()
    if pid != os.getpid() or receipt_ref() is not receipt or preflight is None or preflight.preflight_authenticated is not True or preflight.sha256 != receipt.requestability_preflight_sha256 or receipt.sha256 != digest or _read_bound_file(start_path) != start_payload or _read_bound_file(final_path) != final_payload: return None
    return MappingProxyType({"reviewer_requestability_preflight": preflight})
if hasattr(os, "register_at_fork"): os.register_at_fork(after_in_child=_live_records.clear)

@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReviewerRequestTransaction:
    ledger_root_path_sha256: str
    transaction_key_sha256: str
    transaction_start_sha256: str
    requestability_preflight_sha256: str
    reviewer_request_credential_capability_sha256: str
    reviewer_identity_state_observation_sha256: str
    reviewer_request_reservation_sha256: str
    reviewer_target_attestation_sha256: str
    reviewer_handoff_requirements_sha256: str
    ready_transaction_sha256: str
    predicted_commit_sha: str
    reviewer_handoff_plan_sha256: str
    reviewer_target_policy_sha256: str
    reviewer_target_policy_epoch: int
    reviewer_request_nonce_sha256: str
    repository: str
    pull_request_number: int
    pull_request_node_id_sha256: str
    base_branch: str
    head_branch: str
    reviewer_login: str
    reviewer_user_id: int
    reviewer_node_id_sha256: str
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
    preflight_checked_at_utc: str
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
    credential_broker_freshly_verified: bool = True
    credential_broker_invoked_without_secret_exposure: bool = True
    exact_individual_reviewer_request_performed: bool = True
    reviewer_request_performed: bool = True
    post_reviewer_request_readback_verified: bool = True
    exact_reviewer_set_verified: bool = True
    team_reviewers_absent_verified: bool = True
    credential_material_in_artifact: bool = False
    credential_material_in_process_arguments: bool = False
    credential_material_in_environment: bool = False
    reviewer_mutation_authorized: bool = False
    label_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_TRANSACTION_AUTHORITY
    ledger_scope: str = PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_TRANSACTION_LEDGER_SCOPE
    schema: str = PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_TRANSACTION_SCHEMA
    def __post_init__(self):
        if self.schema != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_TRANSACTION_SCHEMA or self.authority != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_TRANSACTION_AUTHORITY or self.ledger_scope != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_TRANSACTION_LEDGER_SCOPE: raise PilotExactTaskPrReviewerRequestTransactionError("reviewer transaction schema/authority/scope unsupported")
        for name in ("ledger_root_path_sha256", "transaction_key_sha256", "transaction_start_sha256", "requestability_preflight_sha256", "reviewer_request_credential_capability_sha256", "reviewer_identity_state_observation_sha256", "reviewer_request_reservation_sha256", "reviewer_target_attestation_sha256", "reviewer_handoff_requirements_sha256", "ready_transaction_sha256", "reviewer_handoff_plan_sha256", "reviewer_target_policy_sha256", "reviewer_request_nonce_sha256", "pull_request_node_id_sha256", "reviewer_node_id_sha256", "broker_policy_sha256", "broker_executable_path_sha256", "broker_executable_sha256", "broker_request_sha256", "broker_stdout_sha256", "broker_stderr_sha256", "prewrite_pr_response_body_sha256", "prewrite_pr_response_etag_sha256", "post_request_response_body_sha256", "post_request_response_etag_sha256"):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        for name in ("preflight_checked_at_utc", "prewrite_updated_at_utc", "requested_updated_at_utc", "started_at_utc", "mutated_at_utc", "verified_at_utc"): _utc(getattr(self, name), name=name)
        if self.transaction_key_sha256 != self.reviewer_request_nonce_sha256 or self.repository != "Ternedal/ModelRig" or self.base_branch != "main" or _HEAD.fullmatch(self.head_branch) is None or self.pull_request_number < 1 or self.reviewer_user_id < 1 or not isinstance(self.reviewer_login, str) or _LOGIN.fullmatch(self.reviewer_login) is None or self.broker_total_output_bytes < 1 or self.broker_total_output_bytes > _MAX_BROKER_OUTPUT_BYTES: raise PilotExactTaskPrReviewerRequestTransactionError("reviewer transaction target/output binding invalid")
        required_true = ("host_transaction_start_committed", "reviewer_request_authorization_consumed", "reviewer_request_slot_consumed", "reviewer_requestability_revalidated", "fresh_pr_state_revalidated_before_reviewer_request", "no_prior_requested_reviewers_reverified", "credential_broker_freshly_verified", "credential_broker_invoked_without_secret_exposure", "exact_individual_reviewer_request_performed", "reviewer_request_performed", "post_reviewer_request_readback_verified", "exact_reviewer_set_verified", "team_reviewers_absent_verified")
        forced_false = ("credential_material_in_artifact", "credential_material_in_process_arguments", "credential_material_in_environment", "reviewer_mutation_authorized", "label_mutation_authorized", "merge_authorized", "release_authorized", "deploy_authorized", "production_activation_authorized")
        if any(getattr(self, n) is not True for n in required_true): raise PilotExactTaskPrReviewerRequestTransactionError("reviewer transaction evidence incomplete")
        if any(getattr(self, n) is not False for n in forced_false): raise PilotExactTaskPrReviewerRequestTransactionError("reviewer transaction retains forbidden authority")
    @property
    def transaction_authenticated(self): return _get_live_pr_reviewer_request_transaction_inputs(self) is not None
    @property
    def sha256(self): return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()
    def to_dict(self): return {name: getattr(self, name) for name in self.__dataclass_fields__}
    @classmethod
    def from_mapping(cls, value):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__): raise PilotExactTaskPrReviewerRequestTransactionError("reviewer transaction fields mismatch")
        return cls(**dict(value))
    def canonical_json(self): return _canonical(self.to_dict())

def _execute_verified_pilot_exact_task_pr_reviewer_request(*, reviewer_requestability_preflight, ledger, pr_state_reader, subprocess_runner, readback_reader, now_provider, broker_host_control_required):
    preflight, capability, observation, reservation, target, requirements, descriptor = _require_live_preflight(reviewer_requestability_preflight)
    transaction_at = now_provider(); _require_transaction_window(preflight, at_utc=transaction_at)
    fresh = _fresh_exact_pr_state(reservation=reservation, target=target, requirements=requirements, reader=pr_state_reader)
    broker_path = _fresh_broker_binary(descriptor, require_host_control=broker_host_control_required)
    request = _broker_request(preflight, reservation=reservation); request_payload = _canonical_bytes(request); request_sha256 = hashlib.sha256(request_payload).hexdigest()
    started_at = now_provider(); _require_transaction_window(preflight, at_utc=started_at)
    start = _TransactionStart(ledger_root_path_sha256=ledger.root_sha256, transaction_key_sha256=preflight.reviewer_request_nonce_sha256, requestability_preflight_sha256=preflight.sha256, reviewer_request_nonce_sha256=preflight.reviewer_request_nonce_sha256, predicted_commit_sha=preflight.predicted_commit_sha, broker_request_sha256=request_sha256, broker_policy_sha256=preflight.broker_policy_sha256, broker_executable_path_sha256=preflight.broker_executable_path_sha256, broker_executable_sha256=preflight.broker_executable_sha256, repository=preflight.repository, pull_request_number=preflight.pull_request_number, reviewer_login=preflight.reviewer_login, reviewer_user_id=preflight.reviewer_user_id, started_at_utc=started_at)
    start_path, start_payload = ledger.begin(start)
    broker_result, broker_response = _invoke_broker(broker_path=broker_path, protocol=capability.credential_protocol, request_payload=request_payload, request_sha256=request_sha256, preflight=preflight, subprocess_runner=subprocess_runner)
    mutated_at = now_provider()
    readback = _validate_readback(readback_reader(preflight=preflight, reservation=reservation, target=target, requirements=requirements, expected_updated_at_utc=broker_response["updated_at_utc"]), expected_updated_at_utc=broker_response["updated_at_utc"])
    verified_at = now_provider()
    receipt = PilotExactTaskPrReviewerRequestTransaction(ledger_root_path_sha256=ledger.root_sha256, transaction_key_sha256=preflight.reviewer_request_nonce_sha256, transaction_start_sha256=start.sha256, requestability_preflight_sha256=preflight.sha256, reviewer_request_credential_capability_sha256=preflight.reviewer_request_credential_capability_sha256, reviewer_identity_state_observation_sha256=preflight.reviewer_identity_state_observation_sha256, reviewer_request_reservation_sha256=preflight.reviewer_request_reservation_sha256, reviewer_target_attestation_sha256=preflight.reviewer_target_attestation_sha256, reviewer_handoff_requirements_sha256=preflight.reviewer_handoff_requirements_sha256, ready_transaction_sha256=preflight.ready_transaction_sha256, predicted_commit_sha=preflight.predicted_commit_sha, reviewer_handoff_plan_sha256=preflight.reviewer_handoff_plan_sha256, reviewer_target_policy_sha256=preflight.reviewer_target_policy_sha256, reviewer_target_policy_epoch=preflight.reviewer_target_policy_epoch, reviewer_request_nonce_sha256=preflight.reviewer_request_nonce_sha256, repository=preflight.repository, pull_request_number=preflight.pull_request_number, pull_request_node_id_sha256=preflight.pull_request_node_id_sha256, base_branch=preflight.base_branch, head_branch=preflight.head_branch, reviewer_login=preflight.reviewer_login, reviewer_user_id=preflight.reviewer_user_id, reviewer_node_id_sha256=preflight.reviewer_node_id_sha256, broker_policy_sha256=preflight.broker_policy_sha256, broker_executable_path_sha256=preflight.broker_executable_path_sha256, broker_executable_sha256=preflight.broker_executable_sha256, broker_request_sha256=request_sha256, broker_stdout_sha256=broker_result.stdout.sha256, broker_stderr_sha256=broker_result.stderr.sha256, broker_total_output_bytes=broker_result.total_output_bytes, prewrite_pr_response_body_sha256=fresh["pr_response_body_sha256"], prewrite_pr_response_etag_sha256=fresh["pr_response_etag_sha256"], post_request_response_body_sha256=readback["response_body_sha256"], post_request_response_etag_sha256=readback["response_etag_sha256"], preflight_checked_at_utc=preflight.checked_at_utc, prewrite_updated_at_utc=fresh["observed_updated_at_utc"], requested_updated_at_utc=broker_response["updated_at_utc"], started_at_utc=started_at, mutated_at_utc=mutated_at, verified_at_utc=verified_at)
    final_path, final_payload = ledger.finish(receipt); _mark_authenticated(receipt, preflight, start_path=start_path, start_payload=start_payload, final_path=final_path, final_payload=final_payload)
    if receipt.transaction_authenticated is not True: raise PilotExactTaskPrReviewerRequestTransactionError("reviewer transaction lost durable live provenance")
    return receipt

def execute_pilot_exact_task_pr_reviewer_request(reviewer_requestability_preflight: PilotExactTaskPrReviewerRequestabilityPreflight) -> PilotExactTaskPrReviewerRequestTransaction:
    return _execute_verified_pilot_exact_task_pr_reviewer_request(reviewer_requestability_preflight=reviewer_requestability_preflight, ledger=_TransactionLedger(_canonical_ledger_root()), pr_state_reader=state_boundary._read_exact_ready_pr_state, subprocess_runner=run_bounded_subprocess, readback_reader=_read_post_request_pr, now_provider=_now_utc_seconds, broker_host_control_required=True)

__all__ = ["PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_TRANSACTION_SCHEMA", "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_TRANSACTION_AUTHORITY", "PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_TRANSACTION_LEDGER_SCOPE", "PilotExactTaskPrReviewerRequestTransactionError", "PilotExactTaskPrReviewerRequestTransaction", "execute_pilot_exact_task_pr_reviewer_request"]
