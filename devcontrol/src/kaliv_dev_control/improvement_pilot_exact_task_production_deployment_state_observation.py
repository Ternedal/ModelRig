"""ADR-DC-093 read-only exact production Deployment state observation.

Consumes one fresh live ADR-DC-092 production Deployment plan, verifies the
repository and exact merge commit through credential-bound GETs, then observes
the deterministic production/ref/task Deployment lane twice.

Only ``clear`` or one fully exact-existing Deployment is accepted. Duplicate,
partial, conflicting or mismatched remote state fails closed. No remote mutation
or production activation authority is granted.
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
from . import improvement_pilot_exact_task_production_deployment_plan as plan_boundary
from . import improvement_pilot_exact_task_remote_publication_transaction as publication_tx_boundary
from .improvement_pilot_exact_task_production_deployment_plan import (
    PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_PLAN_AUTHORITY,
    PilotExactTaskProductionDeploymentPlanReceipt,
)
from .improvement_pilot_exact_task_remote_publication_transaction import (
    PilotExactTaskGitHubPublisherCredential,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_STATE_OBSERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-production-deployment-state-observation-receipt/v1"
)
PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_STATE_OBSERVATION_AUTHORITY = (
    "host-observed-one-dc-l16-exact-production-deployment-state-only"
)
PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_STATE_OBSERVATION_SCOPE = (
    "exact-remote-production-deployment-state-observation-only-v1"
)

_GITHUB_API_ROOT = "https://api.github.com"
_MAX_API_RESPONSE_BYTES = 4 * 1024 * 1024
_DEPLOYMENT_PAGE_SIZE = 100
_MAX_DEPLOYMENT_PAGES = 10
_TIMEOUT_SECONDS = 30.0
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ALLOWED_STATES = {"absent", "exact"}
_ALLOWED_CLASSES = {"clear", "exact-existing"}


class PilotExactTaskProductionDeploymentStateObservationError(ValueError):
    """Production Deployment plan or remote state is stale/conflicting/unsafe."""


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
        raise PilotExactTaskProductionDeploymentStateObservationError(
            "production deployment-state evidence is not canonical JSON"
        ) from exc


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskProductionDeploymentStateObservationError(
            f"{name} is invalid"
        )
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskProductionDeploymentStateObservationError(
            f"{name} is invalid"
        )
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskProductionDeploymentStateObservationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskProductionDeploymentStateObservationError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _require_live_plan(
    value: Any,
) -> tuple[PilotExactTaskProductionDeploymentPlanReceipt, Any]:
    if type(value) is not PilotExactTaskProductionDeploymentPlanReceipt:
        raise PilotExactTaskProductionDeploymentStateObservationError(
            "exact live ADR-DC-092 production plan is required"
        )
    try:
        replayed = PilotExactTaskProductionDeploymentPlanReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskProductionDeploymentStateObservationError(
            "ADR-DC-092 replay validation failed"
        ) from exc
    required_true = (
        "staging_completion_readiness_authenticated",
        "production_plan_config_host_pinned",
        "readiness_fresh_verified",
        "exact_merge_commit_bound",
        "exact_runtime_build_identity_bound",
        "exact_staging_success_bound",
        "production_deployment_intent_materialized",
        "production_deployment_planned",
        "production_deployment_ready",
    )
    forced_false = (
        "production_promotion_authorized",
        "production_deployment_authorized",
        "production_activation_authorized",
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
        "product_pilot_started",
        "nonce_reusable",
    )
    if (
        replayed != value
        or replayed.sha256 != value.sha256
        or value.authority != PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_PLAN_AUTHORITY
        or value.plan_authenticated is not True
        or value.production_deployment_environment != "production"
        or value.production_deployment_ref != value.merge_commit_sha
        or value.production_deployment_task != "deploy"
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
    ):
        raise PilotExactTaskProductionDeploymentStateObservationError(
            "ADR-DC-093 requires one fresh inert ADR-DC-092 plan"
        )
    if value.source_completion_source == "transaction":
        if (
            value.source_completion_action != "execute_exact_staging_success_status"
            or value.source_remote_write_performed is not True
        ):
            raise PilotExactTaskProductionDeploymentStateObservationError(
                "transaction provenance is inconsistent"
            )
    elif value.source_completion_source == "recovery":
        if (
            value.source_completion_action != "finalize_existing_state"
            or value.source_remote_write_performed is not False
        ):
            raise PilotExactTaskProductionDeploymentStateObservationError(
                "recovery provenance is inconsistent"
            )
    else:
        raise PilotExactTaskProductionDeploymentStateObservationError(
            "completion provenance source is unsupported"
        )
    live = plan_boundary._get_live_production_deployment_plan_inputs(value)
    if live is None:
        raise PilotExactTaskProductionDeploymentStateObservationError(
            "ADR-DC-092 live provenance is unavailable"
        )
    readiness = live.get("staging_completion_readiness")
    if (
        readiness is None
        or getattr(readiness, "evaluation_authenticated", False) is not True
        or getattr(readiness, "sha256", None)
        != value.staging_completion_readiness_sha256
    ):
        raise PilotExactTaskProductionDeploymentStateObservationError(
            "ADR-DC-092 live readiness provenance mismatch"
        )
    return value, readiness


@dataclass(frozen=True, slots=True)
class _RemoteProductionDeploymentState:
    repository: str
    repository_id: str
    merge_commit_sha: str
    deployment_environment: str
    deployment_ref: str
    deployment_task: str
    deployment_state: str
    deployment_id: int | None
    deployment_node_id_sha256: str | None
    deployment_sha: str | None
    observed_payload_sha256: str | None
    observed_description_sha256: str | None
    transient_environment: bool | None
    production_environment: bool | None
    remote_state_class: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.deployment_environment != "production"
            or self.deployment_ref != self.merge_commit_sha
            or self.deployment_task != "deploy"
            or self.deployment_state not in _ALLOWED_STATES
            or self.remote_state_class not in _ALLOWED_CLASSES
        ):
            raise PilotExactTaskProductionDeploymentStateObservationError(
                "remote production deployment projection is invalid"
            )
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        if self.remote_state_class == "clear":
            if (
                self.deployment_state != "absent"
                or self.deployment_id is not None
                or self.deployment_node_id_sha256 is not None
                or self.deployment_sha is not None
                or self.observed_payload_sha256 is not None
                or self.observed_description_sha256 is not None
                or self.transient_environment is not None
                or self.production_environment is not None
            ):
                raise PilotExactTaskProductionDeploymentStateObservationError(
                    "clear production deployment projection is inconsistent"
                )
        else:
            if (
                self.deployment_state != "exact"
                or isinstance(self.deployment_id, bool)
                or not isinstance(self.deployment_id, int)
                or self.deployment_id < 1
                or self.deployment_node_id_sha256 is None
                or self.deployment_sha != self.merge_commit_sha
                or self.observed_payload_sha256 is None
                or self.observed_description_sha256 is None
                or self.transient_environment is not False
                or self.production_environment is not True
            ):
                raise PilotExactTaskProductionDeploymentStateObservationError(
                    "exact-existing production deployment projection is inconsistent"
                )
            _hex64(self.deployment_node_id_sha256, name="deployment_node_id_sha256")
            _hex64(self.observed_payload_sha256, name="observed_payload_sha256")
            _hex64(
                self.observed_description_sha256,
                name="observed_description_sha256",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @property
    def sha256(self) -> str:
        return _sha_text(_canonical(self.to_dict()))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _GitHubProductionDeploymentStateObserver:
    """Credential-bound GET-only observer for exact production Deployment state."""

    def __init__(
        self,
        *,
        credential: PilotExactTaskGitHubPublisherCredential,
        credential_config_sha256: str,
        credential_path: Path,
    ) -> None:
        if type(credential) is not PilotExactTaskGitHubPublisherCredential:
            raise PilotExactTaskProductionDeploymentStateObservationError(
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
            raise PilotExactTaskProductionDeploymentStateObservationError(
                "publisher credential path is unsafe"
            )
        self.credential_path_sha256 = _path_sha256(self.credential_path)
        self._opener = urllib.request.build_opener(_NoRedirect())

    @staticmethod
    def _repo_root(plan: PilotExactTaskProductionDeploymentPlanReceipt) -> str:
        owner, repo = plan.repository.split("/", 1)
        return "/repos/{}/{}".format(
            urllib.parse.quote(owner, safe=""),
            urllib.parse.quote(repo, safe=""),
        )

    def _api_json(
        self,
        *,
        plan: PilotExactTaskProductionDeploymentPlanReceipt,
        path: str,
    ) -> Any:
        root = self._repo_root(plan)
        if (
            not isinstance(path, str)
            or not (path == root or path.startswith(root + "/"))
            or ".." in path
        ):
            raise PilotExactTaskProductionDeploymentStateObservationError(
                "production deployment-state GET is outside exact GitHub scope"
            )
        url = _GITHUB_API_ROOT + path
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.credential.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "ModelRig-DevControl-ExactProductionDeploymentState/1",
            },
        )
        try:
            response = self._opener.open(request, timeout=_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            raise PilotExactTaskProductionDeploymentStateObservationError(
                f"GitHub production deployment-state GET failed with HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PilotExactTaskProductionDeploymentStateObservationError(
                "GitHub production deployment-state GET failed"
            ) from exc
        with response:
            if response.status != 200 or response.geturl() != url:
                raise PilotExactTaskProductionDeploymentStateObservationError(
                    "GitHub production deployment-state response identity/status is unexpected"
                )
            raw = response.read(_MAX_API_RESPONSE_BYTES + 1)
        if not raw or len(raw) > _MAX_API_RESPONSE_BYTES:
            raise PilotExactTaskProductionDeploymentStateObservationError(
                "GitHub production deployment-state response size is invalid"
            )
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PilotExactTaskProductionDeploymentStateObservationError(
                "GitHub production deployment-state response is invalid JSON"
            ) from exc

    @staticmethod
    def _node_hash(value: Any) -> str:
        if not isinstance(value, str) or not value:
            raise PilotExactTaskProductionDeploymentStateObservationError(
                "GitHub Deployment node identity is invalid"
            )
        return _sha_text(value)

    @staticmethod
    def _payload_sha(value: Any) -> str:
        if isinstance(value, str):
            return _sha_text(value)
        if isinstance(value, (Mapping, list)):
            return _sha_text(_canonical(value))
        raise PilotExactTaskProductionDeploymentStateObservationError(
            "GitHub Deployment payload has unsupported shape"
        )

    def _verify_repository_and_commit(
        self,
        plan: PilotExactTaskProductionDeploymentPlanReceipt,
    ) -> None:
        root = self._repo_root(plan)
        repository = self._api_json(plan=plan, path=root)
        if (
            not isinstance(repository, Mapping)
            or str(repository.get("id")) != plan.repository_id
            or repository.get("full_name") != plan.repository
        ):
            raise PilotExactTaskProductionDeploymentStateObservationError(
                "GitHub repository identity changed before production observation"
            )
        commit = self._api_json(
            plan=plan,
            path=f"{root}/commits/{plan.merge_commit_sha}",
        )
        if not isinstance(commit, Mapping) or commit.get("sha") != plan.merge_commit_sha:
            raise PilotExactTaskProductionDeploymentStateObservationError(
                "exact production merge commit no longer resolves"
            )

    def _list_lane(
        self,
        plan: PilotExactTaskProductionDeploymentPlanReceipt,
    ) -> list[Mapping[str, Any]]:
        root = self._repo_root(plan)
        items: list[Mapping[str, Any]] = []
        exhausted = False
        for page in range(1, _MAX_DEPLOYMENT_PAGES + 1):
            query = urllib.parse.urlencode(
                {
                    "sha": plan.merge_commit_sha,
                    "ref": plan.production_deployment_ref,
                    "task": plan.production_deployment_task,
                    "environment": plan.production_deployment_environment,
                    "per_page": _DEPLOYMENT_PAGE_SIZE,
                    "page": page,
                }
            )
            payload = self._api_json(
                plan=plan,
                path=f"{root}/deployments?{query}",
            )
            if not isinstance(payload, list):
                raise PilotExactTaskProductionDeploymentStateObservationError(
                    "GitHub Deployment inventory is not an array"
                )
            for item in payload:
                if not isinstance(item, Mapping):
                    raise PilotExactTaskProductionDeploymentStateObservationError(
                        "GitHub Deployment inventory entry is invalid"
                    )
                items.append(item)
            if len(payload) < _DEPLOYMENT_PAGE_SIZE:
                exhausted = True
                break
        if not exhausted:
            raise PilotExactTaskProductionDeploymentStateObservationError(
                "production Deployment inventory exceeded bounded pagination"
            )
        return items

    def observe(
        self,
        plan: PilotExactTaskProductionDeploymentPlanReceipt,
    ) -> _RemoteProductionDeploymentState:
        self._verify_repository_and_commit(plan)
        items = self._list_lane(plan)
        if not items:
            return _RemoteProductionDeploymentState(
                repository=plan.repository,
                repository_id=plan.repository_id,
                merge_commit_sha=plan.merge_commit_sha,
                deployment_environment="production",
                deployment_ref=plan.production_deployment_ref,
                deployment_task="deploy",
                deployment_state="absent",
                deployment_id=None,
                deployment_node_id_sha256=None,
                deployment_sha=None,
                observed_payload_sha256=None,
                observed_description_sha256=None,
                transient_environment=None,
                production_environment=None,
                remote_state_class="clear",
            )
        if len(items) != 1:
            raise PilotExactTaskProductionDeploymentStateObservationError(
                "multiple GitHub Deployments occupy deterministic production lane"
            )
        item = items[0]
        deployment_id = item.get("id")
        if isinstance(deployment_id, bool) or not isinstance(deployment_id, int) or deployment_id < 1:
            raise PilotExactTaskProductionDeploymentStateObservationError(
                "GitHub production Deployment ID is invalid"
            )
        projection = _RemoteProductionDeploymentState(
            repository=plan.repository,
            repository_id=plan.repository_id,
            merge_commit_sha=plan.merge_commit_sha,
            deployment_environment=str(item.get("environment")),
            deployment_ref=str(item.get("ref")),
            deployment_task=str(item.get("task")),
            deployment_state="exact",
            deployment_id=deployment_id,
            deployment_node_id_sha256=self._node_hash(item.get("node_id")),
            deployment_sha=str(item.get("sha")),
            observed_payload_sha256=self._payload_sha(item.get("payload")),
            observed_description_sha256=_sha_text(str(item.get("description"))),
            transient_environment=item.get("transient_environment"),
            production_environment=item.get("production_environment"),
            remote_state_class="exact-existing",
        )
        if (
            projection.deployment_sha != plan.merge_commit_sha
            or projection.observed_payload_sha256 != plan.production_deployment_payload_sha256
            or projection.observed_description_sha256
            != plan.production_deployment_description_sha256
            or projection.deployment_ref != plan.production_deployment_ref
            or projection.deployment_environment != "production"
            or projection.deployment_task != "deploy"
        ):
            raise PilotExactTaskProductionDeploymentStateObservationError(
                "existing production Deployment does not exactly match frozen plan"
            )
        return projection


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(receipt: Any, *, plan: Any, remote_sha256: str) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            weakref.ref(plan),
            remote_sha256,
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
            or plan.sha256 != receipt.production_deployment_plan_sha256
            or receipt.remote_production_deployment_state_sha256 != remote_sha
        ):
            return None
        return MappingProxyType(
            {"production_deployment_plan": plan, "remote_state_sha256": remote_sha}
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_production_deployment_state_observation_authenticated,
    _get_live_production_deployment_state_observation_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskProductionDeploymentStateObservationReceipt:
    production_deployment_plan_sha256: str
    staging_completion_readiness_sha256: str
    production_deployment_plan_config_sha256: str
    staging_runtime_build_identity_sha256: str
    production_deployment_intent_sha256: str
    production_deployment_payload_sha256: str
    production_deployment_description_sha256: str
    production_deployment_body_sha256: str
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    remote_production_deployment_state_sha256: str
    repository: str
    repository_id: str
    merge_commit_sha: str
    production_deployment_identity: str
    deployment_environment: str
    deployment_ref: str
    deployment_task: str
    deployment_state: str
    deployment_id: int | None
    deployment_node_id_sha256: str | None
    deployment_sha: str | None
    observed_payload_sha256: str | None
    observed_description_sha256: str | None
    transient_environment: bool | None
    production_environment: bool | None
    remote_state_class: str
    source_staging_deployment_id: int
    source_success_status_id: int
    source_completion_source: str
    source_completion_action: str
    source_remote_write_performed: bool
    plan_planned_at_utc: str
    observed_at_utc: str
    production_deployment_plan_authenticated: bool = True
    remote_state_observed: bool = True
    remote_repository_verified: bool = True
    exact_merge_commit_verified: bool = True
    deployment_inventory_bounded: bool = True
    deployment_state_verified: bool = True
    double_observation_matched: bool = True
    deployment_state_acceptable: bool = True
    deployment_lane_clear: bool = False
    exact_existing_deployment: bool = False
    production_promotion_authorized: bool = False
    production_deployment_authorized: bool = False
    production_activation_authorized: bool = False
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
    product_pilot_started: bool = False
    nonce_reusable: bool = False
    observation_scope: str = PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_STATE_OBSERVATION_SCOPE
    authority: str = PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_STATE_OBSERVATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_STATE_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_STATE_OBSERVATION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_STATE_OBSERVATION_AUTHORITY
            or self.observation_scope
            != PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_STATE_OBSERVATION_SCOPE
        ):
            raise PilotExactTaskProductionDeploymentStateObservationError(
                "production deployment-state observation identity is unsupported"
            )
        for name in (
            "production_deployment_plan_sha256",
            "staging_completion_readiness_sha256",
            "production_deployment_plan_config_sha256",
            "staging_runtime_build_identity_sha256",
            "production_deployment_intent_sha256",
            "production_deployment_payload_sha256",
            "production_deployment_description_sha256",
            "production_deployment_body_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
            "remote_production_deployment_state_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.production_deployment_identity
            != f"modelrig-production-{self.merge_commit_sha}"
            or self.deployment_environment != "production"
            or self.deployment_ref != self.merge_commit_sha
            or self.deployment_task != "deploy"
            or self.deployment_state not in _ALLOWED_STATES
            or self.remote_state_class not in _ALLOWED_CLASSES
        ):
            raise PilotExactTaskProductionDeploymentStateObservationError(
                "production deployment-state projection is invalid"
            )
        if self.remote_state_class == "clear":
            if (
                self.deployment_state != "absent"
                or any(
                    value is not None
                    for value in (
                        self.deployment_id,
                        self.deployment_node_id_sha256,
                        self.deployment_sha,
                        self.observed_payload_sha256,
                        self.observed_description_sha256,
                        self.transient_environment,
                        self.production_environment,
                    )
                )
                or self.deployment_lane_clear is not True
                or self.exact_existing_deployment is not False
            ):
                raise PilotExactTaskProductionDeploymentStateObservationError(
                    "clear production deployment receipt is inconsistent"
                )
        else:
            if (
                self.deployment_state != "exact"
                or isinstance(self.deployment_id, bool)
                or not isinstance(self.deployment_id, int)
                or self.deployment_id < 1
                or self.deployment_node_id_sha256 is None
                or self.deployment_sha != self.merge_commit_sha
                or self.observed_payload_sha256
                != self.production_deployment_payload_sha256
                or self.observed_description_sha256
                != self.production_deployment_description_sha256
                or self.transient_environment is not False
                or self.production_environment is not True
                or self.deployment_lane_clear is not False
                or self.exact_existing_deployment is not True
            ):
                raise PilotExactTaskProductionDeploymentStateObservationError(
                    "exact-existing production deployment receipt is inconsistent"
                )
            _hex64(self.deployment_node_id_sha256, name="deployment_node_id_sha256")
        if self.source_completion_source == "transaction":
            if (
                self.source_completion_action != "execute_exact_staging_success_status"
                or self.source_remote_write_performed is not True
            ):
                raise PilotExactTaskProductionDeploymentStateObservationError(
                    "transaction provenance is inconsistent"
                )
        elif self.source_completion_source == "recovery":
            if (
                self.source_completion_action != "finalize_existing_state"
                or self.source_remote_write_performed is not False
            ):
                raise PilotExactTaskProductionDeploymentStateObservationError(
                    "recovery provenance is inconsistent"
                )
        else:
            raise PilotExactTaskProductionDeploymentStateObservationError(
                "completion provenance source is unsupported"
            )
        if (
            isinstance(self.source_staging_deployment_id, bool)
            or not isinstance(self.source_staging_deployment_id, int)
            or self.source_staging_deployment_id < 1
            or isinstance(self.source_success_status_id, bool)
            or not isinstance(self.source_success_status_id, int)
            or self.source_success_status_id < 1
        ):
            raise PilotExactTaskProductionDeploymentStateObservationError(
                "source staging identity is invalid"
            )
        if _utc(self.observed_at_utc, name="observed_at_utc") < _utc(
            self.plan_planned_at_utc,
            name="plan_planned_at_utc",
        ):
            raise PilotExactTaskProductionDeploymentStateObservationError(
                "production observation predates plan"
            )
        required_true = (
            "production_deployment_plan_authenticated",
            "remote_state_observed",
            "remote_repository_verified",
            "exact_merge_commit_verified",
            "deployment_inventory_bounded",
            "deployment_state_verified",
            "double_observation_matched",
            "deployment_state_acceptable",
        )
        forced_false = (
            "production_promotion_authorized",
            "production_deployment_authorized",
            "production_activation_authorized",
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
            "product_pilot_started",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskProductionDeploymentStateObservationError(
                "production deployment-state evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskProductionDeploymentStateObservationError(
                "production deployment-state observation retains forbidden authority"
            )

    @property
    def sha256(self) -> str:
        return _sha_text(self.canonical_json())

    @property
    def observation_authenticated(self) -> bool:
        return (
            _get_live_production_deployment_state_observation_inputs(self)
            is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(cls, value: Any):
        if (
            not isinstance(value, Mapping)
            or set(value) != set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        ):
            raise PilotExactTaskProductionDeploymentStateObservationError(
                "production deployment-state observation fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _normalize_remote_state(
    value: Any,
    plan: PilotExactTaskProductionDeploymentPlanReceipt,
) -> _RemoteProductionDeploymentState:
    if type(value) is not _RemoteProductionDeploymentState:
        raise PilotExactTaskProductionDeploymentStateObservationError(
            "production deployment observer returned invalid state"
        )
    if (
        value.repository != plan.repository
        or value.repository_id != plan.repository_id
        or value.merge_commit_sha != plan.merge_commit_sha
        or value.deployment_environment != "production"
        or value.deployment_ref != plan.production_deployment_ref
        or value.deployment_task != "deploy"
    ):
        raise PilotExactTaskProductionDeploymentStateObservationError(
            "production deployment remote identity differs from frozen plan"
        )
    if value.remote_state_class == "exact-existing":
        if (
            value.deployment_sha != plan.merge_commit_sha
            or value.observed_payload_sha256
            != plan.production_deployment_payload_sha256
            or value.observed_description_sha256
            != plan.production_deployment_description_sha256
            or value.transient_environment is not False
            or value.production_environment is not True
        ):
            raise PilotExactTaskProductionDeploymentStateObservationError(
                "existing production Deployment is not exact frozen plan"
            )
    return value


def _observe_verified_pilot_exact_task_production_deployment_state(
    *,
    production_deployment_plan: PilotExactTaskProductionDeploymentPlanReceipt,
    transport: Any,
    now_provider: Callable[[], str],
) -> PilotExactTaskProductionDeploymentStateObservationReceipt:
    plan, readiness = _require_live_plan(production_deployment_plan)
    if transport is None or not callable(getattr(transport, "observe", None)):
        raise PilotExactTaskProductionDeploymentStateObservationError(
            "read-only production deployment observer is required"
        )
    if (
        getattr(transport, "credential_config_sha256", None)
        != readiness.publisher_credential_config_sha256
        or getattr(transport, "credential_path_sha256", None)
        != readiness.publisher_credential_path_sha256
    ):
        raise PilotExactTaskProductionDeploymentStateObservationError(
            "observer credential identity differs from staging provenance"
        )
    try:
        first = _normalize_remote_state(transport.observe(plan), plan)
        second = _normalize_remote_state(transport.observe(plan), plan)
    except PilotExactTaskProductionDeploymentStateObservationError:
        raise
    except Exception as exc:
        raise PilotExactTaskProductionDeploymentStateObservationError(
            "production deployment observation failed"
        ) from exc
    if first != second:
        raise PilotExactTaskProductionDeploymentStateObservationError(
            "production Deployment state changed between observations"
        )
    observed_at = now_provider()
    if _utc(observed_at, name="observed_at_utc") < _utc(
        plan.planned_at_utc,
        name="plan_planned_at_utc",
    ):
        raise PilotExactTaskProductionDeploymentStateObservationError(
            "system clock moved backwards after ADR-DC-092"
        )
    receipt = PilotExactTaskProductionDeploymentStateObservationReceipt(
        production_deployment_plan_sha256=plan.sha256,
        staging_completion_readiness_sha256=plan.staging_completion_readiness_sha256,
        production_deployment_plan_config_sha256=(
            plan.production_deployment_plan_config_sha256
        ),
        staging_runtime_build_identity_sha256=plan.staging_runtime_build_identity_sha256,
        production_deployment_intent_sha256=plan.production_deployment_intent_sha256,
        production_deployment_payload_sha256=plan.production_deployment_payload_sha256,
        production_deployment_description_sha256=(
            plan.production_deployment_description_sha256
        ),
        production_deployment_body_sha256=plan.production_deployment_body_sha256,
        publisher_credential_config_sha256=readiness.publisher_credential_config_sha256,
        publisher_credential_path_sha256=readiness.publisher_credential_path_sha256,
        remote_production_deployment_state_sha256=first.sha256,
        repository=plan.repository,
        repository_id=plan.repository_id,
        merge_commit_sha=plan.merge_commit_sha,
        production_deployment_identity=plan.production_deployment_identity,
        deployment_environment="production",
        deployment_ref=plan.production_deployment_ref,
        deployment_task="deploy",
        deployment_state=first.deployment_state,
        deployment_id=first.deployment_id,
        deployment_node_id_sha256=first.deployment_node_id_sha256,
        deployment_sha=first.deployment_sha,
        observed_payload_sha256=first.observed_payload_sha256,
        observed_description_sha256=first.observed_description_sha256,
        transient_environment=first.transient_environment,
        production_environment=first.production_environment,
        remote_state_class=first.remote_state_class,
        source_staging_deployment_id=plan.source_staging_deployment_id,
        source_success_status_id=plan.source_success_status_id,
        source_completion_source=plan.source_completion_source,
        source_completion_action=plan.source_completion_action,
        source_remote_write_performed=plan.source_remote_write_performed,
        plan_planned_at_utc=plan.planned_at_utc,
        observed_at_utc=observed_at,
        deployment_lane_clear=first.remote_state_class == "clear",
        exact_existing_deployment=first.remote_state_class == "exact-existing",
    )
    _mark_production_deployment_state_observation_authenticated(
        receipt,
        plan=plan,
        remote_sha256=first.sha256,
    )
    if receipt.observation_authenticated is not True:
        raise PilotExactTaskProductionDeploymentStateObservationError(
            "production deployment observation lost live provenance"
        )
    return receipt


def observe_pilot_exact_task_production_deployment_state(
    production_deployment_plan: PilotExactTaskProductionDeploymentPlanReceipt,
) -> PilotExactTaskProductionDeploymentStateObservationReceipt:
    """Observe one exact production Deployment lane twice without mutation."""
    try:
        credential, credential_digest, credential_path = (
            publication_tx_boundary._canonical_credential()
        )
        transport = _GitHubProductionDeploymentStateObserver(
            credential=credential,
            credential_config_sha256=credential_digest,
            credential_path=credential_path,
        )
        return _observe_verified_pilot_exact_task_production_deployment_state(
            production_deployment_plan=production_deployment_plan,
            transport=transport,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskProductionDeploymentStateObservationError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskProductionDeploymentStateObservationError(
            "exact production Deployment observation failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_STATE_OBSERVATION_SCHEMA",
    "PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_STATE_OBSERVATION_AUTHORITY",
    "PILOT_EXACT_TASK_PRODUCTION_DEPLOYMENT_STATE_OBSERVATION_SCOPE",
    "PilotExactTaskProductionDeploymentStateObservationError",
    "PilotExactTaskProductionDeploymentStateObservationReceipt",
    "observe_pilot_exact_task_production_deployment_state",
]
