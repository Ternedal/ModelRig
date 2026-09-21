"""ADR-DC-078 read-only exact staging Deployment Status lane observation.

Consumes only one fresh live ADR-DC-077 Deployment Status plan. It revalidates the
exact parent staging Deployment and observes the Deployment Status inventory
twice through a credential-bound GET-only transport.

Only two stable states are accepted:

* ``clear``: the exact Deployment has no Deployment Status records.
* ``exact-existing``: exactly one Deployment Status matches the frozen
  ADR-DC-077 ``in_progress`` staging intent.

Any mismatched, conflicting, duplicate, or unstable status history fails
closed. No Deployment Status, Deployment, production, or other remote mutation
is performed or authorized.
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

from ._improvement_pilot_start_consumption_impl import _path_sha256
from . import improvement_pilot_exact_task_remote_publication_transaction as publication_tx_boundary
from . import improvement_pilot_exact_task_staging_deployment_status_plan as plan_boundary
from .improvement_pilot_exact_task_remote_publication_transaction import (
    PilotExactTaskGitHubPublisherCredential,
)
from .improvement_pilot_exact_task_staging_deployment_status_plan import (
    PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_PLAN_AUTHORITY,
    PilotExactTaskStagingDeploymentStatusPlanReceipt,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_STATE_OBSERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-staging-deployment-status-state-observation-receipt/v1"
)
PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_STATE_OBSERVATION_AUTHORITY = (
    "host-observed-one-dc-l16-exact-staging-deployment-status-state-only"
)
PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_STATE_OBSERVATION_SCOPE = (
    "exact-remote-staging-deployment-status-state-observation-only-v1"
)

_GITHUB_API_ROOT = "https://api.github.com"
_MAX_API_RESPONSE_BYTES = 4 * 1024 * 1024
_STATUS_PAGE_SIZE = 100
_MAX_STATUS_PAGES = 10
_TIMEOUT_SECONDS = 30.0
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ALLOWED_LANE_STATES = {"absent", "exact"}
_ALLOWED_CLASSES = {"clear", "exact-existing"}


class PilotExactTaskStagingDeploymentStatusStateObservationError(ValueError):
    """Deployment Status plan or observed remote state is stale/conflicting."""


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
        raise PilotExactTaskStagingDeploymentStatusStateObservationError(
            "staging Deployment Status evidence is not canonical JSON"
        ) from exc


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskStagingDeploymentStatusStateObservationError(
            f"{name} is invalid"
        )
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskStagingDeploymentStatusStateObservationError(
            f"{name} is invalid"
        )
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskStagingDeploymentStatusStateObservationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskStagingDeploymentStatusStateObservationError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _absent_url(value: Any, *, name: str) -> None:
    if value not in (None, ""):
        raise PilotExactTaskStagingDeploymentStatusStateObservationError(
            f"{name} must remain absent"
        )
    return None


def _require_live_plan(
    value: Any,
) -> tuple[PilotExactTaskStagingDeploymentStatusPlanReceipt, Any]:
    if type(value) is not PilotExactTaskStagingDeploymentStatusPlanReceipt:
        raise PilotExactTaskStagingDeploymentStatusStateObservationError(
            "exact live ADR-DC-077 Deployment Status plan is required"
        )
    try:
        replayed = PilotExactTaskStagingDeploymentStatusPlanReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskStagingDeploymentStatusStateObservationError(
            "ADR-DC-077 replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskStagingDeploymentStatusStateObservationError(
            "ADR-DC-077 Deployment Status plan identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_PLAN_AUTHORITY
        or value.plan_authenticated is not True
        or value.post_staging_attestation_authenticated is not True
        or value.post_staging_deployment_verified is not True
        or value.staging_deployment_status_plan_config_host_pinned is not True
        or value.deployment_status_intent_materialized is not True
        or value.deployment_status_transition_planned is not True
        or value.deployment_status_ready is not True
        or value.deployment_status_state != "in_progress"
        or value.deployment_status_environment != "staging"
        or value.deployment_status_auto_inactive is not False
        or value.deployment_status_log_url is not None
        or value.deployment_status_environment_url is not None
        or value.deployment_status_mutation_authorized is not False
        or value.deployment_mutation_authorized is not False
        or value.deploy_authorized is not False
        or value.remote_write_authorized is not False
        or value.production_activation_authorized is not False
        or value.nonce_reusable is not False
    ):
        raise PilotExactTaskStagingDeploymentStatusStateObservationError(
            "ADR-DC-078 requires one fresh inert ADR-DC-077 status plan"
        )
    live = plan_boundary._get_live_staging_deployment_status_plan_inputs(value)
    source = None if live is None else live.get("post_staging_deployment_attestation")
    if (
        source is None
        or getattr(source, "attestation_authenticated", False) is not True
        or getattr(source, "sha256", None)
        != value.post_staging_deployment_attestation_sha256
    ):
        raise PilotExactTaskStagingDeploymentStatusStateObservationError(
            "ADR-DC-077 live post-staging provenance is unavailable"
        )
    return value, source


@dataclass(frozen=True, slots=True)
class _RemoteStagingDeploymentStatusState:
    repository: str
    repository_id: str
    deployment_id: int
    deployment_node_id_sha256: str
    deployment_status_lane_state: str
    deployment_status_id: int | None
    deployment_status_node_id_sha256: str | None
    observed_status_state: str | None
    observed_status_environment: str | None
    observed_status_description_sha256: str | None
    observed_status_log_url: str | None
    observed_status_environment_url: str | None
    status_created_at_utc: str | None
    status_updated_at_utc: str | None
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
            or self.deployment_status_lane_state not in _ALLOWED_LANE_STATES
            or self.remote_state_class not in _ALLOWED_CLASSES
        ):
            raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                "remote staging Deployment Status projection is invalid"
            )
        _hex64(self.deployment_node_id_sha256, name="deployment_node_id_sha256")
        if self.remote_state_class == "clear":
            if (
                self.deployment_status_lane_state != "absent"
                or self.deployment_status_id is not None
                or self.deployment_status_node_id_sha256 is not None
                or self.observed_status_state is not None
                or self.observed_status_environment is not None
                or self.observed_status_description_sha256 is not None
                or self.observed_status_log_url is not None
                or self.observed_status_environment_url is not None
                or self.status_created_at_utc is not None
                or self.status_updated_at_utc is not None
            ):
                raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                    "clear Deployment Status projection is inconsistent"
                )
        else:
            if (
                self.deployment_status_lane_state != "exact"
                or isinstance(self.deployment_status_id, bool)
                or not isinstance(self.deployment_status_id, int)
                or self.deployment_status_id < 1
                or self.deployment_status_node_id_sha256 is None
                or self.observed_status_state != "in_progress"
                or self.observed_status_environment != "staging"
                or self.observed_status_description_sha256 is None
                or self.observed_status_log_url is not None
                or self.observed_status_environment_url is not None
                or self.status_created_at_utc is None
                or self.status_updated_at_utc is None
            ):
                raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                    "exact-existing Deployment Status projection is inconsistent"
                )
            _hex64(
                self.deployment_status_node_id_sha256,
                name="deployment_status_node_id_sha256",
            )
            _hex64(
                self.observed_status_description_sha256,
                name="observed_status_description_sha256",
            )
            created = _utc(self.status_created_at_utc, name="status_created_at_utc")
            updated = _utc(self.status_updated_at_utc, name="status_updated_at_utc")
            if updated < created:
                raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                    "Deployment Status update predates creation"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @property
    def sha256(self) -> str:
        return _sha256_text(_canonical(self.to_dict()))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _GitHubStagingDeploymentStatusStateObserver:
    """Credential-bound GET-only observer for one Deployment Status lane."""

    def __init__(
        self,
        *,
        credential: PilotExactTaskGitHubPublisherCredential,
        credential_config_sha256: str,
        credential_path: Path,
    ) -> None:
        if type(credential) is not PilotExactTaskGitHubPublisherCredential:
            raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                "exact publisher credential is required"
            )
        self.credential = credential
        self.credential_config_sha256 = _hex64(
            credential_config_sha256,
            name="credential_config_sha256",
        )
        self.credential_path = Path(credential_path)
        if (
            not self.credential_path.is_absolute()
            or _has_linkish_component(self.credential_path)
        ):
            raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                "publisher credential path is unsafe"
            )
        self.credential_path_sha256 = _path_sha256(self.credential_path)
        self._opener = urllib.request.build_opener(_NoRedirect())

    @staticmethod
    def _repo_root(plan: PilotExactTaskStagingDeploymentStatusPlanReceipt) -> str:
        owner, repo = plan.repository.split("/", 1)
        return "/repos/{}/{}".format(
            urllib.parse.quote(owner, safe=""),
            urllib.parse.quote(repo, safe=""),
        )

    def _api_json(
        self,
        *,
        plan: PilotExactTaskStagingDeploymentStatusPlanReceipt,
        path: str,
    ) -> Any:
        root = self._repo_root(plan)
        if (
            not isinstance(path, str)
            or not (path == root or path.startswith(root + "/"))
            or ".." in path
        ):
            raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                "Deployment Status GET is outside exact GitHub scope"
            )
        url = _GITHUB_API_ROOT + path
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.credential.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "ModelRig-DevControl-ExactStagingDeploymentStatusState/1",
            },
        )
        try:
            response = self._opener.open(request, timeout=_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                f"GitHub Deployment Status GET failed with HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                "GitHub Deployment Status GET failed"
            ) from exc
        with response:
            if response.status != 200 or response.geturl() != url:
                raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                    "GitHub Deployment Status response identity/status is unexpected"
                )
            raw = response.read(_MAX_API_RESPONSE_BYTES + 1)
        if not raw or len(raw) > _MAX_API_RESPONSE_BYTES:
            raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                "GitHub Deployment Status response size is invalid"
            )
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                "GitHub Deployment Status response is invalid JSON"
            ) from exc

    @staticmethod
    def _payload_sha(value: Any) -> str:
        if isinstance(value, str):
            return _sha256_text(value)
        if isinstance(value, (Mapping, list)):
            return _sha256_text(_canonical(value))
        raise PilotExactTaskStagingDeploymentStatusStateObservationError(
            "GitHub Deployment payload has unsupported shape"
        )

    @staticmethod
    def _node_hash(value: Any, *, name: str) -> str:
        if not isinstance(value, str) or not value:
            raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                f"{name} is invalid"
            )
        return _sha256_text(value)

    def _verify_parent_deployment(
        self,
        plan: PilotExactTaskStagingDeploymentStatusPlanReceipt,
    ) -> None:
        root = self._repo_root(plan)
        deployment_path = f"{root}/deployments/{plan.deployment_id}"
        item = self._api_json(plan=plan, path=deployment_path)
        if not isinstance(item, Mapping):
            raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                "GitHub parent Deployment response is invalid"
            )
        if (
            item.get("id") != plan.deployment_id
            or self._node_hash(
                item.get("node_id"), name="parent Deployment node identity"
            )
            != plan.deployment_node_id_sha256
            or item.get("sha") != plan.merge_commit_sha
            or item.get("ref") != plan.deployment_ref
            or item.get("task") != plan.deployment_task
            or item.get("environment") != plan.deployment_environment
            or item.get("transient_environment") is not False
            or item.get("production_environment") is not False
            or item.get("repository_url")
            != f"{_GITHUB_API_ROOT}/repos/{plan.repository}"
        ):
            raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                "parent GitHub Deployment differs from exact ADR-DC-077 identity"
            )
        description = item.get("description")
        if (
            not isinstance(description, str)
            or self._payload_sha(item.get("payload")) != plan.deployment_payload_sha256
            or _sha256_text(description) != plan.deployment_description_sha256
        ):
            raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                "parent GitHub Deployment payload/description drifted"
            )

    def _list_statuses(
        self,
        plan: PilotExactTaskStagingDeploymentStatusPlanReceipt,
    ) -> list[Mapping[str, Any]]:
        root = self._repo_root(plan)
        matches: list[Mapping[str, Any]] = []
        exhausted = False
        for page in range(1, _MAX_STATUS_PAGES + 1):
            query = urllib.parse.urlencode(
                {"per_page": str(_STATUS_PAGE_SIZE), "page": str(page)}
            )
            path = (
                f"{root}/deployments/{plan.deployment_id}/statuses?{query}"
            )
            payload = self._api_json(plan=plan, path=path)
            if not isinstance(payload, list):
                raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                    "GitHub Deployment Status inventory response is invalid"
                )
            for item in payload:
                if not isinstance(item, Mapping):
                    raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                        "GitHub Deployment Status inventory contains invalid item"
                    )
                matches.append(item)
                if len(matches) > 1:
                    raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                        "multiple statuses already occupy first-status staging lane"
                    )
            if len(payload) < _STATUS_PAGE_SIZE:
                exhausted = True
                break
        if not exhausted:
            raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                "Deployment Status inventory exceeded bounded observation window"
            )
        return matches

    def _exact_projection(
        self,
        plan: PilotExactTaskStagingDeploymentStatusPlanReceipt,
        item: Mapping[str, Any],
    ) -> _RemoteStagingDeploymentStatusState:
        status_id = item.get("id")
        node_id = item.get("node_id")
        description = item.get("description")
        deployment_url = item.get("deployment_url")
        repository_url = item.get("repository_url")
        created_at = item.get("created_at")
        updated_at = item.get("updated_at")
        _absent_url(item.get("log_url"), name="observed log_url")
        _absent_url(item.get("environment_url"), name="observed environment_url")
        _absent_url(item.get("target_url"), name="observed target_url")
        if (
            isinstance(status_id, bool)
            or not isinstance(status_id, int)
            or status_id < 1
            or not isinstance(node_id, str)
            or not node_id
            or item.get("state") != plan.deployment_status_state
            or item.get("environment") != plan.deployment_status_environment
            or description != plan.deployment_status_description
            or deployment_url
            != f"{_GITHUB_API_ROOT}/repos/{plan.repository}/deployments/{plan.deployment_id}"
            or repository_url != f"{_GITHUB_API_ROOT}/repos/{plan.repository}"
        ):
            raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                "existing GitHub Deployment Status differs from exact ADR-DC-077 plan"
            )
        _utc(created_at, name="status_created_at_utc")
        _utc(updated_at, name="status_updated_at_utc")
        return _RemoteStagingDeploymentStatusState(
            repository=plan.repository,
            repository_id=plan.repository_id,
            deployment_id=plan.deployment_id,
            deployment_node_id_sha256=plan.deployment_node_id_sha256,
            deployment_status_lane_state="exact",
            deployment_status_id=status_id,
            deployment_status_node_id_sha256=self._node_hash(
                node_id, name="Deployment Status node identity"
            ),
            observed_status_state=plan.deployment_status_state,
            observed_status_environment=plan.deployment_status_environment,
            observed_status_description_sha256=_sha256_text(description),
            observed_status_log_url=None,
            observed_status_environment_url=None,
            status_created_at_utc=created_at,
            status_updated_at_utc=updated_at,
            remote_state_class="exact-existing",
        )

    def observe(
        self,
        plan: PilotExactTaskStagingDeploymentStatusPlanReceipt,
    ) -> _RemoteStagingDeploymentStatusState:
        if type(plan) is not PilotExactTaskStagingDeploymentStatusPlanReceipt:
            raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                "exact ADR-DC-077 Deployment Status plan is required"
            )
        if (
            self.credential.repository != plan.repository
            or self.credential.repository_id != plan.repository_id
        ):
            raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                "publisher credential is not bound to exact status repository"
            )
        root = self._repo_root(plan)
        repo = self._api_json(plan=plan, path=root)
        if (
            not isinstance(repo, Mapping)
            or str(repo.get("id")) != plan.repository_id
            or repo.get("full_name") != plan.repository
        ):
            raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                "GitHub repository identity differs from status plan"
            )
        self._verify_parent_deployment(plan)
        statuses = self._list_statuses(plan)
        if not statuses:
            return _RemoteStagingDeploymentStatusState(
                repository=plan.repository,
                repository_id=plan.repository_id,
                deployment_id=plan.deployment_id,
                deployment_node_id_sha256=plan.deployment_node_id_sha256,
                deployment_status_lane_state="absent",
                deployment_status_id=None,
                deployment_status_node_id_sha256=None,
                observed_status_state=None,
                observed_status_environment=None,
                observed_status_description_sha256=None,
                observed_status_log_url=None,
                observed_status_environment_url=None,
                status_created_at_utc=None,
                status_updated_at_utc=None,
                remote_state_class="clear",
            )
        return self._exact_projection(plan, statuses[0])


def _normalize_remote_state(
    value: Any,
    plan: PilotExactTaskStagingDeploymentStatusPlanReceipt,
) -> _RemoteStagingDeploymentStatusState:
    if type(value) is not _RemoteStagingDeploymentStatusState:
        raise PilotExactTaskStagingDeploymentStatusStateObservationError(
            "Deployment Status observer returned invalid state"
        )
    if (
        value.repository != plan.repository
        or value.repository_id != plan.repository_id
        or value.deployment_id != plan.deployment_id
        or value.deployment_node_id_sha256 != plan.deployment_node_id_sha256
    ):
        raise PilotExactTaskStagingDeploymentStatusStateObservationError(
            "Deployment Status target identity mismatch"
        )
    if value.remote_state_class == "exact-existing":
        if (
            value.observed_status_state != plan.deployment_status_state
            or value.observed_status_environment != plan.deployment_status_environment
            or value.observed_status_description_sha256
            != plan.deployment_status_description_sha256
            or value.observed_status_log_url is not None
            or value.observed_status_environment_url is not None
        ):
            raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                "exact-existing Deployment Status differs from frozen plan"
            )
    return value


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: Any,
        *,
        plan: PilotExactTaskStagingDeploymentStatusPlanReceipt,
        remote_state_sha256: str,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            weakref.ref(plan),
            remote_state_sha256,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, plan_ref, remote_sha = entry
        plan = plan_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or plan is None
            or receipt.sha256 != digest
            or plan.plan_authenticated is not True
            or plan.sha256 != receipt.staging_deployment_status_plan_sha256
            or receipt.remote_deployment_status_state_sha256 != remote_sha
        ):
            return None
        return MappingProxyType(
            {
                "staging_deployment_status_plan": plan,
                "remote_deployment_status_state_sha256": remote_sha,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_staging_deployment_status_state_observation_authenticated,
    _get_live_staging_deployment_status_state_observation_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskStagingDeploymentStatusStateObservationReceipt:
    staging_deployment_status_plan_sha256: str
    post_staging_deployment_attestation_sha256: str
    completion_source_receipt_sha256: str
    deployment_authorization_sha256: str
    deployment_state_observation_sha256: str
    staging_deployment_plan_sha256: str
    deploy_readiness_evaluation_sha256: str
    post_release_attestation_sha256: str
    deployment_intent_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    upstream_merge_transaction_lock_sha256: str
    release_transaction_lock_sha256: str
    transaction_lock_sha256: str
    recovery_lock_sha256: str | None
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    source_remote_observation_sha256: str
    staging_deployment_status_plan_config_sha256: str
    deployment_status_intent_sha256: str
    remote_deployment_status_state_sha256: str
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
    deployment_status_state_planned: str
    deployment_status_environment_planned: str
    deployment_status_description_sha256: str
    deployment_status_body_sha256: str
    deployment_status_auto_inactive_planned: bool
    deployment_status_log_url_planned: str | None
    deployment_status_environment_url_planned: str | None
    deployment_status_lane_state: str
    deployment_status_id: int | None
    deployment_status_node_id_sha256: str | None
    observed_status_state: str | None
    observed_status_environment: str | None
    observed_status_description_sha256: str | None
    observed_status_log_url: str | None
    observed_status_environment_url: str | None
    status_created_at_utc: str | None
    status_updated_at_utc: str | None
    remote_state_class: str
    observed_at_utc: str
    staging_deployment_status_plan_authenticated: bool = True
    parent_deployment_verified: bool = True
    remote_repository_verified: bool = True
    status_inventory_bounded: bool = True
    status_state_verified: bool = True
    double_observation_matched: bool = True
    status_lane_clear: bool = False
    exact_existing_status: bool = False
    status_state_acceptable: bool = True
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
    observation_scope: str = PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_STATE_OBSERVATION_SCOPE
    authority: str = PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_STATE_OBSERVATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_STATE_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema
            != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_STATE_OBSERVATION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_STATE_OBSERVATION_AUTHORITY
            or self.observation_scope
            != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATUS_STATE_OBSERVATION_SCOPE
        ):
            raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                "Deployment Status observation identity is unsupported"
            )
        for name in (
            "staging_deployment_status_plan_sha256",
            "post_staging_deployment_attestation_sha256",
            "completion_source_receipt_sha256",
            "deployment_authorization_sha256",
            "deployment_state_observation_sha256",
            "staging_deployment_plan_sha256",
            "deploy_readiness_evaluation_sha256",
            "post_release_attestation_sha256",
            "deployment_intent_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "pr_intent_sha256",
            "upstream_merge_transaction_lock_sha256",
            "release_transaction_lock_sha256",
            "transaction_lock_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
            "source_remote_observation_sha256",
            "staging_deployment_status_plan_config_sha256",
            "deployment_status_intent_sha256",
            "remote_deployment_status_state_sha256",
            "deployment_payload_sha256",
            "deployment_description_sha256",
            "deployment_node_id_sha256",
            "deployment_status_description_sha256",
            "deployment_status_body_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        if self.recovery_lock_sha256 is not None:
            _hex64(self.recovery_lock_sha256, name="recovery_lock_sha256")
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.deployment_environment != "staging"
            or self.deployment_task != "deploy"
            or self.deployment_identity != f"modelrig-staging-{self.merge_commit_sha}"
            or self.deployment_ref != f"modelrig-rsi-{self.merge_commit_sha}"
            or isinstance(self.deployment_id, bool)
            or not isinstance(self.deployment_id, int)
            or self.deployment_id < 1
            or self.completion_source not in {"transaction", "recovery"}
            or self.source_action
            not in {"execute_exact_staging_deployment", "finalize_existing_state"}
            or not isinstance(self.source_remote_write_performed, bool)
            or self.deployment_status_state_planned != "in_progress"
            or self.deployment_status_environment_planned != "staging"
            or self.deployment_status_auto_inactive_planned is not False
            or self.deployment_status_log_url_planned is not None
            or self.deployment_status_environment_url_planned is not None
            or self.deployment_status_lane_state not in _ALLOWED_LANE_STATES
            or self.remote_state_class not in _ALLOWED_CLASSES
        ):
            raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                "Deployment Status observation source projection is invalid"
            )
        if self.completion_source == "transaction":
            if (
                self.source_action != "execute_exact_staging_deployment"
                or self.source_remote_write_performed is not True
                or self.recovery_lock_sha256 is not None
            ):
                raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                    "normal Deployment Status observation source is inconsistent"
                )
        elif (
            self.source_action != "finalize_existing_state"
            or self.source_remote_write_performed is not False
            or self.recovery_lock_sha256 is None
        ):
            raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                "recovered Deployment Status observation source is inconsistent"
            )
        if self.remote_state_class == "clear":
            if (
                self.deployment_status_lane_state != "absent"
                or self.deployment_status_id is not None
                or self.deployment_status_node_id_sha256 is not None
                or self.observed_status_state is not None
                or self.observed_status_environment is not None
                or self.observed_status_description_sha256 is not None
                or self.observed_status_log_url is not None
                or self.observed_status_environment_url is not None
                or self.status_created_at_utc is not None
                or self.status_updated_at_utc is not None
                or self.status_lane_clear is not True
                or self.exact_existing_status is not False
            ):
                raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                    "clear Deployment Status observation is inconsistent"
                )
        else:
            if (
                self.deployment_status_lane_state != "exact"
                or isinstance(self.deployment_status_id, bool)
                or not isinstance(self.deployment_status_id, int)
                or self.deployment_status_id < 1
                or self.deployment_status_node_id_sha256 is None
                or self.observed_status_state != self.deployment_status_state_planned
                or self.observed_status_environment
                != self.deployment_status_environment_planned
                or self.observed_status_description_sha256
                != self.deployment_status_description_sha256
                or self.observed_status_log_url is not None
                or self.observed_status_environment_url is not None
                or self.status_created_at_utc is None
                or self.status_updated_at_utc is None
                or self.status_lane_clear is not False
                or self.exact_existing_status is not True
            ):
                raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                    "exact-existing Deployment Status observation is inconsistent"
                )
            _hex64(
                self.deployment_status_node_id_sha256,
                name="deployment_status_node_id_sha256",
            )
            created = _utc(self.status_created_at_utc, name="status_created_at_utc")
            updated = _utc(self.status_updated_at_utc, name="status_updated_at_utc")
            if updated < created:
                raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                    "observed Deployment Status timestamps are inconsistent"
                )
        source_time = _utc(self.source_attested_at_utc, name="source_attested_at_utc")
        observed = _utc(self.observed_at_utc, name="observed_at_utc")
        if observed < source_time:
            raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                "Deployment Status observation predates source attestation"
            )
        required_true = (
            "staging_deployment_status_plan_authenticated",
            "parent_deployment_verified",
            "remote_repository_verified",
            "status_inventory_bounded",
            "status_state_verified",
            "double_observation_matched",
            "status_state_acceptable",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                "Deployment Status observation evidence is incomplete"
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
            raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                "Deployment Status observation retains forbidden authority"
            )

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())

    @property
    def observation_authenticated(self) -> bool:
        return (
            _get_live_staging_deployment_status_state_observation_inputs(self)
            is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskStagingDeploymentStatusStateObservationError(
                "Deployment Status observation receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _observe_verified_pilot_exact_task_staging_deployment_status_state(
    *,
    staging_deployment_status_plan: PilotExactTaskStagingDeploymentStatusPlanReceipt,
    transport: Any,
    now_provider: Callable[[], str],
) -> PilotExactTaskStagingDeploymentStatusStateObservationReceipt:
    plan, _source = _require_live_plan(staging_deployment_status_plan)
    if transport is None or not callable(getattr(transport, "observe", None)):
        raise PilotExactTaskStagingDeploymentStatusStateObservationError(
            "fresh Deployment Status observer is required"
        )
    if (
        getattr(transport, "credential_config_sha256", None)
        != plan.publisher_credential_config_sha256
        or getattr(transport, "credential_path_sha256", None)
        != plan.publisher_credential_path_sha256
    ):
        raise PilotExactTaskStagingDeploymentStatusStateObservationError(
            "Deployment Status observer credential identity differs from ADR-DC-077"
        )
    first = _normalize_remote_state(transport.observe(plan), plan)
    second = _normalize_remote_state(transport.observe(plan), plan)
    if first != second:
        raise PilotExactTaskStagingDeploymentStatusStateObservationError(
            "GitHub Deployment Status state changed between observations"
        )
    observed_at = now_provider()
    if _utc(observed_at, name="observed_at_utc") < _utc(
        plan.source_attested_at_utc,
        name="source_attested_at_utc",
    ):
        raise PilotExactTaskStagingDeploymentStatusStateObservationError(
            "system clock moved backwards before Deployment Status observation"
        )
    remote_sha = first.sha256
    receipt = PilotExactTaskStagingDeploymentStatusStateObservationReceipt(
        staging_deployment_status_plan_sha256=plan.sha256,
        post_staging_deployment_attestation_sha256=plan.post_staging_deployment_attestation_sha256,
        completion_source_receipt_sha256=plan.completion_source_receipt_sha256,
        deployment_authorization_sha256=plan.deployment_authorization_sha256,
        deployment_state_observation_sha256=plan.deployment_state_observation_sha256,
        staging_deployment_plan_sha256=plan.staging_deployment_plan_sha256,
        deploy_readiness_evaluation_sha256=plan.deploy_readiness_evaluation_sha256,
        post_release_attestation_sha256=plan.post_release_attestation_sha256,
        deployment_intent_sha256=plan.deployment_intent_sha256,
        execution_nonce_sha256=plan.execution_nonce_sha256,
        development_task_sha256=plan.development_task_sha256,
        candidate_patch_sha256=plan.candidate_patch_sha256,
        pr_intent_sha256=plan.pr_intent_sha256,
        upstream_merge_transaction_lock_sha256=plan.upstream_merge_transaction_lock_sha256,
        release_transaction_lock_sha256=plan.release_transaction_lock_sha256,
        transaction_lock_sha256=plan.transaction_lock_sha256,
        recovery_lock_sha256=plan.recovery_lock_sha256,
        publisher_credential_config_sha256=plan.publisher_credential_config_sha256,
        publisher_credential_path_sha256=plan.publisher_credential_path_sha256,
        source_remote_observation_sha256=plan.remote_observation_sha256,
        staging_deployment_status_plan_config_sha256=plan.staging_deployment_status_plan_config_sha256,
        deployment_status_intent_sha256=plan.deployment_status_intent_sha256,
        remote_deployment_status_state_sha256=remote_sha,
        repository=plan.repository,
        repository_id=plan.repository_id,
        deployment_environment=plan.deployment_environment,
        merge_commit_sha=plan.merge_commit_sha,
        deployment_identity=plan.deployment_identity,
        deployment_ref=plan.deployment_ref,
        deployment_task=plan.deployment_task,
        deployment_payload_sha256=plan.deployment_payload_sha256,
        deployment_description_sha256=plan.deployment_description_sha256,
        deployment_id=plan.deployment_id,
        deployment_node_id_sha256=plan.deployment_node_id_sha256,
        completion_source=plan.completion_source,
        source_action=plan.source_action,
        source_remote_write_performed=plan.source_remote_write_performed,
        source_attested_at_utc=plan.source_attested_at_utc,
        deployment_status_state_planned=plan.deployment_status_state,
        deployment_status_environment_planned=plan.deployment_status_environment,
        deployment_status_description_sha256=plan.deployment_status_description_sha256,
        deployment_status_body_sha256=plan.deployment_status_body_sha256,
        deployment_status_auto_inactive_planned=plan.deployment_status_auto_inactive,
        deployment_status_log_url_planned=plan.deployment_status_log_url,
        deployment_status_environment_url_planned=plan.deployment_status_environment_url,
        deployment_status_lane_state=first.deployment_status_lane_state,
        deployment_status_id=first.deployment_status_id,
        deployment_status_node_id_sha256=first.deployment_status_node_id_sha256,
        observed_status_state=first.observed_status_state,
        observed_status_environment=first.observed_status_environment,
        observed_status_description_sha256=first.observed_status_description_sha256,
        observed_status_log_url=first.observed_status_log_url,
        observed_status_environment_url=first.observed_status_environment_url,
        status_created_at_utc=first.status_created_at_utc,
        status_updated_at_utc=first.status_updated_at_utc,
        remote_state_class=first.remote_state_class,
        observed_at_utc=observed_at,
        status_lane_clear=(first.remote_state_class == "clear"),
        exact_existing_status=(first.remote_state_class == "exact-existing"),
    )
    _mark_staging_deployment_status_state_observation_authenticated(
        receipt,
        plan=plan,
        remote_state_sha256=remote_sha,
    )
    if receipt.observation_authenticated is not True:
        raise PilotExactTaskStagingDeploymentStatusStateObservationError(
            "Deployment Status observation lost live provenance"
        )
    return receipt


def observe_pilot_exact_task_staging_deployment_status_state(
    staging_deployment_status_plan: PilotExactTaskStagingDeploymentStatusPlanReceipt,
) -> PilotExactTaskStagingDeploymentStatusStateObservationReceipt:
    """Observe one exact first-status staging lane without remote mutation."""
    credential, credential_digest, credential_path = (
        publication_tx_boundary._canonical_credential()
    )
    transport = _GitHubStagingDeploymentStatusStateObserver(
        credential=credential,
        credential_config_sha256=credential_digest,
        credential_path=credential_path,
    )
    return _observe_verified_pilot_exact_task_staging_deployment_status_state(
        staging_deployment_status_plan=staging_deployment_status_plan,
        transport=transport,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []
