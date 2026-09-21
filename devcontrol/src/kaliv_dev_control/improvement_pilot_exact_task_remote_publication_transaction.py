"""ADR-DC-050 one-shot exact remote-publication transaction.

This boundary consumes one exact live ADR-DC-049 authorization before any
remote mutation. It revalidates the exact local commit and clear GitHub lane
after durable transaction consumption, then performs only the authorized
operations: push the exact predicted commit to the deterministic branch and
create the exact deterministic draft pull request.

The transaction never grants or performs merge, release, deployment or
production activation.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import stat
import urllib.error
import urllib.parse
import urllib.request
import weakref
from dataclasses import dataclass, field
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
from .bounded_subprocess import BoundedSubprocessError, run_bounded_subprocess
from .durable_publication import (
    DurablePublicationError,
    create_once_file,
    sync_directory,
    unlink_durable,
)
from . import improvement_pilot_exact_task_remote_publication_authorization as auth_boundary
from .improvement_pilot_exact_task_remote_publication_authorization import (
    PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_AUTHORITY,
    PilotExactTaskRemotePublicationAuthorizationReceipt,
)
from .improvement_pilot_exact_task_remote_publication_plan import (
    PilotExactTaskRemotePublicationPlan,
)
from . import improvement_pilot_exact_task_remote_state_observation as observation_boundary
from .improvement_physical_authority_keyring import (
    PhysicalRequestAuthorityKeyringError,
    _require_posix_host_control,
    _require_windows_host_control,
)
from .trusted_git_runtime import TrustedGitRunner
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_REMOTE_PUBLICATION_TRANSACTION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-remote-publication-transaction-receipt/v1"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_TRANSACTION_AUTHORITY = (
    "host-executed-one-dc-l16-exact-remote-publication-only"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_TRANSACTION_LEDGER_SCOPE = (
    "canonical-host-local-v1"
)
PILOT_EXACT_TASK_GITHUB_PUBLISHER_CREDENTIAL_SCHEMA = (
    "kaliv-rsi-dc-l16-github-publisher-credential/v1"
)
_MAX_ARTIFACT_BYTES = 1024 * 1024
_MAX_API_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_CREDENTIAL_BYTES = 64 * 1024
_TIMEOUT_SECONDS = 30.0
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_BRANCH = re.compile(r"^(?![./])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_CREDENTIAL_ID = re.compile(r"^[A-Za-z0-9._-]{3,128}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_]{20,255}$")
_GITHUB_API_ROOT = "https://api.github.com"
_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-remote-publication-transaction-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-remote-publication-transaction-ledger-v1"
)
_POSIX_CREDENTIAL = Path(
    "/etc/modelrig/devcontrol/authority/"
    "rsi-github-publisher-credential-v1.json"
)
_WINDOWS_CREDENTIAL = (
    Path(r"C:\Program Files\ModelRig\DevControl\authority")
    / "rsi-github-publisher-credential-v1.json"
)


class PilotExactTaskRemotePublicationTransactionError(ValueError):
    """Exact remote publication transaction is stale, replayed or over-broad."""


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
        raise PilotExactTaskRemotePublicationTransactionError(
            "remote publication transaction is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskRemotePublicationTransactionError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskRemotePublicationTransactionError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskRemotePublicationTransactionError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskRemotePublicationTransactionError(
            f"{name} is invalid"
        ) from exc


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
        raise PilotExactTaskRemotePublicationTransactionError(
            f"{name} is not a canonical branch name"
        )
    return value


def _read_bound_file(path: Path) -> bytes | None:
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


@dataclass(frozen=True, slots=True)
class PilotExactTaskGitHubPublisherCredential:
    credential_id: str
    repository: str
    repository_id: str
    username: str
    token: str = field(repr=False)
    schema: str = PILOT_EXACT_TASK_GITHUB_PUBLISHER_CREDENTIAL_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_GITHUB_PUBLISHER_CREDENTIAL_SCHEMA:
            raise PilotExactTaskRemotePublicationTransactionError(
                "publisher credential schema is unsupported"
            )
        if (
            not isinstance(self.credential_id, str)
            or _CREDENTIAL_ID.fullmatch(self.credential_id) is None
        ):
            raise PilotExactTaskRemotePublicationTransactionError(
                "publisher credential_id is invalid"
            )
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
        ):
            raise PilotExactTaskRemotePublicationTransactionError(
                "publisher credential repository is invalid"
            )
        if (
            not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskRemotePublicationTransactionError(
                "publisher credential repository_id is invalid"
            )
        if self.username != "x-access-token":
            raise PilotExactTaskRemotePublicationTransactionError(
                "publisher credential username is unsupported"
            )
        if not isinstance(self.token, str) or _TOKEN.fullmatch(self.token) is None:
            raise PilotExactTaskRemotePublicationTransactionError(
                "publisher credential token is invalid"
            )

    def to_dict(self) -> dict[str, str]:
        return {
            "schema": self.schema,
            "credential_id": self.credential_id,
            "repository": self.repository,
            "repository_id": self.repository_id,
            "username": self.username,
            "token": self.token,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskGitHubPublisherCredential":
        if not isinstance(value, Mapping):
            raise PilotExactTaskRemotePublicationTransactionError(
                "publisher credential must be an object"
            )
        expected = {
            "schema",
            "credential_id",
            "repository",
            "repository_id",
            "username",
            "token",
        }
        if set(value) != expected:
            raise PilotExactTaskRemotePublicationTransactionError(
                "publisher credential fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _parse_credential_payload(
    payload: bytes,
) -> tuple[PilotExactTaskGitHubPublisherCredential, str]:
    if not isinstance(payload, bytes) or not 2 <= len(payload) <= _MAX_CREDENTIAL_BYTES:
        raise PilotExactTaskRemotePublicationTransactionError(
            "publisher credential payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskRemotePublicationTransactionError(
            "publisher credential JSON is invalid"
        ) from exc
    credential = PilotExactTaskGitHubPublisherCredential.from_mapping(raw)
    canonical = credential.canonical_json().encode("utf-8")
    if payload != canonical:
        raise PilotExactTaskRemotePublicationTransactionError(
            "publisher credential is not canonical JSON"
        )
    return credential, hashlib.sha256(payload).hexdigest()


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino, left.st_size) == (
        right.st_dev,
        right.st_ino,
        right.st_size,
    )


def _read_host_credential(
    path: Path,
) -> tuple[PilotExactTaskGitHubPublisherCredential, str, bytes]:
    candidate = Path(path)
    if (
        not candidate.is_absolute()
        or _has_linkish_component(candidate)
        or not candidate.is_file()
    ):
        raise PilotExactTaskRemotePublicationTransactionError(
            "publisher credential path is unsafe"
        )
    try:
        before = candidate.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise PilotExactTaskRemotePublicationTransactionError(
                "publisher credential is not one regular file"
            )
        if os.name == "posix":
            if stat.S_IMODE(before.st_mode) & 0o077:
                raise PilotExactTaskRemotePublicationTransactionError(
                    "publisher credential must not be group/world accessible"
                )
            _require_posix_host_control(candidate, before)
        elif os.name == "nt":
            _require_windows_host_control(candidate, before)
        else:
            raise PilotExactTaskRemotePublicationTransactionError(
                "publisher credential platform is unsupported"
            )
        first = candidate.read_bytes()
        second = candidate.read_bytes()
        after = candidate.lstat()
    except (OSError, PhysicalRequestAuthorityKeyringError) as exc:
        raise PilotExactTaskRemotePublicationTransactionError(
            "publisher credential cannot be safely read"
        ) from exc
    if not _same_file(before, after) or first != second:
        raise PilotExactTaskRemotePublicationTransactionError(
            "publisher credential changed while being read"
        )
    credential, digest = _parse_credential_payload(second)
    return credential, digest, second


def _canonical_credential() -> tuple[
    PilotExactTaskGitHubPublisherCredential, str, Path
]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_CREDENTIAL
        elif os.name == "nt":
            path = _WINDOWS_CREDENTIAL
        else:
            raise PilotExactTaskRemotePublicationTransactionError(
                "publisher credential is unsupported on this platform"
            )
        credential, digest, _payload = _read_host_credential(path)
        return credential, digest, path
    except PhysicalHostStateError as exc:
        raise PilotExactTaskRemotePublicationTransactionError(
            "publisher credential requires an elevated host operator"
        ) from exc


def _require_live_authorization(
    value: Any,
) -> tuple[
    PilotExactTaskRemotePublicationAuthorizationReceipt,
    PilotExactTaskRemotePublicationPlan,
    Any,
    Mapping[str, Any],
]:
    if type(value) is not PilotExactTaskRemotePublicationAuthorizationReceipt:
        raise PilotExactTaskRemotePublicationTransactionError(
            "exact ADR-DC-049 remote publication authorization is required"
        )
    try:
        replayed = PilotExactTaskRemotePublicationAuthorizationReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskRemotePublicationTransactionError(
            "ADR-DC-049 authorization replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskRemotePublicationTransactionError(
            "ADR-DC-049 authorization identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_AUTHORITY
        or value.authorization_authenticated is not True
        or value.host_replay_guard_committed is not True
        or value.remote_state_observation_authenticated is not True
        or value.publication_lane_clear is not True
        or value.fresh_local_commit_revalidated is not True
        or value.fresh_remote_state_revalidated is not True
        or value.remote_publication_authority_reserved is not True
        or value.one_shot_remote_publication_required is not True
        or value.exact_remote_branch_creation_authorized is not True
        or value.exact_commit_push_authorized is not True
        or value.exact_draft_pr_creation_authorized is not True
        or value.remote_write_authorized is not True
        or value.push_authorized is not True
        or value.pr_mutation_authorized is not True
        or value.remote_branch_created is not False
        or value.exact_commit_pushed is not False
        or value.draft_pr_created is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskRemotePublicationTransactionError(
            "transaction requires one live unused ADR-DC-049 authorization"
        )
    inputs = auth_boundary._get_live_remote_publication_authorization_inputs(value)
    if inputs is None:
        raise PilotExactTaskRemotePublicationTransactionError(
            "ADR-DC-049 live authorization inputs are unavailable"
        )
    observation = inputs.get("remote_state_observation")
    plan = inputs.get("remote_publication_plan")
    if (
        observation is None
        or type(plan) is not PilotExactTaskRemotePublicationPlan
        or getattr(observation, "sha256", None) != value.remote_state_observation_sha256
        or plan.sha256 != value.remote_publication_plan_sha256
        or plan.execution_nonce_sha256 != value.execution_nonce_sha256
        or plan.predicted_commit_sha != value.predicted_commit_sha
        or plan.head_branch != value.head_branch
        or plan.base_sha != value.exact_task_base_sha
    ):
        raise PilotExactTaskRemotePublicationTransactionError(
            "ADR-DC-049 authorization is not bound to exact live provenance"
        )
    return value, plan, observation, inputs


def _fresh_authorized_lane(
    *,
    authorization: PilotExactTaskRemotePublicationAuthorizationReceipt,
    plan: PilotExactTaskRemotePublicationPlan,
    observation: Any,
    inputs: Mapping[str, Any],
    observer: Any,
) -> str:
    try:
        digest = auth_boundary._fresh_observation(
            observation=observation,
            plan=plan,
            inputs=inputs,
            observer=observer,
        )
    except Exception as exc:
        raise PilotExactTaskRemotePublicationTransactionError(
            "fresh exact publication lane revalidation failed"
        ) from exc
    if (
        digest != authorization.remote_observation_sha256
        or digest != authorization.fresh_remote_observation_sha256
    ):
        raise PilotExactTaskRemotePublicationTransactionError(
            "fresh publication lane no longer equals ADR-DC-049 authority"
        )
    live = auth_boundary._get_live_remote_publication_authorization_inputs(
        authorization
    )
    if live is None or live.get("remote_state_observation") is not observation:
        raise PilotExactTaskRemotePublicationTransactionError(
            "ADR-DC-049 live authority changed during transaction"
        )
    return digest


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class _GitHubPublisherTransport:
    """Exact GitHub push + draft-PR transport with no secret in argv/env."""

    def __init__(
        self,
        *,
        credential: PilotExactTaskGitHubPublisherCredential,
        credential_config_sha256: str,
        credential_path: Path,
    ) -> None:
        if type(credential) is not PilotExactTaskGitHubPublisherCredential:
            raise PilotExactTaskRemotePublicationTransactionError(
                "exact publisher credential is required"
            )
        self.credential = credential
        self.credential_id = credential.credential_id
        self.credential_config_sha256 = _hex64(
            credential_config_sha256,
            name="publisher credential config digest",
        )
        self.credential_path = Path(credential_path)
        if (
            not self.credential_path.is_absolute()
            or _has_linkish_component(self.credential_path)
        ):
            raise PilotExactTaskRemotePublicationTransactionError(
                "publisher credential path identity is unsafe"
            )
        self.credential_path_sha256 = _path_sha256(self.credential_path)
        self._opener = urllib.request.build_opener(_NoRedirect())

    def validate_for(self, plan: PilotExactTaskRemotePublicationPlan) -> None:
        if (
            type(plan) is not PilotExactTaskRemotePublicationPlan
            or self.credential.repository != plan.repository
            or self.credential.repository_id != plan.repository_id
        ):
            raise PilotExactTaskRemotePublicationTransactionError(
                "publisher credential is not bound to exact remote target"
            )

    def _api_json(
        self,
        *,
        path: str,
        method: str,
        body: Mapping[str, Any] | None = None,
    ) -> Any:
        if (
            not isinstance(path, str)
            or not path.startswith("/repos/")
            or ".." in path
            or method not in {"GET", "POST"}
        ):
            raise PilotExactTaskRemotePublicationTransactionError(
                "publisher API request is outside exact GitHub scope"
            )
        payload = None
        if method == "POST":
            if not isinstance(body, Mapping):
                raise PilotExactTaskRemotePublicationTransactionError(
                    "publisher POST body is missing"
                )
            payload = _canonical(dict(body)).encode("utf-8")
        elif body is not None:
            raise PilotExactTaskRemotePublicationTransactionError(
                "publisher GET cannot carry a body"
            )
        url = _GITHUB_API_ROOT + path
        request = urllib.request.Request(
            url,
            data=payload,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.credential.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "ModelRig-DevControl-ExactPublisher/1",
                **({"Content-Type": "application/json"} if payload is not None else {}),
            },
        )
        try:
            response = self._opener.open(request, timeout=_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            raise PilotExactTaskRemotePublicationTransactionError(
                f"GitHub publisher request failed with HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PilotExactTaskRemotePublicationTransactionError(
                "GitHub publisher request failed"
            ) from exc
        with response:
            expected = 201 if method == "POST" else 200
            if response.status != expected or response.geturl() != url:
                raise PilotExactTaskRemotePublicationTransactionError(
                    "GitHub publisher response identity/status is unexpected"
                )
            raw = response.read(_MAX_API_RESPONSE_BYTES + 1)
        if not raw or len(raw) > _MAX_API_RESPONSE_BYTES:
            raise PilotExactTaskRemotePublicationTransactionError(
                "GitHub publisher response size is invalid"
            )
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PilotExactTaskRemotePublicationTransactionError(
                "GitHub publisher response is invalid JSON"
            ) from exc

    @staticmethod
    def _repo_root(plan: PilotExactTaskRemotePublicationPlan) -> str:
        owner, repo = plan.repository.split("/", 1)
        return (
            f"/repos/{urllib.parse.quote(owner, safe='')}/"
            f"{urllib.parse.quote(repo, safe='')}"
        )

    def _observe_ref(
        self,
        plan: PilotExactTaskRemotePublicationPlan,
        branch: str,
    ) -> str:
        root = self._repo_root(plan)
        branch_q = urllib.parse.quote(_branch(branch, name="publisher branch"), safe="")
        value = self._api_json(
            path=f"{root}/git/ref/heads/{branch_q}",
            method="GET",
        )
        if not isinstance(value, Mapping):
            raise PilotExactTaskRemotePublicationTransactionError(
                "GitHub ref verification response is invalid"
            )
        obj = value.get("object")
        if not isinstance(obj, Mapping) or obj.get("type") != "commit":
            raise PilotExactTaskRemotePublicationTransactionError(
                "GitHub ref does not resolve to one commit"
            )
        return _hex40(obj.get("sha"), name="GitHub verified ref SHA")

    def _matching_prs(self, plan: PilotExactTaskRemotePublicationPlan) -> list[Any]:
        owner, _repo = plan.repository.split("/", 1)
        root = self._repo_root(plan)
        query = urllib.parse.urlencode(
            {
                "state": "all",
                "head": f"{owner}:{plan.head_branch}",
                "base": plan.base_branch,
                "per_page": "100",
            },
            safe=":/",
        )
        value = self._api_json(path=f"{root}/pulls?{query}", method="GET")
        if not isinstance(value, list):
            raise PilotExactTaskRemotePublicationTransactionError(
                "GitHub pull-request verification response is invalid"
            )
        return value

    def _credential_git_config(
        self,
        *,
        ledger_root: Path,
        key: str,
    ) -> tuple[Path, bytes]:
        encoded = base64.b64encode(
            f"{self.credential.username}:{self.credential.token}".encode("ascii")
        ).decode("ascii")
        payload = (
            '[http "https://github.com/"]\n'
            f"\textraHeader = Authorization: Basic {encoded}\n"
        ).encode("ascii")
        path = ledger_root / f".{key}.publisher.gitconfig"
        try:
            create_once_file(path, payload, mode=0o600)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskRemotePublicationTransactionError(
                "ephemeral publisher Git credential config could not be created"
            ) from exc
        return path, payload

    def push_exact_commit(
        self,
        *,
        plan: PilotExactTaskRemotePublicationPlan,
        git_runner: TrustedGitRunner,
        workspace_root: Path,
        ledger_root: Path,
        transaction_key: str,
    ) -> str:
        self.validate_for(plan)
        if not isinstance(git_runner, TrustedGitRunner):
            raise PilotExactTaskRemotePublicationTransactionError(
                "trusted Git runner is required for exact publication"
            )
        workspace = Path(workspace_root)
        if (
            not workspace.is_absolute()
            or _has_linkish_component(workspace)
            or not workspace.is_dir()
        ):
            raise PilotExactTaskRemotePublicationTransactionError(
                "publisher workspace root is unsafe"
            )
        bare = ledger_root / f".{transaction_key}.publisher-bare"
        if bare.exists() or bare.is_symlink():
            raise PilotExactTaskRemotePublicationTransactionError(
                "publisher scratch repository already exists"
            )
        credential_config: Path | None = None
        try:
            git_runner.run(
                ("init", "--bare", "--quiet", os.fspath(bare)),
                cwd=ledger_root,
                maximum=4096,
                timeout_seconds=120,
            )
            source_git_dir_raw = git_runner.run(
                ("rev-parse", "--absolute-git-dir"),
                cwd=workspace,
                maximum=4096,
                timeout_seconds=120,
            ).decode("utf-8", errors="strict").strip()
            source_git_dir = Path(source_git_dir_raw)
            source_objects = source_git_dir / "objects"
            if (
                not source_git_dir.is_absolute()
                or _has_linkish_component(source_git_dir)
                or not source_git_dir.is_dir()
                or not source_objects.is_dir()
                or _has_linkish_component(source_objects)
            ):
                raise PilotExactTaskRemotePublicationTransactionError(
                    "source Git object directory is unsafe"
                )
            alternates = bare / "objects" / "info" / "alternates"
            create_once_file(
                alternates,
                (os.fspath(source_objects.resolve()) + "\n").encode("utf-8"),
                mode=0o600,
            )
            local_ref = "refs/heads/exact-publication-candidate"
            git_runner.run(
                ("update-ref", local_ref, plan.predicted_commit_sha, "0" * 40),
                cwd=bare,
                maximum=4096,
                timeout_seconds=120,
            )
            verified = git_runner.run(
                ("rev-parse", "--verify", local_ref),
                cwd=bare,
                maximum=128,
                timeout_seconds=120,
            ).decode("ascii", errors="strict").strip()
            if verified != plan.predicted_commit_sha:
                raise PilotExactTaskRemotePublicationTransactionError(
                    "publisher scratch ref does not equal exact commit"
                )
            credential_config, _payload = self._credential_git_config(
                ledger_root=ledger_root,
                key=transaction_key,
            )
            environment = git_runner.environment()
            environment["GIT_CONFIG_GLOBAL"] = os.fspath(credential_config)
            command = [
                os.fspath(git_runner.runtime.executable_path),
                "-c",
                "color.ui=false",
                "-c",
                "core.quotepath=false",
                "-c",
                f"core.hooksPath={os.fspath(git_runner._hooks)}",
                "-c",
                "protocol.allow=never",
                "-c",
                "protocol.https.allow=always",
                "-c",
                "http.followRedirects=false",
                "-c",
                "http.sslVerify=true",
                "-c",
                "gc.auto=0",
                "-c",
                "maintenance.auto=false",
                "-c",
                "push.recurseSubmodules=no",
                "push",
                "--porcelain",
                "--no-verify",
                f"--force-with-lease=refs/heads/{plan.head_branch}:",
                f"https://github.com/{plan.repository}.git",
                f"{local_ref}:refs/heads/{plan.head_branch}",
            ]
            git_runner.runtime.verify()
            git_runner._verify_isolation()
            try:
                result = run_bounded_subprocess(
                    command,
                    cwd=bare,
                    env=environment,
                    timeout_seconds=180,
                    max_output_bytes=256 * 1024,
                    stdout_prefix_bytes=256 * 1024,
                    stderr_prefix_bytes=256 * 1024,
                )
            except BoundedSubprocessError as exc:
                raise PilotExactTaskRemotePublicationTransactionError(
                    "exact GitHub push process boundary failed"
                ) from exc
            finally:
                git_runner.runtime.verify()
                git_runner._verify_isolation()
            if (
                result.timed_out
                or result.output_limit_exceeded
                or result.returncode != 0
                or result.stdout.truncated
                or result.stderr.truncated
            ):
                raise PilotExactTaskRemotePublicationTransactionError(
                    "exact GitHub push failed closed"
                )
            return hashlib.sha256(
                result.stdout.prefix + b"\0" + result.stderr.prefix
            ).hexdigest()
        finally:
            if credential_config is not None and credential_config.exists():
                try:
                    unlink_durable(credential_config)
                except Exception:
                    pass
            if bare.exists() and not bare.is_symlink():
                try:
                    shutil.rmtree(bare)
                    sync_directory(ledger_root)
                except Exception:
                    pass

    def observe_after_push(
        self,
        plan: PilotExactTaskRemotePublicationPlan,
    ) -> Mapping[str, Any]:
        base_sha = self._observe_ref(plan, plan.base_branch)
        head_sha = self._observe_ref(plan, plan.head_branch)
        pulls = self._matching_prs(plan)
        if (
            base_sha != plan.base_sha
            or head_sha != plan.predicted_commit_sha
            or pulls
        ):
            raise PilotExactTaskRemotePublicationTransactionError(
                "post-push GitHub state does not match exact publication intent"
            )
        return MappingProxyType(
            {
                "base_sha": base_sha,
                "head_sha": head_sha,
                "matching_pr_count": 0,
            }
        )

    def create_draft_pr(
        self,
        plan: PilotExactTaskRemotePublicationPlan,
    ) -> Mapping[str, Any]:
        root = self._repo_root(plan)
        value = self._api_json(
            path=f"{root}/pulls",
            method="POST",
            body={
                "title": plan.pr_title,
                "body": plan.pr_body,
                "head": plan.head_branch,
                "base": plan.base_branch,
                "draft": True,
                "maintainer_can_modify": False,
            },
        )
        return self._validate_pr(plan, value)

    def _validate_pr(
        self,
        plan: PilotExactTaskRemotePublicationPlan,
        value: Any,
    ) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise PilotExactTaskRemotePublicationTransactionError(
                "GitHub draft pull-request response is invalid"
            )
        number = value.get("number")
        head = value.get("head")
        base = value.get("base")
        if (
            isinstance(number, bool)
            or not isinstance(number, int)
            or number < 1
            or value.get("state") != "open"
            or value.get("draft") is not True
            or value.get("title") != plan.pr_title
            or value.get("body") != plan.pr_body
            or value.get("maintainer_can_modify") is not False
            or not isinstance(head, Mapping)
            or not isinstance(base, Mapping)
            or head.get("ref") != plan.head_branch
            or head.get("sha") != plan.predicted_commit_sha
            or base.get("ref") != plan.base_branch
            or base.get("sha") != plan.base_sha
        ):
            raise PilotExactTaskRemotePublicationTransactionError(
                "GitHub draft pull request does not match exact intent"
            )
        api_url = f"{_GITHUB_API_ROOT}{self._repo_root(plan)}/pulls/{number}"
        return MappingProxyType(
            {
                "number": number,
                "api_url": api_url,
            }
        )

    def verify_draft_pr(
        self,
        plan: PilotExactTaskRemotePublicationPlan,
        number: int,
    ) -> Mapping[str, Any]:
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise PilotExactTaskRemotePublicationTransactionError(
                "pull-request number is invalid"
            )
        root = self._repo_root(plan)
        value = self._api_json(path=f"{root}/pulls/{number}", method="GET")
        verified = self._validate_pr(plan, value)
        matching = self._matching_prs(plan)
        if len(matching) != 1:
            raise PilotExactTaskRemotePublicationTransactionError(
                "exact draft pull request is not unique"
            )
        matched = self._validate_pr(plan, matching[0])
        if matched["number"] != number:
            raise PilotExactTaskRemotePublicationTransactionError(
                "matching pull-request identity changed"
            )
        if self._observe_ref(plan, plan.base_branch) != plan.base_sha:
            raise PilotExactTaskRemotePublicationTransactionError(
                "remote main moved after draft pull-request creation"
            )
        if self._observe_ref(plan, plan.head_branch) != plan.predicted_commit_sha:
            raise PilotExactTaskRemotePublicationTransactionError(
                "remote publication branch moved after draft pull-request creation"
            )
        return verified


def _live_registry():
    records: dict[
        int,
        tuple[
            int,
            str,
            weakref.ReferenceType[Any],
            weakref.ReferenceType[Any],
            Path,
            bytes,
            Path,
            bytes,
            Path,
            bytes,
            Path,
            bytes,
        ],
    ] = {}

    def mark(
        receipt: Any,
        authorization: PilotExactTaskRemotePublicationAuthorizationReceipt,
        *,
        final_path: Path,
        final_payload: bytes,
        lock_path: Path,
        lock_payload: bytes,
        pushed_path: Path,
        pushed_payload: bytes,
        pr_path: Path,
        pr_payload: bytes,
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
            pushed_path,
            pushed_payload,
            pr_path,
            pr_payload,
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
            pushed_path,
            pushed_payload,
            pr_path,
            pr_payload,
        ) = entry
        authorization = authorization_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or authorization is None
            or receipt.sha256 != digest
            or receipt.remote_publication_authorization_sha256
            != authorization.sha256
            or _read_bound_file(final_path) != final_payload
            or _read_bound_file(lock_path) != lock_payload
            or _read_bound_file(pushed_path) != pushed_payload
            or _read_bound_file(pr_path) != pr_payload
        ):
            return None
        inputs = auth_boundary._get_live_remote_publication_authorization_inputs(
            authorization
        )
        if inputs is None:
            return None
        result = dict(inputs)
        result["remote_publication_authorization"] = authorization
        return MappingProxyType(result)

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_remote_publication_transaction_authenticated,
    _get_live_remote_publication_transaction_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskRemotePublicationTransactionReceipt:
    ledger_root_path_sha256: str
    transaction_key_sha256: str
    remote_publication_authorization_sha256: str
    remote_state_observation_sha256: str
    remote_publication_plan_sha256: str
    integration_readiness_sha256: str
    remote_target_config_sha256: str
    remote_repository_identity_sha256: str
    pr_intent_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    publisher_credential_id: str
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    push_result_sha256: str
    task_id: str
    repository: str
    repository_id: str
    provider: str
    host: str
    remote_name: str
    base_branch: str
    head_branch: str
    exact_task_base_sha: str
    predicted_commit_sha: str
    pull_request_number: int
    pull_request_api_url: str
    consumed_at_utc: str
    pushed_at_utc: str
    draft_pr_created_at_utc: str
    completed_at_utc: str
    host_transaction_guard_committed: bool = True
    remote_publication_authorization_authenticated: bool = True
    remote_publication_authorization_consumed: bool = True
    exact_lane_revalidated_after_consumption: bool = True
    remote_branch_created: bool = True
    exact_commit_pushed: bool = True
    draft_pr_created: bool = True
    draft_pr_verified: bool = True
    remote_write_performed: bool = True
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    product_pilot_started: bool = False
    draft: bool = True
    maintainer_can_modify: bool = False
    ledger_scope: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_TRANSACTION_LEDGER_SCOPE
    authority: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_TRANSACTION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_TRANSACTION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_REMOTE_PUBLICATION_TRANSACTION_SCHEMA:
            raise PilotExactTaskRemotePublicationTransactionError(
                "remote publication transaction schema is unsupported"
            )
        if self.ledger_scope != PILOT_EXACT_TASK_REMOTE_PUBLICATION_TRANSACTION_LEDGER_SCOPE:
            raise PilotExactTaskRemotePublicationTransactionError(
                "remote publication transaction ledger scope is unsupported"
            )
        for name in (
            "ledger_root_path_sha256",
            "transaction_key_sha256",
            "remote_publication_authorization_sha256",
            "remote_state_observation_sha256",
            "remote_publication_plan_sha256",
            "integration_readiness_sha256",
            "remote_target_config_sha256",
            "remote_repository_identity_sha256",
            "pr_intent_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
            "push_result_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        if self.transaction_key_sha256 != self.execution_nonce_sha256:
            raise PilotExactTaskRemotePublicationTransactionError(
                "remote publication transaction key must equal execution nonce"
            )
        for name in ("exact_task_base_sha", "predicted_commit_sha"):
            _hex40(getattr(self, name), name=name)
        if (
            not isinstance(self.publisher_credential_id, str)
            or _CREDENTIAL_ID.fullmatch(self.publisher_credential_id) is None
        ):
            raise PilotExactTaskRemotePublicationTransactionError(
                "publisher credential identity is invalid"
            )
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise PilotExactTaskRemotePublicationTransactionError("task_id is invalid")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
        ):
            raise PilotExactTaskRemotePublicationTransactionError(
                "repository is invalid"
            )
        if (
            not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskRemotePublicationTransactionError(
                "repository_id is invalid"
            )
        if self.provider != "github" or self.host != "github.com":
            raise PilotExactTaskRemotePublicationTransactionError(
                "provider/host is unsupported"
            )
        if self.remote_name != "origin" or self.base_branch != "main":
            raise PilotExactTaskRemotePublicationTransactionError(
                "remote/base target is unsupported"
            )
        _branch(self.head_branch, name="head_branch")
        if (
            isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
        ):
            raise PilotExactTaskRemotePublicationTransactionError(
                "pull_request_number is invalid"
            )
        expected_url = (
            f"{_GITHUB_API_ROOT}/repos/{self.repository}/pulls/"
            f"{self.pull_request_number}"
        )
        if self.pull_request_api_url != expected_url:
            raise PilotExactTaskRemotePublicationTransactionError(
                "pull_request_api_url is inconsistent"
            )
        consumed = _utc(self.consumed_at_utc, name="consumed_at_utc")
        pushed = _utc(self.pushed_at_utc, name="pushed_at_utc")
        created = _utc(
            self.draft_pr_created_at_utc,
            name="draft_pr_created_at_utc",
        )
        completed = _utc(self.completed_at_utc, name="completed_at_utc")
        if not (consumed <= pushed <= created <= completed):
            raise PilotExactTaskRemotePublicationTransactionError(
                "remote publication transaction timestamps are inconsistent"
            )
        required_true = (
            "host_transaction_guard_committed",
            "remote_publication_authorization_authenticated",
            "remote_publication_authorization_consumed",
            "exact_lane_revalidated_after_consumption",
            "remote_branch_created",
            "exact_commit_pushed",
            "draft_pr_created",
            "draft_pr_verified",
            "remote_write_performed",
            "draft",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskRemotePublicationTransactionError(
                "remote publication transaction evidence is incomplete"
            )
        forced_false = (
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "product_pilot_started",
            "maintainer_can_modify",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskRemotePublicationTransactionError(
                "completed publication transaction cannot retain higher authority"
            )
        if self.authority != PILOT_EXACT_TASK_REMOTE_PUBLICATION_TRANSACTION_AUTHORITY:
            raise PilotExactTaskRemotePublicationTransactionError(
                "remote publication transaction authority is unsupported"
            )

    @property
    def transaction_authenticated(self) -> bool:
        return _get_live_remote_publication_transaction_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(
        cls,
        value: Any,
    ) -> "PilotExactTaskRemotePublicationTransactionReceipt":
        if not isinstance(value, Mapping):
            raise PilotExactTaskRemotePublicationTransactionError(
                "remote publication transaction receipt must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskRemotePublicationTransactionError(
                "remote publication transaction fields mismatch"
            )
        return cls(**dict(value))

    @classmethod
    def from_json(
        cls,
        text: str,
    ) -> "PilotExactTaskRemotePublicationTransactionReceipt":
        try:
            return cls.from_mapping(json.loads(text))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise PilotExactTaskRemotePublicationTransactionError(
                "remote publication transaction JSON is invalid"
            ) from exc

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskRemotePublicationTransactionLedger:
    """Permanent one-shot transaction state keyed by original execution nonce."""

    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path, Path, Path]:
        digest = _hex64(key, name="transaction_key_sha256")
        return (
            self.root / f"{digest}.json",
            self.root / f".{digest}.lock",
            self.root / f".{digest}.pushed.json",
            self.root / f".{digest}.draft-pr.json",
        )

    def acquire(
        self,
        *,
        authorization: PilotExactTaskRemotePublicationAuthorizationReceipt,
        plan: PilotExactTaskRemotePublicationPlan,
    ) -> bytes:
        key = authorization.execution_nonce_sha256
        final, lock, pushed, pr = self._paths(key)
        if any(path.exists() or path.is_symlink() for path in (final, lock, pushed, pr)):
            raise PilotExactTaskRemotePublicationTransactionError(
                "exact execution nonce already has remote transaction state or needs recovery"
            )
        payload = _canonical(
            {
                "schema": (
                    "kaliv-rsi-dc-l16-exact-task-remote-publication-transaction-lock/v1"
                ),
                "ledger_scope": PILOT_EXACT_TASK_REMOTE_PUBLICATION_TRANSACTION_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "transaction_key_sha256": key,
                "remote_publication_authorization_sha256": authorization.sha256,
                "remote_state_observation_sha256": authorization.remote_state_observation_sha256,
                "remote_publication_plan_sha256": plan.sha256,
                "pr_intent_sha256": plan.pr_intent_sha256,
                "repository": plan.repository,
                "repository_id": plan.repository_id,
                "base_branch": plan.base_branch,
                "head_branch": plan.head_branch,
                "exact_task_base_sha": plan.base_sha,
                "predicted_commit_sha": plan.predicted_commit_sha,
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskRemotePublicationTransactionError(
                "remote transaction authority could not be durably consumed"
            ) from exc
        return payload

    def mark_pushed(
        self,
        *,
        authorization: PilotExactTaskRemotePublicationAuthorizationReceipt,
        plan: PilotExactTaskRemotePublicationPlan,
        push_result_sha256: str,
        pushed_at_utc: str,
        lock_payload: bytes,
    ) -> bytes:
        _hex64(push_result_sha256, name="push_result_sha256")
        _utc(pushed_at_utc, name="pushed_at_utc")
        _final, lock, pushed, _pr = self._paths(authorization.execution_nonce_sha256)
        if _read_bound_file(lock) != lock_payload:
            raise PilotExactTaskRemotePublicationTransactionError(
                "remote transaction lock changed before push marker"
            )
        payload = _canonical(
            {
                "schema": (
                    "kaliv-rsi-dc-l16-exact-task-remote-publication-pushed-marker/v1"
                ),
                "transaction_key_sha256": authorization.execution_nonce_sha256,
                "remote_publication_authorization_sha256": authorization.sha256,
                "remote_publication_plan_sha256": plan.sha256,
                "predicted_commit_sha": plan.predicted_commit_sha,
                "head_branch": plan.head_branch,
                "push_result_sha256": push_result_sha256,
                "pushed_at_utc": pushed_at_utc,
            }
        ).encode("utf-8")
        try:
            create_once_file(pushed, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskRemotePublicationTransactionError(
                "successful exact push could not be durably marked"
            ) from exc
        return payload

    def mark_pr(
        self,
        *,
        authorization: PilotExactTaskRemotePublicationAuthorizationReceipt,
        plan: PilotExactTaskRemotePublicationPlan,
        pull_request_number: int,
        pull_request_api_url: str,
        created_at_utc: str,
        lock_payload: bytes,
        pushed_payload: bytes,
    ) -> bytes:
        _utc(created_at_utc, name="draft_pr_created_at_utc")
        final, lock, pushed, pr = self._paths(authorization.execution_nonce_sha256)
        if final.exists() or final.is_symlink():
            raise PilotExactTaskRemotePublicationTransactionError(
                "remote transaction final receipt already exists"
            )
        if (
            _read_bound_file(lock) != lock_payload
            or _read_bound_file(pushed) != pushed_payload
        ):
            raise PilotExactTaskRemotePublicationTransactionError(
                "remote transaction evidence changed before PR marker"
            )
        payload = _canonical(
            {
                "schema": (
                    "kaliv-rsi-dc-l16-exact-task-remote-publication-draft-pr-marker/v1"
                ),
                "transaction_key_sha256": authorization.execution_nonce_sha256,
                "remote_publication_authorization_sha256": authorization.sha256,
                "remote_publication_plan_sha256": plan.sha256,
                "pull_request_number": pull_request_number,
                "pull_request_api_url": pull_request_api_url,
                "draft": True,
                "maintainer_can_modify": False,
                "created_at_utc": created_at_utc,
            }
        ).encode("utf-8")
        try:
            create_once_file(pr, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskRemotePublicationTransactionError(
                "successful draft pull request could not be durably marked"
            ) from exc
        return payload

    def commit(
        self,
        *,
        receipt: PilotExactTaskRemotePublicationTransactionReceipt,
        authorization: PilotExactTaskRemotePublicationAuthorizationReceipt,
        lock_payload: bytes,
        pushed_payload: bytes,
        pr_payload: bytes,
    ) -> PilotExactTaskRemotePublicationTransactionReceipt:
        final, lock, pushed, pr = self._paths(receipt.transaction_key_sha256)
        if final.exists() or final.is_symlink():
            raise PilotExactTaskRemotePublicationTransactionError(
                "remote transaction receipt already exists"
            )
        if (
            _read_bound_file(lock) != lock_payload
            or _read_bound_file(pushed) != pushed_payload
            or _read_bound_file(pr) != pr_payload
        ):
            raise PilotExactTaskRemotePublicationTransactionError(
                "remote transaction durable evidence changed before finalization"
            )
        payload = receipt.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PilotExactTaskRemotePublicationTransactionError(
                "remote transaction receipt exceeds byte bound"
            )
        try:
            create_once_file(final, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskRemotePublicationTransactionError(
                "remote transaction final receipt could not be durably published"
            ) from exc
        parsed = PilotExactTaskRemotePublicationTransactionReceipt.from_mapping(
            json.loads(payload.decode("utf-8", errors="strict"))
        )
        _mark_remote_publication_transaction_authenticated(
            parsed,
            authorization,
            final_path=final,
            final_payload=payload,
            lock_path=lock,
            lock_payload=lock_payload,
            pushed_path=pushed,
            pushed_payload=pushed_payload,
            pr_path=pr,
            pr_payload=pr_payload,
        )
        if parsed.transaction_authenticated is not True:
            raise PilotExactTaskRemotePublicationTransactionError(
                "remote transaction lost live provenance"
            )
        return parsed


def _execute_verified_pilot_exact_task_remote_publication(
    *,
    remote_publication_authorization: PilotExactTaskRemotePublicationAuthorizationReceipt,
    ledger: _PilotExactTaskRemotePublicationTransactionLedger,
    observer: Any,
    transport: Any,
    now_provider: Callable[[], str],
) -> PilotExactTaskRemotePublicationTransactionReceipt:
    authorization, plan, observation, inputs = _require_live_authorization(
        remote_publication_authorization
    )
    if type(ledger) is not _PilotExactTaskRemotePublicationTransactionLedger:
        raise PilotExactTaskRemotePublicationTransactionError(
            "remote publication transaction ledger is required"
        )
    if transport is None or not callable(getattr(transport, "validate_for", None)):
        raise PilotExactTaskRemotePublicationTransactionError(
            "exact publisher transport is required"
        )
    transport.validate_for(plan)
    credential_id = getattr(transport, "credential_id", None)
    credential_config_sha256 = getattr(
        transport, "credential_config_sha256", None
    )
    credential_path_sha256 = getattr(transport, "credential_path_sha256", None)
    if (
        not isinstance(credential_id, str)
        or _CREDENTIAL_ID.fullmatch(credential_id) is None
    ):
        raise PilotExactTaskRemotePublicationTransactionError(
            "publisher transport credential identity is invalid"
        )
    _hex64(
        credential_config_sha256,
        name="publisher_credential_config_sha256",
    )
    _hex64(
        credential_path_sha256,
        name="publisher_credential_path_sha256",
    )

    _fresh_authorized_lane(
        authorization=authorization,
        plan=plan,
        observation=observation,
        inputs=inputs,
        observer=observer,
    )
    consumed_at = now_provider()
    if _utc(consumed_at, name="consumed_at_utc") < _utc(
        authorization.authorized_at_utc,
        name="authorized_at_utc",
    ):
        raise PilotExactTaskRemotePublicationTransactionError(
            "system clock moved backwards after ADR-DC-049 authorization"
        )

    lock_payload = ledger.acquire(authorization=authorization, plan=plan)

    # The one-shot authority is now durably consumed. Any later failure burns the
    # transaction slot and must be handled by a separate recovery boundary.
    _fresh_authorized_lane(
        authorization=authorization,
        plan=plan,
        observation=observation,
        inputs=inputs,
        observer=observer,
    )

    git_runner = inputs.get("git_runner")
    workspace_root = inputs.get("workspace_root")
    if not isinstance(git_runner, TrustedGitRunner) or workspace_root is None:
        raise PilotExactTaskRemotePublicationTransactionError(
            "live exact Git workspace is unavailable for publication"
        )
    push_result_sha = transport.push_exact_commit(
        plan=plan,
        git_runner=git_runner,
        workspace_root=Path(workspace_root),
        ledger_root=ledger.root,
        transaction_key=authorization.execution_nonce_sha256,
    )
    _hex64(push_result_sha, name="push_result_sha256")
    pushed_state = transport.observe_after_push(plan)
    if (
        not isinstance(pushed_state, Mapping)
        or pushed_state.get("base_sha") != plan.base_sha
        or pushed_state.get("head_sha") != plan.predicted_commit_sha
        or pushed_state.get("matching_pr_count") != 0
    ):
        raise PilotExactTaskRemotePublicationTransactionError(
            "post-push exact state verification failed"
        )
    pushed_at = now_provider()
    if _utc(pushed_at, name="pushed_at_utc") < _utc(
        consumed_at,
        name="consumed_at_utc",
    ):
        raise PilotExactTaskRemotePublicationTransactionError(
            "system clock moved backwards after exact push"
        )
    pushed_payload = ledger.mark_pushed(
        authorization=authorization,
        plan=plan,
        push_result_sha256=push_result_sha,
        pushed_at_utc=pushed_at,
        lock_payload=lock_payload,
    )

    pr = transport.create_draft_pr(plan)
    if not isinstance(pr, Mapping):
        raise PilotExactTaskRemotePublicationTransactionError(
            "draft pull-request creation result is invalid"
        )
    number = pr.get("number")
    api_url = pr.get("api_url")
    if (
        isinstance(number, bool)
        or not isinstance(number, int)
        or number < 1
        or not isinstance(api_url, str)
    ):
        raise PilotExactTaskRemotePublicationTransactionError(
            "draft pull-request identity is invalid"
        )
    verified_pr = transport.verify_draft_pr(plan, number)
    if (
        not isinstance(verified_pr, Mapping)
        or verified_pr.get("number") != number
        or verified_pr.get("api_url") != api_url
    ):
        raise PilotExactTaskRemotePublicationTransactionError(
            "draft pull-request verification failed"
        )
    pr_created_at = now_provider()
    if _utc(pr_created_at, name="draft_pr_created_at_utc") < _utc(
        pushed_at,
        name="pushed_at_utc",
    ):
        raise PilotExactTaskRemotePublicationTransactionError(
            "system clock moved backwards after draft PR creation"
        )
    pr_payload = ledger.mark_pr(
        authorization=authorization,
        plan=plan,
        pull_request_number=number,
        pull_request_api_url=api_url,
        created_at_utc=pr_created_at,
        lock_payload=lock_payload,
        pushed_payload=pushed_payload,
    )

    completed_at = now_provider()
    if _utc(completed_at, name="completed_at_utc") < _utc(
        pr_created_at,
        name="draft_pr_created_at_utc",
    ):
        raise PilotExactTaskRemotePublicationTransactionError(
            "system clock moved backwards during transaction finalization"
        )
    receipt = PilotExactTaskRemotePublicationTransactionReceipt(
        ledger_root_path_sha256=ledger.root_sha256,
        transaction_key_sha256=authorization.execution_nonce_sha256,
        remote_publication_authorization_sha256=authorization.sha256,
        remote_state_observation_sha256=authorization.remote_state_observation_sha256,
        remote_publication_plan_sha256=plan.sha256,
        integration_readiness_sha256=plan.integration_readiness_sha256,
        remote_target_config_sha256=plan.remote_target_config_sha256,
        remote_repository_identity_sha256=plan.remote_repository_identity_sha256,
        pr_intent_sha256=plan.pr_intent_sha256,
        execution_nonce_sha256=plan.execution_nonce_sha256,
        development_task_sha256=plan.development_task_sha256,
        candidate_patch_sha256=plan.candidate_patch_sha256,
        publisher_credential_id=credential_id,
        publisher_credential_config_sha256=credential_config_sha256,
        publisher_credential_path_sha256=credential_path_sha256,
        push_result_sha256=push_result_sha,
        task_id=plan.task_id,
        repository=plan.repository,
        repository_id=plan.repository_id,
        provider=plan.provider,
        host=plan.host,
        remote_name=plan.remote_name,
        base_branch=plan.base_branch,
        head_branch=plan.head_branch,
        exact_task_base_sha=plan.base_sha,
        predicted_commit_sha=plan.predicted_commit_sha,
        pull_request_number=number,
        pull_request_api_url=api_url,
        consumed_at_utc=consumed_at,
        pushed_at_utc=pushed_at,
        draft_pr_created_at_utc=pr_created_at,
        completed_at_utc=completed_at,
    )
    return ledger.commit(
        receipt=receipt,
        authorization=authorization,
        lock_payload=lock_payload,
        pushed_payload=pushed_payload,
        pr_payload=pr_payload,
    )


def _canonical_ledger_root() -> Path:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_LEDGER
        elif os.name == "nt":
            path = _WINDOWS_LEDGER
        else:
            raise PilotExactTaskRemotePublicationTransactionError(
                "remote publication transaction is unsupported on this platform"
            )
        return _require_host_controlled_ledger_root(path)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskRemotePublicationTransactionError(
            "canonical remote transaction ledger is not host-admin controlled"
        ) from exc


def execute_pilot_exact_task_remote_publication(
    remote_publication_authorization: PilotExactTaskRemotePublicationAuthorizationReceipt,
) -> PilotExactTaskRemotePublicationTransactionReceipt:
    """Execute exactly one ADR-DC-050 branch push plus draft-PR transaction."""
    try:
        root = _canonical_ledger_root()
        credential, credential_digest, credential_path = _canonical_credential()
        transport = _GitHubPublisherTransport(
            credential=credential,
            credential_config_sha256=credential_digest,
            credential_path=credential_path,
        )
        ledger = _PilotExactTaskRemotePublicationTransactionLedger(root)
        return _execute_verified_pilot_exact_task_remote_publication(
            remote_publication_authorization=remote_publication_authorization,
            ledger=ledger,
            observer=observation_boundary._GitHubReadOnlyObserver(),
            transport=transport,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskRemotePublicationTransactionError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskRemotePublicationTransactionError(
            "host-controlled exact remote publication failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_TRANSACTION_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_TRANSACTION_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_TRANSACTION_LEDGER_SCOPE",
    "PILOT_EXACT_TASK_GITHUB_PUBLISHER_CREDENTIAL_SCHEMA",
    "PilotExactTaskRemotePublicationTransactionError",
    "PilotExactTaskRemotePublicationTransactionReceipt",
    "execute_pilot_exact_task_remote_publication",
]
