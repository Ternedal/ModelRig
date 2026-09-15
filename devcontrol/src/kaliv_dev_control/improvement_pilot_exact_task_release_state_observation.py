"""ADR-DC-065 read-only exact remote release-state observation.

This boundary accepts only one fresh live ADR-DC-064 deterministic release plan.
It observes the exact GitHub tag/reference and authenticated release inventory
twice, classifying only two acceptable pre-write states:

* ``clear``: deterministic tag absent and matching release absent.
* ``exact-existing``: deterministic lightweight tag points at the exact merge
  commit and one draft/prerelease GitHub Release matches the frozen plan.

Mixed/partial or conflicting state fails closed. No tag, release, deployment or
other remote mutation is performed and no release authority is granted.
"""
from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import weakref
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from ._improvement_pilot_start_consumption_impl import _path_sha256
from . import improvement_pilot_exact_task_release_plan as release_plan_boundary
from . import improvement_pilot_exact_task_remote_publication_transaction as publication_tx_boundary
from .improvement_pilot_exact_task_release_plan import (
    PILOT_EXACT_TASK_RELEASE_PLAN_AUTHORITY,
    PilotExactTaskReleasePlanReceipt,
)
from .improvement_pilot_exact_task_remote_publication_transaction import (
    PilotExactTaskGitHubPublisherCredential,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_RELEASE_STATE_OBSERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-release-state-observation-receipt/v1"
)
PILOT_EXACT_TASK_RELEASE_STATE_OBSERVATION_AUTHORITY = (
    "host-observed-one-dc-l16-exact-release-state-only"
)
PILOT_EXACT_TASK_RELEASE_STATE_OBSERVATION_SCOPE = (
    "exact-remote-release-state-observation-only-v1"
)

_GITHUB_API_ROOT = "https://api.github.com"
_MAX_API_RESPONSE_BYTES = 4 * 1024 * 1024
_RELEASE_PAGE_SIZE = 100
_MAX_RELEASE_PAGES = 10
_TIMEOUT_SECONDS = 30.0
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_ALLOWED_TAG_STATES = {"absent", "exact"}
_ALLOWED_RELEASE_STATES = {"absent", "exact-draft"}
_ALLOWED_CLASSES = {"clear", "exact-existing"}


class PilotExactTaskReleaseStateObservationError(ValueError):
    """Release plan or observed remote release state is stale, partial or unsafe."""


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
        raise PilotExactTaskReleaseStateObservationError(
            "release-state evidence is not canonical JSON"
        ) from exc


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskReleaseStateObservationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskReleaseStateObservationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskReleaseStateObservationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskReleaseStateObservationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _require_live_plan(value: Any) -> tuple[PilotExactTaskReleasePlanReceipt, Any]:
    if type(value) is not PilotExactTaskReleasePlanReceipt:
        raise PilotExactTaskReleaseStateObservationError(
            "exact live ADR-DC-064 release plan is required"
        )
    try:
        replayed = PilotExactTaskReleasePlanReceipt.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskReleaseStateObservationError(
            "ADR-DC-064 replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskReleaseStateObservationError(
            "ADR-DC-064 release-plan identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_RELEASE_PLAN_AUTHORITY
        or value.plan_authenticated is not True
        or value.release_readiness_authenticated is not True
        or value.release_ready is not True
        or value.release_plan_config_host_pinned is not True
        or value.release_intent_materialized is not True
        or value.tag_creation_planned is not True
        or value.github_release_creation_planned is not True
        or value.release_draft is not True
        or value.release_prerelease is not True
        or value.make_latest is not False
        or value.tag_target_sha != value.merge_commit_sha
        or value.tag_write_authorized is not False
        or value.release_mutation_authorized is not False
        or value.release_authorized is not False
        or value.remote_write_authorized is not False
        or value.merge_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.nonce_reusable is not False
    ):
        raise PilotExactTaskReleaseStateObservationError(
            "ADR-DC-065 requires one fresh inert ADR-DC-064 release plan"
        )
    live = release_plan_boundary._get_live_release_plan_inputs(value)
    if live is None:
        raise PilotExactTaskReleaseStateObservationError(
            "ADR-DC-064 live provenance is unavailable"
        )
    readiness = live.get("release_readiness_evaluation")
    if readiness is None or getattr(readiness, "sha256", None) != value.release_readiness_evaluation_sha256:
        raise PilotExactTaskReleaseStateObservationError(
            "ADR-DC-064 live readiness provenance mismatch"
        )
    return value, readiness


@dataclass(frozen=True, slots=True)
class _RemoteReleaseState:
    repository: str
    repository_id: str
    tag_state: str
    tag_target_sha: str | None
    release_state: str
    release_id: int | None
    release_node_id_sha256: str | None
    release_tag_name: str | None
    release_name: str | None
    release_body_sha256: str | None
    release_draft: bool | None
    release_prerelease: bool | None
    release_asset_count: int | None
    remote_state_class: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.tag_state not in _ALLOWED_TAG_STATES
            or self.release_state not in _ALLOWED_RELEASE_STATES
            or self.remote_state_class not in _ALLOWED_CLASSES
        ):
            raise PilotExactTaskReleaseStateObservationError(
                "remote release-state identity is invalid"
            )
        if self.tag_state == "absent":
            if self.tag_target_sha is not None:
                raise PilotExactTaskReleaseStateObservationError(
                    "absent tag carries a target"
                )
        else:
            _hex40(self.tag_target_sha, name="tag_target_sha")
        if self.release_state == "absent":
            if any(
                value is not None
                for value in (
                    self.release_id,
                    self.release_node_id_sha256,
                    self.release_tag_name,
                    self.release_name,
                    self.release_body_sha256,
                    self.release_draft,
                    self.release_prerelease,
                    self.release_asset_count,
                )
            ):
                raise PilotExactTaskReleaseStateObservationError(
                    "absent release carries release metadata"
                )
        else:
            if (
                isinstance(self.release_id, bool)
                or not isinstance(self.release_id, int)
                or self.release_id < 1
                or not isinstance(self.release_tag_name, str)
                or not self.release_tag_name
                or not isinstance(self.release_name, str)
                or not self.release_name
                or self.release_draft is not True
                or self.release_prerelease is not True
                or isinstance(self.release_asset_count, bool)
                or not isinstance(self.release_asset_count, int)
                or self.release_asset_count < 0
            ):
                raise PilotExactTaskReleaseStateObservationError(
                    "exact release metadata is invalid"
                )
            _hex64(self.release_node_id_sha256, name="release_node_id_sha256")
            _hex64(self.release_body_sha256, name="release_body_sha256")
        expected_class = (
            "clear"
            if self.tag_state == "absent" and self.release_state == "absent"
            else "exact-existing"
            if self.tag_state == "exact" and self.release_state == "exact-draft"
            else None
        )
        if expected_class is None or self.remote_state_class != expected_class:
            raise PilotExactTaskReleaseStateObservationError(
                "partial remote release state is forbidden"
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


class _GitHubReleaseStateObserver:
    """Repository-bound authenticated GET-only observer for tag/release state."""

    def __init__(
        self,
        *,
        credential: PilotExactTaskGitHubPublisherCredential,
        credential_config_sha256: str,
        credential_path: Path,
    ) -> None:
        if type(credential) is not PilotExactTaskGitHubPublisherCredential:
            raise PilotExactTaskReleaseStateObservationError(
                "exact publisher credential is required"
            )
        self.credential = credential
        self.credential_config_sha256 = _hex64(
            credential_config_sha256, name="credential_config_sha256"
        )
        self.credential_path = Path(credential_path)
        if (
            not self.credential_path.is_absolute()
            or _has_linkish_component(self.credential_path)
        ):
            raise PilotExactTaskReleaseStateObservationError(
                "publisher credential path is unsafe"
            )
        self.credential_path_sha256 = _path_sha256(self.credential_path)
        self._opener = urllib.request.build_opener(_NoRedirect())

    @staticmethod
    def _repo_root(plan: PilotExactTaskReleasePlanReceipt) -> str:
        owner, repo = plan.repository.split("/", 1)
        return "/repos/{}/{}".format(
            urllib.parse.quote(owner, safe=""),
            urllib.parse.quote(repo, safe=""),
        )

    def _get_json_or_404(
        self,
        *,
        plan: PilotExactTaskReleasePlanReceipt,
        path: str,
    ) -> tuple[int, Any | None]:
        root = self._repo_root(plan)
        if (
            not isinstance(path, str)
            or not (path == root or path.startswith(root + "/"))
            or ".." in path
        ):
            raise PilotExactTaskReleaseStateObservationError(
                "release-state GET is outside exact GitHub scope"
            )
        url = _GITHUB_API_ROOT + path
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.credential.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "ModelRig-DevControl-ExactReleaseState/1",
            },
        )
        try:
            response = self._opener.open(request, timeout=_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return 404, None
            raise PilotExactTaskReleaseStateObservationError(
                f"GitHub release-state GET failed with HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PilotExactTaskReleaseStateObservationError(
                "GitHub release-state GET failed"
            ) from exc
        with response:
            if response.status != 200 or response.geturl() != url:
                raise PilotExactTaskReleaseStateObservationError(
                    "GitHub release-state response identity/status is unexpected"
                )
            raw = response.read(_MAX_API_RESPONSE_BYTES + 1)
        if not raw or len(raw) > _MAX_API_RESPONSE_BYTES:
            raise PilotExactTaskReleaseStateObservationError(
                "GitHub release-state response size is invalid"
            )
        try:
            return 200, json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PilotExactTaskReleaseStateObservationError(
                "GitHub release-state response is invalid JSON"
            ) from exc

    def _observe_tag(self, plan: PilotExactTaskReleasePlanReceipt) -> tuple[str, str | None]:
        root = self._repo_root(plan)
        encoded = urllib.parse.quote(plan.tag_name, safe="")
        status, payload = self._get_json_or_404(
            plan=plan, path=f"{root}/git/ref/tags/{encoded}"
        )
        if status == 404:
            return "absent", None
        obj = payload.get("object") if isinstance(payload, Mapping) else None
        if (
            not isinstance(obj, Mapping)
            or obj.get("type") != "commit"
            or obj.get("sha") != plan.tag_target_sha
        ):
            raise PilotExactTaskReleaseStateObservationError(
                "existing deterministic tag is not the exact lightweight tag target"
            )
        return "exact", plan.tag_target_sha

    def _observe_release(self, plan: PilotExactTaskReleasePlanReceipt) -> dict[str, Any] | None:
        root = self._repo_root(plan)
        matches: list[Mapping[str, Any]] = []
        exhausted = False
        for page in range(1, _MAX_RELEASE_PAGES + 1):
            status, payload = self._get_json_or_404(
                plan=plan,
                path=(
                    f"{root}/releases?per_page={_RELEASE_PAGE_SIZE}&page={page}"
                ),
            )
            if status != 200 or not isinstance(payload, list):
                raise PilotExactTaskReleaseStateObservationError(
                    "GitHub release inventory response is invalid"
                )
            for item in payload:
                if not isinstance(item, Mapping):
                    raise PilotExactTaskReleaseStateObservationError(
                        "GitHub release inventory contains invalid item"
                    )
                if item.get("tag_name") == plan.tag_name:
                    matches.append(item)
            if len(payload) < _RELEASE_PAGE_SIZE:
                exhausted = True
                break
        if len(matches) > 1:
            raise PilotExactTaskReleaseStateObservationError(
                "multiple GitHub releases claim deterministic tag"
            )
        if not matches:
            if not exhausted:
                raise PilotExactTaskReleaseStateObservationError(
                    "release inventory exceeded bounded observation window"
                )
            return None
        item = matches[0]
        assets = item.get("assets")
        node_id = item.get("node_id")
        release_id = item.get("id")
        body = item.get("body")
        if (
            isinstance(release_id, bool)
            or not isinstance(release_id, int)
            or release_id < 1
            or not isinstance(node_id, str)
            or not node_id
            or item.get("tag_name") != plan.tag_name
            or item.get("name") != plan.release_name
            or body != plan.release_body
            or item.get("draft") is not True
            or item.get("prerelease") is not True
            or item.get("published_at") is not None
            or not isinstance(assets, list)
            or len(assets) != 0
        ):
            raise PilotExactTaskReleaseStateObservationError(
                "existing GitHub draft release differs from exact release plan"
            )
        return {
            "release_id": release_id,
            "release_node_id_sha256": _sha256_text(node_id),
            "release_tag_name": plan.tag_name,
            "release_name": plan.release_name,
            "release_body_sha256": _sha256_text(plan.release_body),
            "release_draft": True,
            "release_prerelease": True,
            "release_asset_count": 0,
        }

    def observe(self, plan: PilotExactTaskReleasePlanReceipt) -> _RemoteReleaseState:
        if type(plan) is not PilotExactTaskReleasePlanReceipt:
            raise PilotExactTaskReleaseStateObservationError(
                "exact ADR-DC-064 release plan is required"
            )
        if (
            self.credential.repository != plan.repository
            or self.credential.repository_id != plan.repository_id
        ):
            raise PilotExactTaskReleaseStateObservationError(
                "publisher credential is not bound to exact release repository"
            )
        root = self._repo_root(plan)
        status, repo = self._get_json_or_404(plan=plan, path=root)
        if (
            status != 200
            or not isinstance(repo, Mapping)
            or str(repo.get("id")) != plan.repository_id
            or repo.get("full_name") != plan.repository
        ):
            raise PilotExactTaskReleaseStateObservationError(
                "GitHub repository identity differs from release plan"
            )
        tag_state, tag_target = self._observe_tag(plan)
        release = self._observe_release(plan)
        release_state = "absent" if release is None else "exact-draft"
        if tag_state == "absent" and release_state == "absent":
            state_class = "clear"
        elif tag_state == "exact" and release_state == "exact-draft":
            state_class = "exact-existing"
        else:
            raise PilotExactTaskReleaseStateObservationError(
                "remote release lane is partial and cannot be newly authorized"
            )
        values: dict[str, Any] = {
            "repository": plan.repository,
            "repository_id": plan.repository_id,
            "tag_state": tag_state,
            "tag_target_sha": tag_target,
            "release_state": release_state,
            "release_id": None,
            "release_node_id_sha256": None,
            "release_tag_name": None,
            "release_name": None,
            "release_body_sha256": None,
            "release_draft": None,
            "release_prerelease": None,
            "release_asset_count": None,
            "remote_state_class": state_class,
        }
        if release is not None:
            values.update(release)
        return _RemoteReleaseState(**values)


def _normalize_remote_state(
    value: Any,
    plan: PilotExactTaskReleasePlanReceipt,
) -> _RemoteReleaseState:
    if type(value) is not _RemoteReleaseState:
        raise PilotExactTaskReleaseStateObservationError(
            "release-state observer returned invalid state"
        )
    if (
        value.repository != plan.repository
        or value.repository_id != plan.repository_id
    ):
        raise PilotExactTaskReleaseStateObservationError(
            "release-state repository identity mismatch"
        )
    if value.tag_state == "exact" and value.tag_target_sha != plan.tag_target_sha:
        raise PilotExactTaskReleaseStateObservationError(
            "release-state tag target mismatch"
        )
    if value.release_state == "exact-draft":
        if (
            value.release_tag_name != plan.tag_name
            or value.release_name != plan.release_name
            or value.release_body_sha256 != plan.release_body_sha256
            or value.release_draft is not True
            or value.release_prerelease is not True
            or value.release_asset_count != 0
        ):
            raise PilotExactTaskReleaseStateObservationError(
                "release-state exact draft projection mismatch"
            )
    return value


def _live_registry():
    records: dict[
        int,
        tuple[
            int,
            str,
            weakref.ReferenceType[Any],
            weakref.ReferenceType[Any],
            str,
        ],
    ] = {}

    def mark(
        receipt: Any,
        *,
        plan: PilotExactTaskReleasePlanReceipt,
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
            or plan.sha256 != receipt.release_plan_sha256
            or receipt.remote_release_state_sha256 != remote_sha
        ):
            return None
        return MappingProxyType(
            {
                "release_plan": plan,
                "remote_release_state_sha256": remote_sha,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_release_state_observation_authenticated,
    _get_live_release_state_observation_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskReleaseStateObservationReceipt:
    release_plan_sha256: str
    release_readiness_evaluation_sha256: str
    release_intent_sha256: str
    release_plan_config_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    transaction_lock_sha256: str
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    remote_release_state_sha256: str
    repository: str
    repository_id: str
    release_base_branch: str
    merge_commit_sha: str
    release_version: str
    tag_name: str
    tag_target_sha: str
    release_name: str
    release_body_sha256: str
    release_draft: bool
    release_prerelease: bool
    make_latest: bool
    tag_state: str
    release_state: str
    release_id: int | None
    release_node_id_sha256: str | None
    remote_state_class: str
    observed_at_utc: str
    release_plan_authenticated: bool = True
    remote_state_observed: bool = True
    remote_repository_verified: bool = True
    tag_state_verified: bool = True
    release_state_verified: bool = True
    double_observation_matched: bool = True
    release_lane_clear: bool = False
    exact_existing_release: bool = False
    release_state_acceptable: bool = True
    tag_write_authorized: bool = False
    release_mutation_authorized: bool = False
    release_authorized: bool = False
    remote_write_authorized: bool = False
    merge_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    product_pilot_started: bool = False
    nonce_reusable: bool = False
    observation_scope: str = PILOT_EXACT_TASK_RELEASE_STATE_OBSERVATION_SCOPE
    authority: str = PILOT_EXACT_TASK_RELEASE_STATE_OBSERVATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_RELEASE_STATE_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_RELEASE_STATE_OBSERVATION_SCHEMA
            or self.authority != PILOT_EXACT_TASK_RELEASE_STATE_OBSERVATION_AUTHORITY
            or self.observation_scope != PILOT_EXACT_TASK_RELEASE_STATE_OBSERVATION_SCOPE
        ):
            raise PilotExactTaskReleaseStateObservationError(
                "release-state observation identity is unsupported"
            )
        for name in (
            "release_plan_sha256",
            "release_readiness_evaluation_sha256",
            "release_intent_sha256",
            "release_plan_config_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "pr_intent_sha256",
            "transaction_lock_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
            "remote_release_state_sha256",
            "release_body_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        _hex40(self.tag_target_sha, name="tag_target_sha")
        if (
            self.tag_target_sha != self.merge_commit_sha
            or not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.tag_state not in _ALLOWED_TAG_STATES
            or self.release_state not in _ALLOWED_RELEASE_STATES
            or self.remote_state_class not in _ALLOWED_CLASSES
            or self.release_draft is not True
            or self.release_prerelease is not True
            or self.make_latest is not False
        ):
            raise PilotExactTaskReleaseStateObservationError(
                "release-state observation projection is invalid"
            )
        if self.remote_state_class == "clear":
            if (
                self.tag_state != "absent"
                or self.release_state != "absent"
                or self.release_id is not None
                or self.release_node_id_sha256 is not None
                or self.release_lane_clear is not True
                or self.exact_existing_release is not False
            ):
                raise PilotExactTaskReleaseStateObservationError(
                    "clear release-state projection is inconsistent"
                )
        else:
            if (
                self.tag_state != "exact"
                or self.release_state != "exact-draft"
                or isinstance(self.release_id, bool)
                or not isinstance(self.release_id, int)
                or self.release_id < 1
                or self.release_node_id_sha256 is None
                or self.release_lane_clear is not False
                or self.exact_existing_release is not True
            ):
                raise PilotExactTaskReleaseStateObservationError(
                    "exact-existing release-state projection is inconsistent"
                )
            _hex64(self.release_node_id_sha256, name="release_node_id_sha256")
        _utc(self.observed_at_utc, name="observed_at_utc")
        required_true = (
            "release_plan_authenticated",
            "remote_state_observed",
            "remote_repository_verified",
            "tag_state_verified",
            "release_state_verified",
            "double_observation_matched",
            "release_state_acceptable",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskReleaseStateObservationError(
                "release-state observation evidence is incomplete"
            )
        forced_false = (
            "tag_write_authorized",
            "release_mutation_authorized",
            "release_authorized",
            "remote_write_authorized",
            "merge_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "product_pilot_started",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskReleaseStateObservationError(
                "release-state observation retains forbidden authority"
            )

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())

    @property
    def observation_authenticated(self) -> bool:
        return _get_live_release_state_observation_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskReleaseStateObservationReceipt":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):  # type: ignore[attr-defined]
            raise PilotExactTaskReleaseStateObservationError(
                "release-state observation fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _observe_verified_pilot_exact_task_release_state(
    *,
    release_plan: PilotExactTaskReleasePlanReceipt,
    transport: Any,
    now_provider: Callable[[], str],
) -> PilotExactTaskReleaseStateObservationReceipt:
    plan, readiness = _require_live_plan(release_plan)
    if transport is None or not callable(getattr(transport, "observe", None)):
        raise PilotExactTaskReleaseStateObservationError(
            "read-only release-state GitHub observer is required"
        )
    if (
        getattr(transport, "credential_config_sha256", None)
        != readiness.publisher_credential_config_sha256
        or getattr(transport, "credential_path_sha256", None)
        != readiness.publisher_credential_path_sha256
    ):
        raise PilotExactTaskReleaseStateObservationError(
            "release-state observer credential identity differs from merge transaction"
        )
    try:
        first = _normalize_remote_state(transport.observe(plan), plan)
        second = _normalize_remote_state(transport.observe(plan), plan)
    except PilotExactTaskReleaseStateObservationError:
        raise
    except Exception as exc:
        raise PilotExactTaskReleaseStateObservationError(
            "release-state GitHub observation failed"
        ) from exc
    if first != second:
        raise PilotExactTaskReleaseStateObservationError(
            "GitHub release state changed between observations"
        )
    observed_at = now_provider()
    if _utc(observed_at, name="observed_at_utc") < _utc(
        plan.planned_at_utc, name="planned_at_utc"
    ):
        raise PilotExactTaskReleaseStateObservationError(
            "system clock moved backwards after ADR-DC-064"
        )
    receipt = PilotExactTaskReleaseStateObservationReceipt(
        release_plan_sha256=plan.sha256,
        release_readiness_evaluation_sha256=plan.release_readiness_evaluation_sha256,
        release_intent_sha256=plan.release_intent_sha256,
        release_plan_config_sha256=plan.release_plan_config_sha256,
        execution_nonce_sha256=plan.execution_nonce_sha256,
        development_task_sha256=plan.development_task_sha256,
        candidate_patch_sha256=plan.candidate_patch_sha256,
        pr_intent_sha256=plan.pr_intent_sha256,
        transaction_lock_sha256=plan.transaction_lock_sha256,
        publisher_credential_config_sha256=readiness.publisher_credential_config_sha256,
        publisher_credential_path_sha256=readiness.publisher_credential_path_sha256,
        remote_release_state_sha256=first.sha256,
        repository=plan.repository,
        repository_id=plan.repository_id,
        release_base_branch=plan.release_base_branch,
        merge_commit_sha=plan.merge_commit_sha,
        release_version=plan.release_version,
        tag_name=plan.tag_name,
        tag_target_sha=plan.tag_target_sha,
        release_name=plan.release_name,
        release_body_sha256=plan.release_body_sha256,
        release_draft=plan.release_draft,
        release_prerelease=plan.release_prerelease,
        make_latest=plan.make_latest,
        tag_state=first.tag_state,
        release_state=first.release_state,
        release_id=first.release_id,
        release_node_id_sha256=first.release_node_id_sha256,
        remote_state_class=first.remote_state_class,
        observed_at_utc=observed_at,
        release_lane_clear=first.remote_state_class == "clear",
        exact_existing_release=first.remote_state_class == "exact-existing",
    )
    _mark_release_state_observation_authenticated(
        receipt,
        plan=plan,
        remote_state_sha256=first.sha256,
    )
    if receipt.observation_authenticated is not True:
        raise PilotExactTaskReleaseStateObservationError(
            "release-state observation lost live provenance"
        )
    return receipt


def observe_pilot_exact_task_release_state(
    release_plan: PilotExactTaskReleasePlanReceipt,
) -> PilotExactTaskReleaseStateObservationReceipt:
    """Double-observe exact tag/release state for one fresh ADR-DC-064 plan."""
    try:
        plan, readiness = _require_live_plan(release_plan)
        credential, credential_digest, credential_path = (
            publication_tx_boundary._canonical_credential()
        )
        transport = _GitHubReleaseStateObserver(
            credential=credential,
            credential_config_sha256=credential_digest,
            credential_path=credential_path,
        )
        if (
            credential_digest != readiness.publisher_credential_config_sha256
            or transport.credential_path_sha256
            != readiness.publisher_credential_path_sha256
        ):
            raise PilotExactTaskReleaseStateObservationError(
                "canonical publisher credential differs from merge transaction"
            )
        return _observe_verified_pilot_exact_task_release_state(
            release_plan=plan,
            transport=transport,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskReleaseStateObservationError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskReleaseStateObservationError(
            "exact release-state observation failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_RELEASE_STATE_OBSERVATION_SCHEMA",
    "PILOT_EXACT_TASK_RELEASE_STATE_OBSERVATION_AUTHORITY",
    "PILOT_EXACT_TASK_RELEASE_STATE_OBSERVATION_SCOPE",
    "PilotExactTaskReleaseStateObservationError",
    "PilotExactTaskReleaseStateObservationReceipt",
    "observe_pilot_exact_task_release_state",
]
