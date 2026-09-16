"""ADR-DC-080 one-shot exact first staging Deployment Status transaction.

Consumes one live ADR-DC-079 first-status authorization before any GitHub write,
revalidates the exact clear first-status lane, durably consumes a separate
transaction slot, creates exactly one GitHub Deployment Status, and then proves
the exact created status through the existing ADR-DC-078 read-only observer.

No Deployment mutation, release/tag write, merge, production activation, or
second status transition is performed or authorized here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
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
from ._improvement_pilot_start_consumption_impl import _path_sha256, _safe_ledger_root
from .durable_publication import DurablePublicationError, create_once_file
from . import improvement_pilot_exact_task_remote_publication_transaction as publication_tx_boundary
from . import improvement_pilot_exact_task_staging_deployment_status_authorization as auth_boundary
from . import improvement_pilot_exact_task_staging_deployment_status_state_observation as state_boundary
from .improvement_pilot_exact_task_remote_publication_transaction import (
    PilotExactTaskGitHubPublisherCredential,
)
from .improvement_pilot_exact_task_staging_deployment_status_authorization import (
    PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_AUTHORIZATION_AUTHORITY,
    PilotExactTaskStagingDeploymentStatusAuthorizationReceipt,
)
from .improvement_pilot_exact_task_staging_deployment_status_plan import (
    PilotExactTaskStagingDeploymentStatusPlanReceipt,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_TRANSACTION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-staging-deployment-status-transaction-receipt/v1"
)
PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_TRANSACTION_AUTHORITY = (
    "host-executed-one-dc-l16-exact-first-staging-deployment-status-only"
)
PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_TRANSACTION_SCOPE = (
    "one-shot-exact-first-staging-deployment-status-transaction-v1"
)
PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_TRANSACTION_LEDGER_SCOPE = (
    "canonical-host-local-v1"
)

_GITHUB_API_ROOT = "https://api.github.com"
_MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
_MAX_API_RESPONSE_BYTES = 4 * 1024 * 1024
_TIMEOUT_SECONDS = 30.0
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/rsi-pilot-exact-task-staging-deployment-status-transaction-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-staging-deployment-status-transaction-ledger-v1"
)


class PilotExactTaskStagingDeploymentStatusTransactionError(ValueError):
    """Exact first Deployment Status transaction is stale/replayed/ambiguous."""


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskStagingDeploymentStatusTransactionError(
            "Deployment Status transaction evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskStagingDeploymentStatusTransactionError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskStagingDeploymentStatusTransactionError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskStagingDeploymentStatusTransactionError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskStagingDeploymentStatusTransactionError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_bound(path: Path) -> bytes | None:
    candidate = Path(path)
    if not candidate.is_absolute() or _has_linkish_component(candidate):
        return None
    try:
        payload = candidate.read_bytes()
    except OSError:
        return None
    return payload if payload and len(payload) <= _MAX_ARTIFACT_BYTES else None


def _require_live_authorization(value: Any):
    if type(value) is not PilotExactTaskStagingDeploymentStatusAuthorizationReceipt:
        raise PilotExactTaskStagingDeploymentStatusTransactionError(
            "exact live ADR-DC-079 Deployment Status authorization is required"
        )
    try:
        replayed = PilotExactTaskStagingDeploymentStatusAuthorizationReceipt.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskStagingDeploymentStatusTransactionError(
            "ADR-DC-079 authorization replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskStagingDeploymentStatusTransactionError("ADR-DC-079 authorization identity mismatch")
    required_true = (
        "host_status_guard_committed", "deployment_status_state_observation_authenticated",
        "staging_deployment_status_plan_authenticated", "status_lane_clear",
        "deployment_status_authorization_config_host_pinned", "dual_external_ed25519_authorized",
        "first_deployment_status_authorized", "deployment_status_mutation_authorized",
        "remote_write_authorized",
    )
    required_false = (
        "deployment_mutation_authorized", "deploy_authorized", "release_authorized",
        "tag_write_authorized", "release_mutation_authorized", "merge_authorized",
        "push_authorized", "pr_mutation_authorized", "review_submission_authorized",
        "review_thread_mutation_authorized", "production_activation_authorized",
        "product_pilot_started", "nonce_reusable",
    )
    if (
        value.authority != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_AUTHORIZATION_AUTHORITY
        or value.authorization_authenticated is not True
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in required_false)
        or value.required_remote_state_class != "clear"
        or value.deployment_environment != "staging"
        or value.deployment_task != "deploy"
        or value.deployment_status_state != "in_progress"
        or value.deployment_status_environment != "staging"
        or value.deployment_status_auto_inactive is not False
        or value.deployment_status_log_url is not None
        or value.deployment_status_environment_url is not None
    ):
        raise PilotExactTaskStagingDeploymentStatusTransactionError(
            "ADR-DC-080 requires one exact unconsumed ADR-DC-079 authority"
        )
    live = auth_boundary._get_live_staging_deployment_status_authorization_inputs(value)
    if live is None:
        raise PilotExactTaskStagingDeploymentStatusTransactionError("ADR-DC-079 live provenance is unavailable")
    observation = live.get("deployment_status_state_observation")
    plan = live.get("staging_deployment_status_plan")
    if (
        observation is None
        or getattr(observation, "observation_authenticated", False) is not True
        or getattr(observation, "sha256", None) != value.deployment_status_state_observation_sha256
        or type(plan) is not PilotExactTaskStagingDeploymentStatusPlanReceipt
        or plan.plan_authenticated is not True
        or plan.sha256 != value.staging_deployment_status_plan_sha256
        or plan.deployment_status_intent_sha256 != value.deployment_status_intent_sha256
    ):
        raise PilotExactTaskStagingDeploymentStatusTransactionError("ADR-DC-078/077 live provenance is unavailable")
    return value, observation, plan


def _require_valid_window(authorization, now_utc: str) -> None:
    now = _utc(now_utc, name="transaction time")
    requested = _utc(authorization.requested_at_utc, name="requested_at_utc")
    expires = _utc(authorization.expires_at_utc, name="expires_at_utc")
    if not requested <= now < expires:
        raise PilotExactTaskStagingDeploymentStatusTransactionError(
            "Deployment Status authorization is outside its validity window"
        )


def _clear_state(value: Any, *, authorization):
    if type(value) is not state_boundary._RemoteStagingDeploymentStatusState:
        raise PilotExactTaskStagingDeploymentStatusTransactionError(
            "status observer returned invalid clear-state evidence"
        )
    if (
        value.repository != authorization.repository
        or value.repository_id != authorization.repository_id
        or value.deployment_id != authorization.deployment_id
        or value.deployment_node_id_sha256 != authorization.deployment_node_id_sha256
        or value.remote_state_class != "clear"
        or value.deployment_status_lane_state != "absent"
        or value.deployment_status_id is not None
        or value.deployment_status_node_id_sha256 is not None
        or value.observed_status_state is not None
        or value.observed_status_environment is not None
        or value.observed_status_description_sha256 is not None
        or value.observed_status_log_url is not None
        or value.observed_status_environment_url is not None
        or value.sha256 != authorization.remote_deployment_status_state_sha256
    ):
        raise PilotExactTaskStagingDeploymentStatusTransactionError(
            "remote first-status lane is no longer the authorized clear state"
        )
    return value


def _exact_state(value: Any, *, authorization, deployment_status_id: int, deployment_status_node_id_sha256: str):
    if type(value) is not state_boundary._RemoteStagingDeploymentStatusState:
        raise PilotExactTaskStagingDeploymentStatusTransactionError(
            "status observer returned invalid exact-existing evidence"
        )
    if (
        value.repository != authorization.repository
        or value.repository_id != authorization.repository_id
        or value.deployment_id != authorization.deployment_id
        or value.deployment_node_id_sha256 != authorization.deployment_node_id_sha256
        or value.remote_state_class != "exact-existing"
        or value.deployment_status_lane_state != "exact"
        or value.deployment_status_id != deployment_status_id
        or value.deployment_status_node_id_sha256 != deployment_status_node_id_sha256
        or value.observed_status_state != authorization.deployment_status_state
        or value.observed_status_environment != authorization.deployment_status_environment
        or value.observed_status_description_sha256 != authorization.deployment_status_description_sha256
        or value.observed_status_log_url is not None
        or value.observed_status_environment_url is not None
    ):
        raise PilotExactTaskStagingDeploymentStatusTransactionError(
            "post-write Deployment Status differs from exact authorized intent"
        )
    return value


def _observe_clear_twice(*, authorization, plan, transport: Any) -> str:
    if transport is None or not callable(getattr(transport, "observe", None)):
        raise PilotExactTaskStagingDeploymentStatusTransactionError("fresh Deployment Status observer is required")
    if (
        getattr(transport, "credential_config_sha256", None) != authorization.publisher_credential_config_sha256
        or getattr(transport, "credential_path_sha256", None) != authorization.publisher_credential_path_sha256
    ):
        raise PilotExactTaskStagingDeploymentStatusTransactionError(
            "status observer credential identity differs from ADR-DC-079"
        )
    first = _clear_state(state_boundary._normalize_remote_state(transport.observe(plan), plan), authorization=authorization)
    second = _clear_state(state_boundary._normalize_remote_state(transport.observe(plan), plan), authorization=authorization)
    if first != second:
        raise PilotExactTaskStagingDeploymentStatusTransactionError(
            "remote first-status lane changed during clear-state revalidation"
        )
    return first.sha256


def _observe_exact_twice(*, authorization, plan, transport: Any, deployment_status_id: int, deployment_status_node_id_sha256: str) -> str:
    first = _exact_state(
        state_boundary._normalize_remote_state(transport.observe(plan), plan),
        authorization=authorization,
        deployment_status_id=deployment_status_id,
        deployment_status_node_id_sha256=deployment_status_node_id_sha256,
    )
    second = _exact_state(
        state_boundary._normalize_remote_state(transport.observe(plan), plan),
        authorization=authorization,
        deployment_status_id=deployment_status_id,
        deployment_status_node_id_sha256=deployment_status_node_id_sha256,
    )
    if first != second:
        raise PilotExactTaskStagingDeploymentStatusTransactionError(
            "remote Deployment Status changed during post-write verification"
        )
    return first.sha256


class _GitHubStagingDeploymentStatusWriter:
    """Credential-bound POST-only writer for exactly one first staging status."""

    def __init__(self, *, credential: PilotExactTaskGitHubPublisherCredential, credential_config_sha256: str, credential_path: Path) -> None:
        if type(credential) is not PilotExactTaskGitHubPublisherCredential:
            raise PilotExactTaskStagingDeploymentStatusTransactionError("exact publisher credential is required")
        self.credential = credential
        self.credential_config_sha256 = _hex64(credential_config_sha256, name="credential_config_sha256")
        self.credential_path = Path(credential_path)
        if not self.credential_path.is_absolute() or _has_linkish_component(self.credential_path):
            raise PilotExactTaskStagingDeploymentStatusTransactionError("publisher credential path is unsafe")
        self.credential_path_sha256 = _path_sha256(self.credential_path)
        self._opener = urllib.request.build_opener(state_boundary._NoRedirect())

    @staticmethod
    def _repo_root(authorization) -> str:
        owner, repo = authorization.repository.split("/", 1)
        return "/repos/{}/{}".format(
            urllib.parse.quote(owner, safe=""), urllib.parse.quote(repo, safe="")
        )

    def create(self, authorization) -> tuple[int, str]:
        if type(authorization) is not PilotExactTaskStagingDeploymentStatusAuthorizationReceipt:
            raise PilotExactTaskStagingDeploymentStatusTransactionError("exact ADR-DC-079 authorization is required")
        if self.credential.repository != authorization.repository or self.credential.repository_id != authorization.repository_id:
            raise PilotExactTaskStagingDeploymentStatusTransactionError(
                "publisher credential is not bound to exact status repository"
            )
        try:
            body_obj = json.loads(authorization.deployment_status_body)
        except json.JSONDecodeError as exc:
            raise PilotExactTaskStagingDeploymentStatusTransactionError(
                "frozen Deployment Status body is invalid JSON"
            ) from exc
        body = _canonical(body_obj).encode("utf-8")
        if body.decode("utf-8") != authorization.deployment_status_body:
            raise PilotExactTaskStagingDeploymentStatusTransactionError(
                "frozen Deployment Status body is not canonical"
            )
        url = _GITHUB_API_ROOT + f"{self._repo_root(authorization)}/deployments/{authorization.deployment_id}/statuses"
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.credential.token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "ModelRig-DevControl-ExactStagingDeploymentStatusTransaction/1",
            },
        )
        try:
            response = self._opener.open(request, timeout=_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            raise PilotExactTaskStagingDeploymentStatusTransactionError(
                f"GitHub Deployment Status POST failed with HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PilotExactTaskStagingDeploymentStatusTransactionError(
                "GitHub Deployment Status POST failed"
            ) from exc
        with response:
            if response.status != 201 or response.geturl() != url:
                raise PilotExactTaskStagingDeploymentStatusTransactionError(
                    "GitHub Deployment Status response identity/status is unexpected"
                )
            raw = response.read(_MAX_API_RESPONSE_BYTES + 1)
        if not raw or len(raw) > _MAX_API_RESPONSE_BYTES:
            raise PilotExactTaskStagingDeploymentStatusTransactionError(
                "GitHub Deployment Status response size is invalid"
            )
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PilotExactTaskStagingDeploymentStatusTransactionError(
                "GitHub Deployment Status response is invalid JSON"
            ) from exc
        status_id = result.get("id") if isinstance(result, Mapping) else None
        node_id = result.get("node_id") if isinstance(result, Mapping) else None
        if isinstance(status_id, bool) or not isinstance(status_id, int) or status_id < 1 or not isinstance(node_id, str) or not node_id:
            raise PilotExactTaskStagingDeploymentStatusTransactionError(
                "GitHub Deployment Status response identity is invalid"
            )
        return status_id, hashlib.sha256(node_id.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskStagingDeploymentStatusTransactionReceipt:
    status_transaction_ledger_root_path_sha256: str
    deployment_status_transaction_key_sha256: str
    deployment_status_transaction_lock_sha256: str
    deployment_status_authorization_sha256: str
    deployment_status_state_observation_sha256: str
    staging_deployment_status_plan_sha256: str
    post_staging_deployment_attestation_sha256: str
    completion_source_receipt_sha256: str
    deployment_authorization_sha256: str
    deployment_state_observation_sha256: str
    staging_deployment_plan_sha256: str
    deployment_intent_sha256: str
    execution_nonce_sha256: str
    deployment_status_intent_sha256: str
    remote_pre_write_status_state_sha256: str
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    repository: str
    repository_id: str
    deployment_environment: str
    merge_commit_sha: str
    deployment_identity: str
    deployment_ref: str
    deployment_task: str
    deployment_payload_sha256: str
    deployment_description_sha256: str
    deployment_id: int
    deployment_node_id_sha256: str
    completion_source: str
    source_action: str
    source_remote_write_performed: bool
    source_attested_at_utc: str
    deployment_status_state: str
    deployment_status_environment: str
    deployment_status_description: str
    deployment_status_description_sha256: str
    deployment_status_body: str
    deployment_status_body_sha256: str
    deployment_status_auto_inactive: bool
    deployment_status_log_url: str | None
    deployment_status_environment_url: str | None
    deployment_status_id: int
    deployment_status_node_id_sha256: str
    post_write_remote_status_state_sha256: str
    created_at_utc: str
    transaction_lock_committed: bool = True
    deployment_status_authorization_authenticated: bool = True
    pre_write_clear_revalidated: bool = True
    post_lock_clear_revalidated: bool = True
    first_deployment_status_created: bool = True
    exact_post_write_state_verified: bool = True
    deployment_status_mutation_authorized: bool = False
    deployment_mutation_authorized: bool = False
    deploy_authorized: bool = False
    remote_write_authorized: bool = False
    release_authorized: bool = False
    tag_write_authorized: bool = False
    release_mutation_authorized: bool = False
    merge_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    production_activation_authorized: bool = False
    product_pilot_started: bool = False
    nonce_reusable: bool = False
    transaction_scope: str = PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_TRANSACTION_SCOPE
    authority: str = PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_TRANSACTION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_TRANSACTION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_TRANSACTION_SCHEMA
            or self.authority != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_TRANSACTION_AUTHORITY
            or self.transaction_scope != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_TRANSACTION_SCOPE
        ):
            raise PilotExactTaskStagingDeploymentStatusTransactionError(
                "Deployment Status transaction identity is unsupported"
            )
        for name in (
            "status_transaction_ledger_root_path_sha256", "deployment_status_transaction_key_sha256",
            "deployment_status_transaction_lock_sha256", "deployment_status_authorization_sha256",
            "deployment_status_state_observation_sha256", "staging_deployment_status_plan_sha256",
            "post_staging_deployment_attestation_sha256", "completion_source_receipt_sha256",
            "deployment_authorization_sha256", "deployment_state_observation_sha256",
            "staging_deployment_plan_sha256", "deployment_intent_sha256", "execution_nonce_sha256",
            "deployment_status_intent_sha256", "remote_pre_write_status_state_sha256",
            "publisher_credential_config_sha256", "publisher_credential_path_sha256",
            "deployment_payload_sha256", "deployment_description_sha256", "deployment_node_id_sha256",
            "deployment_status_description_sha256", "deployment_status_body_sha256",
            "deployment_status_node_id_sha256", "post_write_remote_status_state_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        if self.deployment_status_transaction_key_sha256 != self.deployment_status_intent_sha256:
            raise PilotExactTaskStagingDeploymentStatusTransactionError(
                "transaction replay key must equal Deployment Status intent"
            )
        if (
            not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str) or _REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.deployment_environment != "staging" or self.deployment_task != "deploy"
            or self.deployment_identity != f"modelrig-staging-{self.merge_commit_sha}"
            or self.deployment_ref != f"modelrig-rsi-{self.merge_commit_sha}"
            or isinstance(self.deployment_id, bool) or not isinstance(self.deployment_id, int) or self.deployment_id < 1
            or isinstance(self.deployment_status_id, bool) or not isinstance(self.deployment_status_id, int) or self.deployment_status_id < 1
            or self.completion_source not in {"transaction", "recovery"}
            or self.source_action not in {"execute_exact_staging_deployment", "finalize_existing_state"}
            or not isinstance(self.source_remote_write_performed, bool)
            or self.deployment_status_state != "in_progress" or self.deployment_status_environment != "staging"
            or self.deployment_status_auto_inactive is not False
            or self.deployment_status_log_url is not None or self.deployment_status_environment_url is not None
        ):
            raise PilotExactTaskStagingDeploymentStatusTransactionError(
                "Deployment Status transaction projection is invalid"
            )
        if self.completion_source == "transaction":
            if self.source_action != "execute_exact_staging_deployment" or self.source_remote_write_performed is not True:
                raise PilotExactTaskStagingDeploymentStatusTransactionError("normal completion source is inconsistent")
        elif self.source_action != "finalize_existing_state" or self.source_remote_write_performed is not False:
            raise PilotExactTaskStagingDeploymentStatusTransactionError("recovered completion source is inconsistent")
        expected_description = (
            "ModelRig exact RSI staging verification in progress; "
            f"deployment={self.deployment_id}; sha={self.merge_commit_sha[:12]}"
        )
        if (
            self.deployment_status_description != expected_description
            or hashlib.sha256(self.deployment_status_description.encode("utf-8")).hexdigest() != self.deployment_status_description_sha256
            or hashlib.sha256(self.deployment_status_body.encode("utf-8")).hexdigest() != self.deployment_status_body_sha256
        ):
            raise PilotExactTaskStagingDeploymentStatusTransactionError(
                "deterministic Deployment Status payload is invalid"
            )
        source_time = _utc(self.source_attested_at_utc, name="source_attested_at_utc")
        created = _utc(self.created_at_utc, name="created_at_utc")
        if created < source_time:
            raise PilotExactTaskStagingDeploymentStatusTransactionError(
                "Deployment Status transaction predates source attestation"
            )
        required_true = (
            "transaction_lock_committed", "deployment_status_authorization_authenticated",
            "pre_write_clear_revalidated", "post_lock_clear_revalidated",
            "first_deployment_status_created", "exact_post_write_state_verified",
        )
        forced_false = (
            "deployment_status_mutation_authorized", "deployment_mutation_authorized",
            "deploy_authorized", "remote_write_authorized", "release_authorized",
            "tag_write_authorized", "release_mutation_authorized", "merge_authorized",
            "push_authorized", "pr_mutation_authorized", "review_submission_authorized",
            "review_thread_mutation_authorized", "production_activation_authorized",
            "product_pilot_started", "nonce_reusable",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskStagingDeploymentStatusTransactionError(
                "Deployment Status transaction evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskStagingDeploymentStatusTransactionError(
                "Deployment Status transaction grants forbidden residual authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def transaction_authenticated(self) -> bool:
        return _get_live_staging_deployment_status_transaction_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskStagingDeploymentStatusTransactionError(
                "Deployment Status transaction receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskStagingDeploymentStatusTransactionLedger:
    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path]:
        digest = _hex64(key, name="deployment_status_transaction_key_sha256")
        return self.root / f"{digest}.json", self.root / f".{digest}.lock"

    def acquire(self, *, authorization) -> bytes:
        key = authorization.deployment_status_intent_sha256
        final, lock = self._paths(key)
        if final.exists() or final.is_symlink() or lock.exists() or lock.is_symlink():
            raise PilotExactTaskStagingDeploymentStatusTransactionError(
                "Deployment Status transaction already consumed or needs recovery"
            )
        payload = _canonical({
            "schema": "kaliv-rsi-dc-l16-exact-task-staging-deployment-status-transaction-lock/v1",
            "ledger_scope": PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_TRANSACTION_LEDGER_SCOPE,
            "ledger_root_path_sha256": self.root_sha256,
            "deployment_status_transaction_key_sha256": key,
            "deployment_status_authorization_sha256": authorization.sha256,
            "deployment_status_state_observation_sha256": authorization.deployment_status_state_observation_sha256,
            "staging_deployment_status_plan_sha256": authorization.staging_deployment_status_plan_sha256,
            "deployment_status_intent_sha256": authorization.deployment_status_intent_sha256,
            "remote_pre_write_status_state_sha256": authorization.remote_deployment_status_state_sha256,
            "repository": authorization.repository,
            "repository_id": authorization.repository_id,
            "deployment_id": authorization.deployment_id,
            "deployment_node_id_sha256": authorization.deployment_node_id_sha256,
            "deployment_status_state": authorization.deployment_status_state,
            "deployment_status_environment": authorization.deployment_status_environment,
            "deployment_status_description_sha256": authorization.deployment_status_description_sha256,
            "deployment_status_body_sha256": authorization.deployment_status_body_sha256,
        }).encode("utf-8")
        try:
            create_once_file(lock, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskStagingDeploymentStatusTransactionError(
                "Deployment Status transaction lock could not be durably committed"
            ) from exc
        return payload

    def commit(self, *, receipt, lock_payload: bytes, authorization, plan):
        final, lock = self._paths(receipt.deployment_status_transaction_key_sha256)
        try:
            observed_lock = lock.read_bytes()
        except OSError as exc:
            raise PilotExactTaskStagingDeploymentStatusTransactionError(
                "Deployment Status transaction lock is unavailable"
            ) from exc
        if final.exists() or final.is_symlink() or observed_lock != lock_payload:
            raise PilotExactTaskStagingDeploymentStatusTransactionError(
                "durable Deployment Status transaction state changed"
            )
        final_payload = receipt.canonical_json().encode("utf-8")
        try:
            create_once_file(final, final_payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskStagingDeploymentStatusTransactionError(
                "Deployment Status transaction receipt could not be published"
            ) from exc
        parsed = PilotExactTaskStagingDeploymentStatusTransactionReceipt.from_mapping(
            json.loads(final_payload.decode("utf-8"))
        )
        _mark_staging_deployment_status_transaction_authenticated(
            parsed, authorization=authorization, plan=plan,
            final_path=final, final_payload=final_payload,
            lock_path=lock, lock_payload=lock_payload,
        )
        if parsed.transaction_authenticated is not True:
            raise PilotExactTaskStagingDeploymentStatusTransactionError(
                "Deployment Status transaction lost live provenance"
            )
        return parsed


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(receipt, *, authorization, plan, final_path, final_payload, lock_path, lock_payload) -> None:
        key = id(receipt)
        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)
        records[key] = (
            os.getpid(), receipt.sha256, weakref.ref(receipt, cleanup),
            weakref.ref(authorization), weakref.ref(plan),
            final_path, final_payload, lock_path, lock_payload,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, authorization_ref, plan_ref, final_path, final_payload, lock_path, lock_payload = entry
        authorization, plan = authorization_ref(), plan_ref()
        if (
            pid != os.getpid() or receipt_ref() is not receipt
            or authorization is None or plan is None or receipt.sha256 != digest
            or authorization.authorization_authenticated is not True
            or authorization.sha256 != receipt.deployment_status_authorization_sha256
            or plan.plan_authenticated is not True
            or plan.sha256 != receipt.staging_deployment_status_plan_sha256
            or _read_bound(final_path) != final_payload or _read_bound(lock_path) != lock_payload
        ):
            return None
        return MappingProxyType({
            "deployment_status_authorization": authorization,
            "staging_deployment_status_plan": plan,
        })

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_staging_deployment_status_transaction_authenticated,
    _get_live_staging_deployment_status_transaction_inputs,
) = _live_registry()


def _execute_verified_pilot_exact_task_staging_deployment_status(
    *, deployment_status_authorization, ledger, observer, writer, now_provider: Callable[[], str]
):
    authorization, _observation, plan = _require_live_authorization(deployment_status_authorization)
    if (
        getattr(writer, "credential_config_sha256", None) != authorization.publisher_credential_config_sha256
        or getattr(writer, "credential_path_sha256", None) != authorization.publisher_credential_path_sha256
        or not callable(getattr(writer, "create", None))
    ):
        raise PilotExactTaskStagingDeploymentStatusTransactionError(
            "status writer credential identity differs from ADR-DC-079"
        )
    _require_valid_window(authorization, now_provider())
    _observe_clear_twice(authorization=authorization, plan=plan, transport=observer)
    lock_payload = ledger.acquire(authorization=authorization)
    _require_valid_window(authorization, now_provider())
    _observe_clear_twice(authorization=authorization, plan=plan, transport=observer)
    deployment_status_id, deployment_status_node_id_sha256 = writer.create(authorization)
    if isinstance(deployment_status_id, bool) or not isinstance(deployment_status_id, int) or deployment_status_id < 1:
        raise PilotExactTaskStagingDeploymentStatusTransactionError(
            "status writer returned invalid Deployment Status id"
        )
    _hex64(deployment_status_node_id_sha256, name="deployment_status_node_id_sha256")
    post_write_remote_status_state_sha256 = _observe_exact_twice(
        authorization=authorization, plan=plan, transport=observer,
        deployment_status_id=deployment_status_id,
        deployment_status_node_id_sha256=deployment_status_node_id_sha256,
    )
    created_at = now_provider()
    _require_valid_window(authorization, created_at)
    receipt = PilotExactTaskStagingDeploymentStatusTransactionReceipt(
        status_transaction_ledger_root_path_sha256=ledger.root_sha256,
        deployment_status_transaction_key_sha256=authorization.deployment_status_intent_sha256,
        deployment_status_transaction_lock_sha256=hashlib.sha256(lock_payload).hexdigest(),
        deployment_status_authorization_sha256=authorization.sha256,
        deployment_status_state_observation_sha256=authorization.deployment_status_state_observation_sha256,
        staging_deployment_status_plan_sha256=authorization.staging_deployment_status_plan_sha256,
        post_staging_deployment_attestation_sha256=authorization.post_staging_deployment_attestation_sha256,
        completion_source_receipt_sha256=authorization.completion_source_receipt_sha256,
        deployment_authorization_sha256=authorization.deployment_authorization_sha256,
        deployment_state_observation_sha256=authorization.deployment_state_observation_sha256,
        staging_deployment_plan_sha256=authorization.staging_deployment_plan_sha256,
        deployment_intent_sha256=authorization.deployment_intent_sha256,
        execution_nonce_sha256=authorization.execution_nonce_sha256,
        deployment_status_intent_sha256=authorization.deployment_status_intent_sha256,
        remote_pre_write_status_state_sha256=authorization.remote_deployment_status_state_sha256,
        publisher_credential_config_sha256=authorization.publisher_credential_config_sha256,
        publisher_credential_path_sha256=authorization.publisher_credential_path_sha256,
        repository=authorization.repository,
        repository_id=authorization.repository_id,
        deployment_environment=authorization.deployment_environment,
        merge_commit_sha=authorization.merge_commit_sha,
        deployment_identity=authorization.deployment_identity,
        deployment_ref=authorization.deployment_ref,
        deployment_task=authorization.deployment_task,
        deployment_payload_sha256=authorization.deployment_payload_sha256,
        deployment_description_sha256=authorization.deployment_description_sha256,
        deployment_id=authorization.deployment_id,
        deployment_node_id_sha256=authorization.deployment_node_id_sha256,
        completion_source=authorization.completion_source,
        source_action=authorization.source_action,
        source_remote_write_performed=authorization.source_remote_write_performed,
        source_attested_at_utc=authorization.source_attested_at_utc,
        deployment_status_state=authorization.deployment_status_state,
        deployment_status_environment=authorization.deployment_status_environment,
        deployment_status_description=authorization.deployment_status_description,
        deployment_status_description_sha256=authorization.deployment_status_description_sha256,
        deployment_status_body=authorization.deployment_status_body,
        deployment_status_body_sha256=authorization.deployment_status_body_sha256,
        deployment_status_auto_inactive=False,
        deployment_status_log_url=None,
        deployment_status_environment_url=None,
        deployment_status_id=deployment_status_id,
        deployment_status_node_id_sha256=deployment_status_node_id_sha256,
        post_write_remote_status_state_sha256=post_write_remote_status_state_sha256,
        created_at_utc=created_at,
    )
    return ledger.commit(
        receipt=receipt, lock_payload=lock_payload, authorization=authorization, plan=plan
    )


def _canonical_ledger():
    try:
        _require_elevated_operator()
        if os.name == "posix":
            root = _require_host_controlled_ledger_root(_POSIX_LEDGER)
        elif os.name == "nt":
            root = _require_host_controlled_ledger_root(_WINDOWS_LEDGER)
        else:
            raise PilotExactTaskStagingDeploymentStatusTransactionError("platform is unsupported")
    except PhysicalHostStateError as exc:
        raise PilotExactTaskStagingDeploymentStatusTransactionError(
            "Deployment Status transaction ledger is not host-admin controlled"
        ) from exc
    return _PilotExactTaskStagingDeploymentStatusTransactionLedger(root)


def execute_pilot_exact_task_staging_deployment_status(
    deployment_status_authorization: PilotExactTaskStagingDeploymentStatusAuthorizationReceipt,
) -> PilotExactTaskStagingDeploymentStatusTransactionReceipt:
    """Consume one ADR-DC-079 authority and create exactly one first status."""
    credential, credential_digest, credential_path = publication_tx_boundary._canonical_credential()
    observer = state_boundary._GitHubStagingDeploymentStatusStateObserver(
        credential=credential, credential_config_sha256=credential_digest, credential_path=credential_path
    )
    writer = _GitHubStagingDeploymentStatusWriter(
        credential=credential, credential_config_sha256=credential_digest, credential_path=credential_path
    )
    return _execute_verified_pilot_exact_task_staging_deployment_status(
        deployment_status_authorization=deployment_status_authorization,
        ledger=_canonical_ledger(), observer=observer, writer=writer,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []
