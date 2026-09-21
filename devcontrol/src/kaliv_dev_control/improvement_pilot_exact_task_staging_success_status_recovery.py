"""ADR-DC-089 write-free recovery for interrupted staging success-status transactions.

Reconstructs one consumed ADR-DC-088 transaction from durable ADR-DC-087/088
evidence plus current GitHub state. Recovery never retries Deployment Status
creation. A consumed success lane that remains clear is manual/fail-closed.
Only the exact frozen ``success`` staging status can be finalized, under two
fresh detached Ed25519 approvals, into a separate create-once recovery ledger.

No Deployment Status write, Deployment mutation, release/tag write, merge, or
production activation is performed or authorized here.
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
from .asymmetric_authority import (
    AsymmetricAuthorityError,
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    asymmetric_authority_key_custody_policy_sha256,
)
from .durable_publication import DurablePublicationError, create_once_file
from . import improvement_pilot_exact_task_remote_publication_transaction as publication_tx_boundary
from . import improvement_pilot_exact_task_staging_success_status_authorization as auth_boundary
from . import improvement_pilot_exact_task_staging_success_status_state_observation as state_boundary
from . import improvement_pilot_exact_task_staging_success_status_transaction as tx_boundary
from .improvement_pilot_exact_task_remote_publication_transaction import (
    PilotExactTaskGitHubPublisherCredential,
)
from .improvement_pilot_exact_task_staging_success_status_authorization import (
    PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_AUTHORIZATION_AUTHORITY,
    PilotExactTaskStagingSuccessStatusAuthorizationReceipt,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_RECOVERY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-staging-success-status-recovery-receipt/v1"
)
PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_RECOVERY_AUTHORITY = (
    "dual-reviewed-dc-l16-exact-staging-success-status-recovery-only"
)
PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_RECOVERY_SCOPE = (
    "exact-staging-success-status-write-free-recovery-finalization-only-v1"
)
PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_RECOVERY_PAYLOAD_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-staging-success-status-recovery-authorization-payload/v1"
)
PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_RECOVERY_LEDGER_SCOPE = "canonical-host-local-v1"
_RECOVERY_POLICY_DOMAIN = b"kaliv-rsi-dc-l16-exact-task-staging-success-status-recovery-policy/v1\x00"
_MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
_MAX_API_RESPONSE_BYTES = 4 * 1024 * 1024
_STATUS_PAGE_SIZE = 100
_MAX_STATUS_PAGES = 10
_TIMEOUT_SECONDS = 30.0
_MAX_AUTH_SECONDS = 10 * 60
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_GITHUB_API_ROOT = "https://api.github.com"

_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/rsi-pilot-exact-task-staging-success-status-recovery-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-staging-success-status-recovery-ledger-v1"
)

PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_RECOVERY_POLICY = (
    "Recover only one previously consumed ADR-DC-088 staging success-status transaction intent.",
    "Never retry or recreate the GitHub Deployment Status after the ADR-DC-088 lock exists.",
    "A consumed success-status lane that remains remotely clear requires manual intervention.",
    "Permit only write-free finalization when the exact frozen staging success status exists.",
    "Require durable ADR-DC-087 authorization and ADR-DC-088 transaction lock to agree.",
    "Require two independent detached Ed25519 signatures over exact recovery state.",
    "Durably consume recovery authority before finalization.",
    "Reobserve exact remote state after the recovery lock before publishing completion.",
    "Never backfill or replace the ADR-DC-088 transaction receipt.",
    "Never authorize another Deployment Status, Deployment mutation, production activation, or nonce reuse.",
)


class PilotExactTaskStagingSuccessStatusRecoveryError(ValueError):
    """Interrupted staging success-status state is ambiguous or unsafe."""


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "success-status recovery evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskStagingSuccessStatusRecoveryError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskStagingSuccessStatusRecoveryError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskStagingSuccessStatusRecoveryError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_bytes(path: Path) -> bytes | None:
    candidate = Path(path)
    if not candidate.is_absolute() or _has_linkish_component(candidate):
        return None
    try:
        payload = candidate.read_bytes()
    except OSError:
        return None
    return payload if payload and len(payload) <= _MAX_ARTIFACT_BYTES else None


def _read_canonical_object(path: Path, *, name: str) -> tuple[dict[str, Any], bytes]:
    payload = _read_bytes(path)
    if payload is None:
        raise PilotExactTaskStagingSuccessStatusRecoveryError(f"{name} is unavailable")
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskStagingSuccessStatusRecoveryError(f"{name} is invalid JSON") from exc
    if not isinstance(raw, dict) or _canonical(raw).encode("utf-8") != payload:
        raise PilotExactTaskStagingSuccessStatusRecoveryError(f"{name} is not canonical JSON")
    return raw, payload


def pilot_exact_task_staging_success_status_recovery_policy_sha256() -> str:
    payload = json.dumps(
        list(PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_RECOVERY_POLICY),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(_RECOVERY_POLICY_DOMAIN + payload).hexdigest()


@dataclass(frozen=True, slots=True)
class _SuccessStatusRecoveryRemoteState:
    repository: str
    repository_id: str
    deployment_id: int
    deployment_node_id_sha256: str
    current_deployment_status_id: int
    current_deployment_status_node_id_sha256: str
    success_deployment_status_id: int | None
    success_deployment_status_node_id_sha256: str | None
    observed_success_status_state: str | None
    observed_success_status_environment: str | None
    observed_success_status_description_sha256: str | None
    success_status_created_at_utc: str | None
    success_status_updated_at_utc: str | None
    remote_state_class: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
            or isinstance(self.deployment_id, bool)
            or not isinstance(self.deployment_id, int)
            or self.deployment_id < 1
            or isinstance(self.current_deployment_status_id, bool)
            or not isinstance(self.current_deployment_status_id, int)
            or self.current_deployment_status_id < 1
            or self.remote_state_class not in {"clear", "exact_existing"}
        ):
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "remote success-status recovery identity is invalid"
            )
        _hex64(self.deployment_node_id_sha256, name="deployment_node_id_sha256")
        _hex64(
            self.current_deployment_status_node_id_sha256,
            name="current_deployment_status_node_id_sha256",
        )
        if self.remote_state_class == "clear":
            if any(
                value is not None
                for value in (
                    self.success_deployment_status_id,
                    self.success_deployment_status_node_id_sha256,
                    self.observed_success_status_state,
                    self.observed_success_status_environment,
                    self.observed_success_status_description_sha256,
                    self.success_status_created_at_utc,
                    self.success_status_updated_at_utc,
                )
            ):
                raise PilotExactTaskStagingSuccessStatusRecoveryError(
                    "clear success-status recovery state is malformed"
                )
            return
        if (
            isinstance(self.success_deployment_status_id, bool)
            or not isinstance(self.success_deployment_status_id, int)
            or self.success_deployment_status_id < 1
            or self.success_deployment_status_id == self.current_deployment_status_id
            or self.success_deployment_status_node_id_sha256 is None
            or self.observed_success_status_state != "success"
            or self.observed_success_status_environment != "staging"
            or self.observed_success_status_description_sha256 is None
            or self.success_status_created_at_utc is None
            or self.success_status_updated_at_utc is None
        ):
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "exact-existing success-status recovery state is malformed"
            )
        _hex64(
            self.success_deployment_status_node_id_sha256,
            name="success_deployment_status_node_id_sha256",
        )
        _hex64(
            self.observed_success_status_description_sha256,
            name="observed_success_status_description_sha256",
        )
        created = _utc(self.success_status_created_at_utc, name="success_status_created_at_utc")
        updated = _utc(self.success_status_updated_at_utc, name="success_status_updated_at_utc")
        if updated < created:
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "success Deployment Status update predates creation"
            )

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict()).encode("utf-8")).hexdigest()


class _GitHubStagingSuccessStatusRecoveryTransport:
    """Credential-bound GET-only observer for interrupted ADR-DC-088 state."""

    def __init__(
        self,
        *,
        credential: PilotExactTaskGitHubPublisherCredential,
        credential_config_sha256: str,
        credential_path: Path,
    ) -> None:
        if type(credential) is not PilotExactTaskGitHubPublisherCredential:
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "exact publisher credential is required"
            )
        self.credential = credential
        self.credential_config_sha256 = _hex64(
            credential_config_sha256, name="credential_config_sha256"
        )
        self.credential_path = Path(credential_path)
        if not self.credential_path.is_absolute() or _has_linkish_component(self.credential_path):
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "publisher credential path is unsafe"
            )
        self.credential_path_sha256 = _path_sha256(self.credential_path)
        self._opener = urllib.request.build_opener(state_boundary._NoRedirect())

    @staticmethod
    def _repo_root(authorization) -> str:
        owner, repo = authorization.repository.split("/", 1)
        return "/repos/{}/{}".format(
            urllib.parse.quote(owner, safe=""), urllib.parse.quote(repo, safe="")
        )

    def _api_json(self, authorization, path: str) -> Any:
        root = self._repo_root(authorization)
        if not isinstance(path, str) or not (path == root or path.startswith(root + "/")) or ".." in path:
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "success-status recovery GET is outside exact GitHub scope"
            )
        url = _GITHUB_API_ROOT + path
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.credential.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "ModelRig-DevControl-ExactStagingSuccessStatusRecovery/1",
            },
        )
        try:
            response = self._opener.open(request, timeout=_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                f"GitHub success-status recovery GET failed with HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "GitHub success-status recovery GET failed"
            ) from exc
        with response:
            if response.status != 200 or response.geturl() != url:
                raise PilotExactTaskStagingSuccessStatusRecoveryError(
                    "GitHub success-status recovery response identity/status is unexpected"
                )
            raw = response.read(_MAX_API_RESPONSE_BYTES + 1)
        if not raw or len(raw) > _MAX_API_RESPONSE_BYTES:
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "GitHub success-status recovery response size is invalid"
            )
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "GitHub success-status recovery response is invalid JSON"
            ) from exc

    @staticmethod
    def _node_hash(value: Any, *, name: str) -> str:
        if not isinstance(value, str) or not value:
            raise PilotExactTaskStagingSuccessStatusRecoveryError(f"{name} is invalid")
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _absent_url(value: Any, *, name: str) -> None:
        if value not in (None, ""):
            raise PilotExactTaskStagingSuccessStatusRecoveryError(f"{name} must remain absent")

    def observe(self, authorization) -> _SuccessStatusRecoveryRemoteState:
        if type(authorization) is not PilotExactTaskStagingSuccessStatusAuthorizationReceipt:
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "exact durable ADR-DC-087 authorization is required"
            )
        if (
            self.credential.repository != authorization.repository
            or self.credential.repository_id != authorization.repository_id
        ):
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "publisher credential is not bound to recovery repository"
            )
        root = self._repo_root(authorization)
        repository = self._api_json(authorization, root)
        if not isinstance(repository, Mapping) or str(repository.get("id")) != authorization.repository_id:
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "GitHub repository identity differs from durable authorization"
            )
        deployment = self._api_json(
            authorization, f"{root}/deployments/{authorization.deployment_id}"
        )
        if (
            not isinstance(deployment, Mapping)
            or deployment.get("id") != authorization.deployment_id
            or self._node_hash(deployment.get("node_id"), name="Deployment node identity")
            != authorization.deployment_node_id_sha256
            or deployment.get("sha") != authorization.merge_commit_sha
            or deployment.get("environment") != "staging"
            or deployment.get("transient_environment") is not False
            or deployment.get("production_environment") is not False
            or deployment.get("repository_url")
            != f"{_GITHUB_API_ROOT}/repos/{authorization.repository}"
        ):
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "parent GitHub Deployment differs from durable authorization"
            )
        statuses: list[Mapping[str, Any]] = []
        exhausted = False
        for page in range(1, _MAX_STATUS_PAGES + 1):
            query = urllib.parse.urlencode({"per_page": str(_STATUS_PAGE_SIZE), "page": str(page)})
            payload = self._api_json(
                authorization,
                f"{root}/deployments/{authorization.deployment_id}/statuses?{query}",
            )
            if not isinstance(payload, list):
                raise PilotExactTaskStagingSuccessStatusRecoveryError(
                    "GitHub success-status inventory is invalid"
                )
            for item in payload:
                if not isinstance(item, Mapping):
                    raise PilotExactTaskStagingSuccessStatusRecoveryError(
                        "GitHub success-status inventory contains invalid item"
                    )
                statuses.append(item)
                if len(statuses) > 2:
                    raise PilotExactTaskStagingSuccessStatusRecoveryError(
                        "unexpected status history occupies recovery lane"
                    )
            if len(payload) < _STATUS_PAGE_SIZE:
                exhausted = True
                break
        if not exhausted:
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "success-status inventory exceeded bounded recovery window"
            )
        current = [
            item for item in statuses
            if item.get("id") == authorization.current_deployment_status_id
        ]
        if len(current) != 1:
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "exact current in_progress status is missing or duplicated"
            )
        item = current[0]
        self._absent_url(item.get("log_url"), name="current status log_url")
        self._absent_url(item.get("environment_url"), name="current status environment_url")
        self._absent_url(item.get("target_url"), name="current status target_url")
        if (
            self._node_hash(item.get("node_id"), name="current status node identity")
            != authorization.current_deployment_status_node_id_sha256
            or item.get("state") != "in_progress"
            or item.get("environment") != "staging"
        ):
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "current in_progress status differs from durable source"
            )
        if len(statuses) == 1:
            return _SuccessStatusRecoveryRemoteState(
                repository=authorization.repository,
                repository_id=authorization.repository_id,
                deployment_id=authorization.deployment_id,
                deployment_node_id_sha256=authorization.deployment_node_id_sha256,
                current_deployment_status_id=authorization.current_deployment_status_id,
                current_deployment_status_node_id_sha256=authorization.current_deployment_status_node_id_sha256,
                success_deployment_status_id=None,
                success_deployment_status_node_id_sha256=None,
                observed_success_status_state=None,
                observed_success_status_environment=None,
                observed_success_status_description_sha256=None,
                success_status_created_at_utc=None,
                success_status_updated_at_utc=None,
                remote_state_class="clear",
            )
        other = [entry for entry in statuses if entry is not item]
        if len(other) != 1:
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "success-status recovery inventory is ambiguous"
            )
        success = other[0]
        self._absent_url(success.get("log_url"), name="success status log_url")
        self._absent_url(success.get("environment_url"), name="success status environment_url")
        self._absent_url(success.get("target_url"), name="success status target_url")
        status_id = success.get("id")
        description = success.get("description")
        created_at = success.get("created_at")
        updated_at = success.get("updated_at")
        if (
            isinstance(status_id, bool)
            or not isinstance(status_id, int)
            or status_id < 1
            or status_id == authorization.current_deployment_status_id
            or success.get("state") != authorization.success_deployment_status_state
            or success.get("environment") != authorization.success_deployment_status_environment
            or description != authorization.success_deployment_status_description
            or success.get("deployment_url")
            != f"{_GITHUB_API_ROOT}/repos/{authorization.repository}/deployments/{authorization.deployment_id}"
            or success.get("repository_url")
            != f"{_GITHUB_API_ROOT}/repos/{authorization.repository}"
        ):
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "existing success Deployment Status differs from durable authorization"
            )
        _utc(created_at, name="success_status_created_at_utc")
        _utc(updated_at, name="success_status_updated_at_utc")
        return _SuccessStatusRecoveryRemoteState(
            repository=authorization.repository,
            repository_id=authorization.repository_id,
            deployment_id=authorization.deployment_id,
            deployment_node_id_sha256=authorization.deployment_node_id_sha256,
            current_deployment_status_id=authorization.current_deployment_status_id,
            current_deployment_status_node_id_sha256=authorization.current_deployment_status_node_id_sha256,
            success_deployment_status_id=status_id,
            success_deployment_status_node_id_sha256=self._node_hash(
                success.get("node_id"), name="success status node identity"
            ),
            observed_success_status_state=authorization.success_deployment_status_state,
            observed_success_status_environment=authorization.success_deployment_status_environment,
            observed_success_status_description_sha256=hashlib.sha256(
                description.encode("utf-8")
            ).hexdigest(),
            success_status_created_at_utc=created_at,
            success_status_updated_at_utc=updated_at,
            remote_state_class="exact_existing",
        )


@dataclass(frozen=True, slots=True)
class PilotExactTaskStagingSuccessStatusRecoveryState:
    transaction_key_sha256: str
    success_status_authorization_ledger_root_path_sha256: str
    success_status_transaction_ledger_root_path_sha256: str
    success_status_authorization_sha256: str
    success_status_authorization_payload_sha256: str
    success_status_state_observation_sha256: str
    staging_success_status_plan_sha256: str
    staging_runtime_build_identity_sha256: str
    success_deployment_status_intent_sha256: str
    deployment_status_intent_sha256: str
    status_transaction_lock_sha256: str
    status_recovery_lock_sha256: str | None
    success_status_transaction_lock_sha256: str
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    durable_phase: str
    repository: str
    repository_id: str
    deployment_environment: str
    merge_commit_sha: str
    deployment_id: int
    deployment_node_id_sha256: str
    current_deployment_status_id: int
    current_deployment_status_node_id_sha256: str
    success_deployment_status_state: str
    success_deployment_status_environment: str
    success_deployment_status_description_sha256: str
    success_deployment_status_body_sha256: str
    success_deployment_status_id: int | None
    success_deployment_status_node_id_sha256: str | None
    remote_success_status_state_sha256: str
    remote_state_class: str
    action_required: str
    manual_intervention_required: bool
    remote_write_required: bool
    observed_at_utc: str

    def __post_init__(self) -> None:
        for name in (
            "transaction_key_sha256",
            "success_status_authorization_ledger_root_path_sha256",
            "success_status_transaction_ledger_root_path_sha256",
            "success_status_authorization_sha256",
            "success_status_authorization_payload_sha256",
            "success_status_state_observation_sha256",
            "staging_success_status_plan_sha256",
            "staging_runtime_build_identity_sha256",
            "success_deployment_status_intent_sha256",
            "deployment_status_intent_sha256",
            "status_transaction_lock_sha256",
            "success_status_transaction_lock_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
            "deployment_node_id_sha256",
            "current_deployment_status_node_id_sha256",
            "success_deployment_status_description_sha256",
            "success_deployment_status_body_sha256",
            "remote_success_status_state_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        if self.status_recovery_lock_sha256 is not None:
            _hex64(self.status_recovery_lock_sha256, name="status_recovery_lock_sha256")
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        if self.success_deployment_status_node_id_sha256 is not None:
            _hex64(
                self.success_deployment_status_node_id_sha256,
                name="success_deployment_status_node_id_sha256",
            )
        if (
            self.transaction_key_sha256 != self.success_deployment_status_intent_sha256
            or self.durable_phase != "lock_only"
            or self.deployment_environment != "staging"
            or self.success_deployment_status_state != "success"
            or self.success_deployment_status_environment != "staging"
            or self.remote_state_class not in {"clear", "exact_existing"}
            or isinstance(self.deployment_id, bool)
            or not isinstance(self.deployment_id, int)
            or self.deployment_id < 1
            or isinstance(self.current_deployment_status_id, bool)
            or not isinstance(self.current_deployment_status_id, int)
            or self.current_deployment_status_id < 1
        ):
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "success-status recovery state identity/classification is invalid"
            )
        expected = {
            "clear": ("manual_intervention", True, False),
            "exact_existing": ("finalize_existing_state", False, False),
        }[self.remote_state_class]
        if (
            self.action_required,
            self.manual_intervention_required,
            self.remote_write_required,
        ) != expected:
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "success-status recovery action does not match remote state"
            )
        if self.remote_state_class == "clear":
            if (
                self.success_deployment_status_id is not None
                or self.success_deployment_status_node_id_sha256 is not None
            ):
                raise PilotExactTaskStagingSuccessStatusRecoveryError(
                    "clear success-status recovery state carries status identity"
                )
        elif (
            isinstance(self.success_deployment_status_id, bool)
            or not isinstance(self.success_deployment_status_id, int)
            or self.success_deployment_status_id < 1
            or self.success_deployment_status_id == self.current_deployment_status_id
            or self.success_deployment_status_node_id_sha256 is None
        ):
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "exact-existing success-status recovery state lacks status identity"
            )
        _utc(self.observed_at_utc, name="observed_at_utc")

    @property
    def fingerprint_sha256(self) -> str:
        values = self.to_dict()
        values.pop("observed_at_utc")
        return hashlib.sha256(_canonical(values).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def _load_durable_authorization(
    success_deployment_status_intent_sha256: str,
    authorization_ledger_root: Path,
) -> PilotExactTaskStagingSuccessStatusAuthorizationReceipt:
    key = _hex64(
        success_deployment_status_intent_sha256,
        name="success_deployment_status_intent_sha256",
    )
    ledger = auth_boundary._PilotExactTaskStagingSuccessStatusAuthorizationLedger(
        _safe_ledger_root(authorization_ledger_root)
    )
    final, lock = ledger._paths(key)
    raw, final_payload = _read_canonical_object(
        final, name="ADR-DC-087 final success-status authorization receipt"
    )
    try:
        authorization = PilotExactTaskStagingSuccessStatusAuthorizationReceipt.from_mapping(raw)
    except Exception as exc:
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "durable ADR-DC-087 authorization receipt is invalid"
        ) from exc
    if (
        authorization.success_deployment_status_intent_sha256 != key
        or authorization.success_status_key_sha256 != key
        or authorization.authority != PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_AUTHORIZATION_AUTHORITY
        or authorization.success_status_authorization_ledger_root_path_sha256 != ledger.root_sha256
        or authorization.canonical_json().encode("utf-8") != final_payload
    ):
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "durable ADR-DC-087 authorization binding mismatch"
        )
    lock_raw, _lock_payload = _read_canonical_object(
        lock, name="ADR-DC-087 durable success-status authorization lock"
    )
    required = {
        "schema": "kaliv-rsi-dc-l16-exact-task-staging-success-status-authorization-lock/v1",
        "ledger_scope": auth_boundary.PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_AUTHORIZATION_LEDGER_SCOPE,
        "ledger_root_path_sha256": ledger.root_sha256,
        "success_status_key_sha256": key,
        "success_status_state_observation_sha256": authorization.success_status_state_observation_sha256,
        "staging_success_status_plan_sha256": authorization.staging_success_status_plan_sha256,
        "success_deployment_status_intent_sha256": key,
        "remote_success_status_state_sha256": authorization.remote_success_status_state_sha256,
        "success_status_authorization_payload_sha256": authorization.success_status_authorization_payload_sha256,
        "success_status_authorization_config_sha256": authorization.success_status_authorization_config_sha256,
        "repository": authorization.repository,
        "repository_id": authorization.repository_id,
        "deployment_id": authorization.deployment_id,
        "deployment_node_id_sha256": authorization.deployment_node_id_sha256,
        "current_deployment_status_id": authorization.current_deployment_status_id,
        "success_deployment_status_state": authorization.success_deployment_status_state,
        "success_deployment_status_environment": authorization.success_deployment_status_environment,
        "success_deployment_status_description_sha256": authorization.success_deployment_status_description_sha256,
        "success_deployment_status_body_sha256": authorization.success_deployment_status_body_sha256,
    }
    if any(lock_raw.get(name) != value for name, value in required.items()):
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "ADR-DC-087 authorization lock differs from final authorization"
        )
    for name in ("operator_signature_sha256", "reviewer_signature_sha256"):
        _hex64(lock_raw.get(name), name=name)
    return authorization


def _transaction_evidence(
    authorization: PilotExactTaskStagingSuccessStatusAuthorizationReceipt,
    transaction_ledger_root: Path,
) -> tuple[bytes, str]:
    ledger = tx_boundary._PilotExactTaskStagingSuccessStatusTransactionLedger(
        _safe_ledger_root(transaction_ledger_root)
    )
    final, lock = ledger._paths(authorization.success_deployment_status_intent_sha256)
    if final.exists() or final.is_symlink():
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "ADR-DC-088 already has a final receipt; recovery is unnecessary"
        )
    lock_raw, lock_payload = _read_canonical_object(
        lock, name="ADR-DC-088 staging success-status transaction lock"
    )
    expected = {
        "schema": "kaliv-rsi-dc-l16-exact-task-staging-success-status-transaction-lock/v1",
        "ledger_scope": tx_boundary.PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_TRANSACTION_LEDGER_SCOPE,
        "ledger_root_path_sha256": ledger.root_sha256,
        "success_status_transaction_key_sha256": authorization.success_deployment_status_intent_sha256,
        "success_status_authorization_sha256": authorization.sha256,
        "success_status_state_observation_sha256": authorization.success_status_state_observation_sha256,
        "staging_success_status_plan_sha256": authorization.staging_success_status_plan_sha256,
        "success_deployment_status_intent_sha256": authorization.success_deployment_status_intent_sha256,
        "remote_pre_write_success_status_state_sha256": authorization.remote_success_status_state_sha256,
        "repository": authorization.repository,
        "repository_id": authorization.repository_id,
        "deployment_id": authorization.deployment_id,
        "deployment_node_id_sha256": authorization.deployment_node_id_sha256,
        "current_deployment_status_id": authorization.current_deployment_status_id,
        "current_deployment_status_node_id_sha256": authorization.current_deployment_status_node_id_sha256,
        "success_deployment_status_state": authorization.success_deployment_status_state,
        "success_deployment_status_environment": authorization.success_deployment_status_environment,
        "success_deployment_status_description_sha256": authorization.success_deployment_status_description_sha256,
        "success_deployment_status_body_sha256": authorization.success_deployment_status_body_sha256,
    }
    if any(lock_raw.get(name) != value for name, value in expected.items()):
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "ADR-DC-088 transaction lock differs from durable ADR-DC-087 authorization"
        )
    return lock_payload, ledger.root_sha256


def _double_observe(
    transport: Any,
    authorization: PilotExactTaskStagingSuccessStatusAuthorizationReceipt,
) -> _SuccessStatusRecoveryRemoteState:
    if transport is None or not callable(getattr(transport, "observe", None)):
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "exact staging success-status recovery observer is required"
        )
    if (
        getattr(transport, "credential_config_sha256", None)
        != authorization.publisher_credential_config_sha256
        or getattr(transport, "credential_path_sha256", None)
        != authorization.publisher_credential_path_sha256
    ):
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "success-status recovery credential identity differs from ADR-DC-087"
        )
    first = transport.observe(authorization)
    second = transport.observe(authorization)
    if (
        type(first) is not _SuccessStatusRecoveryRemoteState
        or type(second) is not _SuccessStatusRecoveryRemoteState
        or first != second
    ):
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "remote staging success-status recovery state changed between observations"
        )
    if (
        first.repository != authorization.repository
        or first.repository_id != authorization.repository_id
        or first.deployment_id != authorization.deployment_id
        or first.deployment_node_id_sha256 != authorization.deployment_node_id_sha256
        or first.current_deployment_status_id != authorization.current_deployment_status_id
        or first.current_deployment_status_node_id_sha256
        != authorization.current_deployment_status_node_id_sha256
    ):
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "remote success-status recovery identity differs from authorization"
        )
    if first.remote_state_class == "exact_existing" and (
        first.observed_success_status_state != authorization.success_deployment_status_state
        or first.observed_success_status_environment
        != authorization.success_deployment_status_environment
        or first.observed_success_status_description_sha256
        != authorization.success_deployment_status_description_sha256
    ):
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "exact-existing success Deployment Status differs from authorization"
        )
    return first


def _observe_verified_recovery_state(
    *,
    success_deployment_status_intent_sha256: str,
    transaction_ledger_root: Path,
    success_status_authorization_ledger_root: Path,
    transport: Any,
    now_provider: Callable[[], str],
) -> tuple[
    PilotExactTaskStagingSuccessStatusRecoveryState,
    PilotExactTaskStagingSuccessStatusAuthorizationReceipt,
]:
    authorization = _load_durable_authorization(
        success_deployment_status_intent_sha256,
        success_status_authorization_ledger_root,
    )
    lock_payload, transaction_root_sha256 = _transaction_evidence(
        authorization, transaction_ledger_root
    )
    remote = _double_observe(transport, authorization)
    action = "finalize_existing_state" if remote.remote_state_class == "exact_existing" else "manual_intervention"
    observed_at = now_provider()
    _utc(observed_at, name="observed_at_utc")
    return (
        PilotExactTaskStagingSuccessStatusRecoveryState(
            transaction_key_sha256=authorization.success_deployment_status_intent_sha256,
            success_status_authorization_ledger_root_path_sha256=authorization.success_status_authorization_ledger_root_path_sha256,
            success_status_transaction_ledger_root_path_sha256=transaction_root_sha256,
            success_status_authorization_sha256=authorization.sha256,
            success_status_authorization_payload_sha256=authorization.success_status_authorization_payload_sha256,
            success_status_state_observation_sha256=authorization.success_status_state_observation_sha256,
            staging_success_status_plan_sha256=authorization.staging_success_status_plan_sha256,
            staging_runtime_build_identity_sha256=authorization.staging_runtime_build_identity_sha256,
            success_deployment_status_intent_sha256=authorization.success_deployment_status_intent_sha256,
            deployment_status_intent_sha256=authorization.deployment_status_intent_sha256,
            status_transaction_lock_sha256=authorization.status_transaction_lock_sha256,
            status_recovery_lock_sha256=authorization.status_recovery_lock_sha256,
            success_status_transaction_lock_sha256=hashlib.sha256(lock_payload).hexdigest(),
            publisher_credential_config_sha256=authorization.publisher_credential_config_sha256,
            publisher_credential_path_sha256=authorization.publisher_credential_path_sha256,
            durable_phase="lock_only",
            repository=authorization.repository,
            repository_id=authorization.repository_id,
            deployment_environment=authorization.deployment_environment,
            merge_commit_sha=authorization.merge_commit_sha,
            deployment_id=authorization.deployment_id,
            deployment_node_id_sha256=authorization.deployment_node_id_sha256,
            current_deployment_status_id=authorization.current_deployment_status_id,
            current_deployment_status_node_id_sha256=authorization.current_deployment_status_node_id_sha256,
            success_deployment_status_state=authorization.success_deployment_status_state,
            success_deployment_status_environment=authorization.success_deployment_status_environment,
            success_deployment_status_description_sha256=authorization.success_deployment_status_description_sha256,
            success_deployment_status_body_sha256=authorization.success_deployment_status_body_sha256,
            success_deployment_status_id=remote.success_deployment_status_id,
            success_deployment_status_node_id_sha256=remote.success_deployment_status_node_id_sha256,
            remote_success_status_state_sha256=remote.sha256,
            remote_state_class=remote.remote_state_class,
            action_required=action,
            manual_intervention_required=(action == "manual_intervention"),
            remote_write_required=False,
            observed_at_utc=observed_at,
        ),
        authorization,
    )


def _build_recovery_payload(
    *,
    state: PilotExactTaskStagingSuccessStatusRecoveryState,
    requested_at_utc: str,
    expires_at_utc: str,
    operator_actor_id: str,
    operator_system_id: str,
    operator_key_id: str,
    reviewer_actor_id: str,
    reviewer_system_id: str,
    reviewer_key_id: str,
) -> bytes:
    if type(state) is not PilotExactTaskStagingSuccessStatusRecoveryState:
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "exact staging success-status recovery state is required"
        )
    if (
        state.action_required != "finalize_existing_state"
        or state.manual_intervention_required
        or state.remote_write_required
        or state.remote_state_class != "exact_existing"
        or state.success_deployment_status_id is None
        or state.success_deployment_status_node_id_sha256 is None
    ):
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "staging success-status recovery state is not safely finalizable"
        )
    requested = _utc(requested_at_utc, name="requested_at_utc")
    expires = _utc(expires_at_utc, name="expires_at_utc")
    if not requested < expires or (expires - requested).total_seconds() > _MAX_AUTH_SECONDS:
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "staging success-status recovery authorization window is invalid"
        )
    for name, identity in (
        ("operator_actor_id", operator_actor_id),
        ("operator_system_id", operator_system_id),
        ("operator_key_id", operator_key_id),
        ("reviewer_actor_id", reviewer_actor_id),
        ("reviewer_system_id", reviewer_system_id),
        ("reviewer_key_id", reviewer_key_id),
    ):
        pattern = _ACTOR if name.endswith("actor_id") else _IDENTIFIER
        if not isinstance(identity, str) or pattern.fullmatch(identity) is None:
            raise PilotExactTaskStagingSuccessStatusRecoveryError(f"{name} is invalid")
    if (
        operator_actor_id == reviewer_actor_id
        or operator_system_id == reviewer_system_id
        or operator_key_id == reviewer_key_id
    ):
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "recovery operator and reviewer identities must be independent"
        )
    return _canonical(
        {
            "schema": PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_RECOVERY_PAYLOAD_SCHEMA,
            "recovery_policy_sha256": pilot_exact_task_staging_success_status_recovery_policy_sha256(),
            "custody_policy_sha256": asymmetric_authority_key_custody_policy_sha256(),
            "transaction_key_sha256": state.transaction_key_sha256,
            "recovery_state_fingerprint_sha256": state.fingerprint_sha256,
            "action": state.action_required,
            "durable_phase": state.durable_phase,
            "success_status_authorization_sha256": state.success_status_authorization_sha256,
            "success_deployment_status_intent_sha256": state.success_deployment_status_intent_sha256,
            "success_status_transaction_lock_sha256": state.success_status_transaction_lock_sha256,
            "remote_success_status_state_sha256": state.remote_success_status_state_sha256,
            "repository": state.repository,
            "repository_id": state.repository_id,
            "deployment_id": state.deployment_id,
            "deployment_node_id_sha256": state.deployment_node_id_sha256,
            "current_deployment_status_id": state.current_deployment_status_id,
            "current_deployment_status_node_id_sha256": state.current_deployment_status_node_id_sha256,
            "success_deployment_status_state": state.success_deployment_status_state,
            "success_deployment_status_environment": state.success_deployment_status_environment,
            "success_deployment_status_description_sha256": state.success_deployment_status_description_sha256,
            "success_deployment_status_body_sha256": state.success_deployment_status_body_sha256,
            "success_deployment_status_id": state.success_deployment_status_id,
            "success_deployment_status_node_id_sha256": state.success_deployment_status_node_id_sha256,
            "requested_at_utc": requested_at_utc,
            "expires_at_utc": expires_at_utc,
            "operator_actor_id": operator_actor_id,
            "operator_system_id": operator_system_id,
            "operator_key_id": operator_key_id,
            "reviewer_actor_id": reviewer_actor_id,
            "reviewer_system_id": reviewer_system_id,
            "reviewer_key_id": reviewer_key_id,
        }
    ).encode("utf-8")


def build_pilot_exact_task_staging_success_status_recovery_payload(
    state: PilotExactTaskStagingSuccessStatusRecoveryState,
    requested_at_utc: str,
    expires_at_utc: str,
    operator_actor_id: str,
    operator_system_id: str,
    operator_key_id: str,
    reviewer_actor_id: str,
    reviewer_system_id: str,
    reviewer_key_id: str,
) -> bytes:
    """Build exact bytes for two independent success-status recovery signers."""
    return _build_recovery_payload(
        state=state,
        requested_at_utc=requested_at_utc,
        expires_at_utc=expires_at_utc,
        operator_actor_id=operator_actor_id,
        operator_system_id=operator_system_id,
        operator_key_id=operator_key_id,
        reviewer_actor_id=reviewer_actor_id,
        reviewer_system_id=reviewer_system_id,
        reviewer_key_id=reviewer_key_id,
    )


_RECOVERY_PAYLOAD_FIELDS = {
    "schema",
    "recovery_policy_sha256",
    "custody_policy_sha256",
    "transaction_key_sha256",
    "recovery_state_fingerprint_sha256",
    "action",
    "durable_phase",
    "success_status_authorization_sha256",
    "success_deployment_status_intent_sha256",
    "success_status_transaction_lock_sha256",
    "remote_success_status_state_sha256",
    "repository",
    "repository_id",
    "deployment_id",
    "deployment_node_id_sha256",
    "current_deployment_status_id",
    "current_deployment_status_node_id_sha256",
    "success_deployment_status_state",
    "success_deployment_status_environment",
    "success_deployment_status_description_sha256",
    "success_deployment_status_body_sha256",
    "success_deployment_status_id",
    "success_deployment_status_node_id_sha256",
    "requested_at_utc",
    "expires_at_utc",
    "operator_actor_id",
    "operator_system_id",
    "operator_key_id",
    "reviewer_actor_id",
    "reviewer_system_id",
    "reviewer_key_id",
}


def _parse_recovery_payload(payload: bytes) -> dict[str, Any]:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_ARTIFACT_BYTES:
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "success-status recovery authorization payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "success-status recovery payload is invalid JSON"
        ) from exc
    if (
        not isinstance(raw, dict)
        or set(raw) != _RECOVERY_PAYLOAD_FIELDS
        or raw.get("schema") != PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_RECOVERY_PAYLOAD_SCHEMA
        or raw.get("recovery_policy_sha256") != pilot_exact_task_staging_success_status_recovery_policy_sha256()
        or raw.get("custody_policy_sha256") != asymmetric_authority_key_custody_policy_sha256()
        or raw.get("action") != "finalize_existing_state"
        or raw.get("durable_phase") != "lock_only"
        or _canonical(raw).encode("utf-8") != payload
    ):
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "success-status recovery payload fields/canonical form mismatch"
        )
    return raw


def _verify_dual_signatures(
    *,
    payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    at_utc: str,
) -> dict[str, Any]:
    claim = _parse_recovery_payload(payload)
    if type(operator_signature) is not DetachedEd25519AuthoritySignature or type(reviewer_signature) is not DetachedEd25519AuthoritySignature:
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "two detached Ed25519 success-status recovery signatures are required"
        )
    if (
        operator_signature.key_id == reviewer_signature.key_id
        or operator_signature.issuer_actor_id == reviewer_signature.issuer_actor_id
        or operator_signature.issuer_system_id == reviewer_signature.issuer_system_id
    ):
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "success-status recovery signatures must be independent"
        )
    now = _utc(at_utc, name="recovery_at_utc")
    requested = _utc(claim["requested_at_utc"], name="requested_at_utc")
    expires = _utc(claim["expires_at_utc"], name="expires_at_utc")
    if (
        not requested < expires
        or (expires - requested).total_seconds() > _MAX_AUTH_SECONDS
        or not requested <= now < expires
    ):
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "success-status recovery authorization is not currently valid"
        )
    payload_sha = hashlib.sha256(payload).hexdigest()
    for signature, actor_id, system_id, key_id in (
        (operator_signature, claim["operator_actor_id"], claim["operator_system_id"], claim["operator_key_id"]),
        (reviewer_signature, claim["reviewer_actor_id"], claim["reviewer_system_id"], claim["reviewer_key_id"]),
    ):
        if (
            signature.payload_sha256 != payload_sha
            or signature.issuer_actor_id != actor_id
            or signature.issuer_system_id != system_id
            or signature.key_id != key_id
        ):
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "success-status recovery signature binding mismatch"
            )
        signed = _utc(signature.signed_at_utc, name="signed_at_utc")
        if not requested <= signed < expires or signed > now:
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "success-status recovery signature timestamp is outside authorization window"
            )
        try:
            verifier.verify(payload=payload, signature=signature, at_utc=at_utc)
        except AsymmetricAuthorityError as exc:
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "success-status recovery Ed25519 verification failed"
            ) from exc
    return claim


def _claim_matches_state(claim: Mapping[str, Any], state: PilotExactTaskStagingSuccessStatusRecoveryState) -> bool:
    expected = {
        "transaction_key_sha256": state.transaction_key_sha256,
        "recovery_state_fingerprint_sha256": state.fingerprint_sha256,
        "action": state.action_required,
        "durable_phase": state.durable_phase,
        "success_status_authorization_sha256": state.success_status_authorization_sha256,
        "success_deployment_status_intent_sha256": state.success_deployment_status_intent_sha256,
        "success_status_transaction_lock_sha256": state.success_status_transaction_lock_sha256,
        "remote_success_status_state_sha256": state.remote_success_status_state_sha256,
        "repository": state.repository,
        "repository_id": state.repository_id,
        "deployment_id": state.deployment_id,
        "deployment_node_id_sha256": state.deployment_node_id_sha256,
        "current_deployment_status_id": state.current_deployment_status_id,
        "current_deployment_status_node_id_sha256": state.current_deployment_status_node_id_sha256,
        "success_deployment_status_state": state.success_deployment_status_state,
        "success_deployment_status_environment": state.success_deployment_status_environment,
        "success_deployment_status_description_sha256": state.success_deployment_status_description_sha256,
        "success_deployment_status_body_sha256": state.success_deployment_status_body_sha256,
        "success_deployment_status_id": state.success_deployment_status_id,
        "success_deployment_status_node_id_sha256": state.success_deployment_status_node_id_sha256,
    }
    return all(claim.get(name) == value for name, value in expected.items())


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskStagingSuccessStatusRecoveryReceipt:
    recovery_ledger_root_path_sha256: str
    recovery_key_sha256: str
    recovery_authorization_payload_sha256: str
    recovery_state_fingerprint_sha256: str
    recovery_policy_sha256: str
    success_status_authorization_sha256: str
    success_deployment_status_intent_sha256: str
    staging_success_status_plan_sha256: str
    staging_runtime_build_identity_sha256: str
    deployment_status_intent_sha256: str
    status_transaction_lock_sha256: str
    status_recovery_lock_sha256: str | None
    success_status_transaction_lock_sha256: str
    source_durable_phase: str
    source_remote_state_class: str
    final_remote_success_status_state_sha256: str
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    repository: str
    repository_id: str
    deployment_environment: str
    merge_commit_sha: str
    deployment_id: int
    deployment_node_id_sha256: str
    current_deployment_status_id: int
    current_deployment_status_node_id_sha256: str
    success_deployment_status_state: str
    success_deployment_status_environment: str
    success_deployment_status_description_sha256: str
    success_deployment_status_body_sha256: str
    success_deployment_status_id: int
    success_deployment_status_node_id_sha256: str
    action_performed: str
    remote_write_performed: bool
    operator_actor_id: str
    operator_system_id: str
    operator_key_id: str
    reviewer_actor_id: str
    reviewer_system_id: str
    reviewer_key_id: str
    recovered_at_utc: str
    durable_state_verified: bool = True
    remote_state_verified: bool = True
    dual_external_ed25519_authorized: bool = True
    recovery_authority_consumed: bool = True
    exact_success_deployment_status_finalized: bool = True
    recovery_completed: bool = True
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
    recovery_scope: str = PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_RECOVERY_SCOPE
    authority: str = PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_RECOVERY_AUTHORITY
    schema: str = PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_RECOVERY_SCHEMA

    def __post_init__(self) -> None:
        for name in (
            "recovery_ledger_root_path_sha256",
            "recovery_key_sha256",
            "recovery_authorization_payload_sha256",
            "recovery_state_fingerprint_sha256",
            "recovery_policy_sha256",
            "success_status_authorization_sha256",
            "success_deployment_status_intent_sha256",
            "staging_success_status_plan_sha256",
            "staging_runtime_build_identity_sha256",
            "deployment_status_intent_sha256",
            "status_transaction_lock_sha256",
            "success_status_transaction_lock_sha256",
            "final_remote_success_status_state_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
            "deployment_node_id_sha256",
            "current_deployment_status_node_id_sha256",
            "success_deployment_status_description_sha256",
            "success_deployment_status_body_sha256",
            "success_deployment_status_node_id_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        if self.status_recovery_lock_sha256 is not None:
            _hex64(self.status_recovery_lock_sha256, name="status_recovery_lock_sha256")
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        if (
            self.schema != PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_RECOVERY_SCHEMA
            or self.authority != PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_RECOVERY_AUTHORITY
            or self.recovery_scope != PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_RECOVERY_SCOPE
            or self.recovery_key_sha256 != self.success_deployment_status_intent_sha256
            or self.recovery_policy_sha256 != pilot_exact_task_staging_success_status_recovery_policy_sha256()
            or self.source_durable_phase != "lock_only"
            or self.source_remote_state_class != "exact_existing"
            or self.action_performed != "finalize_existing_state"
            or self.remote_write_performed is not False
            or self.deployment_environment != "staging"
            or self.success_deployment_status_state != "success"
            or self.success_deployment_status_environment != "staging"
            or isinstance(self.deployment_id, bool)
            or not isinstance(self.deployment_id, int)
            or self.deployment_id < 1
            or isinstance(self.current_deployment_status_id, bool)
            or not isinstance(self.current_deployment_status_id, int)
            or self.current_deployment_status_id < 1
            or isinstance(self.success_deployment_status_id, bool)
            or not isinstance(self.success_deployment_status_id, int)
            or self.success_deployment_status_id < 1
            or self.success_deployment_status_id == self.current_deployment_status_id
        ):
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "success-status recovery receipt identity/classification is invalid"
            )
        for name in ("operator_actor_id", "reviewer_actor_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
                raise PilotExactTaskStagingSuccessStatusRecoveryError(f"{name} is invalid")
        for name in (
            "operator_system_id", "operator_key_id", "reviewer_system_id", "reviewer_key_id"
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
                raise PilotExactTaskStagingSuccessStatusRecoveryError(f"{name} is invalid")
        if (
            self.operator_actor_id == self.reviewer_actor_id
            or self.operator_system_id == self.reviewer_system_id
            or self.operator_key_id == self.reviewer_key_id
        ):
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "recovery receipt signer identities are not independent"
            )
        _utc(self.recovered_at_utc, name="recovered_at_utc")
        required_true = (
            "durable_state_verified",
            "remote_state_verified",
            "dual_external_ed25519_authorized",
            "recovery_authority_consumed",
            "exact_success_deployment_status_finalized",
            "recovery_completed",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "success-status recovery completion evidence is incomplete"
            )
        forced_false = (
            "deployment_status_mutation_authorized",
            "deployment_mutation_authorized",
            "deploy_authorized",
            "remote_write_authorized",
            "release_authorized",
            "tag_write_authorized",
            "release_mutation_authorized",
            "merge_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "production_activation_authorized",
            "product_pilot_started",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "success-status recovery receipt retains forbidden authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def recovery_authenticated(self) -> bool:
        return _get_live_staging_success_status_recovery_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "success-status recovery receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskStagingSuccessStatusRecoveryLedger:
    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path]:
        digest = _hex64(key, name="recovery_key_sha256")
        return self.root / f"{digest}.json", self.root / f".{digest}.lock"

    def acquire(
        self,
        *,
        state: PilotExactTaskStagingSuccessStatusRecoveryState,
        authorization_payload: bytes,
        operator_signature: DetachedEd25519AuthoritySignature,
        reviewer_signature: DetachedEd25519AuthoritySignature,
    ) -> bytes:
        final, lock = self._paths(state.success_deployment_status_intent_sha256)
        if final.exists() or final.is_symlink() or lock.exists() or lock.is_symlink():
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "success-status recovery intent already consumed"
            )
        payload = _canonical(
            {
                "schema": "kaliv-rsi-dc-l16-exact-task-staging-success-status-recovery-lock/v1",
                "ledger_scope": PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_RECOVERY_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "recovery_key_sha256": state.success_deployment_status_intent_sha256,
                "recovery_state_fingerprint_sha256": state.fingerprint_sha256,
                "recovery_authorization_payload_sha256": hashlib.sha256(authorization_payload).hexdigest(),
                "success_status_authorization_sha256": state.success_status_authorization_sha256,
                "success_status_transaction_lock_sha256": state.success_status_transaction_lock_sha256,
                "action": state.action_required,
                "operator_signature_sha256": hashlib.sha256(
                    operator_signature.canonical_json().encode("utf-8")
                ).hexdigest(),
                "reviewer_signature_sha256": hashlib.sha256(
                    reviewer_signature.canonical_json().encode("utf-8")
                ).hexdigest(),
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "success-status recovery authority could not be durably consumed"
            ) from exc
        return payload

    def commit(self, *, receipt, lock_payload: bytes, source_state):
        final, lock = self._paths(receipt.recovery_key_sha256)
        if final.exists() or final.is_symlink() or _read_bytes(lock) != lock_payload:
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "durable success-status recovery state changed"
            )
        final_payload = receipt.canonical_json().encode("utf-8")
        try:
            create_once_file(final, final_payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "success-status recovery receipt could not be published"
            ) from exc
        parsed = PilotExactTaskStagingSuccessStatusRecoveryReceipt.from_mapping(
            json.loads(final_payload.decode("utf-8"))
        )
        _mark_staging_success_status_recovery_authenticated(
            parsed,
            source_state=source_state,
            final_path=final,
            final_payload=final_payload,
            lock_path=lock,
            lock_payload=lock_payload,
        )
        if parsed.recovery_authenticated is not True:
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "success-status recovery lost live provenance"
            )
        return parsed


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(receipt, *, source_state, final_path, final_payload, lock_path, lock_payload) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(), receipt.sha256, weakref.ref(receipt, cleanup), source_state,
            final_path, final_payload, lock_path, lock_payload,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, source_state, final_path, final_payload, lock_path, lock_payload = entry
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or receipt.sha256 != digest
            or source_state.fingerprint_sha256 != receipt.recovery_state_fingerprint_sha256
            or _read_bytes(final_path) != final_payload
            or _read_bytes(lock_path) != lock_payload
        ):
            return None
        return MappingProxyType({"recovery_state": source_state})

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_staging_success_status_recovery_authenticated,
    _get_live_staging_success_status_recovery_inputs,
) = _live_registry()


def _recover_verified_pilot_exact_task_staging_success_status(
    *,
    authorization_payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    transaction_ledger_root: Path,
    success_status_authorization_ledger_root: Path,
    recovery_ledger: _PilotExactTaskStagingSuccessStatusRecoveryLedger,
    transport: Any,
    now_provider: Callable[[], str],
) -> PilotExactTaskStagingSuccessStatusRecoveryReceipt:
    verified_at = now_provider()
    claim = _verify_dual_signatures(
        payload=authorization_payload,
        operator_signature=operator_signature,
        reviewer_signature=reviewer_signature,
        verifier=verifier,
        at_utc=verified_at,
    )
    state, authorization = _observe_verified_recovery_state(
        success_deployment_status_intent_sha256=claim["success_deployment_status_intent_sha256"],
        transaction_ledger_root=transaction_ledger_root,
        success_status_authorization_ledger_root=success_status_authorization_ledger_root,
        transport=transport,
        now_provider=lambda: verified_at,
    )
    if state.manual_intervention_required or state.remote_write_required or not _claim_matches_state(claim, state):
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "signed success-status recovery state no longer matches exact state"
        )
    lock_payload = recovery_ledger.acquire(
        state=state,
        authorization_payload=authorization_payload,
        operator_signature=operator_signature,
        reviewer_signature=reviewer_signature,
    )
    current, current_authorization = _observe_verified_recovery_state(
        success_deployment_status_intent_sha256=state.success_deployment_status_intent_sha256,
        transaction_ledger_root=transaction_ledger_root,
        success_status_authorization_ledger_root=success_status_authorization_ledger_root,
        transport=transport,
        now_provider=now_provider,
    )
    if (
        current.fingerprint_sha256 != state.fingerprint_sha256
        or current.action_required != "finalize_existing_state"
        or current_authorization.sha256 != authorization.sha256
    ):
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "success-status recovery state changed after durable recovery lock"
        )
    final_remote = _double_observe(transport, authorization)
    if (
        final_remote.remote_state_class != "exact_existing"
        or final_remote.success_deployment_status_id != current.success_deployment_status_id
        or final_remote.success_deployment_status_node_id_sha256
        != current.success_deployment_status_node_id_sha256
    ):
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "write-free success-status recovery final state is no longer exact"
        )
    assert current.success_deployment_status_id is not None
    assert current.success_deployment_status_node_id_sha256 is not None
    recovered_at = now_provider()
    if _utc(recovered_at, name="recovered_at_utc") < _utc(current.observed_at_utc, name="observed_at_utc"):
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "system clock moved backwards during success-status recovery"
        )
    receipt = PilotExactTaskStagingSuccessStatusRecoveryReceipt(
        recovery_ledger_root_path_sha256=recovery_ledger.root_sha256,
        recovery_key_sha256=current.success_deployment_status_intent_sha256,
        recovery_authorization_payload_sha256=hashlib.sha256(authorization_payload).hexdigest(),
        recovery_state_fingerprint_sha256=current.fingerprint_sha256,
        recovery_policy_sha256=pilot_exact_task_staging_success_status_recovery_policy_sha256(),
        success_status_authorization_sha256=current.success_status_authorization_sha256,
        success_deployment_status_intent_sha256=current.success_deployment_status_intent_sha256,
        staging_success_status_plan_sha256=current.staging_success_status_plan_sha256,
        staging_runtime_build_identity_sha256=current.staging_runtime_build_identity_sha256,
        deployment_status_intent_sha256=current.deployment_status_intent_sha256,
        status_transaction_lock_sha256=current.status_transaction_lock_sha256,
        status_recovery_lock_sha256=current.status_recovery_lock_sha256,
        success_status_transaction_lock_sha256=current.success_status_transaction_lock_sha256,
        source_durable_phase=current.durable_phase,
        source_remote_state_class=current.remote_state_class,
        final_remote_success_status_state_sha256=final_remote.sha256,
        publisher_credential_config_sha256=current.publisher_credential_config_sha256,
        publisher_credential_path_sha256=current.publisher_credential_path_sha256,
        repository=current.repository,
        repository_id=current.repository_id,
        deployment_environment=current.deployment_environment,
        merge_commit_sha=current.merge_commit_sha,
        deployment_id=current.deployment_id,
        deployment_node_id_sha256=current.deployment_node_id_sha256,
        current_deployment_status_id=current.current_deployment_status_id,
        current_deployment_status_node_id_sha256=current.current_deployment_status_node_id_sha256,
        success_deployment_status_state=current.success_deployment_status_state,
        success_deployment_status_environment=current.success_deployment_status_environment,
        success_deployment_status_description_sha256=current.success_deployment_status_description_sha256,
        success_deployment_status_body_sha256=current.success_deployment_status_body_sha256,
        success_deployment_status_id=current.success_deployment_status_id,
        success_deployment_status_node_id_sha256=current.success_deployment_status_node_id_sha256,
        action_performed="finalize_existing_state",
        remote_write_performed=False,
        operator_actor_id=claim["operator_actor_id"],
        operator_system_id=claim["operator_system_id"],
        operator_key_id=claim["operator_key_id"],
        reviewer_actor_id=claim["reviewer_actor_id"],
        reviewer_system_id=claim["reviewer_system_id"],
        reviewer_key_id=claim["reviewer_key_id"],
        recovered_at_utc=recovered_at,
    )
    return recovery_ledger.commit(
        receipt=receipt, lock_payload=lock_payload, source_state=current
    )


def _canonical_runtime():
    try:
        _require_elevated_operator()
        if os.name == "posix":
            transaction_root = _require_host_controlled_ledger_root(tx_boundary._POSIX_LEDGER)
            authorization_root = _require_host_controlled_ledger_root(auth_boundary._POSIX_LEDGER)
            recovery_root = _require_host_controlled_ledger_root(_POSIX_LEDGER)
            keyring_path = auth_boundary._POSIX_KEYRING
        elif os.name == "nt":
            transaction_root = _require_host_controlled_ledger_root(tx_boundary._WINDOWS_LEDGER)
            authorization_root = _require_host_controlled_ledger_root(auth_boundary._WINDOWS_LEDGER)
            recovery_root = _require_host_controlled_ledger_root(_WINDOWS_LEDGER)
            keyring_path = auth_boundary._WINDOWS_KEYRING
        else:
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "success-status recovery platform is unsupported"
            )
        first_keyring = auth_boundary._read_host_authority_file(keyring_path)
        second_keyring = auth_boundary._read_host_authority_file(keyring_path)
        if first_keyring != second_keyring:
            raise PilotExactTaskStagingSuccessStatusRecoveryError(
                "success-status recovery keyring changed while being read"
            )
        verifier, _keyring_sha = auth_boundary._parse_keyring(second_keyring)
        credential, credential_digest, credential_path = publication_tx_boundary._canonical_credential()
        transport = _GitHubStagingSuccessStatusRecoveryTransport(
            credential=credential,
            credential_config_sha256=credential_digest,
            credential_path=credential_path,
        )
        return (
            transaction_root,
            authorization_root,
            _PilotExactTaskStagingSuccessStatusRecoveryLedger(recovery_root),
            verifier,
            transport,
        )
    except PilotExactTaskStagingSuccessStatusRecoveryError:
        raise
    except (PhysicalHostStateError, ValueError, TypeError, OSError) as exc:
        raise PilotExactTaskStagingSuccessStatusRecoveryError(
            "success-status recovery runtime is not host-admin controlled"
        ) from exc


def inspect_pilot_exact_task_staging_success_status_recovery(
    success_deployment_status_intent_sha256: str,
) -> PilotExactTaskStagingSuccessStatusRecoveryState:
    """Inspect durable/remote ADR-DC-088 recovery state without mutation."""
    tx_root, auth_root, _recovery_ledger, _verifier, observer = _canonical_runtime()
    state, _authorization = _observe_verified_recovery_state(
        success_deployment_status_intent_sha256=success_deployment_status_intent_sha256,
        transaction_ledger_root=tx_root,
        success_status_authorization_ledger_root=auth_root,
        transport=observer,
        now_provider=_now_utc_seconds,
    )
    return state


def recover_pilot_exact_task_staging_success_status(
    authorization_payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
) -> PilotExactTaskStagingSuccessStatusRecoveryReceipt:
    """Finalize one consumed success-status transaction without remote write."""
    tx_root, auth_root, recovery_ledger, verifier, observer = _canonical_runtime()
    return _recover_verified_pilot_exact_task_staging_success_status(
        authorization_payload=authorization_payload,
        operator_signature=operator_signature,
        reviewer_signature=reviewer_signature,
        verifier=verifier,
        transaction_ledger_root=tx_root,
        success_status_authorization_ledger_root=auth_root,
        recovery_ledger=recovery_ledger,
        transport=observer,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []
