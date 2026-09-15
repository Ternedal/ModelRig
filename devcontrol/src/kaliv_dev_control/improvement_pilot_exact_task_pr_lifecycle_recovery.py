"""ADR-DC-055 dual-authorized recovery for interrupted exact PR lifecycle transactions.

Recovery is intentionally narrower than ADR-DC-054. It never replays the
ready-for-review mutation. It may adopt an already-observed exact non-draft PR
and either request the exact missing reviewer set or finalize already-complete
remote lifecycle state. Both automatic actions require two independent detached
Ed25519 signatures over one exact durable/remote recovery-state fingerprint.

A lock-only transaction whose PR is still draft remains manual/fail-closed.
No merge, release, deploy, production-activation or nonce-reuse authority is
created by this boundary.
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
    TrustedEd25519AuthorityKey,
    asymmetric_authority_key_custody_policy_sha256,
)
from .durable_publication import DurablePublicationError, create_once_file
from .improvement_physical_authority_keyring import (
    PhysicalRequestAuthorityKeyringError,
    _read_keyring_bytes,
)
from . import improvement_pilot_exact_task_local_commit_transaction as local_tx_boundary
from . import improvement_pilot_exact_task_pr_lifecycle_authorization as lifecycle_auth_boundary
from . import improvement_pilot_exact_task_pr_lifecycle_transaction as lifecycle_tx_boundary
from . import improvement_pilot_exact_task_remote_publication_authorization as publication_auth_boundary
from . import improvement_pilot_exact_task_remote_publication_recovery as publication_recovery_boundary
from . import improvement_pilot_exact_task_remote_publication_transaction as publication_tx_boundary
from .improvement_pilot_exact_task_pr_lifecycle_authorization import (
    PilotExactTaskPrLifecycleAuthorizationReceipt,
)
from .improvement_pilot_exact_task_remote_publication_transaction import (
    PilotExactTaskGitHubPublisherCredential,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_PR_LIFECYCLE_RECOVERY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-lifecycle-recovery-receipt/v1"
)
PILOT_EXACT_TASK_PR_LIFECYCLE_RECOVERY_AUTHORITY = (
    "dual-reviewed-dc-l16-exact-pr-lifecycle-recovery-only"
)
PILOT_EXACT_TASK_PR_LIFECYCLE_RECOVERY_LEDGER_SCOPE = "canonical-host-local-v1"
PILOT_EXACT_TASK_PR_LIFECYCLE_RECOVERY_KEYRING_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-lifecycle-recovery-keyring/v1"
)
PILOT_EXACT_TASK_PR_LIFECYCLE_RECOVERY_PAYLOAD_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-lifecycle-recovery-authorization-payload/v1"
)
_RECOVERY_POLICY_DOMAIN = (
    b"kaliv-rsi-dc-l16-exact-task-pr-lifecycle-recovery-policy/v1\0"
)
_MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
_MAX_KEYRING_BYTES = 1024 * 1024
_MAX_API_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_AUTH_SECONDS = 10 * 60
_TIMEOUT_SECONDS = 30.0
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_BRANCH = re.compile(r"^(?![./])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}$")
_NODE = re.compile(r"^[A-Za-z0-9_=-]{8,256}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_GITHUB_API_ROOT = "https://api.github.com"

_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-pr-lifecycle-recovery-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-pr-lifecycle-recovery-ledger-v1"
)
_POSIX_KEYRING = Path(
    "/etc/modelrig/devcontrol/authority/"
    "rsi-pilot-exact-task-pr-lifecycle-recovery-keyring-v1.json"
)
_WINDOWS_KEYRING = (
    Path(r"C:\Program Files\ModelRig\DevControl\authority")
    / "rsi-pilot-exact-task-pr-lifecycle-recovery-keyring-v1.json"
)

PILOT_EXACT_TASK_PR_LIFECYCLE_RECOVERY_POLICY = (
    "Recover only one previously consumed ADR-DC-054 lifecycle transaction nonce.",
    "Reconstruct exact PR/base/head/reviewer intent from durable ADR-DC-053 plus upstream publication evidence.",
    "Never replay ready-for-review; a still-draft PR requires manual intervention.",
    "Permit reviewer-request recovery only when the exact PR is already non-draft and has no requested reviewers.",
    "Permit write-free finalization only when the exact PR is already non-draft with the exact authorized reviewer set.",
    "Require two independent detached Ed25519 signatures over the exact recovery-state fingerprint and action.",
    "Durably consume recovery authorization before any missing reviewer request.",
    "Never make the nonce reusable and never grant push, merge, release, deploy or production activation authority.",
)


class PilotExactTaskPrLifecycleRecoveryError(ValueError):
    """Interrupted lifecycle state is ambiguous, unauthenticated or unsafe."""


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
        raise PilotExactTaskPrLifecycleRecoveryError(
            "lifecycle recovery evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrLifecycleRecoveryError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrLifecycleRecoveryError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrLifecycleRecoveryError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrLifecycleRecoveryError(f"{name} is invalid") from exc


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
        raise PilotExactTaskPrLifecycleRecoveryError(f"{name} is invalid")
    return value


def _node(value: Any) -> str:
    if not isinstance(value, str) or _NODE.fullmatch(value) is None:
        raise PilotExactTaskPrLifecycleRecoveryError(
            "pull-request node id is invalid"
        )
    return value


def pilot_exact_task_pr_lifecycle_recovery_policy_sha256() -> str:
    payload = json.dumps(
        list(PILOT_EXACT_TASK_PR_LIFECYCLE_RECOVERY_POLICY),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(_RECOVERY_POLICY_DOMAIN + payload).hexdigest()


def _read_bytes(path: Path) -> bytes | None:
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


def _read_canonical_object(path: Path, *, name: str) -> tuple[dict[str, Any], bytes]:
    payload = _read_bytes(path)
    if payload is None:
        raise PilotExactTaskPrLifecycleRecoveryError(f"{name} is unavailable")
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrLifecycleRecoveryError(
            f"{name} is invalid JSON"
        ) from exc
    if not isinstance(raw, dict) or _canonical(raw).encode("utf-8") != payload:
        raise PilotExactTaskPrLifecycleRecoveryError(
            f"{name} is not canonical JSON"
        )
    return raw, payload


def _payload_sha256(payload: bytes) -> str:
    if not isinstance(payload, bytes) or not payload:
        raise PilotExactTaskPrLifecycleRecoveryError(
            "durable lifecycle payload is missing"
        )
    return hashlib.sha256(payload).hexdigest()


def _reviewer_set_sha256(
    usernames: tuple[str, ...], teams: tuple[str, ...]
) -> str:
    return hashlib.sha256(
        _canonical(
            {
                "reviewer_usernames": list(usernames),
                "reviewer_team_slugs": list(teams),
            }
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class _LifecycleRecoveryIntent:
    pr_lifecycle_authorization_sha256: str
    post_publication_attestation_sha256: str
    lifecycle_config_sha256: str
    reviewer_set_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    repository: str
    repository_id: str
    base_branch: str
    head_branch: str
    exact_task_base_sha: str
    predicted_commit_sha: str
    pull_request_number: int
    pull_request_api_url: str
    reviewer_usernames: tuple[str, ...]
    reviewer_team_slugs: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "pr_lifecycle_authorization_sha256",
            "post_publication_attestation_sha256",
            "lifecycle_config_sha256",
            "reviewer_set_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "pr_intent_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("exact_task_base_sha", "predicted_commit_sha"):
            _hex40(getattr(self, name), name=name)
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "recovery repository identity is invalid"
            )
        _branch(self.base_branch, name="base_branch")
        _branch(self.head_branch, name="head_branch")
        if (
            isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"{_GITHUB_API_ROOT}/repos/{self.repository}/pulls/{self.pull_request_number}"
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "recovery pull-request identity is invalid"
            )
        if (
            list(self.reviewer_usernames)
            != sorted(set(self.reviewer_usernames))
            or list(self.reviewer_team_slugs)
            != sorted(set(self.reviewer_team_slugs))
            or (
                not self.reviewer_usernames
                and not self.reviewer_team_slugs
            )
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "recovery reviewer set is invalid"
            )
        if (
            _reviewer_set_sha256(
                self.reviewer_usernames, self.reviewer_team_slugs
            )
            != self.reviewer_set_sha256
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "recovery reviewer set hash is inconsistent"
            )


@dataclass(frozen=True, slots=True)
class _LifecycleRemoteState:
    pull_request_node_id: str
    draft: bool
    reviewer_usernames: tuple[str, ...]
    reviewer_team_slugs: tuple[str, ...]
    repository: str
    repository_id: str
    base_branch: str
    base_sha: str
    head_branch: str
    head_sha: str
    pull_request_number: int
    pull_request_api_url: str
    maintainer_can_modify: bool
    state: str

    def __post_init__(self) -> None:
        _node(self.pull_request_node_id)
        if self.state != "open":
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery pull request is not open"
            )
        if not isinstance(self.draft, bool):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery draft state is invalid"
            )
        if self.maintainer_can_modify is not False:
            raise PilotExactTaskPrLifecycleRecoveryError(
                "maintainer_can_modify must remain false"
            )
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "remote recovery repository identity is invalid"
            )
        _branch(self.base_branch, name="base_branch")
        _branch(self.head_branch, name="head_branch")
        _hex40(self.base_sha, name="base_sha")
        _hex40(self.head_sha, name="head_sha")
        if (
            isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"{_GITHUB_API_ROOT}/repos/{self.repository}/pulls/{self.pull_request_number}"
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "remote recovery pull-request identity is invalid"
            )
        if (
            list(self.reviewer_usernames)
            != sorted(set(self.reviewer_usernames))
            or list(self.reviewer_team_slugs)
            != sorted(set(self.reviewer_team_slugs))
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "remote reviewer set is not sorted/unique"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "pull_request_node_id_sha256": hashlib.sha256(
                self.pull_request_node_id.encode("utf-8")
            ).hexdigest(),
            "draft": self.draft,
            "reviewer_usernames": list(self.reviewer_usernames),
            "reviewer_team_slugs": list(self.reviewer_team_slugs),
            "repository": self.repository,
            "repository_id": self.repository_id,
            "base_branch": self.base_branch,
            "base_sha": self.base_sha,
            "head_branch": self.head_branch,
            "head_sha": self.head_sha,
            "pull_request_number": self.pull_request_number,
            "pull_request_api_url": self.pull_request_api_url,
            "maintainer_can_modify": self.maintainer_can_modify,
            "state": self.state,
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            _canonical(self.to_dict()).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class PilotExactTaskPrLifecycleRecoveryState:
    transaction_key_sha256: str
    transaction_lock_sha256: str
    ready_marker_sha256: str | None
    reviewers_marker_sha256: str | None
    pr_lifecycle_authorization_sha256: str
    post_publication_attestation_sha256: str
    lifecycle_config_sha256: str
    reviewer_set_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    repository: str
    repository_id: str
    base_branch: str
    head_branch: str
    exact_task_base_sha: str
    predicted_commit_sha: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_node_id_sha256: str
    reviewer_usernames: tuple[str, ...]
    reviewer_team_slugs: tuple[str, ...]
    durable_transaction_state: str
    remote_lifecycle_state: str
    action_required: str
    manual_intervention_required: bool
    remote_state_sha256: str
    observed_at_utc: str

    def __post_init__(self) -> None:
        for name in (
            "transaction_key_sha256",
            "transaction_lock_sha256",
            "pr_lifecycle_authorization_sha256",
            "post_publication_attestation_sha256",
            "lifecycle_config_sha256",
            "reviewer_set_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "pr_intent_sha256",
            "pull_request_node_id_sha256",
            "remote_state_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("ready_marker_sha256", "reviewers_marker_sha256"):
            value = getattr(self, name)
            if value is not None:
                _hex64(value, name=name)
        for name in ("exact_task_base_sha", "predicted_commit_sha"):
            _hex40(getattr(self, name), name=name)
        if self.transaction_key_sha256 != self.execution_nonce_sha256:
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery key differs from execution nonce"
            )
        if self.durable_transaction_state not in {
            "lock_only",
            "ready_marked",
            "reviewers_marked",
        }:
            raise PilotExactTaskPrLifecycleRecoveryError(
                "durable lifecycle recovery state is invalid"
            )
        if self.remote_lifecycle_state not in {
            "draft_empty",
            "ready_empty",
            "ready_exact_reviewers",
        }:
            raise PilotExactTaskPrLifecycleRecoveryError(
                "remote lifecycle recovery state is invalid"
            )
        if self.action_required not in {
            "manual_intervention",
            "request_missing_reviewers",
            "finalize_existing_state",
        }:
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery action is invalid"
            )
        if self.manual_intervention_required is not (
            self.action_required == "manual_intervention"
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "manual-intervention flag is inconsistent"
            )
        if (
            self.action_required == "request_missing_reviewers"
            and self.remote_lifecycle_state != "ready_empty"
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "reviewer recovery requires exact non-draft empty-reviewer state"
            )
        if (
            self.action_required == "finalize_existing_state"
            and self.remote_lifecycle_state != "ready_exact_reviewers"
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "write-free finalization requires exact reviewer state"
            )
        if (
            self.action_required == "manual_intervention"
            and self.remote_lifecycle_state != "draft_empty"
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "manual lifecycle state is inconsistent"
            )
        if (
            isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"{_GITHUB_API_ROOT}/repos/{self.repository}/pulls/{self.pull_request_number}"
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "recovery PR identity is invalid"
            )
        if (
            _reviewer_set_sha256(
                self.reviewer_usernames, self.reviewer_team_slugs
            )
            != self.reviewer_set_sha256
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "recovery reviewer set digest is inconsistent"
            )
        _utc(self.observed_at_utc, name="observed_at_utc")

    def fingerprint_mapping(self) -> dict[str, Any]:
        value = self.to_dict()
        value.pop("observed_at_utc")
        return value

    @property
    def fingerprint_sha256(self) -> str:
        return hashlib.sha256(
            _canonical(self.fingerprint_mapping()).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        result = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }
        result["reviewer_usernames"] = list(self.reviewer_usernames)
        result["reviewer_team_slugs"] = list(self.reviewer_team_slugs)
        return result


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class _GitHubLifecycleRecoveryTransport:
    """Credential-free exact reads and optional exact reviewer request."""

    def __init__(
        self,
        credential: PilotExactTaskGitHubPublisherCredential | None = None,
        *,
        credential_config_sha256: str | None = None,
        credential_path: Path | None = None,
    ) -> None:
        self.credential = credential
        self.credential_config_sha256 = credential_config_sha256
        self.credential_path = None if credential_path is None else Path(
            credential_path
        )
        self._opener = urllib.request.build_opener(_NoRedirect())

    @staticmethod
    def _repo_root(intent: _LifecycleRecoveryIntent) -> str:
        owner, repo = intent.repository.split("/", 1)
        return (
            f"/repos/{urllib.parse.quote(owner, safe='')}/"
            f"{urllib.parse.quote(repo, safe='')}"
        )

    def _request(
        self,
        *,
        path: str,
        method: str,
        body: Mapping[str, Any] | None = None,
        expected_status: int,
    ) -> Any:
        if (
            not isinstance(path, str)
            or not path.startswith("/repos/")
            or ".." in path
            or method not in {"GET", "POST"}
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery GitHub request is outside exact scope"
            )
        payload = None
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ModelRig-DevControl-LifecycleRecovery/1",
        }
        if method == "POST":
            if self.credential is None or not isinstance(body, Mapping):
                raise PilotExactTaskPrLifecycleRecoveryError(
                    "reviewer recovery lacks exact credential/body"
                )
            payload = _canonical(dict(body)).encode("utf-8")
            headers["Content-Type"] = "application/json"
            headers["Authorization"] = f"Bearer {self.credential.token}"
        elif body is not None:
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery GET cannot carry a body"
            )
        url = _GITHUB_API_ROOT + path
        request = urllib.request.Request(
            url,
            data=payload,
            method=method,
            headers=headers,
        )
        try:
            response = self._opener.open(request, timeout=_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            raise PilotExactTaskPrLifecycleRecoveryError(
                f"lifecycle recovery GitHub request failed with HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery GitHub request failed"
            ) from exc
        with response:
            if response.status != expected_status or response.geturl() != url:
                raise PilotExactTaskPrLifecycleRecoveryError(
                    "lifecycle recovery GitHub response identity/status is unexpected"
                )
            raw = response.read(_MAX_API_RESPONSE_BYTES + 1)
        if not raw or len(raw) > _MAX_API_RESPONSE_BYTES:
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery GitHub response size is invalid"
            )
        try:
            return json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery GitHub response is invalid JSON"
            ) from exc

    def observe(self, intent: _LifecycleRecoveryIntent) -> _LifecycleRemoteState:
        root = self._repo_root(intent)
        pr = self._request(
            path=f"{root}/pulls/{intent.pull_request_number}",
            method="GET",
            expected_status=200,
        )
        reviewers = self._request(
            path=(
                f"{root}/pulls/{intent.pull_request_number}/"
                "requested_reviewers"
            ),
            method="GET",
            expected_status=200,
        )
        if not isinstance(pr, Mapping) or not isinstance(reviewers, Mapping):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery observation is invalid"
            )
        base = pr.get("base")
        head = pr.get("head")
        base_repo = base.get("repo") if isinstance(base, Mapping) else None
        if (
            not isinstance(base, Mapping)
            or not isinstance(head, Mapping)
            or not isinstance(base_repo, Mapping)
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery refs are invalid"
            )
        users = reviewers.get("users")
        teams = reviewers.get("teams")
        if not isinstance(users, list) or not isinstance(teams, list):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery requested-reviewer state is invalid"
            )
        usernames: list[str] = []
        team_slugs: list[str] = []
        for item in users:
            if not isinstance(item, Mapping) or not isinstance(
                item.get("login"), str
            ):
                raise PilotExactTaskPrLifecycleRecoveryError(
                    "requested reviewer identity is invalid"
                )
            usernames.append(item["login"].lower())
        for item in teams:
            if not isinstance(item, Mapping) or not isinstance(
                item.get("slug"), str
            ):
                raise PilotExactTaskPrLifecycleRecoveryError(
                    "requested reviewer team identity is invalid"
                )
            team_slugs.append(item["slug"].lower())
        state = _LifecycleRemoteState(
            pull_request_node_id=_node(pr.get("node_id")),
            draft=pr.get("draft"),
            reviewer_usernames=tuple(sorted(usernames)),
            reviewer_team_slugs=tuple(sorted(team_slugs)),
            repository=intent.repository,
            repository_id=str(base_repo.get("id")),
            base_branch=base.get("ref"),
            base_sha=base.get("sha"),
            head_branch=head.get("ref"),
            head_sha=head.get("sha"),
            pull_request_number=pr.get("number"),
            pull_request_api_url=pr.get("url"),
            maintainer_can_modify=pr.get("maintainer_can_modify"),
            state=pr.get("state"),
        )
        _validate_remote_state(state, intent)
        return state

    def request_reviewers(self, intent: _LifecycleRecoveryIntent) -> None:
        if self.credential is None:
            raise PilotExactTaskPrLifecycleRecoveryError(
                "reviewer recovery credential is unavailable"
            )
        if (
            self.credential.repository != intent.repository
            or self.credential.repository_id != intent.repository_id
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "reviewer recovery credential is not repository-bound"
            )
        root = self._repo_root(intent)
        value = self._request(
            path=(
                f"{root}/pulls/{intent.pull_request_number}/"
                "requested_reviewers"
            ),
            method="POST",
            body={
                "reviewers": list(intent.reviewer_usernames),
                "team_reviewers": list(intent.reviewer_team_slugs),
            },
            expected_status=201,
        )
        if not isinstance(value, Mapping) or value.get(
            "number"
        ) != intent.pull_request_number:
            raise PilotExactTaskPrLifecycleRecoveryError(
                "reviewer recovery did not return exact pull request"
            )


def _validate_remote_state(
    state: _LifecycleRemoteState, intent: _LifecycleRecoveryIntent
) -> None:
    if (
        state.repository != intent.repository
        or state.repository_id != intent.repository_id
        or state.base_branch != intent.base_branch
        or state.base_sha != intent.exact_task_base_sha
        or state.head_branch != intent.head_branch
        or state.head_sha != intent.predicted_commit_sha
        or state.pull_request_number != intent.pull_request_number
        or state.pull_request_api_url != intent.pull_request_api_url
    ):
        raise PilotExactTaskPrLifecycleRecoveryError(
            "GitHub lifecycle recovery state is not exact"
        )


def _load_authorization(
    *,
    key: str,
    authorization_ledger_root: Path,
) -> tuple[PilotExactTaskPrLifecycleAuthorizationReceipt, bytes]:
    ledger = lifecycle_auth_boundary._PilotExactTaskPrLifecycleAuthorizationLedger(
        authorization_ledger_root
    )
    final, lock = ledger._paths(key)
    raw, payload = _read_canonical_object(
        final, name="ADR-DC-053 lifecycle authorization receipt"
    )
    lock_raw, _lock_payload = _read_canonical_object(
        lock, name="ADR-DC-053 lifecycle authorization lock"
    )
    try:
        receipt = PilotExactTaskPrLifecycleAuthorizationReceipt.from_mapping(raw)
    except Exception as exc:
        raise PilotExactTaskPrLifecycleRecoveryError(
            "ADR-DC-053 durable authorization receipt is invalid"
        ) from exc
    if (
        receipt.execution_nonce_sha256 != key
        or receipt.lifecycle_key_sha256 != key
        or receipt.host_lifecycle_guard_committed is not True
        or receipt.ready_for_review_authorized is not True
        or receipt.reviewer_request_authorized is not True
        or receipt.pr_mutation_authorized is not True
        or receipt.remote_write_authorized is not True
        or receipt.push_authorized is not False
        or receipt.merge_authorized is not False
        or receipt.release_authorized is not False
        or receipt.deploy_authorized is not False
        or receipt.production_activation_authorized is not False
    ):
        raise PilotExactTaskPrLifecycleRecoveryError(
            "ADR-DC-053 durable authorization is not exact"
        )
    expected_lock = {
        "schema",
        "ledger_scope",
        "ledger_root_path_sha256",
        "lifecycle_key_sha256",
        "post_publication_attestation_sha256",
        "lifecycle_authorization_payload_sha256",
        "lifecycle_config_sha256",
        "reviewer_set_sha256",
        "pull_request_number",
        "predicted_commit_sha",
    }
    if (
        set(lock_raw) != expected_lock
        or lock_raw.get("schema")
        != "kaliv-rsi-dc-l16-exact-task-pr-lifecycle-authorization-lock/v1"
        or lock_raw.get("ledger_scope")
        != lifecycle_auth_boundary.PILOT_EXACT_TASK_PR_LIFECYCLE_LEDGER_SCOPE
        or lock_raw.get("ledger_root_path_sha256") != ledger.root_sha256
        or lock_raw.get("lifecycle_key_sha256") != key
        or lock_raw.get("post_publication_attestation_sha256")
        != receipt.post_publication_attestation_sha256
        or lock_raw.get("lifecycle_authorization_payload_sha256")
        != receipt.lifecycle_authorization_payload_sha256
        or lock_raw.get("lifecycle_config_sha256")
        != receipt.lifecycle_config_sha256
        or lock_raw.get("reviewer_set_sha256") != receipt.reviewer_set_sha256
        or lock_raw.get("pull_request_number") != receipt.pull_request_number
        or lock_raw.get("predicted_commit_sha") != receipt.predicted_commit_sha
    ):
        raise PilotExactTaskPrLifecycleRecoveryError(
            "ADR-DC-053 lifecycle authorization lock does not bind receipt"
        )
    return receipt, payload


def _reconstruct_intent(
    *,
    key: str,
    lifecycle_authorization_ledger_root: Path,
    publication_authorization_ledger_root: Path,
    local_transaction_ledger_root: Path,
) -> _LifecycleRecoveryIntent:
    authorization, _payload = _load_authorization(
        key=key,
        authorization_ledger_root=lifecycle_authorization_ledger_root,
    )
    try:
        publication_auth, local_tx = publication_recovery_boundary._load_receipts(
            key=key,
            authorization_ledger_root=publication_authorization_ledger_root,
            local_transaction_ledger_root=local_transaction_ledger_root,
        )
        publication_intent = publication_recovery_boundary._intent(
            publication_auth, local_tx
        )
    except Exception as exc:
        raise PilotExactTaskPrLifecycleRecoveryError(
            "upstream exact publication intent reconstruction failed"
        ) from exc
    if (
        authorization.execution_nonce_sha256 != publication_intent.execution_nonce_sha256
        or authorization.development_task_sha256
        != publication_intent.development_task_sha256
        or authorization.candidate_patch_sha256
        != publication_intent.candidate_patch_sha256
        or authorization.pr_intent_sha256 != publication_intent.pr_intent_sha256
        or authorization.repository != publication_intent.repository
        or authorization.repository_id != publication_intent.repository_id
        or authorization.base_branch != publication_intent.base_branch
        or authorization.head_branch != publication_intent.head_branch
        or authorization.predicted_commit_sha
        != publication_intent.predicted_commit_sha
    ):
        raise PilotExactTaskPrLifecycleRecoveryError(
            "ADR-DC-053 lifecycle intent disagrees with durable publication intent"
        )
    return _LifecycleRecoveryIntent(
        pr_lifecycle_authorization_sha256=authorization.sha256,
        post_publication_attestation_sha256=authorization.post_publication_attestation_sha256,
        lifecycle_config_sha256=authorization.lifecycle_config_sha256,
        reviewer_set_sha256=authorization.reviewer_set_sha256,
        execution_nonce_sha256=key,
        development_task_sha256=authorization.development_task_sha256,
        candidate_patch_sha256=authorization.candidate_patch_sha256,
        pr_intent_sha256=authorization.pr_intent_sha256,
        repository=authorization.repository,
        repository_id=authorization.repository_id,
        base_branch=authorization.base_branch,
        head_branch=authorization.head_branch,
        exact_task_base_sha=publication_intent.base_sha,
        predicted_commit_sha=authorization.predicted_commit_sha,
        pull_request_number=authorization.pull_request_number,
        pull_request_api_url=authorization.pull_request_api_url,
        reviewer_usernames=authorization.reviewer_usernames,
        reviewer_team_slugs=authorization.reviewer_team_slugs,
    )


def _validate_transaction_lock(
    raw: Mapping[str, Any],
    *,
    key: str,
    intent: _LifecycleRecoveryIntent,
    transaction_ledger_root_sha256: str,
) -> tuple[str, str, str]:
    expected = {
        "schema",
        "ledger_scope",
        "ledger_root_path_sha256",
        "transaction_key_sha256",
        "pr_lifecycle_authorization_sha256",
        "post_publication_attestation_sha256",
        "lifecycle_config_sha256",
        "reviewer_set_sha256",
        "pull_request_number",
        "predicted_commit_sha",
        "pre_state_sha256",
        "publisher_credential_config_sha256",
        "publisher_credential_path_sha256",
    }
    if (
        set(raw) != expected
        or raw.get("schema")
        != "kaliv-rsi-dc-l16-exact-task-pr-lifecycle-transaction-lock/v1"
        or raw.get("ledger_scope")
        != lifecycle_tx_boundary.PILOT_EXACT_TASK_PR_LIFECYCLE_TRANSACTION_LEDGER_SCOPE
        or raw.get("ledger_root_path_sha256")
        != transaction_ledger_root_sha256
        or raw.get("transaction_key_sha256") != key
        or raw.get("pr_lifecycle_authorization_sha256")
        != intent.pr_lifecycle_authorization_sha256
        or raw.get("post_publication_attestation_sha256")
        != intent.post_publication_attestation_sha256
        or raw.get("lifecycle_config_sha256")
        != intent.lifecycle_config_sha256
        or raw.get("reviewer_set_sha256") != intent.reviewer_set_sha256
        or raw.get("pull_request_number") != intent.pull_request_number
        or raw.get("predicted_commit_sha") != intent.predicted_commit_sha
    ):
        raise PilotExactTaskPrLifecycleRecoveryError(
            "ADR-DC-054 transaction lock does not bind exact lifecycle intent"
        )
    return (
        _hex64(raw.get("pre_state_sha256"), name="pre_state_sha256"),
        _hex64(
            raw.get("publisher_credential_config_sha256"),
            name="publisher_credential_config_sha256",
        ),
        _hex64(
            raw.get("publisher_credential_path_sha256"),
            name="publisher_credential_path_sha256",
        ),
    )


def _validate_ready_marker(
    raw: Mapping[str, Any], *, key: str, intent: _LifecycleRecoveryIntent
) -> tuple[str, str, str]:
    expected = {
        "schema",
        "transaction_key_sha256",
        "pr_lifecycle_authorization_sha256",
        "pull_request_node_id_sha256",
        "ready_state_sha256",
        "ready_at_utc",
    }
    if (
        set(raw) != expected
        or raw.get("schema")
        != "kaliv-rsi-dc-l16-exact-task-pr-lifecycle-ready-marker/v1"
        or raw.get("transaction_key_sha256") != key
        or raw.get("pr_lifecycle_authorization_sha256")
        != intent.pr_lifecycle_authorization_sha256
    ):
        raise PilotExactTaskPrLifecycleRecoveryError(
            "ADR-DC-054 ready marker is not exact"
        )
    node_sha = _hex64(
        raw.get("pull_request_node_id_sha256"),
        name="pull_request_node_id_sha256",
    )
    state_sha = _hex64(
        raw.get("ready_state_sha256"), name="ready_state_sha256"
    )
    timestamp = raw.get("ready_at_utc")
    _utc(timestamp, name="ready_at_utc")
    return node_sha, state_sha, timestamp


def _validate_reviewers_marker(
    raw: Mapping[str, Any], *, key: str, intent: _LifecycleRecoveryIntent
) -> tuple[str, str]:
    expected = {
        "schema",
        "transaction_key_sha256",
        "pr_lifecycle_authorization_sha256",
        "reviewer_set_sha256",
        "final_state_sha256",
        "reviewers_requested_at_utc",
    }
    if (
        set(raw) != expected
        or raw.get("schema")
        != "kaliv-rsi-dc-l16-exact-task-pr-lifecycle-reviewers-marker/v1"
        or raw.get("transaction_key_sha256") != key
        or raw.get("pr_lifecycle_authorization_sha256")
        != intent.pr_lifecycle_authorization_sha256
        or raw.get("reviewer_set_sha256") != intent.reviewer_set_sha256
    ):
        raise PilotExactTaskPrLifecycleRecoveryError(
            "ADR-DC-054 reviewers marker is not exact"
        )
    state_sha = _hex64(
        raw.get("final_state_sha256"), name="final_state_sha256"
    )
    timestamp = raw.get("reviewers_requested_at_utc")
    _utc(timestamp, name="reviewers_requested_at_utc")
    return state_sha, timestamp


def _observe_verified_recovery_state(
    *,
    execution_nonce_sha256: str,
    transaction_ledger_root: Path,
    lifecycle_authorization_ledger_root: Path,
    publication_authorization_ledger_root: Path,
    local_transaction_ledger_root: Path,
    transport: Any,
    now_provider: Callable[[], str],
) -> tuple[PilotExactTaskPrLifecycleRecoveryState, _LifecycleRecoveryIntent]:
    key = _hex64(
        execution_nonce_sha256, name="execution_nonce_sha256"
    )
    intent = _reconstruct_intent(
        key=key,
        lifecycle_authorization_ledger_root=lifecycle_authorization_ledger_root,
        publication_authorization_ledger_root=publication_authorization_ledger_root,
        local_transaction_ledger_root=local_transaction_ledger_root,
    )
    ledger = lifecycle_tx_boundary._PilotExactTaskPrLifecycleTransactionLedger(
        transaction_ledger_root
    )
    final, lock, ready, reviewers = ledger._paths(key)
    if final.exists() or final.is_symlink():
        raise PilotExactTaskPrLifecycleRecoveryError(
            "ADR-DC-054 transaction already completed; recovery is not applicable"
        )
    lock_raw, lock_payload = _read_canonical_object(
        lock, name="ADR-DC-054 transaction lock"
    )
    (
        pre_state_sha256,
        _credential_config_sha256,
        _credential_path_sha256,
    ) = _validate_transaction_lock(
        lock_raw,
        key=key,
        intent=intent,
        transaction_ledger_root_sha256=ledger.root_sha256,
    )
    ready_present = ready.exists() or ready.is_symlink()
    reviewers_present = reviewers.exists() or reviewers.is_symlink()
    if reviewers_present and not ready_present:
        raise PilotExactTaskPrLifecycleRecoveryError(
            "reviewers marker exists without ready marker"
        )

    ready_hash = None
    reviewers_hash = None
    ready_node_sha = None
    ready_state_sha = None
    reviewers_state_sha = None
    if ready_present:
        ready_raw, ready_payload = _read_canonical_object(
            ready, name="ADR-DC-054 ready marker"
        )
        ready_node_sha, ready_state_sha, _ready_at = _validate_ready_marker(
            ready_raw, key=key, intent=intent
        )
        ready_hash = _payload_sha256(ready_payload)
    if reviewers_present:
        reviewers_raw, reviewers_payload = _read_canonical_object(
            reviewers, name="ADR-DC-054 reviewers marker"
        )
        (
            reviewers_state_sha,
            _reviewers_at,
        ) = _validate_reviewers_marker(
            reviewers_raw, key=key, intent=intent
        )
        reviewers_hash = _payload_sha256(reviewers_payload)

    durable_state = (
        "reviewers_marked"
        if reviewers_present
        else "ready_marked"
        if ready_present
        else "lock_only"
    )
    if transport is None or not callable(getattr(transport, "observe", None)):
        raise PilotExactTaskPrLifecycleRecoveryError(
            "read-only lifecycle recovery observer is required"
        )
    remote = transport.observe(intent)
    if type(remote) is not _LifecycleRemoteState:
        raise PilotExactTaskPrLifecycleRecoveryError(
            "lifecycle recovery observer returned invalid state"
        )
    _validate_remote_state(remote, intent)
    node_sha = hashlib.sha256(
        remote.pull_request_node_id.encode("utf-8")
    ).hexdigest()
    if ready_node_sha is not None and ready_node_sha != node_sha:
        raise PilotExactTaskPrLifecycleRecoveryError(
            "remote PR node differs from durable ready marker"
        )

    exact_reviewers = (
        remote.reviewer_usernames == intent.reviewer_usernames
        and remote.reviewer_team_slugs == intent.reviewer_team_slugs
    )
    no_reviewers = (
        not remote.reviewer_usernames and not remote.reviewer_team_slugs
    )
    if remote.draft:
        if not no_reviewers or durable_state != "lock_only":
            raise PilotExactTaskPrLifecycleRecoveryError(
                "draft remote state contradicts durable lifecycle phase"
            )
        if remote.sha256 != pre_state_sha256:
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lock-only draft state differs from consumed pre-state"
            )
        remote_state = "draft_empty"
        action = "manual_intervention"
    elif no_reviewers:
        if durable_state == "reviewers_marked":
            raise PilotExactTaskPrLifecycleRecoveryError(
                "reviewers marker exists but GitHub has no requested reviewers"
            )
        if (
            durable_state == "ready_marked"
            and ready_state_sha != remote.sha256
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "current ready state differs from durable ready marker"
            )
        remote_state = "ready_empty"
        action = "request_missing_reviewers"
    elif exact_reviewers:
        if durable_state == "lock_only":
            raise PilotExactTaskPrLifecycleRecoveryError(
                "exact reviewer state without a durable ready marker is ambiguous"
            )
        if (
            durable_state == "reviewers_marked"
            and reviewers_state_sha != remote.sha256
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "current reviewer state differs from durable reviewers marker"
            )
        remote_state = "ready_exact_reviewers"
        action = "finalize_existing_state"
    else:
        raise PilotExactTaskPrLifecycleRecoveryError(
            "remote lifecycle reviewer state is partial or unexpected"
        )

    observed_at = now_provider()
    _utc(observed_at, name="observed_at_utc")
    state = PilotExactTaskPrLifecycleRecoveryState(
        transaction_key_sha256=key,
        transaction_lock_sha256=_payload_sha256(lock_payload),
        ready_marker_sha256=ready_hash,
        reviewers_marker_sha256=reviewers_hash,
        pr_lifecycle_authorization_sha256=intent.pr_lifecycle_authorization_sha256,
        post_publication_attestation_sha256=intent.post_publication_attestation_sha256,
        lifecycle_config_sha256=intent.lifecycle_config_sha256,
        reviewer_set_sha256=intent.reviewer_set_sha256,
        execution_nonce_sha256=key,
        development_task_sha256=intent.development_task_sha256,
        candidate_patch_sha256=intent.candidate_patch_sha256,
        pr_intent_sha256=intent.pr_intent_sha256,
        repository=intent.repository,
        repository_id=intent.repository_id,
        base_branch=intent.base_branch,
        head_branch=intent.head_branch,
        exact_task_base_sha=intent.exact_task_base_sha,
        predicted_commit_sha=intent.predicted_commit_sha,
        pull_request_number=intent.pull_request_number,
        pull_request_api_url=intent.pull_request_api_url,
        pull_request_node_id_sha256=node_sha,
        reviewer_usernames=intent.reviewer_usernames,
        reviewer_team_slugs=intent.reviewer_team_slugs,
        durable_transaction_state=durable_state,
        remote_lifecycle_state=remote_state,
        action_required=action,
        manual_intervention_required=action == "manual_intervention",
        remote_state_sha256=remote.sha256,
        observed_at_utc=observed_at,
    )
    return state, intent


def _build_recovery_payload(
    *,
    state: PilotExactTaskPrLifecycleRecoveryState,
    requested_at_utc: str,
    expires_at_utc: str,
    operator_actor_id: str,
    operator_system_id: str,
    operator_key_id: str,
    reviewer_actor_id: str,
    reviewer_system_id: str,
    reviewer_key_id: str,
) -> bytes:
    if type(state) is not PilotExactTaskPrLifecycleRecoveryState:
        raise PilotExactTaskPrLifecycleRecoveryError(
            "exact lifecycle recovery state is required"
        )
    if state.action_required == "manual_intervention":
        raise PilotExactTaskPrLifecycleRecoveryError(
            "manual-intervention lifecycle state cannot mint automatic recovery authority"
        )
    for name, value in (
        ("operator_actor_id", operator_actor_id),
        ("operator_system_id", operator_system_id),
        ("operator_key_id", operator_key_id),
        ("reviewer_actor_id", reviewer_actor_id),
        ("reviewer_system_id", reviewer_system_id),
        ("reviewer_key_id", reviewer_key_id),
    ):
        pattern = _ACTOR if name.endswith("actor_id") else _IDENTIFIER
        if not isinstance(value, str) or pattern.fullmatch(value) is None:
            raise PilotExactTaskPrLifecycleRecoveryError(
                f"{name} is invalid"
            )
    if operator_key_id == reviewer_key_id or operator_actor_id == reviewer_actor_id:
        raise PilotExactTaskPrLifecycleRecoveryError(
            "lifecycle recovery requires independent operator/reviewer authorities"
        )
    requested = _utc(requested_at_utc, name="requested_at_utc")
    expires = _utc(expires_at_utc, name="expires_at_utc")
    if not (
        requested < expires
        and int((expires - requested).total_seconds()) <= _MAX_AUTH_SECONDS
    ):
        raise PilotExactTaskPrLifecycleRecoveryError(
            "lifecycle recovery authorization window is invalid"
        )
    payload = {
        "schema": PILOT_EXACT_TASK_PR_LIFECYCLE_RECOVERY_PAYLOAD_SCHEMA,
        "recovery_policy_sha256": pilot_exact_task_pr_lifecycle_recovery_policy_sha256(),
        "custody_policy_sha256": asymmetric_authority_key_custody_policy_sha256(),
        "transaction_key_sha256": state.transaction_key_sha256,
        "recovery_state_fingerprint_sha256": state.fingerprint_sha256,
        "action": state.action_required,
        "pr_lifecycle_authorization_sha256": state.pr_lifecycle_authorization_sha256,
        "post_publication_attestation_sha256": state.post_publication_attestation_sha256,
        "lifecycle_config_sha256": state.lifecycle_config_sha256,
        "reviewer_set_sha256": state.reviewer_set_sha256,
        "execution_nonce_sha256": state.execution_nonce_sha256,
        "development_task_sha256": state.development_task_sha256,
        "candidate_patch_sha256": state.candidate_patch_sha256,
        "pr_intent_sha256": state.pr_intent_sha256,
        "repository": state.repository,
        "repository_id": state.repository_id,
        "base_branch": state.base_branch,
        "head_branch": state.head_branch,
        "exact_task_base_sha": state.exact_task_base_sha,
        "predicted_commit_sha": state.predicted_commit_sha,
        "pull_request_number": state.pull_request_number,
        "pull_request_api_url": state.pull_request_api_url,
        "pull_request_node_id_sha256": state.pull_request_node_id_sha256,
        "reviewer_usernames": list(state.reviewer_usernames),
        "reviewer_team_slugs": list(state.reviewer_team_slugs),
        "operator_actor_id": operator_actor_id,
        "operator_system_id": operator_system_id,
        "operator_key_id": operator_key_id,
        "reviewer_actor_id": reviewer_actor_id,
        "reviewer_system_id": reviewer_system_id,
        "reviewer_key_id": reviewer_key_id,
        "requested_at_utc": requested_at_utc,
        "expires_at_utc": expires_at_utc,
    }
    return _canonical(payload).encode("utf-8")


def build_pilot_exact_task_pr_lifecycle_recovery_payload(
    state: PilotExactTaskPrLifecycleRecoveryState,
    requested_at_utc: str,
    expires_at_utc: str,
    operator_actor_id: str,
    operator_system_id: str,
    operator_key_id: str,
    reviewer_actor_id: str,
    reviewer_system_id: str,
    reviewer_key_id: str,
) -> bytes:
    """Build exact bytes for two independent lifecycle recovery signers."""
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


def _parse_recovery_payload(payload: bytes) -> dict[str, Any]:
    if (
        not isinstance(payload, bytes)
        or not payload
        or len(payload) > _MAX_ARTIFACT_BYTES
    ):
        raise PilotExactTaskPrLifecycleRecoveryError(
            "lifecycle recovery authorization payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrLifecycleRecoveryError(
            "lifecycle recovery payload is invalid JSON"
        ) from exc
    expected = {
        "schema",
        "recovery_policy_sha256",
        "custody_policy_sha256",
        "transaction_key_sha256",
        "recovery_state_fingerprint_sha256",
        "action",
        "pr_lifecycle_authorization_sha256",
        "post_publication_attestation_sha256",
        "lifecycle_config_sha256",
        "reviewer_set_sha256",
        "execution_nonce_sha256",
        "development_task_sha256",
        "candidate_patch_sha256",
        "pr_intent_sha256",
        "repository",
        "repository_id",
        "base_branch",
        "head_branch",
        "exact_task_base_sha",
        "predicted_commit_sha",
        "pull_request_number",
        "pull_request_api_url",
        "pull_request_node_id_sha256",
        "reviewer_usernames",
        "reviewer_team_slugs",
        "operator_actor_id",
        "operator_system_id",
        "operator_key_id",
        "reviewer_actor_id",
        "reviewer_system_id",
        "reviewer_key_id",
        "requested_at_utc",
        "expires_at_utc",
    }
    if (
        not isinstance(raw, dict)
        or set(raw) != expected
        or _canonical(raw).encode("utf-8") != payload
        or raw.get("schema")
        != PILOT_EXACT_TASK_PR_LIFECYCLE_RECOVERY_PAYLOAD_SCHEMA
        or raw.get("recovery_policy_sha256")
        != pilot_exact_task_pr_lifecycle_recovery_policy_sha256()
        or raw.get("custody_policy_sha256")
        != asymmetric_authority_key_custody_policy_sha256()
        or raw.get("action")
        not in {"request_missing_reviewers", "finalize_existing_state"}
    ):
        raise PilotExactTaskPrLifecycleRecoveryError(
            "lifecycle recovery payload fields/policy mismatch"
        )
    for name in (
        "transaction_key_sha256",
        "recovery_state_fingerprint_sha256",
        "pr_lifecycle_authorization_sha256",
        "post_publication_attestation_sha256",
        "lifecycle_config_sha256",
        "reviewer_set_sha256",
        "execution_nonce_sha256",
        "development_task_sha256",
        "candidate_patch_sha256",
        "pr_intent_sha256",
        "pull_request_node_id_sha256",
    ):
        _hex64(raw[name], name=name)
    for name in ("exact_task_base_sha", "predicted_commit_sha"):
        _hex40(raw[name], name=name)
    requested = _utc(raw["requested_at_utc"], name="requested_at_utc")
    expires = _utc(raw["expires_at_utc"], name="expires_at_utc")
    if not (
        requested < expires
        and int((expires - requested).total_seconds()) <= _MAX_AUTH_SECONDS
    ):
        raise PilotExactTaskPrLifecycleRecoveryError(
            "lifecycle recovery authorization window is invalid"
        )
    if (
        raw["operator_key_id"] == raw["reviewer_key_id"]
        or raw["operator_actor_id"] == raw["reviewer_actor_id"]
    ):
        raise PilotExactTaskPrLifecycleRecoveryError(
            "lifecycle recovery signer independence is invalid"
        )
    return raw


def _parse_keyring(
    payload: bytes,
) -> tuple[Ed25519AuthorityVerifier, str]:
    if (
        not isinstance(payload, bytes)
        or not payload
        or len(payload) > _MAX_KEYRING_BYTES
    ):
        raise PilotExactTaskPrLifecycleRecoveryError(
            "lifecycle recovery keyring is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrLifecycleRecoveryError(
            "lifecycle recovery keyring JSON is invalid"
        ) from exc
    if (
        not isinstance(raw, dict)
        or set(raw) != {"schema", "minimum_keyring_epoch", "keys"}
        or raw.get("schema")
        != PILOT_EXACT_TASK_PR_LIFECYCLE_RECOVERY_KEYRING_SCHEMA
    ):
        raise PilotExactTaskPrLifecycleRecoveryError(
            "lifecycle recovery keyring fields/schema mismatch"
        )
    epoch = raw["minimum_keyring_epoch"]
    keys_raw = raw["keys"]
    if (
        isinstance(epoch, bool)
        or not isinstance(epoch, int)
        or epoch < 1
        or not isinstance(keys_raw, list)
        or not 2 <= len(keys_raw) <= 64
    ):
        raise PilotExactTaskPrLifecycleRecoveryError(
            "lifecycle recovery keyring content is invalid"
        )
    keys: dict[str, TrustedEd25519AuthorityKey] = {}
    for item in keys_raw:
        try:
            key = TrustedEd25519AuthorityKey.from_mapping(item)
        except Exception as exc:
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery trusted key is invalid"
            ) from exc
        if key.key_id in keys:
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery key IDs are duplicated"
            )
        keys[key.key_id] = key
    if list(keys) != sorted(keys):
        raise PilotExactTaskPrLifecycleRecoveryError(
            "lifecycle recovery keyring keys must be sorted"
        )
    canonical = _canonical(
        {
            "schema": PILOT_EXACT_TASK_PR_LIFECYCLE_RECOVERY_KEYRING_SCHEMA,
            "minimum_keyring_epoch": epoch,
            "keys": [keys[key_id].to_dict() for key_id in sorted(keys)],
        }
    ).encode("utf-8")
    if canonical != payload:
        raise PilotExactTaskPrLifecycleRecoveryError(
            "lifecycle recovery keyring is not canonical JSON"
        )
    return (
        Ed25519AuthorityVerifier(keys, minimum_keyring_epoch=epoch),
        hashlib.sha256(payload).hexdigest(),
    )


def _verify_dual_signatures(
    *,
    payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    at_utc: str,
) -> dict[str, Any]:
    claim = _parse_recovery_payload(payload)
    if (
        type(operator_signature) is not DetachedEd25519AuthoritySignature
        or type(reviewer_signature) is not DetachedEd25519AuthoritySignature
    ):
        raise PilotExactTaskPrLifecycleRecoveryError(
            "two detached Ed25519 lifecycle recovery signatures are required"
        )
    payload_sha = hashlib.sha256(payload).hexdigest()
    bindings = (
        (
            operator_signature,
            claim["operator_actor_id"],
            claim["operator_system_id"],
            claim["operator_key_id"],
        ),
        (
            reviewer_signature,
            claim["reviewer_actor_id"],
            claim["reviewer_system_id"],
            claim["reviewer_key_id"],
        ),
    )
    for signature, actor_id, system_id, key_id in bindings:
        if (
            signature.payload_sha256 != payload_sha
            or signature.issuer_actor_id != actor_id
            or signature.issuer_system_id != system_id
            or signature.key_id != key_id
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery signature binding mismatch"
            )
        try:
            verifier.verify(
                payload=payload, signature=signature, at_utc=at_utc
            )
        except AsymmetricAuthorityError as exc:
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery Ed25519 verification failed"
            ) from exc
    now = _utc(at_utc, name="recovery verification time")
    if not (
        _utc(claim["requested_at_utc"], name="requested_at_utc")
        <= now
        < _utc(claim["expires_at_utc"], name="expires_at_utc")
    ):
        raise PilotExactTaskPrLifecycleRecoveryError(
            "lifecycle recovery authorization is not currently valid"
        )
    return claim


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrLifecycleRecoveryReceipt:
    recovery_ledger_root_path_sha256: str
    recovery_key_sha256: str
    recovery_state_fingerprint_sha256: str
    recovery_authorization_payload_sha256: str
    transaction_lock_sha256: str
    ready_marker_sha256: str | None
    reviewers_marker_sha256: str | None
    pr_lifecycle_authorization_sha256: str
    post_publication_attestation_sha256: str
    lifecycle_config_sha256: str
    reviewer_set_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    repository: str
    repository_id: str
    base_branch: str
    head_branch: str
    exact_task_base_sha: str
    predicted_commit_sha: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_node_id_sha256: str
    reviewer_usernames: tuple[str, ...]
    reviewer_team_slugs: tuple[str, ...]
    recovery_action: str
    durable_transaction_state: str
    operator_actor_id: str
    operator_system_id: str
    operator_key_id: str
    reviewer_actor_id: str
    reviewer_system_id: str
    reviewer_key_id: str
    recovered_at_utc: str
    host_recovery_guard_committed: bool = True
    dual_ed25519_recovery_authorized: bool = True
    durable_transaction_state_verified: bool = True
    exact_pr_verified: bool = True
    ready_for_review_verified: bool = True
    reviewer_requests_verified: bool = True
    remote_write_performed: bool = False
    ready_for_review_authorized: bool = False
    reviewer_request_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    product_pilot_started: bool = False
    draft: bool = False
    nonce_reusable: bool = False
    ledger_scope: str = PILOT_EXACT_TASK_PR_LIFECYCLE_RECOVERY_LEDGER_SCOPE
    authority: str = PILOT_EXACT_TASK_PR_LIFECYCLE_RECOVERY_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PR_LIFECYCLE_RECOVERY_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PR_LIFECYCLE_RECOVERY_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PR_LIFECYCLE_RECOVERY_AUTHORITY
            or self.ledger_scope
            != PILOT_EXACT_TASK_PR_LIFECYCLE_RECOVERY_LEDGER_SCOPE
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery receipt identity is unsupported"
            )
        for name in (
            "recovery_ledger_root_path_sha256",
            "recovery_key_sha256",
            "recovery_state_fingerprint_sha256",
            "recovery_authorization_payload_sha256",
            "transaction_lock_sha256",
            "pr_lifecycle_authorization_sha256",
            "post_publication_attestation_sha256",
            "lifecycle_config_sha256",
            "reviewer_set_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "pr_intent_sha256",
            "pull_request_node_id_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("ready_marker_sha256", "reviewers_marker_sha256"):
            value = getattr(self, name)
            if value is not None:
                _hex64(value, name=name)
        for name in ("exact_task_base_sha", "predicted_commit_sha"):
            _hex40(getattr(self, name), name=name)
        if self.recovery_key_sha256 != self.execution_nonce_sha256:
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery key differs from execution nonce"
            )
        if self.recovery_action not in {
            "request_missing_reviewers",
            "finalize_existing_state",
        }:
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery receipt action is invalid"
            )
        if self.durable_transaction_state not in {
            "lock_only",
            "ready_marked",
            "reviewers_marked",
        }:
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery receipt durable state is invalid"
            )
        if (
            isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"{_GITHUB_API_ROOT}/repos/{self.repository}/pulls/{self.pull_request_number}"
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "recovered lifecycle PR identity is invalid"
            )
        if (
            _reviewer_set_sha256(
                self.reviewer_usernames, self.reviewer_team_slugs
            )
            != self.reviewer_set_sha256
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "recovered lifecycle reviewer set hash is inconsistent"
            )
        _utc(self.recovered_at_utc, name="recovered_at_utc")
        required_true = (
            "host_recovery_guard_committed",
            "dual_ed25519_recovery_authorized",
            "durable_transaction_state_verified",
            "exact_pr_verified",
            "ready_for_review_verified",
            "reviewer_requests_verified",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery receipt evidence is incomplete"
            )
        forced_false = (
            "ready_for_review_authorized",
            "reviewer_request_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "product_pilot_started",
            "draft",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery receipt retains forbidden authority"
            )
        if self.remote_write_performed is not (
            self.recovery_action == "request_missing_reviewers"
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery remote-write flag is inconsistent"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            self.canonical_json().encode("utf-8")
        ).hexdigest()

    @property
    def recovery_authenticated(self) -> bool:
        return _get_live_recovery_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        result = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }
        result["reviewer_usernames"] = list(self.reviewer_usernames)
        result["reviewer_team_slugs"] = list(self.reviewer_team_slugs)
        return result

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskPrLifecycleRecoveryReceipt":
        if (
            not isinstance(value, Mapping)
            or set(value) != set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery receipt fields mismatch"
            )
        data = dict(value)
        if not isinstance(data.get("reviewer_usernames"), list) or not isinstance(
            data.get("reviewer_team_slugs"), list
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery reviewer sets are invalid"
            )
        data["reviewer_usernames"] = tuple(data["reviewer_usernames"])
        data["reviewer_team_slugs"] = tuple(data["reviewer_team_slugs"])
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskPrLifecycleRecoveryLedger:
    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path]:
        digest = _hex64(key, name="recovery_key_sha256")
        return self.root / f"{digest}.json", self.root / f".{digest}.lock"

    def acquire(
        self,
        *,
        state: PilotExactTaskPrLifecycleRecoveryState,
        authorization_payload: bytes,
        operator_signature: DetachedEd25519AuthoritySignature,
        reviewer_signature: DetachedEd25519AuthoritySignature,
    ) -> bytes:
        final, lock = self._paths(state.execution_nonce_sha256)
        if (
            final.exists()
            or final.is_symlink()
            or lock.exists()
            or lock.is_symlink()
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery nonce already consumed or needs recovery"
            )
        payload = _canonical(
            {
                "schema": "kaliv-rsi-dc-l16-exact-task-pr-lifecycle-recovery-lock/v1",
                "recovery_key_sha256": state.execution_nonce_sha256,
                "recovery_state_fingerprint_sha256": state.fingerprint_sha256,
                "recovery_authorization_payload_sha256": hashlib.sha256(
                    authorization_payload
                ).hexdigest(),
                "operator_signature_sha256": hashlib.sha256(
                    operator_signature.canonical_json().encode("utf-8")
                ).hexdigest(),
                "reviewer_signature_sha256": hashlib.sha256(
                    reviewer_signature.canonical_json().encode("utf-8")
                ).hexdigest(),
                "action": state.action_required,
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery authorization could not be durably consumed"
            ) from exc
        return payload

    def commit(
        self,
        *,
        receipt: PilotExactTaskPrLifecycleRecoveryReceipt,
        lock_payload: bytes,
    ) -> PilotExactTaskPrLifecycleRecoveryReceipt:
        final, lock = self._paths(receipt.recovery_key_sha256)
        if (
            final.exists()
            or final.is_symlink()
            or _read_bytes(lock) != lock_payload
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery durable state changed before finalization"
            )
        payload = receipt.canonical_json().encode("utf-8")
        try:
            create_once_file(final, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery receipt could not be durably published"
            ) from exc
        parsed = PilotExactTaskPrLifecycleRecoveryReceipt.from_mapping(
            json.loads(payload.decode("utf-8"))
        )
        _mark_recovery_authenticated(
            parsed,
            final_path=final,
            final_payload=payload,
            lock_path=lock,
            lock_payload=lock_payload,
        )
        if parsed.recovery_authenticated is not True:
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery receipt lost live provenance"
            )
        return parsed


def _live_registry():
    records: dict[
        int,
        tuple[int, str, weakref.ReferenceType[Any], Path, bytes, Path, bytes],
    ] = {}

    def mark(
        receipt: Any,
        *,
        final_path: Path,
        final_payload: bytes,
        lock_path: Path,
        lock_payload: bytes,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            final_path,
            final_payload,
            lock_path,
            lock_payload,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        (
            pid,
            digest,
            ref,
            final_path,
            final_payload,
            lock_path,
            lock_payload,
        ) = entry
        if (
            pid != os.getpid()
            or ref() is not receipt
            or receipt.sha256 != digest
            or _read_bytes(final_path) != final_payload
            or _read_bytes(lock_path) != lock_payload
        ):
            return None
        return MappingProxyType({"receipt_sha256": digest})

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_recovery_authenticated, _get_live_recovery_inputs = _live_registry()


def _recover_verified_pilot_exact_task_pr_lifecycle(
    *,
    authorization_payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    transaction_ledger_root: Path,
    lifecycle_authorization_ledger_root: Path,
    publication_authorization_ledger_root: Path,
    local_transaction_ledger_root: Path,
    recovery_ledger: _PilotExactTaskPrLifecycleRecoveryLedger,
    read_transport: Any,
    write_transport: Any | None,
    now_provider: Callable[[], str],
) -> PilotExactTaskPrLifecycleRecoveryReceipt:
    verified_at = now_provider()
    claim = _verify_dual_signatures(
        payload=authorization_payload,
        operator_signature=operator_signature,
        reviewer_signature=reviewer_signature,
        verifier=verifier,
        at_utc=verified_at,
    )
    state, intent = _observe_verified_recovery_state(
        execution_nonce_sha256=claim["transaction_key_sha256"],
        transaction_ledger_root=transaction_ledger_root,
        lifecycle_authorization_ledger_root=lifecycle_authorization_ledger_root,
        publication_authorization_ledger_root=publication_authorization_ledger_root,
        local_transaction_ledger_root=local_transaction_ledger_root,
        transport=read_transport,
        now_provider=now_provider,
    )
    bindings = {
        "recovery_state_fingerprint_sha256": state.fingerprint_sha256,
        "action": state.action_required,
        "pr_lifecycle_authorization_sha256": state.pr_lifecycle_authorization_sha256,
        "post_publication_attestation_sha256": state.post_publication_attestation_sha256,
        "lifecycle_config_sha256": state.lifecycle_config_sha256,
        "reviewer_set_sha256": state.reviewer_set_sha256,
        "execution_nonce_sha256": state.execution_nonce_sha256,
        "development_task_sha256": state.development_task_sha256,
        "candidate_patch_sha256": state.candidate_patch_sha256,
        "pr_intent_sha256": state.pr_intent_sha256,
        "repository": state.repository,
        "repository_id": state.repository_id,
        "base_branch": state.base_branch,
        "head_branch": state.head_branch,
        "exact_task_base_sha": state.exact_task_base_sha,
        "predicted_commit_sha": state.predicted_commit_sha,
        "pull_request_number": state.pull_request_number,
        "pull_request_api_url": state.pull_request_api_url,
        "pull_request_node_id_sha256": state.pull_request_node_id_sha256,
        "reviewer_usernames": list(state.reviewer_usernames),
        "reviewer_team_slugs": list(state.reviewer_team_slugs),
    }
    if any(claim.get(name) != value for name, value in bindings.items()):
        raise PilotExactTaskPrLifecycleRecoveryError(
            "signed lifecycle recovery state changed before execution"
        )
    lock_payload = recovery_ledger.acquire(
        state=state,
        authorization_payload=authorization_payload,
        operator_signature=operator_signature,
        reviewer_signature=reviewer_signature,
    )
    current, current_intent = _observe_verified_recovery_state(
        execution_nonce_sha256=state.execution_nonce_sha256,
        transaction_ledger_root=transaction_ledger_root,
        lifecycle_authorization_ledger_root=lifecycle_authorization_ledger_root,
        publication_authorization_ledger_root=publication_authorization_ledger_root,
        local_transaction_ledger_root=local_transaction_ledger_root,
        transport=read_transport,
        now_provider=now_provider,
    )
    if (
        current.fingerprint_sha256 != state.fingerprint_sha256
        or current_intent != intent
    ):
        raise PilotExactTaskPrLifecycleRecoveryError(
            "lifecycle recovery state changed after durable authorization consumption"
        )

    remote_write_performed = False
    if state.action_required == "request_missing_reviewers":
        if write_transport is None or not callable(
            getattr(write_transport, "request_reviewers", None)
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery transport cannot request exact reviewers"
            )
        write_transport.request_reviewers(intent)
        after_remote = read_transport.observe(intent)
        if type(after_remote) is not _LifecycleRemoteState:
            raise PilotExactTaskPrLifecycleRecoveryError(
                "recovered reviewer state observation is invalid"
            )
        _validate_remote_state(after_remote, intent)
        if (
            after_remote.draft is not False
            or after_remote.reviewer_usernames != intent.reviewer_usernames
            or after_remote.reviewer_team_slugs != intent.reviewer_team_slugs
            or hashlib.sha256(after_remote.pull_request_node_id.encode("utf-8")).hexdigest()
            != state.pull_request_node_id_sha256
        ):
            raise PilotExactTaskPrLifecycleRecoveryError(
                "recovered reviewer request could not be re-observed exactly"
            )
        remote_write_performed = True
    else:
        if state.remote_lifecycle_state != "ready_exact_reviewers":
            raise PilotExactTaskPrLifecycleRecoveryError(
                "write-free lifecycle finalization state is not exact"
            )

    recovered_at = now_provider()
    if _utc(recovered_at, name="recovered_at_utc") < _utc(
        verified_at, name="verified_at_utc"
    ):
        raise PilotExactTaskPrLifecycleRecoveryError(
            "system clock moved backwards during lifecycle recovery"
        )
    receipt = PilotExactTaskPrLifecycleRecoveryReceipt(
        recovery_ledger_root_path_sha256=recovery_ledger.root_sha256,
        recovery_key_sha256=state.execution_nonce_sha256,
        recovery_state_fingerprint_sha256=state.fingerprint_sha256,
        recovery_authorization_payload_sha256=hashlib.sha256(
            authorization_payload
        ).hexdigest(),
        transaction_lock_sha256=state.transaction_lock_sha256,
        ready_marker_sha256=state.ready_marker_sha256,
        reviewers_marker_sha256=state.reviewers_marker_sha256,
        pr_lifecycle_authorization_sha256=state.pr_lifecycle_authorization_sha256,
        post_publication_attestation_sha256=state.post_publication_attestation_sha256,
        lifecycle_config_sha256=state.lifecycle_config_sha256,
        reviewer_set_sha256=state.reviewer_set_sha256,
        execution_nonce_sha256=state.execution_nonce_sha256,
        development_task_sha256=state.development_task_sha256,
        candidate_patch_sha256=state.candidate_patch_sha256,
        pr_intent_sha256=state.pr_intent_sha256,
        repository=state.repository,
        repository_id=state.repository_id,
        base_branch=state.base_branch,
        head_branch=state.head_branch,
        exact_task_base_sha=state.exact_task_base_sha,
        predicted_commit_sha=state.predicted_commit_sha,
        pull_request_number=state.pull_request_number,
        pull_request_api_url=state.pull_request_api_url,
        pull_request_node_id_sha256=state.pull_request_node_id_sha256,
        reviewer_usernames=state.reviewer_usernames,
        reviewer_team_slugs=state.reviewer_team_slugs,
        recovery_action=state.action_required,
        durable_transaction_state=state.durable_transaction_state,
        operator_actor_id=claim["operator_actor_id"],
        operator_system_id=claim["operator_system_id"],
        operator_key_id=claim["operator_key_id"],
        reviewer_actor_id=claim["reviewer_actor_id"],
        reviewer_system_id=claim["reviewer_system_id"],
        reviewer_key_id=claim["reviewer_key_id"],
        recovered_at_utc=recovered_at,
        remote_write_performed=remote_write_performed,
    )
    return recovery_ledger.commit(
        receipt=receipt, lock_payload=lock_payload
    )


def _canonical_roots() -> tuple[Path, Path, Path, Path, Path]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            values = (
                _POSIX_LEDGER,
                lifecycle_tx_boundary._POSIX_LEDGER,
                lifecycle_auth_boundary._POSIX_LEDGER,
                publication_auth_boundary._POSIX_LEDGER,
                local_tx_boundary._POSIX_LEDGER,
            )
        elif os.name == "nt":
            values = (
                _WINDOWS_LEDGER,
                lifecycle_tx_boundary._WINDOWS_LEDGER,
                lifecycle_auth_boundary._WINDOWS_LEDGER,
                publication_auth_boundary._WINDOWS_LEDGER,
                local_tx_boundary._WINDOWS_LEDGER,
            )
        else:
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery platform is unsupported"
            )
        return tuple(
            _require_host_controlled_ledger_root(Path(value))
            for value in values
        )  # type: ignore[return-value]
    except PhysicalHostStateError as exc:
        raise PilotExactTaskPrLifecycleRecoveryError(
            "lifecycle recovery ledgers are not host-admin controlled"
        ) from exc


def _canonical_keyring() -> tuple[Ed25519AuthorityVerifier, str]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_KEYRING
        elif os.name == "nt":
            path = _WINDOWS_KEYRING
        else:
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery keyring platform is unsupported"
            )
        try:
            payload = _read_keyring_bytes(path, require_host_control=True)
        except PhysicalRequestAuthorityKeyringError as exc:
            raise PilotExactTaskPrLifecycleRecoveryError(
                "lifecycle recovery keyring is not host-admin controlled"
            ) from exc
        return _parse_keyring(payload)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskPrLifecycleRecoveryError(
            "lifecycle recovery keyring requires elevated host operator"
        ) from exc


def observe_pilot_exact_task_pr_lifecycle_recovery(
    execution_nonce_sha256: str,
) -> PilotExactTaskPrLifecycleRecoveryState:
    """Read one interrupted ADR-DC-054 lifecycle transaction without mutation."""
    (
        recovery_root,
        tx_root,
        lifecycle_auth_root,
        publication_auth_root,
        local_root,
    ) = _canonical_roots()
    del recovery_root
    state, _intent = _observe_verified_recovery_state(
        execution_nonce_sha256=execution_nonce_sha256,
        transaction_ledger_root=tx_root,
        lifecycle_authorization_ledger_root=lifecycle_auth_root,
        publication_authorization_ledger_root=publication_auth_root,
        local_transaction_ledger_root=local_root,
        transport=_GitHubLifecycleRecoveryTransport(),
        now_provider=_now_utc_seconds,
    )
    return state


def recover_pilot_exact_task_pr_lifecycle(
    authorization_payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
) -> PilotExactTaskPrLifecycleRecoveryReceipt:
    """Perform only dual-authorized reviewer recovery or write-free finalization."""
    try:
        (
            recovery_root,
            tx_root,
            lifecycle_auth_root,
            publication_auth_root,
            local_root,
        ) = _canonical_roots()
        verifier, _keyring_sha256 = _canonical_keyring()
        claim = _parse_recovery_payload(authorization_payload)
        read_transport = _GitHubLifecycleRecoveryTransport()
        write_transport = None
        if claim["action"] == "request_missing_reviewers":
            credential, digest, credential_path = (
                publication_tx_boundary._canonical_credential()
            )
            tx_ledger = lifecycle_tx_boundary._PilotExactTaskPrLifecycleTransactionLedger(
                tx_root
            )
            _final, lock, _ready, _reviewers = tx_ledger._paths(
                claim["transaction_key_sha256"]
            )
            lock_raw, _lock_payload = _read_canonical_object(
                lock, name="ADR-DC-054 transaction lock"
            )
            expected_path_sha = _path_sha256(credential_path)
            if (
                lock_raw.get("publisher_credential_config_sha256") != digest
                or lock_raw.get("publisher_credential_path_sha256")
                != expected_path_sha
            ):
                raise PilotExactTaskPrLifecycleRecoveryError(
                    "current publisher credential identity differs from consumed ADR-DC-054 credential"
                )
            write_transport = _GitHubLifecycleRecoveryTransport(
                credential,
                credential_config_sha256=digest,
                credential_path=credential_path,
            )
        return _recover_verified_pilot_exact_task_pr_lifecycle(
            authorization_payload=authorization_payload,
            operator_signature=operator_signature,
            reviewer_signature=reviewer_signature,
            verifier=verifier,
            transaction_ledger_root=tx_root,
            lifecycle_authorization_ledger_root=lifecycle_auth_root,
            publication_authorization_ledger_root=publication_auth_root,
            local_transaction_ledger_root=local_root,
            recovery_ledger=_PilotExactTaskPrLifecycleRecoveryLedger(
                recovery_root
            ),
            read_transport=read_transport,
            write_transport=write_transport,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskPrLifecycleRecoveryError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskPrLifecycleRecoveryError(
            "host-controlled PR lifecycle recovery failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_PR_LIFECYCLE_RECOVERY_SCHEMA",
    "PILOT_EXACT_TASK_PR_LIFECYCLE_RECOVERY_AUTHORITY",
    "PILOT_EXACT_TASK_PR_LIFECYCLE_RECOVERY_KEYRING_SCHEMA",
    "PilotExactTaskPrLifecycleRecoveryError",
    "PilotExactTaskPrLifecycleRecoveryState",
    "PilotExactTaskPrLifecycleRecoveryReceipt",
    "pilot_exact_task_pr_lifecycle_recovery_policy_sha256",
    "build_pilot_exact_task_pr_lifecycle_recovery_payload",
    "observe_pilot_exact_task_pr_lifecycle_recovery",
    "recover_pilot_exact_task_pr_lifecycle",
]
