"""ADR-DC-051 authenticated recovery for interrupted exact remote publication.

Recovery is intentionally narrower than ADR-DC-050.  It never replays a push.
It may only adopt an already-observed exact remote head, then either create the
missing deterministic draft pull request or finalize an already-existing exact
draft pull request.  Both actions require two independent detached Ed25519
signatures over one exact durable/remote recovery-state fingerprint.
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
from . import improvement_pilot_exact_task_local_commit_transaction as local_tx_boundary
from . import improvement_pilot_exact_task_remote_publication_authorization as auth_boundary
from . import improvement_pilot_exact_task_remote_publication_plan as plan_boundary
from . import improvement_pilot_exact_task_remote_publication_transaction as tx_boundary
from .improvement_pilot_exact_task_local_commit_transaction import (
    PilotExactTaskLocalCommitTransactionReceipt,
)
from .improvement_pilot_exact_task_remote_publication_authorization import (
    PilotExactTaskRemotePublicationAuthorizationReceipt,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_REMOTE_PUBLICATION_RECOVERY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-remote-publication-recovery-receipt/v1"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_RECOVERY_AUTHORITY = (
    "dual-reviewed-dc-l16-exact-remote-publication-recovery-only"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_RECOVERY_LEDGER_SCOPE = "canonical-host-local-v1"
PILOT_EXACT_TASK_REMOTE_PUBLICATION_RECOVERY_KEYRING_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-remote-publication-recovery-keyring/v1"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_RECOVERY_PAYLOAD_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-remote-publication-recovery-authorization-payload/v1"
)
_RECOVERY_POLICY_DOMAIN = b"kaliv-rsi-dc-l16-exact-task-remote-publication-recovery-policy/v1\0"
_MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
_MAX_KEYRING_BYTES = 1024 * 1024
_MAX_API_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_AUTH_SECONDS = 10 * 60
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_GITHUB_API_ROOT = "https://api.github.com"
_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-remote-publication-recovery-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-remote-publication-recovery-ledger-v1"
)
_POSIX_KEYRING = Path(
    "/etc/modelrig/devcontrol/"
    "rsi-pilot-exact-task-remote-publication-recovery-keyring-v1.json"
)
_WINDOWS_KEYRING = (
    Path(r"C:\ProgramData\ModelRig\DevControl\config")
    / "rsi-pilot-exact-task-remote-publication-recovery-keyring-v1.json"
)

PILOT_EXACT_TASK_REMOTE_PUBLICATION_RECOVERY_POLICY = (
    "Recover only one previously consumed ADR-DC-050 execution nonce.",
    "Reconstruct deterministic draft-PR intent from durable ADR-DC-049 and ADR-DC-044 evidence and require the original pr_intent_sha256.",
    "Never replay a missing push; an absent exact remote head requires manual intervention.",
    "Require the exact remote base and exact remote candidate head before recovery can mutate anything.",
    "Require two independent detached Ed25519 signatures over the exact recovery-state fingerprint and action.",
    "Durably consume recovery authorization before any draft-PR creation.",
    "Permit only missing exact draft-PR creation or finalization of an already exact draft PR.",
    "Never make the execution nonce reusable and never grant merge, release, deploy or production activation authority.",
)


class PilotExactTaskRemotePublicationRecoveryError(ValueError):
    """Interrupted publication state is ambiguous, unauthenticated or unsafe."""


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
        raise PilotExactTaskRemotePublicationRecoveryError(
            "recovery evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskRemotePublicationRecoveryError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskRemotePublicationRecoveryError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskRemotePublicationRecoveryError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskRemotePublicationRecoveryError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def pilot_exact_task_remote_publication_recovery_policy_sha256() -> str:
    payload = json.dumps(
        list(PILOT_EXACT_TASK_REMOTE_PUBLICATION_RECOVERY_POLICY),
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
        raise PilotExactTaskRemotePublicationRecoveryError(f"{name} is unavailable")
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskRemotePublicationRecoveryError(f"{name} is invalid JSON") from exc
    if not isinstance(raw, dict) or _canonical(raw).encode("utf-8") != payload:
        raise PilotExactTaskRemotePublicationRecoveryError(f"{name} is not canonical JSON")
    return raw, payload


@dataclass(frozen=True, slots=True)
class _RecoveryIntent:
    remote_publication_authorization_sha256: str
    remote_publication_plan_sha256: str
    pr_intent_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    integration_readiness_sha256: str
    task_id: str
    repository: str
    repository_id: str
    base_branch: str
    head_branch: str
    base_sha: str
    predicted_commit_sha: str
    root_tree_sha: str
    pr_title: str
    pr_body: str

    def __post_init__(self) -> None:
        for name in (
            "remote_publication_authorization_sha256",
            "remote_publication_plan_sha256",
            "pr_intent_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "integration_readiness_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("base_sha", "predicted_commit_sha", "root_tree_sha"):
            _hex40(getattr(self, name), name=name)
        if self.base_branch != "main":
            raise PilotExactTaskRemotePublicationRecoveryError("recovery base branch is unsupported")
        expected_title = plan_boundary._expected_pr_title(
            task_id=self.task_id,
            predicted_commit_sha=self.predicted_commit_sha,
        )
        expected_body = plan_boundary._expected_pr_body(
            task_id=self.task_id,
            repository=self.repository,
            repository_id=self.repository_id,
            base_branch=self.base_branch,
            head_branch=self.head_branch,
            base_sha=self.base_sha,
            predicted_commit_sha=self.predicted_commit_sha,
            root_tree_sha=self.root_tree_sha,
            candidate_patch_sha256=self.candidate_patch_sha256,
            integration_readiness_sha256=self.integration_readiness_sha256,
        )
        if self.pr_title != expected_title or self.pr_body != expected_body:
            raise PilotExactTaskRemotePublicationRecoveryError(
                "reconstructed draft-PR text is not deterministic"
            )
        intent = plan_boundary._pr_intent_sha256(
            repository=self.repository,
            repository_id=self.repository_id,
            provider="github",
            host="github.com",
            remote_name="origin",
            base_branch=self.base_branch,
            head_branch=self.head_branch,
            base_sha=self.base_sha,
            predicted_commit_sha=self.predicted_commit_sha,
            pr_title=self.pr_title,
            pr_body=self.pr_body,
        )
        if intent != self.pr_intent_sha256:
            raise PilotExactTaskRemotePublicationRecoveryError(
                "reconstructed draft-PR intent hash differs from ADR-DC-049"
            )


@dataclass(frozen=True, slots=True)
class PilotExactTaskRemotePublicationRecoveryState:
    transaction_key_sha256: str
    transaction_lock_sha256: str
    pushed_marker_sha256: str | None
    draft_pr_marker_sha256: str | None
    remote_publication_authorization_sha256: str
    remote_publication_plan_sha256: str
    pr_intent_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    integration_readiness_sha256: str
    task_id: str
    repository: str
    repository_id: str
    base_branch: str
    head_branch: str
    exact_task_base_sha: str
    predicted_commit_sha: str
    root_tree_sha: str
    durable_transaction_state: str
    remote_head_state: str
    pull_request_number: int | None
    pull_request_api_url: str | None
    action_required: str
    manual_intervention_required: bool
    observed_at_utc: str

    def __post_init__(self) -> None:
        for name in (
            "transaction_key_sha256",
            "transaction_lock_sha256",
            "remote_publication_authorization_sha256",
            "remote_publication_plan_sha256",
            "pr_intent_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "integration_readiness_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("pushed_marker_sha256", "draft_pr_marker_sha256"):
            value = getattr(self, name)
            if value is not None:
                _hex64(value, name=name)
        for name in ("exact_task_base_sha", "predicted_commit_sha", "root_tree_sha"):
            _hex40(getattr(self, name), name=name)
        if self.transaction_key_sha256 != self.execution_nonce_sha256:
            raise PilotExactTaskRemotePublicationRecoveryError("recovery key differs from execution nonce")
        if self.durable_transaction_state not in {"lock_only", "pushed_marked", "pr_marked"}:
            raise PilotExactTaskRemotePublicationRecoveryError("durable recovery state is invalid")
        if self.remote_head_state not in {"absent", "exact"}:
            raise PilotExactTaskRemotePublicationRecoveryError("remote head state is invalid")
        if self.action_required not in {"manual_intervention", "create_missing_pr", "finalize_existing_pr"}:
            raise PilotExactTaskRemotePublicationRecoveryError("recovery action is invalid")
        if self.manual_intervention_required is not (self.action_required == "manual_intervention"):
            raise PilotExactTaskRemotePublicationRecoveryError("manual-intervention flag is inconsistent")
        if self.action_required != "manual_intervention" and self.remote_head_state != "exact":
            raise PilotExactTaskRemotePublicationRecoveryError("automatic recovery requires exact remote head")
        if self.action_required == "finalize_existing_pr":
            if not isinstance(self.pull_request_number, int) or self.pull_request_number < 1 or not self.pull_request_api_url:
                raise PilotExactTaskRemotePublicationRecoveryError("existing exact PR identity is missing")
        elif self.pull_request_number is not None or self.pull_request_api_url is not None:
            raise PilotExactTaskRemotePublicationRecoveryError("unexpected pull-request identity in recovery state")
        _utc(self.observed_at_utc, name="observed_at_utc")

    def fingerprint_mapping(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
            if name != "observed_at_utc"
        }

    @property
    def fingerprint_sha256(self) -> str:
        return hashlib.sha256(_canonical(self.fingerprint_mapping()).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class _GitHubRecoveryTransport:
    """Read exact GitHub recovery state and optionally create one draft PR."""

    def __init__(self, credential: Any | None = None) -> None:
        self.credential = credential
        self._opener = urllib.request.build_opener(_NoRedirect())

    def _request(self, *, path: str, method: str, body: Mapping[str, Any] | None = None, allow_404: bool = False) -> tuple[int, Any | None]:
        if not path.startswith("/repos/") or ".." in path or method not in {"GET", "POST"}:
            raise PilotExactTaskRemotePublicationRecoveryError("recovery GitHub request is outside exact scope")
        payload = None
        if method == "POST":
            if body is None or self.credential is None:
                raise PilotExactTaskRemotePublicationRecoveryError("recovery PR creation lacks exact credential/body")
            payload = _canonical(dict(body)).encode("utf-8")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ModelRig-DevControl-Recovery/1",
        }
        if self.credential is not None:
            headers["Authorization"] = f"Bearer {self.credential.token}"
        if payload is not None:
            headers["Content-Type"] = "application/json"
        url = _GITHUB_API_ROOT + path
        request = urllib.request.Request(url, data=payload, method=method, headers=headers)
        try:
            response = self._opener.open(request, timeout=30.0)
        except urllib.error.HTTPError as exc:
            if allow_404 and exc.code == 404:
                return 404, None
            raise PilotExactTaskRemotePublicationRecoveryError(
                f"recovery GitHub request failed with HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PilotExactTaskRemotePublicationRecoveryError("recovery GitHub request failed") from exc
        with response:
            expected = 201 if method == "POST" else 200
            if response.status != expected or response.geturl() != url:
                raise PilotExactTaskRemotePublicationRecoveryError("recovery GitHub response identity/status is unexpected")
            raw = response.read(_MAX_API_RESPONSE_BYTES + 1)
        if not raw or len(raw) > _MAX_API_RESPONSE_BYTES:
            raise PilotExactTaskRemotePublicationRecoveryError("recovery GitHub response size is invalid")
        try:
            return expected, json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PilotExactTaskRemotePublicationRecoveryError("recovery GitHub response is invalid JSON") from exc

    @staticmethod
    def _root(intent: _RecoveryIntent) -> str:
        owner, repo = intent.repository.split("/", 1)
        return f"/repos/{urllib.parse.quote(owner, safe='')}/{urllib.parse.quote(repo, safe='')}"

    def _ref(self, intent: _RecoveryIntent, branch: str, *, allow_absent: bool) -> str | None:
        status, value = self._request(
            path=f"{self._root(intent)}/git/ref/heads/{urllib.parse.quote(branch, safe='')}",
            method="GET",
            allow_404=allow_absent,
        )
        if status == 404:
            return None
        if not isinstance(value, Mapping) or not isinstance(value.get("object"), Mapping):
            raise PilotExactTaskRemotePublicationRecoveryError("recovery ref response is invalid")
        obj = value["object"]
        if obj.get("type") != "commit":
            raise PilotExactTaskRemotePublicationRecoveryError("recovery ref is not a commit")
        return _hex40(obj.get("sha"), name="recovery ref SHA")

    def _validate_pr(self, intent: _RecoveryIntent, value: Any) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise PilotExactTaskRemotePublicationRecoveryError("recovery PR response is invalid")
        number = value.get("number")
        api_url = value.get("url")
        base = value.get("base")
        head = value.get("head")
        if (
            isinstance(number, bool)
            or not isinstance(number, int)
            or number < 1
            or api_url != f"{_GITHUB_API_ROOT}/repos/{intent.repository}/pulls/{number}"
            or value.get("state") != "open"
            or value.get("draft") is not True
            or value.get("maintainer_can_modify") is not False
            or value.get("title") != intent.pr_title
            or value.get("body") != intent.pr_body
            or not isinstance(base, Mapping)
            or not isinstance(head, Mapping)
            or base.get("ref") != intent.base_branch
            or base.get("sha") != intent.base_sha
            or head.get("ref") != intent.head_branch
            or head.get("sha") != intent.predicted_commit_sha
        ):
            raise PilotExactTaskRemotePublicationRecoveryError("GitHub PR does not equal exact recovery intent")
        return MappingProxyType({"number": number, "api_url": api_url})

    def observe(self, intent: _RecoveryIntent) -> Mapping[str, Any]:
        base = self._ref(intent, intent.base_branch, allow_absent=False)
        head = self._ref(intent, intent.head_branch, allow_absent=True)
        owner, _repo = intent.repository.split("/", 1)
        query = urllib.parse.urlencode(
            {"state": "all", "head": f"{owner}:{intent.head_branch}", "base": intent.base_branch, "per_page": "100"},
            safe=":/",
        )
        _status, pulls = self._request(path=f"{self._root(intent)}/pulls?{query}", method="GET")
        if not isinstance(pulls, list) or len(pulls) > 1:
            raise PilotExactTaskRemotePublicationRecoveryError("recovery PR state is ambiguous")
        pr = None if not pulls else self._validate_pr(intent, pulls[0])
        return MappingProxyType({"base_sha": base, "head_sha": head, "pull_request": pr})

    def create_draft_pr(self, intent: _RecoveryIntent) -> Mapping[str, Any]:
        if self.credential is None:
            raise PilotExactTaskRemotePublicationRecoveryError("recovery transport has no publisher credential")
        if self.credential.repository != intent.repository or self.credential.repository_id != intent.repository_id:
            raise PilotExactTaskRemotePublicationRecoveryError("publisher credential targets another repository")
        _status, value = self._request(
            path=f"{self._root(intent)}/pulls",
            method="POST",
            body={
                "title": intent.pr_title,
                "body": intent.pr_body,
                "head": intent.head_branch,
                "base": intent.base_branch,
                "draft": True,
                "maintainer_can_modify": False,
            },
        )
        return self._validate_pr(intent, value)


def _load_receipts(
    *,
    key: str,
    authorization_ledger_root: Path,
    local_transaction_ledger_root: Path,
) -> tuple[PilotExactTaskRemotePublicationAuthorizationReceipt, PilotExactTaskLocalCommitTransactionReceipt]:
    auth_root = _safe_ledger_root(authorization_ledger_root)
    local_root = _safe_ledger_root(local_transaction_ledger_root)
    auth_raw, _ = _read_canonical_object(auth_root / f"{key}.json", name="ADR-DC-049 durable authorization")
    local_raw, _ = _read_canonical_object(local_root / f"{key}.json", name="ADR-DC-044 durable transaction")
    try:
        auth = PilotExactTaskRemotePublicationAuthorizationReceipt.from_mapping(auth_raw)
        local = PilotExactTaskLocalCommitTransactionReceipt.from_mapping(local_raw)
    except Exception as exc:
        raise PilotExactTaskRemotePublicationRecoveryError("durable upstream receipt validation failed") from exc
    if (
        auth.execution_nonce_sha256 != key
        or getattr(local, "execution_nonce_sha256", None) != key
        or auth.predicted_commit_sha != getattr(local, "predicted_commit_sha", None)
        or auth.exact_task_base_sha != getattr(local, "base_sha", None)
        or auth.development_task_sha256 != getattr(local, "development_task_sha256", None)
        or auth.candidate_patch_sha256 != getattr(local, "candidate_patch_sha256", None)
        or getattr(local, "local_commit_created", None) is not True
    ):
        raise PilotExactTaskRemotePublicationRecoveryError("durable upstream receipts are not one exact candidate")
    return auth, local


def _intent(auth: PilotExactTaskRemotePublicationAuthorizationReceipt, local: PilotExactTaskLocalCommitTransactionReceipt) -> _RecoveryIntent:
    root_tree = _hex40(getattr(local, "root_tree_sha", None), name="durable root tree SHA")
    title = plan_boundary._expected_pr_title(task_id=auth.task_id, predicted_commit_sha=auth.predicted_commit_sha)
    body = plan_boundary._expected_pr_body(
        task_id=auth.task_id,
        repository=auth.repository,
        repository_id=auth.repository_id,
        base_branch=auth.base_branch,
        head_branch=auth.head_branch,
        base_sha=auth.exact_task_base_sha,
        predicted_commit_sha=auth.predicted_commit_sha,
        root_tree_sha=root_tree,
        candidate_patch_sha256=auth.candidate_patch_sha256,
        integration_readiness_sha256=auth.integration_readiness_sha256,
    )
    return _RecoveryIntent(
        remote_publication_authorization_sha256=auth.sha256,
        remote_publication_plan_sha256=auth.remote_publication_plan_sha256,
        pr_intent_sha256=auth.pr_intent_sha256,
        execution_nonce_sha256=auth.execution_nonce_sha256,
        development_task_sha256=auth.development_task_sha256,
        candidate_patch_sha256=auth.candidate_patch_sha256,
        integration_readiness_sha256=auth.integration_readiness_sha256,
        task_id=auth.task_id,
        repository=auth.repository,
        repository_id=auth.repository_id,
        base_branch=auth.base_branch,
        head_branch=auth.head_branch,
        base_sha=auth.exact_task_base_sha,
        predicted_commit_sha=auth.predicted_commit_sha,
        root_tree_sha=root_tree,
        pr_title=title,
        pr_body=body,
    )


def _marker_hash(path: Path) -> str | None:
    payload = _read_bytes(path)
    return None if payload is None else hashlib.sha256(payload).hexdigest()


def _validate_lock(raw: Mapping[str, Any], intent: _RecoveryIntent, transaction_root_sha256: str) -> None:
    expected = {
        "schema",
        "ledger_scope",
        "ledger_root_path_sha256",
        "transaction_key_sha256",
        "remote_publication_authorization_sha256",
        "remote_state_observation_sha256",
        "remote_publication_plan_sha256",
        "pr_intent_sha256",
        "repository",
        "repository_id",
        "base_branch",
        "head_branch",
        "exact_task_base_sha",
        "predicted_commit_sha",
    }
    if set(raw) != expected or raw.get("schema") != "kaliv-rsi-dc-l16-exact-task-remote-publication-transaction-lock/v1":
        raise PilotExactTaskRemotePublicationRecoveryError("ADR-DC-050 lock fields/schema mismatch")
    checks = {
        "ledger_root_path_sha256": transaction_root_sha256,
        "transaction_key_sha256": intent.execution_nonce_sha256,
        "remote_publication_authorization_sha256": intent.remote_publication_authorization_sha256,
        "remote_publication_plan_sha256": intent.remote_publication_plan_sha256,
        "pr_intent_sha256": intent.pr_intent_sha256,
        "repository": intent.repository,
        "repository_id": intent.repository_id,
        "base_branch": intent.base_branch,
        "head_branch": intent.head_branch,
        "exact_task_base_sha": intent.base_sha,
        "predicted_commit_sha": intent.predicted_commit_sha,
    }
    if any(raw.get(name) != value for name, value in checks.items()):
        raise PilotExactTaskRemotePublicationRecoveryError("ADR-DC-050 lock is not bound to exact durable intent")


def _validate_pushed(raw: Mapping[str, Any], intent: _RecoveryIntent) -> None:
    expected = {
        "schema",
        "transaction_key_sha256",
        "remote_publication_authorization_sha256",
        "remote_publication_plan_sha256",
        "predicted_commit_sha",
        "head_branch",
        "push_result_sha256",
        "pushed_at_utc",
    }
    if set(raw) != expected or raw.get("schema") != "kaliv-rsi-dc-l16-exact-task-remote-publication-pushed-marker/v1":
        raise PilotExactTaskRemotePublicationRecoveryError("ADR-DC-050 pushed marker fields/schema mismatch")
    if (
        raw.get("transaction_key_sha256") != intent.execution_nonce_sha256
        or raw.get("remote_publication_authorization_sha256") != intent.remote_publication_authorization_sha256
        or raw.get("remote_publication_plan_sha256") != intent.remote_publication_plan_sha256
        or raw.get("predicted_commit_sha") != intent.predicted_commit_sha
        or raw.get("head_branch") != intent.head_branch
    ):
        raise PilotExactTaskRemotePublicationRecoveryError("ADR-DC-050 pushed marker binding mismatch")
    _hex64(raw.get("push_result_sha256"), name="durable push result SHA")
    _utc(raw.get("pushed_at_utc"), name="durable pushed_at_utc")


def _validate_pr_marker(raw: Mapping[str, Any], intent: _RecoveryIntent) -> tuple[int, str]:
    expected = {
        "schema",
        "transaction_key_sha256",
        "remote_publication_authorization_sha256",
        "remote_publication_plan_sha256",
        "pull_request_number",
        "pull_request_api_url",
        "draft",
        "maintainer_can_modify",
        "created_at_utc",
    }
    if set(raw) != expected or raw.get("schema") != "kaliv-rsi-dc-l16-exact-task-remote-publication-draft-pr-marker/v1":
        raise PilotExactTaskRemotePublicationRecoveryError("ADR-DC-050 PR marker fields/schema mismatch")
    number = raw.get("pull_request_number")
    api_url = raw.get("pull_request_api_url")
    if (
        raw.get("transaction_key_sha256") != intent.execution_nonce_sha256
        or raw.get("remote_publication_authorization_sha256") != intent.remote_publication_authorization_sha256
        or raw.get("remote_publication_plan_sha256") != intent.remote_publication_plan_sha256
        or isinstance(number, bool)
        or not isinstance(number, int)
        or number < 1
        or api_url != f"{_GITHUB_API_ROOT}/repos/{intent.repository}/pulls/{number}"
        or raw.get("draft") is not True
        or raw.get("maintainer_can_modify") is not False
    ):
        raise PilotExactTaskRemotePublicationRecoveryError("ADR-DC-050 PR marker binding mismatch")
    _utc(raw.get("created_at_utc"), name="durable PR created_at_utc")
    return number, api_url


def _observe_verified_recovery_state(
    *,
    execution_nonce_sha256: str,
    transaction_ledger_root: Path,
    authorization_ledger_root: Path,
    local_transaction_ledger_root: Path,
    transport: Any,
    now_provider: Callable[[], str],
) -> tuple[PilotExactTaskRemotePublicationRecoveryState, _RecoveryIntent]:
    key = _hex64(execution_nonce_sha256, name="execution_nonce_sha256")
    tx_root = _safe_ledger_root(transaction_ledger_root)
    ledger = tx_boundary._PilotExactTaskRemotePublicationTransactionLedger(tx_root)
    final, lock, pushed, pr = ledger._paths(key)
    if final.exists() or final.is_symlink():
        raise PilotExactTaskRemotePublicationRecoveryError("ADR-DC-050 already has a final transaction receipt")
    lock_raw, lock_payload = _read_canonical_object(lock, name="ADR-DC-050 transaction lock")
    auth, local = _load_receipts(
        key=key,
        authorization_ledger_root=authorization_ledger_root,
        local_transaction_ledger_root=local_transaction_ledger_root,
    )
    intent = _intent(auth, local)
    _validate_lock(lock_raw, intent, ledger.root_sha256)
    pushed_hash = None
    pr_hash = None
    marker_number = None
    marker_url = None
    if pushed.exists() or pushed.is_symlink():
        pushed_raw, pushed_payload = _read_canonical_object(pushed, name="ADR-DC-050 pushed marker")
        _validate_pushed(pushed_raw, intent)
        pushed_hash = hashlib.sha256(pushed_payload).hexdigest()
    if pr.exists() or pr.is_symlink():
        if pushed_hash is None:
            raise PilotExactTaskRemotePublicationRecoveryError("PR marker exists without pushed marker")
        pr_raw, pr_payload = _read_canonical_object(pr, name="ADR-DC-050 PR marker")
        marker_number, marker_url = _validate_pr_marker(pr_raw, intent)
        pr_hash = hashlib.sha256(pr_payload).hexdigest()
    if transport is None or not callable(getattr(transport, "observe", None)):
        raise PilotExactTaskRemotePublicationRecoveryError("read-only recovery transport is required")
    remote = transport.observe(intent)
    if not isinstance(remote, Mapping) or remote.get("base_sha") != intent.base_sha:
        raise PilotExactTaskRemotePublicationRecoveryError("remote main no longer equals exact task base")
    head = remote.get("head_sha")
    remote_pr = remote.get("pull_request")
    if head not in {None, intent.predicted_commit_sha}:
        raise PilotExactTaskRemotePublicationRecoveryError("remote recovery branch points to another commit")
    if head is None and (pushed_hash is not None or pr_hash is not None or remote_pr is not None):
        raise PilotExactTaskRemotePublicationRecoveryError("durable/remote recovery evidence contradicts absent head")
    if pr_hash is not None:
        if not isinstance(remote_pr, Mapping) or remote_pr.get("number") != marker_number or remote_pr.get("api_url") != marker_url:
            raise PilotExactTaskRemotePublicationRecoveryError("durable PR marker differs from remote PR")
    if head is None:
        action = "manual_intervention"
        number = None
        api_url = None
        remote_head_state = "absent"
    elif remote_pr is None:
        action = "create_missing_pr"
        number = None
        api_url = None
        remote_head_state = "exact"
    else:
        if not isinstance(remote_pr, Mapping):
            raise PilotExactTaskRemotePublicationRecoveryError("remote PR identity is invalid")
        action = "finalize_existing_pr"
        number = remote_pr.get("number")
        api_url = remote_pr.get("api_url")
        remote_head_state = "exact"
    durable_state = "pr_marked" if pr_hash is not None else "pushed_marked" if pushed_hash is not None else "lock_only"
    state = PilotExactTaskRemotePublicationRecoveryState(
        transaction_key_sha256=key,
        transaction_lock_sha256=hashlib.sha256(lock_payload).hexdigest(),
        pushed_marker_sha256=pushed_hash,
        draft_pr_marker_sha256=pr_hash,
        remote_publication_authorization_sha256=auth.sha256,
        remote_publication_plan_sha256=auth.remote_publication_plan_sha256,
        pr_intent_sha256=auth.pr_intent_sha256,
        execution_nonce_sha256=key,
        development_task_sha256=auth.development_task_sha256,
        candidate_patch_sha256=auth.candidate_patch_sha256,
        integration_readiness_sha256=auth.integration_readiness_sha256,
        task_id=auth.task_id,
        repository=auth.repository,
        repository_id=auth.repository_id,
        base_branch=auth.base_branch,
        head_branch=auth.head_branch,
        exact_task_base_sha=auth.exact_task_base_sha,
        predicted_commit_sha=auth.predicted_commit_sha,
        root_tree_sha=intent.root_tree_sha,
        durable_transaction_state=durable_state,
        remote_head_state=remote_head_state,
        pull_request_number=number,
        pull_request_api_url=api_url,
        action_required=action,
        manual_intervention_required=(action == "manual_intervention"),
        observed_at_utc=now_provider(),
    )
    return state, intent


def build_pilot_exact_task_remote_publication_recovery_payload(
    state: PilotExactTaskRemotePublicationRecoveryState,
    action: str,
    requested_at_utc: str,
    expires_at_utc: str,
    operator_actor_id: str,
    operator_system_id: str,
    operator_key_id: str,
    reviewer_actor_id: str,
    reviewer_system_id: str,
    reviewer_key_id: str,
) -> bytes:
    if type(state) is not PilotExactTaskRemotePublicationRecoveryState:
        raise PilotExactTaskRemotePublicationRecoveryError("exact recovery state is required")
    if state.manual_intervention_required:
        raise PilotExactTaskRemotePublicationRecoveryError("lock-only absent-head state cannot be automatically recovered")
    if action != state.action_required or action not in {"create_missing_pr", "finalize_existing_pr"}:
        raise PilotExactTaskRemotePublicationRecoveryError("recovery action does not equal observed state")
    requested = _utc(requested_at_utc, name="requested_at_utc")
    expires = _utc(expires_at_utc, name="expires_at_utc")
    observed = _utc(state.observed_at_utc, name="observed_at_utc")
    if observed > requested or expires <= requested or (expires - requested).total_seconds() > _MAX_AUTH_SECONDS:
        raise PilotExactTaskRemotePublicationRecoveryError("recovery authorization time window is invalid")
    for name, value in (
        ("operator_actor_id", operator_actor_id),
        ("reviewer_actor_id", reviewer_actor_id),
    ):
        if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
            raise PilotExactTaskRemotePublicationRecoveryError(f"{name} is invalid")
    for name, value in (
        ("operator_system_id", operator_system_id),
        ("operator_key_id", operator_key_id),
        ("reviewer_system_id", reviewer_system_id),
        ("reviewer_key_id", reviewer_key_id),
    ):
        if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
            raise PilotExactTaskRemotePublicationRecoveryError(f"{name} is invalid")
    if operator_actor_id == reviewer_actor_id or operator_system_id == reviewer_system_id or operator_key_id == reviewer_key_id:
        raise PilotExactTaskRemotePublicationRecoveryError("recovery operator and reviewer must be independent")
    payload = {
        "schema": PILOT_EXACT_TASK_REMOTE_PUBLICATION_RECOVERY_PAYLOAD_SCHEMA,
        "recovery_state_fingerprint_sha256": state.fingerprint_sha256,
        "transaction_key_sha256": state.transaction_key_sha256,
        "remote_publication_authorization_sha256": state.remote_publication_authorization_sha256,
        "remote_publication_plan_sha256": state.remote_publication_plan_sha256,
        "pr_intent_sha256": state.pr_intent_sha256,
        "repository": state.repository,
        "repository_id": state.repository_id,
        "head_branch": state.head_branch,
        "predicted_commit_sha": state.predicted_commit_sha,
        "action": action,
        "requested_at_utc": requested_at_utc,
        "expires_at_utc": expires_at_utc,
        "operator_actor_id": operator_actor_id,
        "operator_system_id": operator_system_id,
        "operator_key_id": operator_key_id,
        "reviewer_actor_id": reviewer_actor_id,
        "reviewer_system_id": reviewer_system_id,
        "reviewer_key_id": reviewer_key_id,
        "recovery_policy_sha256": pilot_exact_task_remote_publication_recovery_policy_sha256(),
        "custody_policy_sha256": asymmetric_authority_key_custody_policy_sha256(),
        "nonce_reusable": False,
    }
    return _canonical(payload).encode("utf-8")


def _parse_recovery_payload(payload: bytes) -> dict[str, Any]:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_ARTIFACT_BYTES:
        raise PilotExactTaskRemotePublicationRecoveryError("recovery authorization payload is invalid")
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskRemotePublicationRecoveryError("recovery authorization payload is invalid JSON") from exc
    expected = {
        "schema", "recovery_state_fingerprint_sha256", "transaction_key_sha256",
        "remote_publication_authorization_sha256", "remote_publication_plan_sha256",
        "pr_intent_sha256", "repository", "repository_id", "head_branch",
        "predicted_commit_sha", "action", "requested_at_utc", "expires_at_utc",
        "operator_actor_id", "operator_system_id", "operator_key_id",
        "reviewer_actor_id", "reviewer_system_id", "reviewer_key_id",
        "recovery_policy_sha256", "custody_policy_sha256", "nonce_reusable",
    }
    if not isinstance(raw, dict) or set(raw) != expected or _canonical(raw).encode("utf-8") != payload:
        raise PilotExactTaskRemotePublicationRecoveryError("recovery authorization payload fields/canonical form mismatch")
    if raw["schema"] != PILOT_EXACT_TASK_REMOTE_PUBLICATION_RECOVERY_PAYLOAD_SCHEMA:
        raise PilotExactTaskRemotePublicationRecoveryError("recovery authorization payload schema is unsupported")
    if raw["recovery_policy_sha256"] != pilot_exact_task_remote_publication_recovery_policy_sha256() or raw["custody_policy_sha256"] != asymmetric_authority_key_custody_policy_sha256() or raw["nonce_reusable"] is not False:
        raise PilotExactTaskRemotePublicationRecoveryError("recovery authorization policy is unsupported")
    for name in ("recovery_state_fingerprint_sha256", "transaction_key_sha256", "remote_publication_authorization_sha256", "remote_publication_plan_sha256", "pr_intent_sha256"):
        _hex64(raw[name], name=name)
    _hex40(raw["predicted_commit_sha"], name="predicted_commit_sha")
    if raw["action"] not in {"create_missing_pr", "finalize_existing_pr"}:
        raise PilotExactTaskRemotePublicationRecoveryError("recovery authorization action is invalid")
    return raw


def _parse_keyring(payload: bytes) -> tuple[Ed25519AuthorityVerifier, str]:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_KEYRING_BYTES:
        raise PilotExactTaskRemotePublicationRecoveryError("recovery keyring is invalid")
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskRemotePublicationRecoveryError("recovery keyring JSON is invalid") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema", "minimum_keyring_epoch", "keys"} or raw.get("schema") != PILOT_EXACT_TASK_REMOTE_PUBLICATION_RECOVERY_KEYRING_SCHEMA:
        raise PilotExactTaskRemotePublicationRecoveryError("recovery keyring fields/schema mismatch")
    epoch = raw["minimum_keyring_epoch"]
    keys_raw = raw["keys"]
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 1 or not isinstance(keys_raw, list) or len(keys_raw) < 2 or len(keys_raw) > 64:
        raise PilotExactTaskRemotePublicationRecoveryError("recovery keyring content is invalid")
    keys: dict[str, TrustedEd25519AuthorityKey] = {}
    for item in keys_raw:
        try:
            key = TrustedEd25519AuthorityKey.from_mapping(item)
        except Exception as exc:
            raise PilotExactTaskRemotePublicationRecoveryError("recovery trusted key is invalid") from exc
        if key.key_id in keys:
            raise PilotExactTaskRemotePublicationRecoveryError("recovery key IDs are duplicated")
        keys[key.key_id] = key
    canonical = _canonical({"schema": PILOT_EXACT_TASK_REMOTE_PUBLICATION_RECOVERY_KEYRING_SCHEMA, "minimum_keyring_epoch": epoch, "keys": [key.to_dict() for key in keys.values()]}).encode("utf-8")
    if canonical != payload:
        raise PilotExactTaskRemotePublicationRecoveryError("recovery keyring is not canonical JSON")
    return Ed25519AuthorityVerifier(keys, minimum_keyring_epoch=epoch), hashlib.sha256(payload).hexdigest()


def _verify_dual_signatures(*, payload: bytes, operator_signature: DetachedEd25519AuthoritySignature, reviewer_signature: DetachedEd25519AuthoritySignature, verifier: Ed25519AuthorityVerifier, at_utc: str) -> dict[str, Any]:
    raw = _parse_recovery_payload(payload)
    if type(operator_signature) is not DetachedEd25519AuthoritySignature or type(reviewer_signature) is not DetachedEd25519AuthoritySignature or not isinstance(verifier, Ed25519AuthorityVerifier):
        raise PilotExactTaskRemotePublicationRecoveryError("dual Ed25519 recovery authority is required")
    for signature, prefix in ((operator_signature, "operator"), (reviewer_signature, "reviewer")):
        if (
            signature.issuer_actor_id != raw[f"{prefix}_actor_id"]
            or signature.issuer_system_id != raw[f"{prefix}_system_id"]
            or signature.key_id != raw[f"{prefix}_key_id"]
            or signature.payload_sha256 != hashlib.sha256(payload).hexdigest()
        ):
            raise PilotExactTaskRemotePublicationRecoveryError(f"recovery {prefix} signature binding mismatch")
    if operator_signature.key_id == reviewer_signature.key_id or operator_signature.issuer_actor_id == reviewer_signature.issuer_actor_id or operator_signature.issuer_system_id == reviewer_signature.issuer_system_id:
        raise PilotExactTaskRemotePublicationRecoveryError("recovery signatures are not independent")
    now = _utc(at_utc, name="recovery verification time")
    requested = _utc(raw["requested_at_utc"], name="requested_at_utc")
    expires = _utc(raw["expires_at_utc"], name="expires_at_utc")
    if not (requested <= now < expires):
        raise PilotExactTaskRemotePublicationRecoveryError("recovery authorization is not currently valid")
    try:
        verifier.verify(payload=payload, signature=operator_signature, at_utc=at_utc)
        verifier.verify(payload=payload, signature=reviewer_signature, at_utc=at_utc)
    except AsymmetricAuthorityError as exc:
        raise PilotExactTaskRemotePublicationRecoveryError("recovery signature verification failed") from exc
    return raw


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskRemotePublicationRecoveryReceipt:
    recovery_ledger_root_path_sha256: str
    recovery_key_sha256: str
    recovery_state_fingerprint_sha256: str
    recovery_authorization_payload_sha256: str
    remote_publication_authorization_sha256: str
    remote_publication_plan_sha256: str
    pr_intent_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    task_id: str
    repository: str
    repository_id: str
    base_branch: str
    head_branch: str
    exact_task_base_sha: str
    predicted_commit_sha: str
    root_tree_sha: str
    pull_request_number: int
    pull_request_api_url: str
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
    deterministic_pr_intent_reconstructed: bool = True
    remote_base_verified: bool = True
    remote_exact_head_verified: bool = True
    draft_pr_created: bool = True
    draft_pr_verified: bool = True
    remote_write_performed: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    product_pilot_started: bool = False
    nonce_reusable: bool = False
    ledger_scope: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_RECOVERY_LEDGER_SCOPE
    authority: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_RECOVERY_AUTHORITY
    schema: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_RECOVERY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_REMOTE_PUBLICATION_RECOVERY_SCHEMA or self.authority != PILOT_EXACT_TASK_REMOTE_PUBLICATION_RECOVERY_AUTHORITY or self.ledger_scope != PILOT_EXACT_TASK_REMOTE_PUBLICATION_RECOVERY_LEDGER_SCOPE:
            raise PilotExactTaskRemotePublicationRecoveryError("recovery receipt identity is unsupported")
        for name in ("recovery_ledger_root_path_sha256", "recovery_key_sha256", "recovery_state_fingerprint_sha256", "recovery_authorization_payload_sha256", "remote_publication_authorization_sha256", "remote_publication_plan_sha256", "pr_intent_sha256", "execution_nonce_sha256", "development_task_sha256", "candidate_patch_sha256"):
            _hex64(getattr(self, name), name=name)
        for name in ("exact_task_base_sha", "predicted_commit_sha", "root_tree_sha"):
            _hex40(getattr(self, name), name=name)
        if self.recovery_key_sha256 != self.execution_nonce_sha256:
            raise PilotExactTaskRemotePublicationRecoveryError("recovery key differs from execution nonce")
        if self.recovery_action not in {"create_missing_pr", "finalize_existing_pr"} or self.durable_transaction_state not in {"lock_only", "pushed_marked", "pr_marked"}:
            raise PilotExactTaskRemotePublicationRecoveryError("recovery receipt action/state is invalid")
        if isinstance(self.pull_request_number, bool) or not isinstance(self.pull_request_number, int) or self.pull_request_number < 1 or self.pull_request_api_url != f"{_GITHUB_API_ROOT}/repos/{self.repository}/pulls/{self.pull_request_number}":
            raise PilotExactTaskRemotePublicationRecoveryError("recovered pull-request identity is invalid")
        _utc(self.recovered_at_utc, name="recovered_at_utc")
        required = ("host_recovery_guard_committed", "dual_ed25519_recovery_authorized", "durable_transaction_state_verified", "deterministic_pr_intent_reconstructed", "remote_base_verified", "remote_exact_head_verified", "draft_pr_created", "draft_pr_verified")
        if any(getattr(self, name) is not True for name in required):
            raise PilotExactTaskRemotePublicationRecoveryError("recovery receipt evidence is incomplete")
        forced_false = ("remote_write_authorized", "push_authorized", "pr_mutation_authorized", "merge_authorized", "release_authorized", "deploy_authorized", "production_activation_authorized", "product_pilot_started", "nonce_reusable")
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskRemotePublicationRecoveryError("recovery receipt retains forbidden authority")
        if self.remote_write_performed is not (self.recovery_action == "create_missing_pr"):
            raise PilotExactTaskRemotePublicationRecoveryError("recovery remote-write flag is inconsistent")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def recovery_authenticated(self) -> bool:
        return _get_live_recovery_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}  # type: ignore[attr-defined]

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskRemotePublicationRecoveryReceipt":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):  # type: ignore[attr-defined]
            raise PilotExactTaskRemotePublicationRecoveryError("recovery receipt fields mismatch")
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskRemotePublicationRecoveryLedger:
    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path]:
        digest = _hex64(key, name="recovery_key_sha256")
        return self.root / f"{digest}.json", self.root / f".{digest}.lock"

    def acquire(self, *, state: PilotExactTaskRemotePublicationRecoveryState, authorization_payload: bytes, operator_signature: DetachedEd25519AuthoritySignature, reviewer_signature: DetachedEd25519AuthoritySignature) -> bytes:
        final, lock = self._paths(state.execution_nonce_sha256)
        if final.exists() or final.is_symlink() or lock.exists() or lock.is_symlink():
            raise PilotExactTaskRemotePublicationRecoveryError("recovery nonce already consumed or needs recovery")
        payload = _canonical({
            "schema": "kaliv-rsi-dc-l16-exact-task-remote-publication-recovery-lock/v1",
            "recovery_key_sha256": state.execution_nonce_sha256,
            "recovery_state_fingerprint_sha256": state.fingerprint_sha256,
            "recovery_authorization_payload_sha256": hashlib.sha256(authorization_payload).hexdigest(),
            "operator_signature_sha256": hashlib.sha256(operator_signature.canonical_json().encode("utf-8")).hexdigest(),
            "reviewer_signature_sha256": hashlib.sha256(reviewer_signature.canonical_json().encode("utf-8")).hexdigest(),
            "action": state.action_required,
        }).encode("utf-8")
        try:
            create_once_file(lock, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskRemotePublicationRecoveryError("recovery authorization could not be durably consumed") from exc
        return payload

    def commit(self, *, receipt: PilotExactTaskRemotePublicationRecoveryReceipt, lock_payload: bytes) -> PilotExactTaskRemotePublicationRecoveryReceipt:
        final, lock = self._paths(receipt.recovery_key_sha256)
        if final.exists() or final.is_symlink() or _read_bytes(lock) != lock_payload:
            raise PilotExactTaskRemotePublicationRecoveryError("recovery durable state changed before finalization")
        payload = receipt.canonical_json().encode("utf-8")
        try:
            create_once_file(final, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskRemotePublicationRecoveryError("recovery receipt could not be durably published") from exc
        parsed = PilotExactTaskRemotePublicationRecoveryReceipt.from_mapping(json.loads(payload.decode("utf-8")))
        _mark_recovery_authenticated(parsed, final_path=final, final_payload=payload, lock_path=lock, lock_payload=lock_payload)
        if parsed.recovery_authenticated is not True:
            raise PilotExactTaskRemotePublicationRecoveryError("recovery receipt lost live provenance")
        return parsed


def _live_registry():
    records: dict[int, tuple[int, str, weakref.ReferenceType[Any], Path, bytes, Path, bytes]] = {}

    def mark(receipt: Any, *, final_path: Path, final_payload: bytes, lock_path: Path, lock_payload: bytes) -> None:
        key = id(receipt)
        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)
        records[key] = (os.getpid(), receipt.sha256, weakref.ref(receipt, cleanup), final_path, final_payload, lock_path, lock_payload)

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, ref, final_path, final_payload, lock_path, lock_payload = entry
        if pid != os.getpid() or ref() is not receipt or receipt.sha256 != digest or _read_bytes(final_path) != final_payload or _read_bytes(lock_path) != lock_payload:
            return None
        return MappingProxyType({"receipt_sha256": digest})

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_recovery_authenticated, _get_live_recovery_inputs = _live_registry()


def _recover_verified_pilot_exact_task_remote_publication(
    *,
    authorization_payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    transaction_ledger_root: Path,
    authorization_ledger_root: Path,
    local_transaction_ledger_root: Path,
    recovery_ledger: _PilotExactTaskRemotePublicationRecoveryLedger,
    transport: Any,
    now_provider: Callable[[], str],
) -> PilotExactTaskRemotePublicationRecoveryReceipt:
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
        authorization_ledger_root=authorization_ledger_root,
        local_transaction_ledger_root=local_transaction_ledger_root,
        transport=transport,
        now_provider=now_provider,
    )
    if (
        state.fingerprint_sha256 != claim["recovery_state_fingerprint_sha256"]
        or state.action_required != claim["action"]
        or state.remote_publication_authorization_sha256 != claim["remote_publication_authorization_sha256"]
        or state.remote_publication_plan_sha256 != claim["remote_publication_plan_sha256"]
        or state.pr_intent_sha256 != claim["pr_intent_sha256"]
        or state.repository != claim["repository"]
        or state.repository_id != claim["repository_id"]
        or state.head_branch != claim["head_branch"]
        or state.predicted_commit_sha != claim["predicted_commit_sha"]
    ):
        raise PilotExactTaskRemotePublicationRecoveryError("signed recovery state changed before execution")
    lock_payload = recovery_ledger.acquire(
        state=state,
        authorization_payload=authorization_payload,
        operator_signature=operator_signature,
        reviewer_signature=reviewer_signature,
    )
    current, current_intent = _observe_verified_recovery_state(
        execution_nonce_sha256=state.execution_nonce_sha256,
        transaction_ledger_root=transaction_ledger_root,
        authorization_ledger_root=authorization_ledger_root,
        local_transaction_ledger_root=local_transaction_ledger_root,
        transport=transport,
        now_provider=now_provider,
    )
    if current.fingerprint_sha256 != state.fingerprint_sha256 or current_intent != intent:
        raise PilotExactTaskRemotePublicationRecoveryError("recovery state changed after durable authorization consumption")
    if state.action_required == "create_missing_pr":
        if not callable(getattr(transport, "create_draft_pr", None)):
            raise PilotExactTaskRemotePublicationRecoveryError("recovery transport cannot create exact draft PR")
        created = transport.create_draft_pr(intent)
        if not isinstance(created, Mapping):
            raise PilotExactTaskRemotePublicationRecoveryError("recovery draft-PR creation result is invalid")
        after, _ = _observe_verified_recovery_state(
            execution_nonce_sha256=state.execution_nonce_sha256,
            transaction_ledger_root=transaction_ledger_root,
            authorization_ledger_root=authorization_ledger_root,
            local_transaction_ledger_root=local_transaction_ledger_root,
            transport=transport,
            now_provider=now_provider,
        )
        if after.action_required != "finalize_existing_pr" or after.pull_request_number != created.get("number") or after.pull_request_api_url != created.get("api_url"):
            raise PilotExactTaskRemotePublicationRecoveryError("created recovery PR could not be re-observed exactly")
        number = after.pull_request_number
        api_url = after.pull_request_api_url
        remote_write_performed = True
    else:
        number = state.pull_request_number
        api_url = state.pull_request_api_url
        remote_write_performed = False
    if not isinstance(number, int) or number < 1 or not isinstance(api_url, str):
        raise PilotExactTaskRemotePublicationRecoveryError("recovered exact PR identity is unavailable")
    recovered_at = now_provider()
    if _utc(recovered_at, name="recovered_at_utc") < _utc(verified_at, name="verified_at_utc"):
        raise PilotExactTaskRemotePublicationRecoveryError("system clock moved backwards during recovery")
    receipt = PilotExactTaskRemotePublicationRecoveryReceipt(
        recovery_ledger_root_path_sha256=recovery_ledger.root_sha256,
        recovery_key_sha256=state.execution_nonce_sha256,
        recovery_state_fingerprint_sha256=state.fingerprint_sha256,
        recovery_authorization_payload_sha256=hashlib.sha256(authorization_payload).hexdigest(),
        remote_publication_authorization_sha256=state.remote_publication_authorization_sha256,
        remote_publication_plan_sha256=state.remote_publication_plan_sha256,
        pr_intent_sha256=state.pr_intent_sha256,
        execution_nonce_sha256=state.execution_nonce_sha256,
        development_task_sha256=state.development_task_sha256,
        candidate_patch_sha256=state.candidate_patch_sha256,
        task_id=state.task_id,
        repository=state.repository,
        repository_id=state.repository_id,
        base_branch=state.base_branch,
        head_branch=state.head_branch,
        exact_task_base_sha=state.exact_task_base_sha,
        predicted_commit_sha=state.predicted_commit_sha,
        root_tree_sha=state.root_tree_sha,
        pull_request_number=number,
        pull_request_api_url=api_url,
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
    return recovery_ledger.commit(receipt=receipt, lock_payload=lock_payload)


def _canonical_roots() -> tuple[Path, Path, Path, Path]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            recovery = _POSIX_LEDGER
            tx = tx_boundary._POSIX_LEDGER
            auth = auth_boundary._POSIX_LEDGER
            local = local_tx_boundary._POSIX_LEDGER
        elif os.name == "nt":
            recovery = _WINDOWS_LEDGER
            tx = tx_boundary._WINDOWS_LEDGER
            auth = auth_boundary._WINDOWS_LEDGER
            local = local_tx_boundary._WINDOWS_LEDGER
        else:
            raise PilotExactTaskRemotePublicationRecoveryError("recovery platform is unsupported")
        return tuple(_require_host_controlled_ledger_root(path) for path in (recovery, tx, auth, local))  # type: ignore[return-value]
    except PhysicalHostStateError as exc:
        raise PilotExactTaskRemotePublicationRecoveryError("recovery ledgers are not host-admin controlled") from exc


def _canonical_keyring() -> tuple[Ed25519AuthorityVerifier, str]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_KEYRING
        elif os.name == "nt":
            path = _WINDOWS_KEYRING
        else:
            raise PilotExactTaskRemotePublicationRecoveryError("recovery keyring platform is unsupported")
        _require_host_controlled_ledger_root(path.parent)
        payload = _read_bytes(path)
        if payload is None or len(payload) > _MAX_KEYRING_BYTES:
            raise PilotExactTaskRemotePublicationRecoveryError("recovery keyring is unavailable")
        return _parse_keyring(payload)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskRemotePublicationRecoveryError("recovery keyring is not host-admin controlled") from exc


def observe_pilot_exact_task_remote_publication_recovery(
    execution_nonce_sha256: str,
) -> PilotExactTaskRemotePublicationRecoveryState:
    """Observe one interrupted ADR-DC-050 transaction without mutation."""
    recovery_root, tx_root, auth_root, local_root = _canonical_roots()
    del recovery_root
    state, _intent_value = _observe_verified_recovery_state(
        execution_nonce_sha256=execution_nonce_sha256,
        transaction_ledger_root=tx_root,
        authorization_ledger_root=auth_root,
        local_transaction_ledger_root=local_root,
        transport=_GitHubRecoveryTransport(),
        now_provider=_now_utc_seconds,
    )
    return state


def recover_pilot_exact_task_remote_publication(
    authorization_payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
) -> PilotExactTaskRemotePublicationRecoveryReceipt:
    """Perform only the dual-authorized missing-PR/finalization recovery action."""
    try:
        recovery_root, tx_root, auth_root, local_root = _canonical_roots()
        verifier, _keyring_sha256 = _canonical_keyring()
        claim = _parse_recovery_payload(authorization_payload)
        credential = None
        if claim["action"] == "create_missing_pr":
            credential, _digest, _path = tx_boundary._canonical_credential()
        return _recover_verified_pilot_exact_task_remote_publication(
            authorization_payload=authorization_payload,
            operator_signature=operator_signature,
            reviewer_signature=reviewer_signature,
            verifier=verifier,
            transaction_ledger_root=tx_root,
            authorization_ledger_root=auth_root,
            local_transaction_ledger_root=local_root,
            recovery_ledger=_PilotExactTaskRemotePublicationRecoveryLedger(recovery_root),
            transport=_GitHubRecoveryTransport(credential),
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskRemotePublicationRecoveryError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskRemotePublicationRecoveryError("host-controlled publication recovery failed closed") from exc


__all__ = [
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_RECOVERY_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_RECOVERY_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_RECOVERY_KEYRING_SCHEMA",
    "PilotExactTaskRemotePublicationRecoveryError",
    "PilotExactTaskRemotePublicationRecoveryState",
    "PilotExactTaskRemotePublicationRecoveryReceipt",
    "pilot_exact_task_remote_publication_recovery_policy_sha256",
    "build_pilot_exact_task_remote_publication_recovery_payload",
    "observe_pilot_exact_task_remote_publication_recovery",
    "recover_pilot_exact_task_remote_publication",
]
