"""ADR-DC-072 read-only exact remote staging-deployment state observation.

This boundary accepts only one fresh live ADR-DC-071 staging deployment plan.
It revalidates the deterministic release tag, then observes the GitHub
Deployment inventory twice through a credential-bound GET-only transport.

Only two stable pre-write states are accepted:

* ``clear``: no deployment exists for the exact staging/ref/task lane.
* ``exact-existing``: exactly one deployment matches the frozen plan.

Partial, conflicting, duplicate, or mismatched state fails closed. No
Deployment, Deployment Status, release, tag, or other remote mutation is
performed and no deployment authority is granted.
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
from . import improvement_pilot_exact_task_staging_deployment_plan as plan_boundary
from . import improvement_pilot_exact_task_remote_publication_transaction as publication_tx_boundary
from .improvement_pilot_exact_task_staging_deployment_plan import (
    PILOT_EXACT_TASK_STAGING_DEPLOYMENT_PLAN_AUTHORITY,
    PilotExactTaskStagingDeploymentPlanReceipt,
)
from .improvement_pilot_exact_task_remote_publication_transaction import (
    PilotExactTaskGitHubPublisherCredential,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATE_OBSERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-staging-deployment-state-observation-receipt/v1"
)
PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATE_OBSERVATION_AUTHORITY = (
    "host-observed-one-dc-l16-exact-staging-deployment-state-only"
)
PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATE_OBSERVATION_SCOPE = (
    "exact-remote-staging-deployment-state-observation-only-v1"
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
_ALLOWED_DEPLOYMENT_STATES = {"absent", "exact"}
_ALLOWED_CLASSES = {"clear", "exact-existing"}


class PilotExactTaskStagingDeploymentStateObservationError(ValueError):
    """Deployment plan or observed remote state is stale, conflicting, or unsafe."""


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
        raise PilotExactTaskStagingDeploymentStateObservationError(
            "staging deployment-state evidence is not canonical JSON"
        ) from exc


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskStagingDeploymentStateObservationError(
            f"{name} is invalid"
        )
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskStagingDeploymentStateObservationError(
            f"{name} is invalid"
        )
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskStagingDeploymentStateObservationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskStagingDeploymentStateObservationError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _require_live_plan(
    value: Any,
) -> tuple[PilotExactTaskStagingDeploymentPlanReceipt, Any]:
    if type(value) is not PilotExactTaskStagingDeploymentPlanReceipt:
        raise PilotExactTaskStagingDeploymentStateObservationError(
            "exact live ADR-DC-071 staging deployment plan is required"
        )
    try:
        replayed = PilotExactTaskStagingDeploymentPlanReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskStagingDeploymentStateObservationError(
            "ADR-DC-071 replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskStagingDeploymentStateObservationError(
            "ADR-DC-071 staging deployment-plan identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_PLAN_AUTHORITY
        or value.plan_authenticated is not True
        or value.deploy_readiness_authenticated is not True
        or value.deploy_ready is not True
        or value.staging_deployment_plan_config_host_pinned is not True
        or value.deployment_intent_materialized is not True
        or value.deployment_creation_planned is not True
        or value.deployment_environment != "staging"
        or value.deployment_ref != value.tag_name
        or value.tag_target_sha != value.merge_commit_sha
        or value.deployment_task != "deploy"
        or value.auto_merge is not False
        or value.required_contexts != ()
        or value.transient_environment is not False
        or value.production_environment is not False
        or value.deploy_readiness_authorized is not False
        or value.deployment_mutation_authorized is not False
        or value.deploy_authorized is not False
        or value.remote_write_authorized is not False
        or value.release_authorized is not False
        or value.production_activation_authorized is not False
        or value.nonce_reusable is not False
    ):
        raise PilotExactTaskStagingDeploymentStateObservationError(
            "ADR-DC-072 requires one fresh inert ADR-DC-071 staging plan"
        )
    live = plan_boundary._get_live_staging_deployment_plan_inputs(value)
    if live is None:
        raise PilotExactTaskStagingDeploymentStateObservationError(
            "ADR-DC-071 live provenance is unavailable"
        )
    readiness = live.get("deploy_readiness_evaluation")
    if (
        readiness is None
        or getattr(readiness, "evaluation_authenticated", False) is not True
        or getattr(readiness, "sha256", None)
        != value.deploy_readiness_evaluation_sha256
    ):
        raise PilotExactTaskStagingDeploymentStateObservationError(
            "ADR-DC-071 live deploy-readiness provenance mismatch"
        )
    return value, readiness


@dataclass(frozen=True, slots=True)
class _RemoteStagingDeploymentState:
    repository: str
    repository_id: str
    tag_target_sha: str
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
            or self.deployment_environment != "staging"
            or self.deployment_task != "deploy"
            or not isinstance(self.deployment_ref, str)
            or not self.deployment_ref
            or self.deployment_state not in _ALLOWED_DEPLOYMENT_STATES
            or self.remote_state_class not in _ALLOWED_CLASSES
        ):
            raise PilotExactTaskStagingDeploymentStateObservationError(
                "remote staging deployment projection is invalid"
            )
        _hex40(self.tag_target_sha, name="tag_target_sha")
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
                raise PilotExactTaskStagingDeploymentStateObservationError(
                    "clear staging deployment projection is inconsistent"
                )
        else:
            if (
                self.deployment_state != "exact"
                or isinstance(self.deployment_id, bool)
                or not isinstance(self.deployment_id, int)
                or self.deployment_id < 1
                or self.deployment_node_id_sha256 is None
                or self.deployment_sha is None
                or self.observed_payload_sha256 is None
                or self.observed_description_sha256 is None
                or self.transient_environment is not False
                or self.production_environment is not False
            ):
                raise PilotExactTaskStagingDeploymentStateObservationError(
                    "exact-existing staging deployment projection is inconsistent"
                )
            _hex64(self.deployment_node_id_sha256, name="deployment_node_id_sha256")
            _hex40(self.deployment_sha, name="deployment_sha")
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
        return _sha256_text(_canonical(self.to_dict()))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _GitHubStagingDeploymentStateObserver:
    """Credential-bound GET-only observer for exact staging Deployment state."""

    def __init__(
        self,
        *,
        credential: PilotExactTaskGitHubPublisherCredential,
        credential_config_sha256: str,
        credential_path: Path,
    ) -> None:
        if type(credential) is not PilotExactTaskGitHubPublisherCredential:
            raise PilotExactTaskStagingDeploymentStateObservationError(
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
            raise PilotExactTaskStagingDeploymentStateObservationError(
                "publisher credential path is unsafe"
            )
        self.credential_path_sha256 = _path_sha256(self.credential_path)
        self._opener = urllib.request.build_opener(_NoRedirect())

    @staticmethod
    def _repo_root(plan: PilotExactTaskStagingDeploymentPlanReceipt) -> str:
        owner, repo = plan.repository.split("/", 1)
        return "/repos/{}/{}".format(
            urllib.parse.quote(owner, safe=""),
            urllib.parse.quote(repo, safe=""),
        )

    def _api_json(
        self,
        *,
        plan: PilotExactTaskStagingDeploymentPlanReceipt,
        path: str,
    ) -> Any:
        root = self._repo_root(plan)
        if (
            not isinstance(path, str)
            or not (path == root or path.startswith(root + "/"))
            or ".." in path
        ):
            raise PilotExactTaskStagingDeploymentStateObservationError(
                "staging deployment-state GET is outside exact GitHub scope"
            )
        url = _GITHUB_API_ROOT + path
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.credential.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "ModelRig-DevControl-ExactStagingDeploymentState/1",
            },
        )
        try:
            response = self._opener.open(request, timeout=_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            raise PilotExactTaskStagingDeploymentStateObservationError(
                f"GitHub staging deployment-state GET failed with HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PilotExactTaskStagingDeploymentStateObservationError(
                "GitHub staging deployment-state GET failed"
            ) from exc
        with response:
            if response.status != 200 or response.geturl() != url:
                raise PilotExactTaskStagingDeploymentStateObservationError(
                    "GitHub staging deployment-state response identity/status is unexpected"
                )
            raw = response.read(_MAX_API_RESPONSE_BYTES + 1)
        if not raw or len(raw) > _MAX_API_RESPONSE_BYTES:
            raise PilotExactTaskStagingDeploymentStateObservationError(
                "GitHub staging deployment-state response size is invalid"
            )
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PilotExactTaskStagingDeploymentStateObservationError(
                "GitHub staging deployment-state response is invalid JSON"
            ) from exc

    @staticmethod
    def _node_hash(value: Any) -> str:
        if not isinstance(value, str) or not value:
            raise PilotExactTaskStagingDeploymentStateObservationError(
                "GitHub Deployment node identity is invalid"
            )
        return _sha256_text(value)

    @staticmethod
    def _payload_sha(value: Any) -> str:
        if isinstance(value, str):
            return _sha256_text(value)
        if isinstance(value, (Mapping, list)):
            return _sha256_text(_canonical(value))
        raise PilotExactTaskStagingDeploymentStateObservationError(
            "GitHub Deployment payload has unsupported shape"
        )

    def _verify_exact_tag(
        self,
        plan: PilotExactTaskStagingDeploymentPlanReceipt,
    ) -> None:
        root = self._repo_root(plan)
        encoded = urllib.parse.quote(plan.tag_name, safe="")
        payload = self._api_json(
            plan=plan,
            path=f"{root}/git/ref/tags/{encoded}",
        )
        obj = payload.get("object") if isinstance(payload, Mapping) else None
        if (
            not isinstance(obj, Mapping)
            or obj.get("type") != "commit"
            or obj.get("sha") != plan.tag_target_sha
        ):
            raise PilotExactTaskStagingDeploymentStateObservationError(
                "deterministic release tag no longer proves exact deployment target"
            )

    def _list_exact_lane(
        self,
        plan: PilotExactTaskStagingDeploymentPlanReceipt,
    ) -> list[Mapping[str, Any]]:
        root = self._repo_root(plan)
        matches: list[Mapping[str, Any]] = []
        exhausted = False
        query_base = {
            "ref": plan.deployment_ref,
            "task": plan.deployment_task,
            "environment": plan.deployment_environment,
            "per_page": str(_DEPLOYMENT_PAGE_SIZE),
        }
        for page in range(1, _MAX_DEPLOYMENT_PAGES + 1):
            query = dict(query_base)
            query["page"] = str(page)
            path = f"{root}/deployments?{urllib.parse.urlencode(query)}"
            payload = self._api_json(plan=plan, path=path)
            if not isinstance(payload, list):
                raise PilotExactTaskStagingDeploymentStateObservationError(
                    "GitHub Deployment inventory response is invalid"
                )
            for item in payload:
                if not isinstance(item, Mapping):
                    raise PilotExactTaskStagingDeploymentStateObservationError(
                        "GitHub Deployment inventory contains invalid item"
                    )
                matches.append(item)
                if len(matches) > 1:
                    raise PilotExactTaskStagingDeploymentStateObservationError(
                        "multiple GitHub Deployments occupy deterministic staging lane"
                    )
            if len(payload) < _DEPLOYMENT_PAGE_SIZE:
                exhausted = True
                break
        if not exhausted:
            raise PilotExactTaskStagingDeploymentStateObservationError(
                "Deployment inventory exceeded bounded observation window"
            )
        return matches

    def _exact_projection(
        self,
        plan: PilotExactTaskStagingDeploymentPlanReceipt,
        item: Mapping[str, Any],
    ) -> _RemoteStagingDeploymentState:
        deployment_id = item.get("id")
        node_id = item.get("node_id")
        payload = item.get("payload")
        description = item.get("description")
        repository_url = item.get("repository_url")
        if (
            isinstance(deployment_id, bool)
            or not isinstance(deployment_id, int)
            or deployment_id < 1
            or not isinstance(node_id, str)
            or not node_id
            or item.get("sha") != plan.merge_commit_sha
            or item.get("ref") != plan.deployment_ref
            or item.get("task") != plan.deployment_task
            or item.get("environment") != plan.deployment_environment
            or description != plan.deployment_description
            or item.get("transient_environment") is not False
            or item.get("production_environment") is not False
            or repository_url != f"{_GITHUB_API_ROOT}/repos/{plan.repository}"
        ):
            raise PilotExactTaskStagingDeploymentStateObservationError(
                "existing GitHub Deployment differs from exact staging plan"
            )
        payload_sha = self._payload_sha(payload)
        if payload_sha != plan.deployment_payload_sha256:
            raise PilotExactTaskStagingDeploymentStateObservationError(
                "existing GitHub Deployment payload differs from exact staging plan"
            )
        return _RemoteStagingDeploymentState(
            repository=plan.repository,
            repository_id=plan.repository_id,
            tag_target_sha=plan.tag_target_sha,
            deployment_environment=plan.deployment_environment,
            deployment_ref=plan.deployment_ref,
            deployment_task=plan.deployment_task,
            deployment_state="exact",
            deployment_id=deployment_id,
            deployment_node_id_sha256=self._node_hash(node_id),
            deployment_sha=plan.merge_commit_sha,
            observed_payload_sha256=payload_sha,
            observed_description_sha256=_sha256_text(description),
            transient_environment=False,
            production_environment=False,
            remote_state_class="exact-existing",
        )

    def observe(
        self,
        plan: PilotExactTaskStagingDeploymentPlanReceipt,
    ) -> _RemoteStagingDeploymentState:
        if type(plan) is not PilotExactTaskStagingDeploymentPlanReceipt:
            raise PilotExactTaskStagingDeploymentStateObservationError(
                "exact ADR-DC-071 staging deployment plan is required"
            )
        if (
            self.credential.repository != plan.repository
            or self.credential.repository_id != plan.repository_id
        ):
            raise PilotExactTaskStagingDeploymentStateObservationError(
                "publisher credential is not bound to exact deployment repository"
            )
        root = self._repo_root(plan)
        repo = self._api_json(plan=plan, path=root)
        if (
            not isinstance(repo, Mapping)
            or str(repo.get("id")) != plan.repository_id
            or repo.get("full_name") != plan.repository
        ):
            raise PilotExactTaskStagingDeploymentStateObservationError(
                "GitHub repository identity differs from staging deployment plan"
            )
        self._verify_exact_tag(plan)
        matches = self._list_exact_lane(plan)
        if not matches:
            return _RemoteStagingDeploymentState(
                repository=plan.repository,
                repository_id=plan.repository_id,
                tag_target_sha=plan.tag_target_sha,
                deployment_environment=plan.deployment_environment,
                deployment_ref=plan.deployment_ref,
                deployment_task=plan.deployment_task,
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
        return self._exact_projection(plan, matches[0])


def _normalize_remote_state(
    value: Any,
    plan: PilotExactTaskStagingDeploymentPlanReceipt,
) -> _RemoteStagingDeploymentState:
    if type(value) is not _RemoteStagingDeploymentState:
        raise PilotExactTaskStagingDeploymentStateObservationError(
            "staging deployment-state observer returned invalid state"
        )
    if (
        value.repository != plan.repository
        or value.repository_id != plan.repository_id
        or value.tag_target_sha != plan.tag_target_sha
        or value.deployment_environment != plan.deployment_environment
        or value.deployment_ref != plan.deployment_ref
        or value.deployment_task != plan.deployment_task
    ):
        raise PilotExactTaskStagingDeploymentStateObservationError(
            "staging deployment-state target identity mismatch"
        )
    if value.remote_state_class == "exact-existing":
        if (
            value.deployment_sha != plan.merge_commit_sha
            or value.observed_payload_sha256 != plan.deployment_payload_sha256
            or value.observed_description_sha256
            != plan.deployment_description_sha256
            or value.transient_environment is not False
            or value.production_environment is not False
        ):
            raise PilotExactTaskStagingDeploymentStateObservationError(
                "exact-existing Deployment projection differs from frozen plan"
            )
    return value


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: Any,
        *,
        plan: PilotExactTaskStagingDeploymentPlanReceipt,
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
            or plan.sha256 != receipt.staging_deployment_plan_sha256
            or receipt.remote_deployment_state_sha256 != remote_sha
        ):
            return None
        return MappingProxyType(
            {
                "staging_deployment_plan": plan,
                "remote_deployment_state_sha256": remote_sha,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_staging_deployment_state_observation_authenticated,
    _get_live_staging_deployment_state_observation_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskStagingDeploymentStateObservationReceipt:
    staging_deployment_plan_sha256: str
    deploy_readiness_evaluation_sha256: str
    post_release_attestation_sha256: str
    deploy_readiness_policy_sha256: str
    staging_deployment_plan_config_sha256: str
    deployment_intent_sha256: str
    release_authorization_sha256: str
    release_intent_sha256: str
    release_plan_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    upstream_merge_transaction_lock_sha256: str
    release_transaction_lock_sha256: str
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    remote_deployment_state_sha256: str
    repository: str
    repository_id: str
    deployment_environment: str
    release_base_branch: str
    deployment_base_branch: str
    merge_commit_sha: str
    release_version: str
    tag_name: str
    tag_target_sha: str
    release_id: int
    release_node_id_sha256: str
    deployment_identity: str
    deployment_ref: str
    deployment_task: str
    deployment_payload_sha256: str
    deployment_description_sha256: str
    auto_merge: bool
    required_contexts: tuple[str, ...]
    transient_environment: bool
    production_environment: bool
    deployment_state: str
    deployment_id: int | None
    deployment_node_id_sha256: str | None
    deployment_sha: str | None
    observed_payload_sha256: str | None
    observed_description_sha256: str | None
    remote_state_class: str
    observed_at_utc: str
    staging_deployment_plan_authenticated: bool = True
    remote_state_observed: bool = True
    remote_repository_verified: bool = True
    exact_release_tag_verified: bool = True
    deployment_inventory_bounded: bool = True
    deployment_state_verified: bool = True
    double_observation_matched: bool = True
    deployment_lane_clear: bool = False
    exact_existing_deployment: bool = False
    deployment_state_acceptable: bool = True
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
    observation_scope: str = PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATE_OBSERVATION_SCOPE
    authority: str = PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATE_OBSERVATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATE_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATE_OBSERVATION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATE_OBSERVATION_AUTHORITY
            or self.observation_scope
            != PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATE_OBSERVATION_SCOPE
        ):
            raise PilotExactTaskStagingDeploymentStateObservationError(
                "staging deployment-state observation identity is unsupported"
            )
        for name in (
            "staging_deployment_plan_sha256",
            "deploy_readiness_evaluation_sha256",
            "post_release_attestation_sha256",
            "deploy_readiness_policy_sha256",
            "staging_deployment_plan_config_sha256",
            "deployment_intent_sha256",
            "release_authorization_sha256",
            "release_intent_sha256",
            "release_plan_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "pr_intent_sha256",
            "upstream_merge_transaction_lock_sha256",
            "release_transaction_lock_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
            "remote_deployment_state_sha256",
            "release_node_id_sha256",
            "deployment_payload_sha256",
            "deployment_description_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("merge_commit_sha", "tag_target_sha"):
            _hex40(getattr(self, name), name=name)
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.deployment_environment != "staging"
            or self.tag_target_sha != self.merge_commit_sha
            or self.deployment_ref != self.tag_name
            or self.deployment_task != "deploy"
            or self.auto_merge is not False
            or self.required_contexts != ()
            or self.transient_environment is not False
            or self.production_environment is not False
            or self.deployment_state not in _ALLOWED_DEPLOYMENT_STATES
            or self.remote_state_class not in _ALLOWED_CLASSES
            or isinstance(self.release_id, bool)
            or not isinstance(self.release_id, int)
            or self.release_id < 1
        ):
            raise PilotExactTaskStagingDeploymentStateObservationError(
                "staging deployment-state receipt projection is invalid"
            )
        if self.remote_state_class == "clear":
            if (
                self.deployment_state != "absent"
                or self.deployment_id is not None
                or self.deployment_node_id_sha256 is not None
                or self.deployment_sha is not None
                or self.observed_payload_sha256 is not None
                or self.observed_description_sha256 is not None
                or self.deployment_lane_clear is not True
                or self.exact_existing_deployment is not False
            ):
                raise PilotExactTaskStagingDeploymentStateObservationError(
                    "clear staging deployment-state receipt is inconsistent"
                )
        else:
            if (
                self.deployment_state != "exact"
                or isinstance(self.deployment_id, bool)
                or not isinstance(self.deployment_id, int)
                or self.deployment_id < 1
                or self.deployment_node_id_sha256 is None
                or self.deployment_sha != self.merge_commit_sha
                or self.observed_payload_sha256 != self.deployment_payload_sha256
                or self.observed_description_sha256
                != self.deployment_description_sha256
                or self.deployment_lane_clear is not False
                or self.exact_existing_deployment is not True
            ):
                raise PilotExactTaskStagingDeploymentStateObservationError(
                    "exact-existing staging deployment-state receipt is inconsistent"
                )
            _hex64(self.deployment_node_id_sha256, name="deployment_node_id_sha256")
            _hex64(self.observed_payload_sha256, name="observed_payload_sha256")
            _hex64(
                self.observed_description_sha256,
                name="observed_description_sha256",
            )
        _utc(self.observed_at_utc, name="observed_at_utc")
        required_true = (
            "staging_deployment_plan_authenticated",
            "remote_state_observed",
            "remote_repository_verified",
            "exact_release_tag_verified",
            "deployment_inventory_bounded",
            "deployment_state_verified",
            "double_observation_matched",
            "deployment_state_acceptable",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskStagingDeploymentStateObservationError(
                "staging deployment-state observation evidence is incomplete"
            )
        forced_false = (
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
            raise PilotExactTaskStagingDeploymentStateObservationError(
                "staging deployment-state observation retains forbidden authority"
            )

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())

    @property
    def observation_authenticated(self) -> bool:
        return _get_live_staging_deployment_state_observation_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        result = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }
        result["required_contexts"] = list(self.required_contexts)
        return result

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskStagingDeploymentStateObservationReceipt":
        if (
            not isinstance(value, Mapping)
            or set(value) != set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        ):
            raise PilotExactTaskStagingDeploymentStateObservationError(
                "staging deployment-state observation fields mismatch"
            )
        contexts = value.get("required_contexts")
        if not isinstance(contexts, list):
            raise PilotExactTaskStagingDeploymentStateObservationError(
                "staging deployment-state required_contexts must be an array"
            )
        data = dict(value)
        data["required_contexts"] = tuple(contexts)
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _observe_verified_pilot_exact_task_staging_deployment_state(
    *,
    staging_deployment_plan: PilotExactTaskStagingDeploymentPlanReceipt,
    transport: Any,
    now_provider: Callable[[], str],
) -> PilotExactTaskStagingDeploymentStateObservationReceipt:
    plan, readiness = _require_live_plan(staging_deployment_plan)
    if transport is None or not callable(getattr(transport, "observe", None)):
        raise PilotExactTaskStagingDeploymentStateObservationError(
            "read-only staging deployment GitHub observer is required"
        )
    if (
        getattr(transport, "credential_config_sha256", None)
        != readiness.publisher_credential_config_sha256
        or getattr(transport, "credential_path_sha256", None)
        != readiness.publisher_credential_path_sha256
    ):
        raise PilotExactTaskStagingDeploymentStateObservationError(
            "deployment-state observer credential identity differs from ADR-DC-070"
        )
    try:
        first = _normalize_remote_state(transport.observe(plan), plan)
        second = _normalize_remote_state(transport.observe(plan), plan)
    except PilotExactTaskStagingDeploymentStateObservationError:
        raise
    except Exception as exc:
        raise PilotExactTaskStagingDeploymentStateObservationError(
            "staging deployment-state GitHub observation failed"
        ) from exc
    if first != second:
        raise PilotExactTaskStagingDeploymentStateObservationError(
            "GitHub staging deployment state changed between observations"
        )
    observed_at = now_provider()
    if _utc(observed_at, name="observed_at_utc") < _utc(
        plan.planned_at_utc,
        name="planned_at_utc",
    ):
        raise PilotExactTaskStagingDeploymentStateObservationError(
            "system clock moved backwards after ADR-DC-071"
        )
    receipt = PilotExactTaskStagingDeploymentStateObservationReceipt(
        staging_deployment_plan_sha256=plan.sha256,
        deploy_readiness_evaluation_sha256=plan.deploy_readiness_evaluation_sha256,
        post_release_attestation_sha256=plan.post_release_attestation_sha256,
        deploy_readiness_policy_sha256=plan.deploy_readiness_policy_sha256,
        staging_deployment_plan_config_sha256=plan.staging_deployment_plan_config_sha256,
        deployment_intent_sha256=plan.deployment_intent_sha256,
        release_authorization_sha256=plan.release_authorization_sha256,
        release_intent_sha256=plan.release_intent_sha256,
        release_plan_sha256=plan.release_plan_sha256,
        execution_nonce_sha256=plan.execution_nonce_sha256,
        development_task_sha256=plan.development_task_sha256,
        candidate_patch_sha256=plan.candidate_patch_sha256,
        pr_intent_sha256=plan.pr_intent_sha256,
        upstream_merge_transaction_lock_sha256=plan.upstream_merge_transaction_lock_sha256,
        release_transaction_lock_sha256=plan.release_transaction_lock_sha256,
        publisher_credential_config_sha256=readiness.publisher_credential_config_sha256,
        publisher_credential_path_sha256=readiness.publisher_credential_path_sha256,
        remote_deployment_state_sha256=first.sha256,
        repository=plan.repository,
        repository_id=plan.repository_id,
        deployment_environment=plan.deployment_environment,
        release_base_branch=plan.release_base_branch,
        deployment_base_branch=plan.deployment_base_branch,
        merge_commit_sha=plan.merge_commit_sha,
        release_version=plan.release_version,
        tag_name=plan.tag_name,
        tag_target_sha=plan.tag_target_sha,
        release_id=plan.release_id,
        release_node_id_sha256=plan.release_node_id_sha256,
        deployment_identity=plan.deployment_identity,
        deployment_ref=plan.deployment_ref,
        deployment_task=plan.deployment_task,
        deployment_payload_sha256=plan.deployment_payload_sha256,
        deployment_description_sha256=plan.deployment_description_sha256,
        auto_merge=plan.auto_merge,
        required_contexts=plan.required_contexts,
        transient_environment=plan.transient_environment,
        production_environment=plan.production_environment,
        deployment_state=first.deployment_state,
        deployment_id=first.deployment_id,
        deployment_node_id_sha256=first.deployment_node_id_sha256,
        deployment_sha=first.deployment_sha,
        observed_payload_sha256=first.observed_payload_sha256,
        observed_description_sha256=first.observed_description_sha256,
        remote_state_class=first.remote_state_class,
        observed_at_utc=observed_at,
        deployment_lane_clear=first.remote_state_class == "clear",
        exact_existing_deployment=first.remote_state_class == "exact-existing",
    )
    _mark_staging_deployment_state_observation_authenticated(
        receipt,
        plan=plan,
        remote_state_sha256=first.sha256,
    )
    if receipt.observation_authenticated is not True:
        raise PilotExactTaskStagingDeploymentStateObservationError(
            "staging deployment-state observation lost live provenance"
        )
    return receipt


def observe_pilot_exact_task_staging_deployment_state(
    staging_deployment_plan: PilotExactTaskStagingDeploymentPlanReceipt,
) -> PilotExactTaskStagingDeploymentStateObservationReceipt:
    """Double-observe one exact staging Deployment lane without remote mutation."""
    try:
        plan, readiness = _require_live_plan(staging_deployment_plan)
        credential, credential_digest, credential_path = (
            publication_tx_boundary._canonical_credential()
        )
        transport = _GitHubStagingDeploymentStateObserver(
            credential=credential,
            credential_config_sha256=credential_digest,
            credential_path=credential_path,
        )
        if (
            credential_digest != readiness.publisher_credential_config_sha256
            or transport.credential_path_sha256
            != readiness.publisher_credential_path_sha256
        ):
            raise PilotExactTaskStagingDeploymentStateObservationError(
                "canonical publisher credential differs from ADR-DC-070"
            )
        return _observe_verified_pilot_exact_task_staging_deployment_state(
            staging_deployment_plan=plan,
            transport=transport,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskStagingDeploymentStateObservationError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskStagingDeploymentStateObservationError(
            "exact staging deployment-state observation failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATE_OBSERVATION_SCHEMA",
    "PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATE_OBSERVATION_AUTHORITY",
    "PILOT_EXACT_TASK_STAGING_DEPLOYMENT_STATE_OBSERVATION_SCOPE",
    "PilotExactTaskStagingDeploymentStateObservationError",
    "PilotExactTaskStagingDeploymentStateObservationReceipt",
    "observe_pilot_exact_task_staging_deployment_state",
]
