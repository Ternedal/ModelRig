"""ADR-DC-086 read-only observation of the staging success Deployment Status lane.

Consumes one fresh live ADR-DC-085 success-status plan and re-observes the exact
staging Deployment Status inventory through the existing publisher credential.

The already-attested ``in_progress`` status must still exist exactly.  The
success lane then has only two acceptable stable states:

* ``clear``: only that exact ``in_progress`` status exists;
* ``exact-existing``: that exact status plus exactly one status matching the
  frozen ADR-DC-085 ``success`` intent exists.

Everything else fails closed.  This boundary performs GET requests only and
grants no Deployment Status, Deployment, release, production, or other write
authority.
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
from . import improvement_pilot_exact_task_staging_success_status_plan as success_plan_boundary
from .improvement_pilot_exact_task_remote_publication_transaction import (
    PilotExactTaskGitHubPublisherCredential,
)
from .improvement_pilot_exact_task_staging_success_status_plan import (
    PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_PLAN_AUTHORITY,
    PilotExactTaskStagingSuccessStatusPlanReceipt,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_STATE_OBSERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-staging-success-status-state-observation-receipt/v1"
)
PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_STATE_OBSERVATION_AUTHORITY = (
    "host-observed-one-dc-l16-exact-staging-success-status-state-only"
)
PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_STATE_OBSERVATION_SCOPE = (
    "exact-remote-staging-success-status-state-observation-only-v1"
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
_ALLOWED_CLASSES = {"clear", "exact-existing"}


class PilotExactTaskStagingSuccessStatusStateObservationError(ValueError):
    """Success-status plan or observed remote state is stale/conflicting."""


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
        raise PilotExactTaskStagingSuccessStatusStateObservationError(
            "staging success-status evidence is not canonical JSON"
        ) from exc


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskStagingSuccessStatusStateObservationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskStagingSuccessStatusStateObservationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskStagingSuccessStatusStateObservationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskStagingSuccessStatusStateObservationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _absent_url(value: Any, *, name: str) -> None:
    if value not in (None, ""):
        raise PilotExactTaskStagingSuccessStatusStateObservationError(
            f"{name} must remain absent"
        )
    return None


def _require_live_plan(
    value: Any,
) -> PilotExactTaskStagingSuccessStatusPlanReceipt:
    if type(value) is not PilotExactTaskStagingSuccessStatusPlanReceipt:
        raise PilotExactTaskStagingSuccessStatusStateObservationError(
            "exact live ADR-DC-085 staging success-status plan is required"
        )
    try:
        replayed = PilotExactTaskStagingSuccessStatusPlanReceipt.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskStagingSuccessStatusStateObservationError(
            "ADR-DC-085 replay validation failed"
        ) from exc
    required_true = (
        "staging_runtime_build_identity_authenticated",
        "exact_runtime_commit_verified",
        "exact_runtime_artifacts_verified",
        "success_status_plan_config_host_pinned",
        "success_status_intent_materialized",
        "success_status_transition_planned",
        "success_deployment_status_ready",
    )
    forced_false = (
        "success_deployment_status_authorized",
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
    if (
        replayed != value
        or replayed.sha256 != value.sha256
        or value.authority != PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_PLAN_AUTHORITY
        or value.plan_authenticated is not True
        or value.current_deployment_status_state != "in_progress"
        or value.current_deployment_status_environment != "staging"
        or value.success_deployment_status_state != "success"
        or value.success_deployment_status_environment != "staging"
        or value.success_deployment_status_auto_inactive is not False
        or value.success_deployment_status_log_url is not None
        or value.success_deployment_status_environment_url is not None
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
    ):
        raise PilotExactTaskStagingSuccessStatusStateObservationError(
            "ADR-DC-086 requires one fresh inert ADR-DC-085 success-status plan"
        )
    live = success_plan_boundary._get_live_staging_success_status_plan_inputs(value)
    source = None if live is None else live.get("staging_runtime_build_identity")
    if (
        source is None
        or getattr(source, "verification_authenticated", False) is not True
        or getattr(source, "sha256", None) != value.staging_runtime_build_identity_sha256
    ):
        raise PilotExactTaskStagingSuccessStatusStateObservationError(
            "ADR-DC-085 live runtime-build provenance is unavailable"
        )
    return value


@dataclass(frozen=True, slots=True)
class _RemoteStagingSuccessStatusState:
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
    observed_success_status_log_url: str | None
    observed_success_status_environment_url: str | None
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
            or self.remote_state_class not in _ALLOWED_CLASSES
        ):
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                "remote staging success-status projection is invalid"
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
                    self.observed_success_status_log_url,
                    self.observed_success_status_environment_url,
                    self.success_status_created_at_utc,
                    self.success_status_updated_at_utc,
                )
            ):
                raise PilotExactTaskStagingSuccessStatusStateObservationError(
                    "clear success-status projection is inconsistent"
                )
        else:
            if (
                isinstance(self.success_deployment_status_id, bool)
                or not isinstance(self.success_deployment_status_id, int)
                or self.success_deployment_status_id < 1
                or self.success_deployment_status_node_id_sha256 is None
                or self.observed_success_status_state != "success"
                or self.observed_success_status_environment != "staging"
                or self.observed_success_status_description_sha256 is None
                or self.observed_success_status_log_url is not None
                or self.observed_success_status_environment_url is not None
                or self.success_status_created_at_utc is None
                or self.success_status_updated_at_utc is None
            ):
                raise PilotExactTaskStagingSuccessStatusStateObservationError(
                    "exact-existing success-status projection is inconsistent"
                )
            _hex64(
                self.success_deployment_status_node_id_sha256,
                name="success_deployment_status_node_id_sha256",
            )
            _hex64(
                self.observed_success_status_description_sha256,
                name="observed_success_status_description_sha256",
            )
            created = _utc(
                self.success_status_created_at_utc,
                name="success_status_created_at_utc",
            )
            updated = _utc(
                self.success_status_updated_at_utc,
                name="success_status_updated_at_utc",
            )
            if updated < created:
                raise PilotExactTaskStagingSuccessStatusStateObservationError(
                    "success Deployment Status update predates creation"
                )

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @property
    def sha256(self) -> str:
        return _sha256_text(_canonical(self.to_dict()))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _GitHubStagingSuccessStatusStateObserver:
    """Credential-bound GET-only observer for the post-runtime success lane."""

    def __init__(
        self,
        *,
        credential: PilotExactTaskGitHubPublisherCredential,
        credential_config_sha256: str,
        credential_path: Path,
    ) -> None:
        if type(credential) is not PilotExactTaskGitHubPublisherCredential:
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
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
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                "publisher credential path is unsafe"
            )
        self.credential_path_sha256 = _path_sha256(self.credential_path)
        self._opener = urllib.request.build_opener(_NoRedirect())

    @staticmethod
    def _repo_root(plan: PilotExactTaskStagingSuccessStatusPlanReceipt) -> str:
        owner, repo = plan.repository.split("/", 1)
        return "/repos/{}/{}".format(
            urllib.parse.quote(owner, safe=""),
            urllib.parse.quote(repo, safe=""),
        )

    def _api_json(
        self,
        *,
        plan: PilotExactTaskStagingSuccessStatusPlanReceipt,
        path: str,
    ) -> Any:
        root = self._repo_root(plan)
        if (
            not isinstance(path, str)
            or not (path == root or path.startswith(root + "/"))
            or ".." in path
        ):
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                "success-status GET is outside exact GitHub scope"
            )
        url = _GITHUB_API_ROOT + path
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.credential.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "ModelRig-DevControl-ExactStagingSuccessStatusState/1",
            },
        )
        try:
            response = self._opener.open(request, timeout=_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                f"GitHub success-status GET failed with HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                "GitHub success-status GET failed"
            ) from exc
        with response:
            if response.status != 200 or response.geturl() != url:
                raise PilotExactTaskStagingSuccessStatusStateObservationError(
                    "GitHub success-status response identity/status is unexpected"
                )
            raw = response.read(_MAX_API_RESPONSE_BYTES + 1)
        if not raw or len(raw) > _MAX_API_RESPONSE_BYTES:
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                "GitHub success-status response size is invalid"
            )
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                "GitHub success-status response is invalid JSON"
            ) from exc

    @staticmethod
    def _node_hash(value: Any, *, name: str) -> str:
        if not isinstance(value, str) or not value:
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                f"{name} is invalid"
            )
        return _sha256_text(value)

    def _verify_repository(
        self,
        plan: PilotExactTaskStagingSuccessStatusPlanReceipt,
    ) -> None:
        root = self._repo_root(plan)
        repo = self._api_json(plan=plan, path=root)
        if (
            not isinstance(repo, Mapping)
            or str(repo.get("id")) != plan.repository_id
            or repo.get("full_name") != plan.repository
        ):
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                "GitHub repository identity differs from success-status plan"
            )

    def _verify_parent_deployment(
        self,
        plan: PilotExactTaskStagingSuccessStatusPlanReceipt,
    ) -> None:
        root = self._repo_root(plan)
        item = self._api_json(
            plan=plan,
            path=f"{root}/deployments/{plan.deployment_id}",
        )
        if not isinstance(item, Mapping):
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                "GitHub parent Deployment response is invalid"
            )
        if (
            item.get("id") != plan.deployment_id
            or self._node_hash(
                item.get("node_id"), name="parent Deployment node identity"
            )
            != plan.deployment_node_id_sha256
            or item.get("sha") != plan.merge_commit_sha
            or item.get("environment") != "staging"
            or item.get("transient_environment") is not False
            or item.get("production_environment") is not False
            or item.get("repository_url")
            != f"{_GITHUB_API_ROOT}/repos/{plan.repository}"
        ):
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                "parent GitHub Deployment differs from exact ADR-DC-085 identity"
            )

    def _list_statuses(
        self,
        plan: PilotExactTaskStagingSuccessStatusPlanReceipt,
    ) -> list[Mapping[str, Any]]:
        root = self._repo_root(plan)
        statuses: list[Mapping[str, Any]] = []
        exhausted = False
        for page in range(1, _MAX_STATUS_PAGES + 1):
            query = urllib.parse.urlencode(
                {"per_page": str(_STATUS_PAGE_SIZE), "page": str(page)}
            )
            payload = self._api_json(
                plan=plan,
                path=f"{root}/deployments/{plan.deployment_id}/statuses?{query}",
            )
            if not isinstance(payload, list):
                raise PilotExactTaskStagingSuccessStatusStateObservationError(
                    "GitHub Deployment Status inventory response is invalid"
                )
            for item in payload:
                if not isinstance(item, Mapping):
                    raise PilotExactTaskStagingSuccessStatusStateObservationError(
                        "GitHub Deployment Status inventory contains invalid item"
                    )
                statuses.append(item)
                if len(statuses) > 2:
                    raise PilotExactTaskStagingSuccessStatusStateObservationError(
                        "unexpected status history occupies staging success lane"
                    )
            if len(payload) < _STATUS_PAGE_SIZE:
                exhausted = True
                break
        if not exhausted:
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                "Deployment Status inventory exceeded bounded observation window"
            )
        return statuses

    def _verify_current_status(
        self,
        plan: PilotExactTaskStagingSuccessStatusPlanReceipt,
        item: Mapping[str, Any],
    ) -> None:
        _absent_url(item.get("log_url"), name="current status log_url")
        _absent_url(item.get("environment_url"), name="current status environment_url")
        _absent_url(item.get("target_url"), name="current status target_url")
        if (
            item.get("id") != plan.current_deployment_status_id
            or self._node_hash(
                item.get("node_id"), name="current Deployment Status node identity"
            )
            != plan.current_deployment_status_node_id_sha256
            or item.get("state") != "in_progress"
            or item.get("environment") != "staging"
            or item.get("deployment_url")
            != f"{_GITHUB_API_ROOT}/repos/{plan.repository}/deployments/{plan.deployment_id}"
            or item.get("repository_url")
            != f"{_GITHUB_API_ROOT}/repos/{plan.repository}"
        ):
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                "current in_progress status differs from attested ADR-DC-085 source"
            )

    def _success_projection(
        self,
        plan: PilotExactTaskStagingSuccessStatusPlanReceipt,
        item: Mapping[str, Any],
    ) -> _RemoteStagingSuccessStatusState:
        status_id = item.get("id")
        node_id = item.get("node_id")
        description = item.get("description")
        created_at = item.get("created_at")
        updated_at = item.get("updated_at")
        _absent_url(item.get("log_url"), name="success status log_url")
        _absent_url(item.get("environment_url"), name="success status environment_url")
        _absent_url(item.get("target_url"), name="success status target_url")
        if (
            isinstance(status_id, bool)
            or not isinstance(status_id, int)
            or status_id < 1
            or status_id == plan.current_deployment_status_id
            or not isinstance(node_id, str)
            or not node_id
            or item.get("state") != plan.success_deployment_status_state
            or item.get("environment") != plan.success_deployment_status_environment
            or description != plan.success_deployment_status_description
            or item.get("deployment_url")
            != f"{_GITHUB_API_ROOT}/repos/{plan.repository}/deployments/{plan.deployment_id}"
            or item.get("repository_url")
            != f"{_GITHUB_API_ROOT}/repos/{plan.repository}"
        ):
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                "existing success Deployment Status differs from exact ADR-DC-085 plan"
            )
        _utc(created_at, name="success_status_created_at_utc")
        _utc(updated_at, name="success_status_updated_at_utc")
        return _RemoteStagingSuccessStatusState(
            repository=plan.repository,
            repository_id=plan.repository_id,
            deployment_id=plan.deployment_id,
            deployment_node_id_sha256=plan.deployment_node_id_sha256,
            current_deployment_status_id=plan.current_deployment_status_id,
            current_deployment_status_node_id_sha256=(
                plan.current_deployment_status_node_id_sha256
            ),
            success_deployment_status_id=status_id,
            success_deployment_status_node_id_sha256=self._node_hash(
                node_id, name="success Deployment Status node identity"
            ),
            observed_success_status_state=plan.success_deployment_status_state,
            observed_success_status_environment=plan.success_deployment_status_environment,
            observed_success_status_description_sha256=_sha256_text(description),
            observed_success_status_log_url=None,
            observed_success_status_environment_url=None,
            success_status_created_at_utc=created_at,
            success_status_updated_at_utc=updated_at,
            remote_state_class="exact-existing",
        )

    def observe(
        self,
        plan: PilotExactTaskStagingSuccessStatusPlanReceipt,
    ) -> _RemoteStagingSuccessStatusState:
        if type(plan) is not PilotExactTaskStagingSuccessStatusPlanReceipt:
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                "exact ADR-DC-085 success-status plan is required"
            )
        if (
            self.credential.repository != plan.repository
            or self.credential.repository_id != plan.repository_id
        ):
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                "publisher credential is not bound to exact success-status repository"
            )
        self._verify_repository(plan)
        self._verify_parent_deployment(plan)
        statuses = self._list_statuses(plan)
        if not statuses:
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                "attested in_progress status disappeared from staging Deployment"
            )
        current = [
            item
            for item in statuses
            if item.get("id") == plan.current_deployment_status_id
        ]
        if len(current) != 1:
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                "exact current in_progress status is missing or duplicated"
            )
        self._verify_current_status(plan, current[0])
        if len(statuses) == 1:
            return _RemoteStagingSuccessStatusState(
                repository=plan.repository,
                repository_id=plan.repository_id,
                deployment_id=plan.deployment_id,
                deployment_node_id_sha256=plan.deployment_node_id_sha256,
                current_deployment_status_id=plan.current_deployment_status_id,
                current_deployment_status_node_id_sha256=(
                    plan.current_deployment_status_node_id_sha256
                ),
                success_deployment_status_id=None,
                success_deployment_status_node_id_sha256=None,
                observed_success_status_state=None,
                observed_success_status_environment=None,
                observed_success_status_description_sha256=None,
                observed_success_status_log_url=None,
                observed_success_status_environment_url=None,
                success_status_created_at_utc=None,
                success_status_updated_at_utc=None,
                remote_state_class="clear",
            )
        other = [item for item in statuses if item is not current[0]]
        if len(other) != 1:
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                "success-status inventory is ambiguous"
            )
        return self._success_projection(plan, other[0])


def _normalize_remote_state(
    value: Any,
    plan: PilotExactTaskStagingSuccessStatusPlanReceipt,
) -> _RemoteStagingSuccessStatusState:
    if type(value) is not _RemoteStagingSuccessStatusState:
        raise PilotExactTaskStagingSuccessStatusStateObservationError(
            "success-status observer returned invalid state"
        )
    if (
        value.repository != plan.repository
        or value.repository_id != plan.repository_id
        or value.deployment_id != plan.deployment_id
        or value.deployment_node_id_sha256 != plan.deployment_node_id_sha256
        or value.current_deployment_status_id != plan.current_deployment_status_id
        or value.current_deployment_status_node_id_sha256
        != plan.current_deployment_status_node_id_sha256
    ):
        raise PilotExactTaskStagingSuccessStatusStateObservationError(
            "success-status target identity mismatch"
        )
    if value.remote_state_class == "exact-existing":
        if (
            value.observed_success_status_state != plan.success_deployment_status_state
            or value.observed_success_status_environment
            != plan.success_deployment_status_environment
            or value.observed_success_status_description_sha256
            != plan.success_deployment_status_description_sha256
            or value.observed_success_status_log_url is not None
            or value.observed_success_status_environment_url is not None
        ):
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                "exact-existing success status differs from frozen plan"
            )
    return value


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: Any,
        *,
        plan: PilotExactTaskStagingSuccessStatusPlanReceipt,
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
            or plan.sha256 != receipt.staging_success_status_plan_sha256
            or receipt.remote_success_status_state_sha256 != remote_sha
        ):
            return None
        return MappingProxyType(
            {
                "staging_success_status_plan": plan,
                "remote_success_status_state_sha256": remote_sha,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_staging_success_status_state_observation_authenticated,
    _get_live_staging_success_status_state_observation_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskStagingSuccessStatusStateObservationReceipt:
    staging_success_status_plan_sha256: str
    staging_runtime_build_identity_sha256: str
    success_deployment_status_intent_sha256: str
    deployment_status_intent_sha256: str
    status_transaction_lock_sha256: str
    status_recovery_lock_sha256: str | None
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    repository: str
    repository_id: str
    deployment_id: int
    deployment_node_id_sha256: str
    merge_commit_sha: str
    current_deployment_status_id: int
    current_deployment_status_node_id_sha256: str
    success_deployment_status_state_planned: str
    success_deployment_status_environment_planned: str
    success_deployment_status_description_sha256: str
    success_deployment_status_body_sha256: str
    remote_success_status_state_sha256: str
    remote_state_class: str
    success_deployment_status_id: int | None
    success_deployment_status_node_id_sha256: str | None
    observed_success_status_state: str | None
    observed_success_status_environment: str | None
    observed_success_status_description_sha256: str | None
    observed_success_status_log_url: str | None
    observed_success_status_environment_url: str | None
    success_status_created_at_utc: str | None
    success_status_updated_at_utc: str | None
    source_planned_at_utc: str
    observed_at_utc: str
    plan_authenticated: bool = True
    parent_deployment_verified: bool = True
    remote_repository_verified: bool = True
    current_in_progress_status_verified: bool = True
    status_inventory_bounded: bool = True
    success_status_state_verified: bool = True
    double_observation_matched: bool = True
    success_status_lane_clear: bool = False
    exact_existing_success_status: bool = False
    success_status_state_acceptable: bool = True
    success_deployment_status_ready: bool = True
    success_deployment_status_authorized: bool = False
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
    observation_scope: str = PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_STATE_OBSERVATION_SCOPE
    authority: str = PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_STATE_OBSERVATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_STATE_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_STATE_OBSERVATION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_STATE_OBSERVATION_AUTHORITY
            or self.observation_scope
            != PILOT_EXACT_TASK_STAGING_SUCCESS_STATUS_STATE_OBSERVATION_SCOPE
        ):
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                "success-status observation identity is unsupported"
            )
        for name in (
            "staging_success_status_plan_sha256",
            "staging_runtime_build_identity_sha256",
            "success_deployment_status_intent_sha256",
            "deployment_status_intent_sha256",
            "status_transaction_lock_sha256",
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
            or self.success_deployment_status_state_planned != "success"
            or self.success_deployment_status_environment_planned != "staging"
            or self.remote_state_class not in _ALLOWED_CLASSES
        ):
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                "success-status observation source projection is invalid"
            )
        if self.remote_state_class == "clear":
            if (
                self.success_deployment_status_id is not None
                or self.success_deployment_status_node_id_sha256 is not None
                or self.observed_success_status_state is not None
                or self.observed_success_status_environment is not None
                or self.observed_success_status_description_sha256 is not None
                or self.observed_success_status_log_url is not None
                or self.observed_success_status_environment_url is not None
                or self.success_status_created_at_utc is not None
                or self.success_status_updated_at_utc is not None
                or self.success_status_lane_clear is not True
                or self.exact_existing_success_status is not False
            ):
                raise PilotExactTaskStagingSuccessStatusStateObservationError(
                    "clear success-status observation is inconsistent"
                )
        else:
            if (
                isinstance(self.success_deployment_status_id, bool)
                or not isinstance(self.success_deployment_status_id, int)
                or self.success_deployment_status_id < 1
                or self.success_deployment_status_node_id_sha256 is None
                or self.observed_success_status_state
                != self.success_deployment_status_state_planned
                or self.observed_success_status_environment
                != self.success_deployment_status_environment_planned
                or self.observed_success_status_description_sha256
                != self.success_deployment_status_description_sha256
                or self.observed_success_status_log_url is not None
                or self.observed_success_status_environment_url is not None
                or self.success_status_created_at_utc is None
                or self.success_status_updated_at_utc is None
                or self.success_status_lane_clear is not False
                or self.exact_existing_success_status is not True
            ):
                raise PilotExactTaskStagingSuccessStatusStateObservationError(
                    "exact-existing success-status observation is inconsistent"
                )
            _hex64(
                self.success_deployment_status_node_id_sha256,
                name="success_deployment_status_node_id_sha256",
            )
            _hex64(
                self.observed_success_status_description_sha256,
                name="observed_success_status_description_sha256",
            )
            if _utc(
                self.success_status_updated_at_utc,
                name="success_status_updated_at_utc",
            ) < _utc(
                self.success_status_created_at_utc,
                name="success_status_created_at_utc",
            ):
                raise PilotExactTaskStagingSuccessStatusStateObservationError(
                    "observed success-status timestamps are inconsistent"
                )
        if _utc(self.observed_at_utc, name="observed_at_utc") < _utc(
            self.source_planned_at_utc,
            name="source_planned_at_utc",
        ):
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                "success-status observation predates ADR-DC-085 plan"
            )
        required_true = (
            "plan_authenticated",
            "parent_deployment_verified",
            "remote_repository_verified",
            "current_in_progress_status_verified",
            "status_inventory_bounded",
            "success_status_state_verified",
            "double_observation_matched",
            "success_status_state_acceptable",
            "success_deployment_status_ready",
        )
        forced_false = (
            "success_deployment_status_authorized",
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
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                "success-status observation evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                "success-status observation retains forbidden authority"
            )

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())

    @property
    def observation_authenticated(self) -> bool:
        return _get_live_staging_success_status_state_observation_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskStagingSuccessStatusStateObservationError(
                "success-status observation receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _observe_verified_pilot_exact_task_staging_success_status_state(
    *,
    staging_success_status_plan: PilotExactTaskStagingSuccessStatusPlanReceipt,
    transport: Any,
    now_provider: Callable[[], str],
) -> PilotExactTaskStagingSuccessStatusStateObservationReceipt:
    plan = _require_live_plan(staging_success_status_plan)
    if transport is None or not callable(getattr(transport, "observe", None)):
        raise PilotExactTaskStagingSuccessStatusStateObservationError(
            "fresh success-status observer is required"
        )
    if (
        getattr(transport, "credential_config_sha256", None)
        != plan.publisher_credential_config_sha256
        or getattr(transport, "credential_path_sha256", None)
        != plan.publisher_credential_path_sha256
    ):
        raise PilotExactTaskStagingSuccessStatusStateObservationError(
            "success-status observer credential identity differs from ADR-DC-085"
        )
    first = _normalize_remote_state(transport.observe(plan), plan)
    second = _normalize_remote_state(transport.observe(plan), plan)
    if first != second:
        raise PilotExactTaskStagingSuccessStatusStateObservationError(
            "GitHub success-status state changed between observations"
        )
    observed_at = now_provider()
    if _utc(observed_at, name="observed_at_utc") < _utc(
        plan.planned_at_utc,
        name="source_planned_at_utc",
    ):
        raise PilotExactTaskStagingSuccessStatusStateObservationError(
            "system clock moved backwards before success-status observation"
        )
    remote_sha = first.sha256
    receipt = PilotExactTaskStagingSuccessStatusStateObservationReceipt(
        staging_success_status_plan_sha256=plan.sha256,
        staging_runtime_build_identity_sha256=plan.staging_runtime_build_identity_sha256,
        success_deployment_status_intent_sha256=plan.success_deployment_status_intent_sha256,
        deployment_status_intent_sha256=plan.deployment_status_intent_sha256,
        status_transaction_lock_sha256=plan.status_transaction_lock_sha256,
        status_recovery_lock_sha256=plan.status_recovery_lock_sha256,
        publisher_credential_config_sha256=plan.publisher_credential_config_sha256,
        publisher_credential_path_sha256=plan.publisher_credential_path_sha256,
        repository=plan.repository,
        repository_id=plan.repository_id,
        deployment_id=plan.deployment_id,
        deployment_node_id_sha256=plan.deployment_node_id_sha256,
        merge_commit_sha=plan.merge_commit_sha,
        current_deployment_status_id=plan.current_deployment_status_id,
        current_deployment_status_node_id_sha256=(
            plan.current_deployment_status_node_id_sha256
        ),
        success_deployment_status_state_planned=plan.success_deployment_status_state,
        success_deployment_status_environment_planned=(
            plan.success_deployment_status_environment
        ),
        success_deployment_status_description_sha256=(
            plan.success_deployment_status_description_sha256
        ),
        success_deployment_status_body_sha256=plan.success_deployment_status_body_sha256,
        remote_success_status_state_sha256=remote_sha,
        remote_state_class=first.remote_state_class,
        success_deployment_status_id=first.success_deployment_status_id,
        success_deployment_status_node_id_sha256=(
            first.success_deployment_status_node_id_sha256
        ),
        observed_success_status_state=first.observed_success_status_state,
        observed_success_status_environment=first.observed_success_status_environment,
        observed_success_status_description_sha256=(
            first.observed_success_status_description_sha256
        ),
        observed_success_status_log_url=first.observed_success_status_log_url,
        observed_success_status_environment_url=(
            first.observed_success_status_environment_url
        ),
        success_status_created_at_utc=first.success_status_created_at_utc,
        success_status_updated_at_utc=first.success_status_updated_at_utc,
        source_planned_at_utc=plan.planned_at_utc,
        observed_at_utc=observed_at,
        success_status_lane_clear=(first.remote_state_class == "clear"),
        exact_existing_success_status=(first.remote_state_class == "exact-existing"),
    )
    _mark_staging_success_status_state_observation_authenticated(
        receipt,
        plan=plan,
        remote_state_sha256=remote_sha,
    )
    if receipt.observation_authenticated is not True:
        raise PilotExactTaskStagingSuccessStatusStateObservationError(
            "success-status observation lost live provenance"
        )
    return receipt


def observe_pilot_exact_task_staging_success_status_state(
    staging_success_status_plan: PilotExactTaskStagingSuccessStatusPlanReceipt,
) -> PilotExactTaskStagingSuccessStatusStateObservationReceipt:
    """Observe the exact staging success-status lane without remote mutation."""
    plan = _require_live_plan(staging_success_status_plan)
    credential, credential_digest, credential_path = (
        publication_tx_boundary._canonical_credential()
    )
    transport = _GitHubStagingSuccessStatusStateObserver(
        credential=credential,
        credential_config_sha256=credential_digest,
        credential_path=credential_path,
    )
    return _observe_verified_pilot_exact_task_staging_success_status_state(
        staging_success_status_plan=plan,
        transport=transport,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []
