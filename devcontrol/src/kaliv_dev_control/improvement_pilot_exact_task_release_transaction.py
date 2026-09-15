"""ADR-DC-067 one-shot exact deterministic release transaction.

Consumes one live ADR-DC-066 release authorization before any GitHub write,
fresh-revalidates the exact clear release lane, creates exactly one lightweight
tag followed by exactly one draft/prerelease GitHub Release, and durably records
phase evidence as lock -> tag marker -> release marker -> final receipt.

This boundary never retries an existing partial transaction. Recovery of
ambiguous lock/tag/release states is deliberately deferred to ADR-DC-068.
Deployment and production activation remain forbidden.
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
from . import improvement_pilot_exact_task_release_authorization as auth_boundary
from . import improvement_pilot_exact_task_release_state_observation as state_boundary
from . import improvement_pilot_exact_task_remote_publication_transaction as publication_tx_boundary
from .improvement_pilot_exact_task_release_authorization import (
    PILOT_EXACT_TASK_RELEASE_AUTHORIZATION_AUTHORITY,
    PilotExactTaskReleaseAuthorizationReceipt,
)
from .improvement_pilot_exact_task_remote_publication_transaction import (
    PilotExactTaskGitHubPublisherCredential,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_RELEASE_TRANSACTION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-release-transaction-receipt/v1"
)
PILOT_EXACT_TASK_RELEASE_TRANSACTION_AUTHORITY = (
    "host-executed-one-dc-l16-exact-tag-and-draft-release-only"
)
PILOT_EXACT_TASK_RELEASE_TRANSACTION_SCOPE = (
    "one-shot-exact-tag-and-draft-release-transaction-v1"
)
PILOT_EXACT_TASK_RELEASE_TRANSACTION_LEDGER_SCOPE = "canonical-host-local-v1"

_GITHUB_API_ROOT = "https://api.github.com"
_MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
_MAX_API_RESPONSE_BYTES = 4 * 1024 * 1024
_TIMEOUT_SECONDS = 30.0
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_BRANCH = re.compile(r"^(?![./])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}$")
_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/rsi-pilot-exact-task-release-transaction-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-release-transaction-ledger-v1"
)


class PilotExactTaskReleaseTransactionError(ValueError):
    """Exact release transaction is stale, replayed, ambiguous or over-broad."""


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
        raise PilotExactTaskReleaseTransactionError(
            "release transaction evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskReleaseTransactionError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskReleaseTransactionError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskReleaseTransactionError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskReleaseTransactionError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _branch(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or value.strip() != value
        or _BRANCH.fullmatch(value) is None
        or value.endswith(("/", ".", ".lock"))
        or "@{" in value
        or "\\" in value
    ):
        raise PilotExactTaskReleaseTransactionError(f"{name} is invalid")
    return value


def _tag(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or value.strip() != value
        or _TAG.fullmatch(value) is None
        or value.endswith(("/", ".", ".lock"))
        or ".." in value
        or "@{" in value
        or "\\" in value
    ):
        raise PilotExactTaskReleaseTransactionError(f"{name} is invalid")
    return value


def _read_bound(path: Path) -> bytes | None:
    candidate = Path(path)
    if not candidate.is_absolute() or _has_linkish_component(candidate):
        return None
    try:
        payload = candidate.read_bytes()
    except OSError:
        return None
    if not payload or len(payload) > _MAX_ARTIFACT_BYTES:
        return None
    return payload


def _require_live_authorization(
    value: Any,
) -> tuple[PilotExactTaskReleaseAuthorizationReceipt, Any, Any, Any]:
    if type(value) is not PilotExactTaskReleaseAuthorizationReceipt:
        raise PilotExactTaskReleaseTransactionError(
            "exact live ADR-DC-066 release authorization is required"
        )
    try:
        replayed = PilotExactTaskReleaseAuthorizationReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskReleaseTransactionError(
            "ADR-DC-066 authorization replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskReleaseTransactionError(
            "ADR-DC-066 authorization identity mismatch"
        )
    required_true = (
        "host_release_guard_committed",
        "release_state_observation_authenticated",
        "release_plan_authenticated",
        "release_lane_clear",
        "release_authorization_config_host_pinned",
        "dual_external_ed25519_authorized",
        "tag_write_authorized",
        "release_mutation_authorized",
        "release_authorized",
        "remote_write_authorized",
    )
    required_false = (
        "merge_authorized",
        "push_authorized",
        "pr_mutation_authorized",
        "review_submission_authorized",
        "review_thread_mutation_authorized",
        "ready_for_review_authorized",
        "reviewer_request_authorized",
        "deploy_authorized",
        "production_activation_authorized",
        "product_pilot_started",
        "nonce_reusable",
    )
    if (
        value.authority != PILOT_EXACT_TASK_RELEASE_AUTHORIZATION_AUTHORITY
        or value.authorization_authenticated is not True
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in required_false)
        or value.release_draft is not True
        or value.release_prerelease is not True
        or value.make_latest is not False
    ):
        raise PilotExactTaskReleaseTransactionError(
            "ADR-DC-067 requires one exact unconsumed ADR-DC-066 authority"
        )
    live = auth_boundary._get_live_release_authorization_inputs(value)
    if live is None:
        raise PilotExactTaskReleaseTransactionError(
            "ADR-DC-066 live provenance is unavailable"
        )
    observation = live.get("release_state_observation")
    config = live.get("release_authorization_config")
    if (
        observation is None
        or getattr(observation, "sha256", None)
        != value.release_state_observation_sha256
        or config is None
        or getattr(config, "sha256", None)
        != value.release_authorization_config_sha256
    ):
        raise PilotExactTaskReleaseTransactionError(
            "ADR-DC-066 live provenance binding mismatch"
        )
    state_live = state_boundary._get_live_release_state_observation_inputs(
        observation
    )
    if state_live is None:
        raise PilotExactTaskReleaseTransactionError(
            "ADR-DC-065 live provenance is unavailable through ADR-DC-066"
        )
    plan = state_live.get("release_plan")
    if (
        plan is None
        or getattr(plan, "sha256", None) != value.release_plan_sha256
        or getattr(plan, "release_intent_sha256", None)
        != value.release_intent_sha256
    ):
        raise PilotExactTaskReleaseTransactionError(
            "ADR-DC-064 live release plan binding mismatch"
        )
    return value, observation, config, plan


def _require_valid_window(
    authorization: PilotExactTaskReleaseAuthorizationReceipt,
    now_utc: str,
) -> None:
    now = _utc(now_utc, name="transaction time")
    requested = _utc(authorization.requested_at_utc, name="requested_at_utc")
    expires = _utc(authorization.expires_at_utc, name="expires_at_utc")
    if not requested <= now < expires:
        raise PilotExactTaskReleaseTransactionError(
            "release authorization is outside its validity window"
        )


def _clear_state(
    value: Any,
    *,
    authorization: PilotExactTaskReleaseAuthorizationReceipt,
) -> Any:
    if type(value) is not state_boundary._RemoteReleaseState:
        raise PilotExactTaskReleaseTransactionError(
            "release transport returned invalid clear-state evidence"
        )
    if (
        value.repository != authorization.repository
        or value.repository_id != authorization.repository_id
        or value.remote_state_class != "clear"
        or value.tag_state != "absent"
        or value.release_state != "absent"
        or value.tag_target_sha is not None
        or value.release_id is not None
        or value.release_node_id_sha256 is not None
        or value.sha256 != authorization.remote_release_state_sha256
    ):
        raise PilotExactTaskReleaseTransactionError(
            "remote release lane is no longer the authorized clear state"
        )
    return value


def _exact_state(
    value: Any,
    *,
    authorization: PilotExactTaskReleaseAuthorizationReceipt,
    release_id: int,
    release_node_id_sha256: str,
) -> Any:
    if type(value) is not state_boundary._RemoteReleaseState:
        raise PilotExactTaskReleaseTransactionError(
            "release transport returned invalid exact-existing evidence"
        )
    if (
        value.repository != authorization.repository
        or value.repository_id != authorization.repository_id
        or value.remote_state_class != "exact-existing"
        or value.tag_state != "exact"
        or value.tag_target_sha != authorization.tag_target_sha
        or value.release_state != "exact-draft"
        or value.release_id != release_id
        or value.release_node_id_sha256 != release_node_id_sha256
        or value.release_tag_name != authorization.tag_name
        or value.release_name != authorization.release_name
        or value.release_body_sha256 != authorization.release_body_sha256
        or value.release_draft is not True
        or value.release_prerelease is not True
        or value.release_asset_count != 0
    ):
        raise PilotExactTaskReleaseTransactionError(
            "final remote release state differs from exact authorization"
        )
    return value


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _GitHubExactReleaseTransactionTransport:
    """Credential-bound observer plus exactly two release mutation endpoints."""

    def __init__(
        self,
        *,
        credential: PilotExactTaskGitHubPublisherCredential,
        credential_config_sha256: str,
        credential_path: Path,
    ) -> None:
        if type(credential) is not PilotExactTaskGitHubPublisherCredential:
            raise PilotExactTaskReleaseTransactionError(
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
            raise PilotExactTaskReleaseTransactionError(
                "publisher credential path is unsafe"
            )
        self.credential_path_sha256 = _path_sha256(self.credential_path)
        self._observer = state_boundary._GitHubReleaseStateObserver(
            credential=credential,
            credential_config_sha256=credential_config_sha256,
            credential_path=credential_path,
        )
        self._opener = urllib.request.build_opener(_NoRedirect())

    def observe(self, plan: Any) -> Any:
        return self._observer.observe(plan)

    def observe_tag_phase(self, plan: Any) -> tuple[str, str | None, bool]:
        tag_state, target = self._observer._observe_tag(plan)
        release = self._observer._observe_release(plan)
        return tag_state, target, release is None

    @staticmethod
    def _repo_root(
        authorization: PilotExactTaskReleaseAuthorizationReceipt,
    ) -> str:
        owner, repo = authorization.repository.split("/", 1)
        return "/repos/{}/{}".format(
            urllib.parse.quote(owner, safe=""),
            urllib.parse.quote(repo, safe=""),
        )

    def _post_json(
        self,
        *,
        authorization: PilotExactTaskReleaseAuthorizationReceipt,
        path: str,
        body: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        root = self._repo_root(authorization)
        if (
            path not in {f"{root}/git/refs", f"{root}/releases"}
            or ".." in path
        ):
            raise PilotExactTaskReleaseTransactionError(
                "release transaction POST is outside exact GitHub scope"
            )
        url = _GITHUB_API_ROOT + path
        request = urllib.request.Request(
            url,
            data=_canonical(dict(body)).encode("utf-8"),
            method="POST",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.credential.token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "ModelRig-DevControl-ExactReleaseTransaction/1",
            },
        )
        try:
            response = self._opener.open(
                request,
                timeout=_TIMEOUT_SECONDS,
            )
        except urllib.error.HTTPError as exc:
            raise PilotExactTaskReleaseTransactionError(
                f"GitHub release transaction POST failed with HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PilotExactTaskReleaseTransactionError(
                "GitHub release transaction POST failed"
            ) from exc
        with response:
            if response.status != 201 or response.geturl() != url:
                raise PilotExactTaskReleaseTransactionError(
                    "GitHub release transaction response status/identity is unexpected"
                )
            raw = response.read(_MAX_API_RESPONSE_BYTES + 1)
        if not raw or len(raw) > _MAX_API_RESPONSE_BYTES:
            raise PilotExactTaskReleaseTransactionError(
                "GitHub release transaction response size is invalid"
            )
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PilotExactTaskReleaseTransactionError(
                "GitHub release transaction response is invalid JSON"
            ) from exc
        if not isinstance(value, Mapping):
            raise PilotExactTaskReleaseTransactionError(
                "GitHub release transaction response is not an object"
            )
        return value

    def create_tag(
        self,
        authorization: PilotExactTaskReleaseAuthorizationReceipt,
    ) -> str:
        root = self._repo_root(authorization)
        value = self._post_json(
            authorization=authorization,
            path=f"{root}/git/refs",
            body={
                "ref": f"refs/tags/{authorization.tag_name}",
                "sha": authorization.tag_target_sha,
            },
        )
        obj = value.get("object")
        if (
            value.get("ref") != f"refs/tags/{authorization.tag_name}"
            or not isinstance(obj, Mapping)
            or obj.get("type") != "commit"
            or obj.get("sha") != authorization.tag_target_sha
        ):
            raise PilotExactTaskReleaseTransactionError(
                "created GitHub tag does not match exact authorization"
            )
        return authorization.tag_target_sha

    def create_release(
        self,
        authorization: PilotExactTaskReleaseAuthorizationReceipt,
        *,
        release_body: str,
    ) -> tuple[int, str]:
        root = self._repo_root(authorization)
        value = self._post_json(
            authorization=authorization,
            path=f"{root}/releases",
            body={
                "tag_name": authorization.tag_name,
                "target_commitish": authorization.tag_target_sha,
                "name": authorization.release_name,
                "body": release_body,
                "draft": True,
                "prerelease": True,
                "make_latest": "false",
            },
        )
        release_id = value.get("id")
        node_id = value.get("node_id")
        assets = value.get("assets")
        if (
            isinstance(release_id, bool)
            or not isinstance(release_id, int)
            or release_id < 1
            or not isinstance(node_id, str)
            or not node_id
            or value.get("tag_name") != authorization.tag_name
            or value.get("name") != authorization.release_name
            or value.get("body") != release_body
            or value.get("draft") is not True
            or value.get("prerelease") is not True
            or value.get("published_at") is not None
            or not isinstance(assets, list)
            or assets
        ):
            raise PilotExactTaskReleaseTransactionError(
                "created GitHub draft release differs from exact authorization"
            )
        return (
            release_id,
            hashlib.sha256(node_id.encode("utf-8")).hexdigest(),
        )


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskReleaseTransactionReceipt:
    release_transaction_ledger_root_path_sha256: str
    release_key_sha256: str
    release_authorization_sha256: str
    release_authorization_payload_sha256: str
    release_state_observation_sha256: str
    release_plan_sha256: str
    release_readiness_evaluation_sha256: str
    release_intent_sha256: str
    release_plan_config_sha256: str
    remote_release_state_sha256: str
    release_authorization_config_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    upstream_merge_transaction_lock_sha256: str
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    transaction_lock_sha256: str
    tag_marker_sha256: str
    release_marker_sha256: str
    final_remote_release_state_sha256: str
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
    release_id: int
    release_node_id_sha256: str
    locked_at_utc: str
    tag_created_at_utc: str
    release_created_at_utc: str
    completed_at_utc: str
    release_authorization_authenticated: bool = True
    release_authority_consumed: bool = True
    host_transaction_lock_committed: bool = True
    exact_clear_lane_revalidated: bool = True
    tag_created: bool = True
    tag_marker_committed: bool = True
    release_created: bool = True
    release_marker_committed: bool = True
    final_remote_state_verified: bool = True
    double_final_observation_matched: bool = True
    transaction_completed: bool = True
    tag_write_authorized: bool = False
    release_mutation_authorized: bool = False
    release_authorized: bool = False
    remote_write_authorized: bool = False
    merge_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    ready_for_review_authorized: bool = False
    reviewer_request_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    product_pilot_started: bool = False
    nonce_reusable: bool = False
    transaction_scope: str = PILOT_EXACT_TASK_RELEASE_TRANSACTION_SCOPE
    authority: str = PILOT_EXACT_TASK_RELEASE_TRANSACTION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_RELEASE_TRANSACTION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_RELEASE_TRANSACTION_SCHEMA
            or self.authority != PILOT_EXACT_TASK_RELEASE_TRANSACTION_AUTHORITY
            or self.transaction_scope != PILOT_EXACT_TASK_RELEASE_TRANSACTION_SCOPE
        ):
            raise PilotExactTaskReleaseTransactionError(
                "release transaction receipt identity is unsupported"
            )
        for name in (
            "release_transaction_ledger_root_path_sha256",
            "release_key_sha256",
            "release_authorization_sha256",
            "release_authorization_payload_sha256",
            "release_state_observation_sha256",
            "release_plan_sha256",
            "release_readiness_evaluation_sha256",
            "release_intent_sha256",
            "release_plan_config_sha256",
            "remote_release_state_sha256",
            "release_authorization_config_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "pr_intent_sha256",
            "upstream_merge_transaction_lock_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
            "transaction_lock_sha256",
            "tag_marker_sha256",
            "release_marker_sha256",
            "final_remote_release_state_sha256",
            "release_body_sha256",
            "release_node_id_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("merge_commit_sha", "tag_target_sha"):
            _hex40(getattr(self, name), name=name)
        if (
            self.release_key_sha256 != self.execution_nonce_sha256
            or self.tag_target_sha != self.merge_commit_sha
            or not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskReleaseTransactionError(
                "release transaction repository/key projection is invalid"
            )
        _branch(self.release_base_branch, name="release_base_branch")
        _tag(self.tag_name, name="tag_name")
        if (
            self.release_version != f"rsi-{self.merge_commit_sha}"
            or self.tag_name != f"modelrig-rsi-{self.merge_commit_sha}"
            or self.release_name
            != f"ModelRig RSI {self.merge_commit_sha[:12]}"
        ):
            raise PilotExactTaskReleaseTransactionError(
                "release transaction deterministic release identity mismatch"
            )
        if (
            self.release_draft is not True
            or self.release_prerelease is not True
            or self.make_latest is not False
            or isinstance(self.release_id, bool)
            or not isinstance(self.release_id, int)
            or self.release_id < 1
            or not isinstance(self.release_name, str)
            or not self.release_name
        ):
            raise PilotExactTaskReleaseTransactionError(
                "release transaction release projection is invalid"
            )
        locked = _utc(self.locked_at_utc, name="locked_at_utc")
        tag_created = _utc(
            self.tag_created_at_utc,
            name="tag_created_at_utc",
        )
        release_created = _utc(
            self.release_created_at_utc,
            name="release_created_at_utc",
        )
        completed = _utc(self.completed_at_utc, name="completed_at_utc")
        if not locked <= tag_created <= release_created <= completed:
            raise PilotExactTaskReleaseTransactionError(
                "release transaction timestamps are not monotonic"
            )
        required_true = (
            "release_authorization_authenticated",
            "release_authority_consumed",
            "host_transaction_lock_committed",
            "exact_clear_lane_revalidated",
            "tag_created",
            "tag_marker_committed",
            "release_created",
            "release_marker_committed",
            "final_remote_state_verified",
            "double_final_observation_matched",
            "transaction_completed",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskReleaseTransactionError(
                "release transaction completion evidence is incomplete"
            )
        forced_false = (
            "tag_write_authorized",
            "release_mutation_authorized",
            "release_authorized",
            "remote_write_authorized",
            "merge_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "ready_for_review_authorized",
            "reviewer_request_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "product_pilot_started",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskReleaseTransactionError(
                "completed release transaction retains forbidden authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            self.canonical_json().encode("utf-8")
        ).hexdigest()

    @property
    def transaction_authenticated(self) -> bool:
        return _get_live_release_transaction_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(
        cls,
        value: Any,
    ) -> "PilotExactTaskReleaseTransactionReceipt":
        if (
            not isinstance(value, Mapping)
            or set(value) != set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        ):
            raise PilotExactTaskReleaseTransactionError(
                "release transaction receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskReleaseTransactionLedger:
    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path, Path, Path]:
        digest = _hex64(key, name="release_key_sha256")
        return (
            self.root / f"{digest}.json",
            self.root / f".{digest}.lock",
            self.root / f".{digest}.tag.json",
            self.root / f".{digest}.release.json",
        )

    def acquire(
        self,
        *,
        authorization: PilotExactTaskReleaseAuthorizationReceipt,
        locked_at_utc: str,
    ) -> bytes:
        final, lock, tag_marker, release_marker = self._paths(
            authorization.execution_nonce_sha256
        )
        if any(
            path.exists() or path.is_symlink()
            for path in (final, lock, tag_marker, release_marker)
        ):
            raise PilotExactTaskReleaseTransactionError(
                "release transaction already consumed or needs recovery"
            )
        payload = _canonical(
            {
                "schema": (
                    "kaliv-rsi-dc-l16-exact-task-"
                    "release-transaction-lock/v1"
                ),
                "ledger_scope": PILOT_EXACT_TASK_RELEASE_TRANSACTION_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "release_key_sha256": authorization.execution_nonce_sha256,
                "release_authorization_sha256": authorization.sha256,
                "release_authorization_payload_sha256": (
                    authorization.release_authorization_payload_sha256
                ),
                "release_state_observation_sha256": (
                    authorization.release_state_observation_sha256
                ),
                "release_plan_sha256": authorization.release_plan_sha256,
                "release_intent_sha256": authorization.release_intent_sha256,
                "remote_release_state_sha256": (
                    authorization.remote_release_state_sha256
                ),
                "release_authorization_config_sha256": (
                    authorization.release_authorization_config_sha256
                ),
                "publisher_credential_config_sha256": (
                    authorization.publisher_credential_config_sha256
                ),
                "publisher_credential_path_sha256": (
                    authorization.publisher_credential_path_sha256
                ),
                "repository": authorization.repository,
                "repository_id": authorization.repository_id,
                "release_base_branch": authorization.release_base_branch,
                "merge_commit_sha": authorization.merge_commit_sha,
                "tag_name": authorization.tag_name,
                "tag_target_sha": authorization.tag_target_sha,
                "release_name": authorization.release_name,
                "release_body_sha256": authorization.release_body_sha256,
                "release_draft": True,
                "release_prerelease": True,
                "make_latest": False,
                "locked_at_utc": locked_at_utc,
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskReleaseTransactionError(
                "release transaction lock could not be durably committed"
            ) from exc
        return payload

    def mark_tag(
        self,
        *,
        authorization: PilotExactTaskReleaseAuthorizationReceipt,
        lock_payload: bytes,
        tag_created_at_utc: str,
    ) -> bytes:
        _final, lock, tag_marker, release_marker = self._paths(
            authorization.execution_nonce_sha256
        )
        if release_marker.exists() or release_marker.is_symlink():
            raise PilotExactTaskReleaseTransactionError(
                "release marker exists before tag marker"
            )
        if (
            _read_bound(lock) != lock_payload
            or tag_marker.exists()
            or tag_marker.is_symlink()
        ):
            raise PilotExactTaskReleaseTransactionError(
                "release transaction durable state changed before tag marker"
            )
        payload = _canonical(
            {
                "schema": (
                    "kaliv-rsi-dc-l16-exact-task-"
                    "release-transaction-tag-marker/v1"
                ),
                "release_authorization_sha256": authorization.sha256,
                "release_key_sha256": authorization.execution_nonce_sha256,
                "tag_name": authorization.tag_name,
                "tag_target_sha": authorization.tag_target_sha,
                "tag_created_at_utc": tag_created_at_utc,
            }
        ).encode("utf-8")
        try:
            create_once_file(tag_marker, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskReleaseTransactionError(
                "tag marker could not be durably committed"
            ) from exc
        return payload

    def mark_release(
        self,
        *,
        authorization: PilotExactTaskReleaseAuthorizationReceipt,
        lock_payload: bytes,
        tag_marker_payload: bytes,
        release_id: int,
        release_node_id_sha256: str,
        release_created_at_utc: str,
    ) -> bytes:
        _final, lock, tag_marker, release_marker = self._paths(
            authorization.execution_nonce_sha256
        )
        if (
            _read_bound(lock) != lock_payload
            or _read_bound(tag_marker) != tag_marker_payload
            or release_marker.exists()
            or release_marker.is_symlink()
        ):
            raise PilotExactTaskReleaseTransactionError(
                "release transaction durable state changed before release marker"
            )
        payload = _canonical(
            {
                "schema": (
                    "kaliv-rsi-dc-l16-exact-task-"
                    "release-transaction-release-marker/v1"
                ),
                "release_authorization_sha256": authorization.sha256,
                "release_key_sha256": authorization.execution_nonce_sha256,
                "tag_name": authorization.tag_name,
                "release_id": release_id,
                "release_node_id_sha256": _hex64(
                    release_node_id_sha256,
                    name="release_node_id_sha256",
                ),
                "release_created_at_utc": release_created_at_utc,
            }
        ).encode("utf-8")
        try:
            create_once_file(release_marker, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskReleaseTransactionError(
                "release marker could not be durably committed"
            ) from exc
        return payload

    def commit(
        self,
        *,
        receipt: PilotExactTaskReleaseTransactionReceipt,
        authorization: PilotExactTaskReleaseAuthorizationReceipt,
        lock_payload: bytes,
        tag_marker_payload: bytes,
        release_marker_payload: bytes,
    ) -> PilotExactTaskReleaseTransactionReceipt:
        final, lock, tag_marker, release_marker = self._paths(
            receipt.release_key_sha256
        )
        if (
            final.exists()
            or final.is_symlink()
            or _read_bound(lock) != lock_payload
            or _read_bound(tag_marker) != tag_marker_payload
            or _read_bound(release_marker) != release_marker_payload
        ):
            raise PilotExactTaskReleaseTransactionError(
                "release transaction durable state changed before finalization"
            )
        payload = receipt.canonical_json().encode("utf-8")
        try:
            create_once_file(final, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskReleaseTransactionError(
                "release transaction final receipt could not be durably published"
            ) from exc
        parsed = PilotExactTaskReleaseTransactionReceipt.from_mapping(
            json.loads(payload.decode("utf-8"))
        )
        _mark_release_transaction_authenticated(
            parsed,
            authorization=authorization,
            final_path=final,
            final_payload=payload,
            lock_path=lock,
            lock_payload=lock_payload,
            tag_marker_path=tag_marker,
            tag_marker_payload=tag_marker_payload,
            release_marker_path=release_marker,
            release_marker_payload=release_marker_payload,
        )
        if parsed.transaction_authenticated is not True:
            raise PilotExactTaskReleaseTransactionError(
                "release transaction lost live provenance"
            )
        return parsed


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: PilotExactTaskReleaseTransactionReceipt,
        *,
        authorization: PilotExactTaskReleaseAuthorizationReceipt,
        final_path: Path,
        final_payload: bytes,
        lock_path: Path,
        lock_payload: bytes,
        tag_marker_path: Path,
        tag_marker_payload: bytes,
        release_marker_path: Path,
        release_marker_payload: bytes,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            weakref.ref(authorization),
            final_path,
            final_payload,
            lock_path,
            lock_payload,
            tag_marker_path,
            tag_marker_payload,
            release_marker_path,
            release_marker_payload,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        (
            pid,
            digest,
            receipt_ref,
            authorization_ref,
            final_path,
            final_payload,
            lock_path,
            lock_payload,
            tag_marker_path,
            tag_marker_payload,
            release_marker_path,
            release_marker_payload,
        ) = entry
        authorization = authorization_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or authorization is None
            or receipt.sha256 != digest
            or authorization.sha256 != receipt.release_authorization_sha256
            or _read_bound(final_path) != final_payload
            or _read_bound(lock_path) != lock_payload
            or _read_bound(tag_marker_path) != tag_marker_payload
            or _read_bound(release_marker_path) != release_marker_payload
        ):
            return None
        return MappingProxyType({"release_authorization": authorization})

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_release_transaction_authenticated,
    _get_live_release_transaction_inputs,
) = _live_registry()


def _credential_identity_matches(
    transport: Any,
    authorization: PilotExactTaskReleaseAuthorizationReceipt,
) -> bool:
    return (
        getattr(transport, "credential_config_sha256", None)
        == authorization.publisher_credential_config_sha256
        and getattr(transport, "credential_path_sha256", None)
        == authorization.publisher_credential_path_sha256
    )


def _double_clear(
    transport: Any,
    *,
    plan: Any,
    authorization: PilotExactTaskReleaseAuthorizationReceipt,
) -> str:
    first = _clear_state(
        transport.observe(plan),
        authorization=authorization,
    )
    second = _clear_state(
        transport.observe(plan),
        authorization=authorization,
    )
    if first != second:
        raise PilotExactTaskReleaseTransactionError(
            "clear release state changed between observations"
        )
    return first.sha256


def _double_tag_phase(
    transport: Any,
    *,
    plan: Any,
    authorization: PilotExactTaskReleaseAuthorizationReceipt,
) -> None:
    first = transport.observe_tag_phase(plan)
    second = transport.observe_tag_phase(plan)
    expected = ("exact", authorization.tag_target_sha, True)
    if first != expected or second != expected or first != second:
        raise PilotExactTaskReleaseTransactionError(
            "tag phase is not exact tag plus absent release"
        )


def _double_exact(
    transport: Any,
    *,
    plan: Any,
    authorization: PilotExactTaskReleaseAuthorizationReceipt,
    release_id: int,
    release_node_id_sha256: str,
) -> Any:
    first = _exact_state(
        transport.observe(plan),
        authorization=authorization,
        release_id=release_id,
        release_node_id_sha256=release_node_id_sha256,
    )
    second = _exact_state(
        transport.observe(plan),
        authorization=authorization,
        release_id=release_id,
        release_node_id_sha256=release_node_id_sha256,
    )
    if first != second:
        raise PilotExactTaskReleaseTransactionError(
            "final release state changed between observations"
        )
    return first


def _execute_verified_pilot_exact_task_release(
    *,
    release_authorization: PilotExactTaskReleaseAuthorizationReceipt,
    transport: Any,
    ledger: _PilotExactTaskReleaseTransactionLedger,
    now_provider: Callable[[], str],
) -> PilotExactTaskReleaseTransactionReceipt:
    authorization, _observation, _config, plan = _require_live_authorization(
        release_authorization
    )
    if transport is None or not all(
        callable(getattr(transport, name, None))
        for name in (
            "observe",
            "observe_tag_phase",
            "create_tag",
            "create_release",
        )
    ):
        raise PilotExactTaskReleaseTransactionError(
            "exact release transaction transport is required"
        )
    if not _credential_identity_matches(transport, authorization):
        raise PilotExactTaskReleaseTransactionError(
            "release transaction credential identity differs from ADR-DC-066"
        )

    locked_at = now_provider()
    _require_valid_window(authorization, locked_at)
    _double_clear(
        transport,
        plan=plan,
        authorization=authorization,
    )

    lock_payload = ledger.acquire(
        authorization=authorization,
        locked_at_utc=locked_at,
    )
    lock_sha = hashlib.sha256(lock_payload).hexdigest()

    if _require_live_authorization(authorization)[0] is not authorization:
        raise PilotExactTaskReleaseTransactionError(
            "ADR-DC-066 live authority changed after transaction consumption"
        )
    _require_valid_window(authorization, now_provider())
    _double_clear(
        transport,
        plan=plan,
        authorization=authorization,
    )
    _require_valid_window(authorization, now_provider())

    tag_target = transport.create_tag(authorization)
    if tag_target != authorization.tag_target_sha:
        raise PilotExactTaskReleaseTransactionError(
            "release transaction tag write returned unexpected target"
        )
    tag_created_at = now_provider()
    tag_marker_payload = ledger.mark_tag(
        authorization=authorization,
        lock_payload=lock_payload,
        tag_created_at_utc=tag_created_at,
    )
    tag_marker_sha = hashlib.sha256(tag_marker_payload).hexdigest()
    _double_tag_phase(
        transport,
        plan=plan,
        authorization=authorization,
    )

    _require_valid_window(authorization, now_provider())
    release_body = getattr(plan, "release_body", None)
    if (
        not isinstance(release_body, str)
        or hashlib.sha256(release_body.encode("utf-8")).hexdigest()
        != authorization.release_body_sha256
    ):
        raise PilotExactTaskReleaseTransactionError(
            "live release body differs from ADR-DC-066 authorization"
        )
    release_id, release_node_id_sha256 = transport.create_release(
        authorization,
        release_body=release_body,
    )
    release_created_at = now_provider()
    release_marker_payload = ledger.mark_release(
        authorization=authorization,
        lock_payload=lock_payload,
        tag_marker_payload=tag_marker_payload,
        release_id=release_id,
        release_node_id_sha256=release_node_id_sha256,
        release_created_at_utc=release_created_at,
    )
    release_marker_sha = hashlib.sha256(release_marker_payload).hexdigest()

    final_state = _double_exact(
        transport,
        plan=plan,
        authorization=authorization,
        release_id=release_id,
        release_node_id_sha256=release_node_id_sha256,
    )
    completed_at = now_provider()
    if _utc(completed_at, name="completed_at_utc") < _utc(
        release_created_at,
        name="release_created_at_utc",
    ):
        raise PilotExactTaskReleaseTransactionError(
            "system clock moved backwards during release transaction"
        )

    receipt = PilotExactTaskReleaseTransactionReceipt(
        release_transaction_ledger_root_path_sha256=ledger.root_sha256,
        release_key_sha256=authorization.execution_nonce_sha256,
        release_authorization_sha256=authorization.sha256,
        release_authorization_payload_sha256=(
            authorization.release_authorization_payload_sha256
        ),
        release_state_observation_sha256=(
            authorization.release_state_observation_sha256
        ),
        release_plan_sha256=authorization.release_plan_sha256,
        release_readiness_evaluation_sha256=(
            authorization.release_readiness_evaluation_sha256
        ),
        release_intent_sha256=authorization.release_intent_sha256,
        release_plan_config_sha256=authorization.release_plan_config_sha256,
        remote_release_state_sha256=authorization.remote_release_state_sha256,
        release_authorization_config_sha256=(
            authorization.release_authorization_config_sha256
        ),
        execution_nonce_sha256=authorization.execution_nonce_sha256,
        development_task_sha256=authorization.development_task_sha256,
        candidate_patch_sha256=authorization.candidate_patch_sha256,
        pr_intent_sha256=authorization.pr_intent_sha256,
        upstream_merge_transaction_lock_sha256=(
            authorization.transaction_lock_sha256
        ),
        publisher_credential_config_sha256=(
            authorization.publisher_credential_config_sha256
        ),
        publisher_credential_path_sha256=(
            authorization.publisher_credential_path_sha256
        ),
        transaction_lock_sha256=lock_sha,
        tag_marker_sha256=tag_marker_sha,
        release_marker_sha256=release_marker_sha,
        final_remote_release_state_sha256=final_state.sha256,
        repository=authorization.repository,
        repository_id=authorization.repository_id,
        release_base_branch=authorization.release_base_branch,
        merge_commit_sha=authorization.merge_commit_sha,
        release_version=authorization.release_version,
        tag_name=authorization.tag_name,
        tag_target_sha=authorization.tag_target_sha,
        release_name=authorization.release_name,
        release_body_sha256=authorization.release_body_sha256,
        release_draft=True,
        release_prerelease=True,
        make_latest=False,
        release_id=release_id,
        release_node_id_sha256=release_node_id_sha256,
        locked_at_utc=locked_at,
        tag_created_at_utc=tag_created_at,
        release_created_at_utc=release_created_at,
        completed_at_utc=completed_at,
    )
    return ledger.commit(
        receipt=receipt,
        authorization=authorization,
        lock_payload=lock_payload,
        tag_marker_payload=tag_marker_payload,
        release_marker_payload=release_marker_payload,
    )


def _canonical_ledger() -> _PilotExactTaskReleaseTransactionLedger:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            root = _require_host_controlled_ledger_root(_POSIX_LEDGER)
        elif os.name == "nt":
            root = _require_host_controlled_ledger_root(_WINDOWS_LEDGER)
        else:
            raise PilotExactTaskReleaseTransactionError(
                "release transaction platform is unsupported"
            )
        return _PilotExactTaskReleaseTransactionLedger(root)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskReleaseTransactionError(
            "release transaction ledger is not host-admin controlled"
        ) from exc


def execute_pilot_exact_task_release(
    release_authorization: PilotExactTaskReleaseAuthorizationReceipt,
) -> PilotExactTaskReleaseTransactionReceipt:
    """Consume one exact ADR-DC-066 authority and create tag + draft release."""
    try:
        authorization, _observation, _config, _plan = (
            _require_live_authorization(release_authorization)
        )
        credential, credential_digest, credential_path = (
            publication_tx_boundary._canonical_credential()
        )
        transport = _GitHubExactReleaseTransactionTransport(
            credential=credential,
            credential_config_sha256=credential_digest,
            credential_path=credential_path,
        )
        return _execute_verified_pilot_exact_task_release(
            release_authorization=authorization,
            transport=transport,
            ledger=_canonical_ledger(),
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskReleaseTransactionError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskReleaseTransactionError(
            "exact release transaction failed closed"
        ) from exc


__all__: list[str] = []
