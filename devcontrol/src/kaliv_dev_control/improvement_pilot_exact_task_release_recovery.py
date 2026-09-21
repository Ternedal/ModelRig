"""ADR-DC-068 dual-authorized recovery for interrupted exact release transactions.

This boundary reconstructs one consumed ADR-DC-067 release transaction from
durable ADR-DC-066/067 evidence and current GitHub state.

It never recreates a missing tag. A clear lock-only lane remains manual. When
the exact tag already exists but the draft release is absent, two new detached
Ed25519 approvals may authorize exactly one missing-release POST. When the exact
tag and exact draft release already exist, recovery finalizes write-free.

Parent ADR-DC-067 markers are never backfilled. Recovery has its own create-once
ledger and grants no release, deploy or production authority after completion.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
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
from . import improvement_pilot_exact_task_release_authorization as auth_boundary
from . import improvement_pilot_exact_task_release_plan as plan_boundary
from . import improvement_pilot_exact_task_release_state_observation as state_boundary
from . import improvement_pilot_exact_task_release_transaction as tx_boundary
from . import improvement_pilot_exact_task_remote_publication_transaction as publication_tx_boundary
from .improvement_pilot_exact_task_release_authorization import (
    PILOT_EXACT_TASK_RELEASE_AUTHORIZATION_AUTHORITY,
    PilotExactTaskReleaseAuthorizationReceipt,
)
from .improvement_pilot_exact_task_remote_publication_transaction import (
    PilotExactTaskGitHubPublisherCredential,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_RELEASE_RECOVERY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-release-recovery-receipt/v1"
)
PILOT_EXACT_TASK_RELEASE_RECOVERY_AUTHORITY = (
    "dual-reviewed-dc-l16-exact-release-recovery-only"
)
PILOT_EXACT_TASK_RELEASE_RECOVERY_SCOPE = (
    "exact-tag-draft-release-recovery-finalization-only-v1"
)
PILOT_EXACT_TASK_RELEASE_RECOVERY_PAYLOAD_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-release-recovery-authorization-payload/v1"
)
PILOT_EXACT_TASK_RELEASE_RECOVERY_LEDGER_SCOPE = "canonical-host-local-v1"
_RECOVERY_POLICY_DOMAIN = b"kaliv-rsi-dc-l16-exact-task-release-recovery-policy/v1\x00"
_MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
_MAX_AUTH_SECONDS = 10 * 60
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_BRANCH = re.compile(r"^(?![./])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}$")
_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/rsi-pilot-exact-task-release-recovery-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-release-recovery-ledger-v1"
)

PILOT_EXACT_TASK_RELEASE_RECOVERY_POLICY = (
    "Recover only one previously consumed ADR-DC-067 release transaction nonce.",
    "Never recreate or retry the deterministic tag.",
    "A consumed lane with no remote tag remains manual and fail-closed.",
    "Permit one missing draft-release POST only when the exact tag already exists.",
    "Permit write-free finalization when the exact tag and exact draft release exist.",
    "Require durable ADR-DC-066 authorization and ADR-DC-067 lock/markers to agree.",
    "Require two independent detached Ed25519 signatures over exact recovery state.",
    "Durably consume recovery authority before any recovery release write.",
    "Never backfill ADR-DC-067 markers.",
    "Never make the nonce reusable or grant release, deploy or production authority.",
)


class PilotExactTaskReleaseRecoveryError(ValueError):
    """Interrupted release state is ambiguous, unauthenticated or unsafe."""


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
        raise PilotExactTaskReleaseRecoveryError(
            "release recovery evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskReleaseRecoveryError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskReleaseRecoveryError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskReleaseRecoveryError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskReleaseRecoveryError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


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
        raise PilotExactTaskReleaseRecoveryError(f"{name} is unavailable")
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskReleaseRecoveryError(f"{name} is invalid JSON") from exc
    if not isinstance(raw, dict) or _canonical(raw).encode("utf-8") != payload:
        raise PilotExactTaskReleaseRecoveryError(f"{name} is not canonical JSON")
    return raw, payload


def _payload_sha256(payload: bytes) -> str:
    if not isinstance(payload, bytes) or not payload:
        raise PilotExactTaskReleaseRecoveryError("durable recovery payload is missing")
    return hashlib.sha256(payload).hexdigest()


def pilot_exact_task_release_recovery_policy_sha256() -> str:
    payload = json.dumps(
        list(PILOT_EXACT_TASK_RELEASE_RECOVERY_POLICY),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(_RECOVERY_POLICY_DOMAIN + payload).hexdigest()


@dataclass(frozen=True, slots=True)
class _ReleaseProjection:
    repository: str
    repository_id: str
    tag_name: str
    tag_target_sha: str
    release_name: str
    release_body: str


@dataclass(frozen=True, slots=True)
class _ReleaseRecoveryRemoteState:
    repository: str
    repository_id: str
    tag_state: str
    tag_target_sha: str | None
    release_state: str
    release_id: int | None
    release_node_id_sha256: str | None
    remote_state_class: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskReleaseRecoveryError(
                "remote release recovery repository identity is invalid"
            )
        if self.remote_state_class == "clear":
            if (
                self.tag_state != "absent"
                or self.tag_target_sha is not None
                or self.release_state != "absent"
                or self.release_id is not None
                or self.release_node_id_sha256 is not None
            ):
                raise PilotExactTaskReleaseRecoveryError(
                    "clear release recovery state is malformed"
                )
        elif self.remote_state_class == "tag_only":
            if (
                self.tag_state != "exact"
                or self.tag_target_sha is None
                or self.release_state != "absent"
                or self.release_id is not None
                or self.release_node_id_sha256 is not None
            ):
                raise PilotExactTaskReleaseRecoveryError(
                    "tag-only release recovery state is malformed"
                )
            _hex40(self.tag_target_sha, name="tag_target_sha")
        elif self.remote_state_class == "exact_existing":
            if (
                self.tag_state != "exact"
                or self.tag_target_sha is None
                or self.release_state != "exact-draft"
                or isinstance(self.release_id, bool)
                or not isinstance(self.release_id, int)
                or self.release_id < 1
                or self.release_node_id_sha256 is None
            ):
                raise PilotExactTaskReleaseRecoveryError(
                    "exact-existing release recovery state is malformed"
                )
            _hex40(self.tag_target_sha, name="tag_target_sha")
            _hex64(
                self.release_node_id_sha256,
                name="release_node_id_sha256",
            )
        else:
            raise PilotExactTaskReleaseRecoveryError(
                "remote release recovery state class is unsupported"
            )

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            _canonical(self.to_dict()).encode("utf-8")
        ).hexdigest()


class _GitHubReleaseRecoveryTransport:
    """Credential-bound GET observer plus one exact missing-release POST."""

    def __init__(
        self,
        *,
        credential: PilotExactTaskGitHubPublisherCredential,
        credential_config_sha256: str,
        credential_path: Path,
    ) -> None:
        if type(credential) is not PilotExactTaskGitHubPublisherCredential:
            raise PilotExactTaskReleaseRecoveryError(
                "exact publisher credential is required"
            )
        self.credential_config_sha256 = _hex64(
            credential_config_sha256,
            name="credential_config_sha256",
        )
        self.credential_path = Path(credential_path)
        if (
            not self.credential_path.is_absolute()
            or _has_linkish_component(self.credential_path)
        ):
            raise PilotExactTaskReleaseRecoveryError(
                "publisher credential path is unsafe"
            )
        self.credential_path_sha256 = _path_sha256(self.credential_path)
        self._observer = state_boundary._GitHubReleaseStateObserver(
            credential=credential,
            credential_config_sha256=credential_config_sha256,
            credential_path=credential_path,
        )
        self._writer = tx_boundary._GitHubExactReleaseTransactionTransport(
            credential=credential,
            credential_config_sha256=credential_config_sha256,
            credential_path=credential_path,
        )

    @staticmethod
    def _projection(
        authorization: PilotExactTaskReleaseAuthorizationReceipt,
    ) -> _ReleaseProjection:
        body = plan_boundary._release_body_fields(
            repository=authorization.repository,
            release_base_branch=authorization.release_base_branch,
            merge_commit_sha=authorization.merge_commit_sha,
            development_task_sha256=authorization.development_task_sha256,
            candidate_patch_sha256=authorization.candidate_patch_sha256,
            release_readiness_evaluation_sha256=(
                authorization.release_readiness_evaluation_sha256
            ),
        )
        if (
            hashlib.sha256(body.encode("utf-8")).hexdigest()
            != authorization.release_body_sha256
        ):
            raise PilotExactTaskReleaseRecoveryError(
                "deterministic release body differs from durable authorization"
            )
        return _ReleaseProjection(
            repository=authorization.repository,
            repository_id=authorization.repository_id,
            tag_name=authorization.tag_name,
            tag_target_sha=authorization.tag_target_sha,
            release_name=authorization.release_name,
            release_body=body,
        )

    def observe(
        self,
        authorization: PilotExactTaskReleaseAuthorizationReceipt,
    ) -> _ReleaseRecoveryRemoteState:
        plan = self._projection(authorization)
        if (
            self._observer.credential.repository != authorization.repository
            or self._observer.credential.repository_id != authorization.repository_id
        ):
            raise PilotExactTaskReleaseRecoveryError(
                "publisher credential is not bound to exact release repository"
            )
        root = self._observer._repo_root(plan)
        status, repo = self._observer._get_json_or_404(plan=plan, path=root)
        if (
            status != 200
            or not isinstance(repo, Mapping)
            or str(repo.get("id")) != authorization.repository_id
            or repo.get("full_name") != authorization.repository
        ):
            raise PilotExactTaskReleaseRecoveryError(
                "GitHub repository identity differs from release authorization"
            )
        try:
            tag_state, tag_target = self._observer._observe_tag(plan)
            release = self._observer._observe_release(plan)
        except Exception as exc:
            raise PilotExactTaskReleaseRecoveryError(
                "GitHub release recovery observation failed closed"
            ) from exc
        if tag_state == "absent" and release is None:
            return _ReleaseRecoveryRemoteState(
                repository=authorization.repository,
                repository_id=authorization.repository_id,
                tag_state="absent",
                tag_target_sha=None,
                release_state="absent",
                release_id=None,
                release_node_id_sha256=None,
                remote_state_class="clear",
            )
        if tag_state == "exact" and release is None:
            return _ReleaseRecoveryRemoteState(
                repository=authorization.repository,
                repository_id=authorization.repository_id,
                tag_state="exact",
                tag_target_sha=authorization.tag_target_sha,
                release_state="absent",
                release_id=None,
                release_node_id_sha256=None,
                remote_state_class="tag_only",
            )
        if tag_state == "exact" and release is not None:
            return _ReleaseRecoveryRemoteState(
                repository=authorization.repository,
                repository_id=authorization.repository_id,
                tag_state="exact",
                tag_target_sha=authorization.tag_target_sha,
                release_state="exact-draft",
                release_id=release["release_id"],
                release_node_id_sha256=release["release_node_id_sha256"],
                remote_state_class="exact_existing",
            )
        raise PilotExactTaskReleaseRecoveryError(
            "remote release state is unsafe for recovery"
        )

    def create_release(
        self,
        authorization: PilotExactTaskReleaseAuthorizationReceipt,
    ) -> tuple[int, str]:
        plan = self._projection(authorization)
        return self._writer.create_release(
            authorization,
            release_body=plan.release_body,
        )


@dataclass(frozen=True, slots=True)
class PilotExactTaskReleaseRecoveryState:
    transaction_key_sha256: str
    release_authorization_sha256: str
    release_authorization_payload_sha256: str
    release_state_observation_sha256: str
    release_plan_sha256: str
    release_readiness_evaluation_sha256: str
    release_intent_sha256: str
    original_remote_release_state_sha256: str
    release_authorization_config_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    upstream_merge_transaction_lock_sha256: str
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    transaction_lock_sha256: str
    tag_marker_sha256: str | None
    release_marker_sha256: str | None
    durable_phase: str
    repository: str
    repository_id: str
    release_base_branch: str
    merge_commit_sha: str
    release_version: str
    tag_name: str
    tag_target_sha: str
    release_name: str
    release_body_sha256: str
    release_id: int | None
    release_node_id_sha256: str | None
    remote_release_state_sha256: str
    remote_state_class: str
    action_required: str
    manual_intervention_required: bool
    remote_write_required: bool
    observed_at_utc: str

    def __post_init__(self) -> None:
        for name in (
            "transaction_key_sha256",
            "release_authorization_sha256",
            "release_authorization_payload_sha256",
            "release_state_observation_sha256",
            "release_plan_sha256",
            "release_readiness_evaluation_sha256",
            "release_intent_sha256",
            "original_remote_release_state_sha256",
            "release_authorization_config_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "pr_intent_sha256",
            "upstream_merge_transaction_lock_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
            "transaction_lock_sha256",
            "remote_release_state_sha256",
            "release_body_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("tag_marker_sha256", "release_marker_sha256"):
            value = getattr(self, name)
            if value is not None:
                _hex64(value, name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        _hex40(self.tag_target_sha, name="tag_target_sha")
        if (
            self.transaction_key_sha256 != self.execution_nonce_sha256
            or self.tag_target_sha != self.merge_commit_sha
            or self.durable_phase not in {"lock_only", "tag_marked", "release_marked"}
            or self.remote_state_class not in {"clear", "tag_only", "exact_existing"}
        ):
            raise PilotExactTaskReleaseRecoveryError(
                "release recovery state identity/classification is invalid"
            )
        if self.durable_phase == "lock_only":
            if self.tag_marker_sha256 is not None or self.release_marker_sha256 is not None:
                raise PilotExactTaskReleaseRecoveryError(
                    "lock-only recovery state carries phase markers"
                )
        elif self.durable_phase == "tag_marked":
            if self.tag_marker_sha256 is None or self.release_marker_sha256 is not None:
                raise PilotExactTaskReleaseRecoveryError(
                    "tag-marked recovery state markers are inconsistent"
                )
        else:
            if self.tag_marker_sha256 is None or self.release_marker_sha256 is None:
                raise PilotExactTaskReleaseRecoveryError(
                    "release-marked recovery state markers are incomplete"
                )
        expected = {
            "clear": ("manual_intervention", True, False),
            "tag_only": ("create_missing_release", False, True),
            "exact_existing": ("finalize_existing_state", False, False),
        }[self.remote_state_class]
        if (
            (self.action_required, self.manual_intervention_required, self.remote_write_required)
            != expected
        ):
            raise PilotExactTaskReleaseRecoveryError(
                "release recovery action does not match remote state"
            )
        if self.remote_state_class == "clear" and self.durable_phase != "lock_only":
            raise PilotExactTaskReleaseRecoveryError(
                "durable release marker evidence contradicts missing remote tag"
            )
        if self.remote_state_class == "tag_only" and self.durable_phase == "release_marked":
            raise PilotExactTaskReleaseRecoveryError(
                "release marker contradicts missing remote release"
            )
        if self.remote_state_class == "exact_existing":
            if (
                isinstance(self.release_id, bool)
                or not isinstance(self.release_id, int)
                or self.release_id < 1
                or self.release_node_id_sha256 is None
            ):
                raise PilotExactTaskReleaseRecoveryError(
                    "exact-existing recovery state lacks release identity"
                )
            _hex64(self.release_node_id_sha256, name="release_node_id_sha256")
        else:
            if self.release_id is not None or self.release_node_id_sha256 is not None:
                raise PilotExactTaskReleaseRecoveryError(
                    "non-final recovery state carries release identity"
                )
        _utc(self.observed_at_utc, name="observed_at_utc")

    @property
    def fingerprint_sha256(self) -> str:
        # Observation time is audit metadata, not part of the state identity.
        # This lets a signed inspection remain valid while recover() freshly
        # reobserves the same durable/remote state inside the signature window.
        values = self.to_dict()
        values.pop("observed_at_utc")
        return hashlib.sha256(_canonical(values).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def _load_durable_authorization(
    execution_nonce_sha256: str,
    authorization_ledger_root: Path,
) -> PilotExactTaskReleaseAuthorizationReceipt:
    key = _hex64(execution_nonce_sha256, name="execution_nonce_sha256")
    ledger = auth_boundary._PilotExactTaskReleaseAuthorizationLedger(
        _safe_ledger_root(authorization_ledger_root)
    )
    final, lock = ledger._paths(key)
    raw, final_payload = _read_canonical_object(
        final,
        name="ADR-DC-066 final authorization receipt",
    )
    try:
        authorization = PilotExactTaskReleaseAuthorizationReceipt.from_mapping(raw)
    except Exception as exc:
        raise PilotExactTaskReleaseRecoveryError(
            "durable ADR-DC-066 authorization receipt is invalid"
        ) from exc
    if (
        authorization.execution_nonce_sha256 != key
        or authorization.release_key_sha256 != key
        or authorization.authority != PILOT_EXACT_TASK_RELEASE_AUTHORIZATION_AUTHORITY
        or authorization.release_ledger_root_path_sha256 != ledger.root_sha256
        or authorization.canonical_json().encode("utf-8") != final_payload
    ):
        raise PilotExactTaskReleaseRecoveryError(
            "durable ADR-DC-066 authorization binding mismatch"
        )
    lock_raw, _lock_payload = _read_canonical_object(
        lock,
        name="ADR-DC-066 durable authorization lock",
    )
    required = {
        "schema": "kaliv-rsi-dc-l16-exact-task-release-authorization-lock/v1",
        "ledger_scope": auth_boundary.PILOT_EXACT_TASK_RELEASE_AUTHORIZATION_LEDGER_SCOPE,
        "ledger_root_path_sha256": ledger.root_sha256,
        "release_key_sha256": key,
        "release_state_observation_sha256": authorization.release_state_observation_sha256,
        "release_plan_sha256": authorization.release_plan_sha256,
        "release_intent_sha256": authorization.release_intent_sha256,
        "remote_release_state_sha256": authorization.remote_release_state_sha256,
        "release_authorization_payload_sha256": authorization.release_authorization_payload_sha256,
        "release_authorization_config_sha256": authorization.release_authorization_config_sha256,
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
    }
    if any(lock_raw.get(name) != value for name, value in required.items()):
        raise PilotExactTaskReleaseRecoveryError(
            "ADR-DC-066 authorization lock differs from final authorization"
        )
    for name in ("operator_signature_sha256", "reviewer_signature_sha256"):
        _hex64(lock_raw.get(name), name=name)
    return authorization


def _transaction_evidence(
    authorization: PilotExactTaskReleaseAuthorizationReceipt,
    transaction_ledger_root: Path,
) -> tuple[str, bytes, bytes | None, bytes | None, dict[str, Any] | None]:
    ledger = tx_boundary._PilotExactTaskReleaseTransactionLedger(
        _safe_ledger_root(transaction_ledger_root)
    )
    final, lock, tag_marker, release_marker = ledger._paths(
        authorization.execution_nonce_sha256
    )
    if final.exists() or final.is_symlink():
        raise PilotExactTaskReleaseRecoveryError(
            "ADR-DC-067 already has a final receipt; recovery is unnecessary"
        )
    lock_raw, lock_payload = _read_canonical_object(
        lock,
        name="ADR-DC-067 transaction lock",
    )
    expected_lock = {
        "schema": "kaliv-rsi-dc-l16-exact-task-release-transaction-lock/v1",
        "ledger_scope": tx_boundary.PILOT_EXACT_TASK_RELEASE_TRANSACTION_LEDGER_SCOPE,
        "ledger_root_path_sha256": ledger.root_sha256,
        "release_key_sha256": authorization.execution_nonce_sha256,
        "release_authorization_sha256": authorization.sha256,
        "release_authorization_payload_sha256": authorization.release_authorization_payload_sha256,
        "release_state_observation_sha256": authorization.release_state_observation_sha256,
        "release_plan_sha256": authorization.release_plan_sha256,
        "release_intent_sha256": authorization.release_intent_sha256,
        "remote_release_state_sha256": authorization.remote_release_state_sha256,
        "release_authorization_config_sha256": authorization.release_authorization_config_sha256,
        "publisher_credential_config_sha256": authorization.publisher_credential_config_sha256,
        "publisher_credential_path_sha256": authorization.publisher_credential_path_sha256,
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
    }
    if any(lock_raw.get(name) != value for name, value in expected_lock.items()):
        raise PilotExactTaskReleaseRecoveryError(
            "ADR-DC-067 transaction lock differs from durable authorization"
        )
    _utc(lock_raw.get("locked_at_utc"), name="locked_at_utc")
    tag_payload = None
    release_payload = None
    release_raw = None
    if tag_marker.exists() or tag_marker.is_symlink():
        tag_raw, tag_payload = _read_canonical_object(
            tag_marker,
            name="ADR-DC-067 tag marker",
        )
        if (
            tag_raw.get("schema")
            != "kaliv-rsi-dc-l16-exact-task-release-transaction-tag-marker/v1"
            or tag_raw.get("release_authorization_sha256") != authorization.sha256
            or tag_raw.get("release_key_sha256") != authorization.execution_nonce_sha256
            or tag_raw.get("tag_name") != authorization.tag_name
            or tag_raw.get("tag_target_sha") != authorization.tag_target_sha
        ):
            raise PilotExactTaskReleaseRecoveryError(
                "ADR-DC-067 tag marker differs from exact authorization"
            )
        _utc(tag_raw.get("tag_created_at_utc"), name="tag_created_at_utc")
    if release_marker.exists() or release_marker.is_symlink():
        if tag_payload is None:
            raise PilotExactTaskReleaseRecoveryError(
                "ADR-DC-067 release marker exists without tag marker"
            )
        release_raw, release_payload = _read_canonical_object(
            release_marker,
            name="ADR-DC-067 release marker",
        )
        if (
            release_raw.get("schema")
            != "kaliv-rsi-dc-l16-exact-task-release-transaction-release-marker/v1"
            or release_raw.get("release_authorization_sha256") != authorization.sha256
            or release_raw.get("release_key_sha256") != authorization.execution_nonce_sha256
            or release_raw.get("tag_name") != authorization.tag_name
        ):
            raise PilotExactTaskReleaseRecoveryError(
                "ADR-DC-067 release marker differs from exact authorization"
            )
        if (
            isinstance(release_raw.get("release_id"), bool)
            or not isinstance(release_raw.get("release_id"), int)
            or release_raw["release_id"] < 1
        ):
            raise PilotExactTaskReleaseRecoveryError(
                "ADR-DC-067 release marker ID is invalid"
            )
        _hex64(
            release_raw.get("release_node_id_sha256"),
            name="release_node_id_sha256",
        )
        _utc(
            release_raw.get("release_created_at_utc"),
            name="release_created_at_utc",
        )
    phase = (
        "release_marked"
        if release_payload is not None
        else "tag_marked"
        if tag_payload is not None
        else "lock_only"
    )
    return phase, lock_payload, tag_payload, release_payload, release_raw


def _double_observe(
    transport: Any,
    authorization: PilotExactTaskReleaseAuthorizationReceipt,
) -> _ReleaseRecoveryRemoteState:
    if transport is None or not callable(getattr(transport, "observe", None)):
        raise PilotExactTaskReleaseRecoveryError(
            "exact release recovery observer is required"
        )
    if (
        getattr(transport, "credential_config_sha256", None)
        != authorization.publisher_credential_config_sha256
        or getattr(transport, "credential_path_sha256", None)
        != authorization.publisher_credential_path_sha256
    ):
        raise PilotExactTaskReleaseRecoveryError(
            "release recovery credential identity differs from ADR-DC-066"
        )
    first = transport.observe(authorization)
    second = transport.observe(authorization)
    if (
        type(first) is not _ReleaseRecoveryRemoteState
        or type(second) is not _ReleaseRecoveryRemoteState
        or first != second
    ):
        raise PilotExactTaskReleaseRecoveryError(
            "remote release recovery state changed between observations"
        )
    if (
        first.repository != authorization.repository
        or first.repository_id != authorization.repository_id
        or (
            first.tag_state == "exact"
            and first.tag_target_sha != authorization.tag_target_sha
        )
    ):
        raise PilotExactTaskReleaseRecoveryError(
            "remote release recovery identity differs from authorization"
        )
    return first


def _observe_verified_recovery_state(
    *,
    execution_nonce_sha256: str,
    transaction_ledger_root: Path,
    release_authorization_ledger_root: Path,
    transport: Any,
    now_provider: Callable[[], str],
) -> tuple[PilotExactTaskReleaseRecoveryState, PilotExactTaskReleaseAuthorizationReceipt]:
    authorization = _load_durable_authorization(
        execution_nonce_sha256,
        release_authorization_ledger_root,
    )
    phase, lock_payload, tag_payload, release_payload, release_raw = (
        _transaction_evidence(authorization, transaction_ledger_root)
    )
    remote = _double_observe(transport, authorization)
    if phase in {"tag_marked", "release_marked"} and remote.remote_state_class == "clear":
        raise PilotExactTaskReleaseRecoveryError(
            "durable tag evidence contradicts missing remote tag"
        )
    if phase == "release_marked" and remote.remote_state_class != "exact_existing":
        raise PilotExactTaskReleaseRecoveryError(
            "durable release marker contradicts remote release state"
        )
    if release_raw is not None and (
        remote.release_id != release_raw["release_id"]
        or remote.release_node_id_sha256
        != release_raw["release_node_id_sha256"]
    ):
        raise PilotExactTaskReleaseRecoveryError(
            "durable release marker identity differs from GitHub release"
        )
    action, manual, remote_write = {
        "clear": ("manual_intervention", True, False),
        "tag_only": ("create_missing_release", False, True),
        "exact_existing": ("finalize_existing_state", False, False),
    }[remote.remote_state_class]
    observed_at = now_provider()
    _utc(observed_at, name="observed_at_utc")
    return (
        PilotExactTaskReleaseRecoveryState(
            transaction_key_sha256=authorization.execution_nonce_sha256,
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
            original_remote_release_state_sha256=(
                authorization.remote_release_state_sha256
            ),
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
            transaction_lock_sha256=_payload_sha256(lock_payload),
            tag_marker_sha256=(
                None if tag_payload is None else _payload_sha256(tag_payload)
            ),
            release_marker_sha256=(
                None
                if release_payload is None
                else _payload_sha256(release_payload)
            ),
            durable_phase=phase,
            repository=authorization.repository,
            repository_id=authorization.repository_id,
            release_base_branch=authorization.release_base_branch,
            merge_commit_sha=authorization.merge_commit_sha,
            release_version=authorization.release_version,
            tag_name=authorization.tag_name,
            tag_target_sha=authorization.tag_target_sha,
            release_name=authorization.release_name,
            release_body_sha256=authorization.release_body_sha256,
            release_id=remote.release_id,
            release_node_id_sha256=remote.release_node_id_sha256,
            remote_release_state_sha256=remote.sha256,
            remote_state_class=remote.remote_state_class,
            action_required=action,
            manual_intervention_required=manual,
            remote_write_required=remote_write,
            observed_at_utc=observed_at,
        ),
        authorization,
    )


def _build_recovery_payload(
    *,
    state: PilotExactTaskReleaseRecoveryState,
    requested_at_utc: str,
    expires_at_utc: str,
    operator_actor_id: str,
    operator_system_id: str,
    operator_key_id: str,
    reviewer_actor_id: str,
    reviewer_system_id: str,
    reviewer_key_id: str,
) -> bytes:
    if type(state) is not PilotExactTaskReleaseRecoveryState:
        raise PilotExactTaskReleaseRecoveryError(
            "exact ADR-DC-068 recovery state is required"
        )
    if state.manual_intervention_required or state.action_required not in {
        "create_missing_release",
        "finalize_existing_state",
    }:
        raise PilotExactTaskReleaseRecoveryError(
            "manual release recovery state cannot be automatically authorized"
        )
    requested = _utc(requested_at_utc, name="requested_at_utc")
    expires = _utc(expires_at_utc, name="expires_at_utc")
    if (
        not requested < expires
        or (expires - requested).total_seconds() > _MAX_AUTH_SECONDS
    ):
        raise PilotExactTaskReleaseRecoveryError(
            "release recovery authorization window is invalid"
        )
    identities = (
        ("operator_actor_id", operator_actor_id),
        ("operator_system_id", operator_system_id),
        ("operator_key_id", operator_key_id),
        ("reviewer_actor_id", reviewer_actor_id),
        ("reviewer_system_id", reviewer_system_id),
        ("reviewer_key_id", reviewer_key_id),
    )
    for name, value in identities:
        pattern = _ACTOR if name.endswith("actor_id") else _IDENTIFIER
        if not isinstance(value, str) or pattern.fullmatch(value) is None:
            raise PilotExactTaskReleaseRecoveryError(f"{name} is invalid")
    if (
        operator_actor_id == reviewer_actor_id
        or operator_system_id == reviewer_system_id
        or operator_key_id == reviewer_key_id
    ):
        raise PilotExactTaskReleaseRecoveryError(
            "release recovery signers must be independent"
        )
    payload = {
        "schema": PILOT_EXACT_TASK_RELEASE_RECOVERY_PAYLOAD_SCHEMA,
        "recovery_policy_sha256": pilot_exact_task_release_recovery_policy_sha256(),
        "custody_policy_sha256": asymmetric_authority_key_custody_policy_sha256(),
        "transaction_key_sha256": state.transaction_key_sha256,
        "recovery_state_fingerprint_sha256": state.fingerprint_sha256,
        "action": state.action_required,
        "durable_phase": state.durable_phase,
        "release_authorization_sha256": state.release_authorization_sha256,
        "release_intent_sha256": state.release_intent_sha256,
        "execution_nonce_sha256": state.execution_nonce_sha256,
        "development_task_sha256": state.development_task_sha256,
        "candidate_patch_sha256": state.candidate_patch_sha256,
        "pr_intent_sha256": state.pr_intent_sha256,
        "transaction_lock_sha256": state.transaction_lock_sha256,
        "tag_marker_sha256": state.tag_marker_sha256,
        "release_marker_sha256": state.release_marker_sha256,
        "remote_release_state_sha256": state.remote_release_state_sha256,
        "repository": state.repository,
        "repository_id": state.repository_id,
        "release_base_branch": state.release_base_branch,
        "merge_commit_sha": state.merge_commit_sha,
        "release_version": state.release_version,
        "tag_name": state.tag_name,
        "tag_target_sha": state.tag_target_sha,
        "release_name": state.release_name,
        "release_body_sha256": state.release_body_sha256,
        "release_id": state.release_id,
        "release_node_id_sha256": state.release_node_id_sha256,
        "requested_at_utc": requested_at_utc,
        "expires_at_utc": expires_at_utc,
        "operator_actor_id": operator_actor_id,
        "operator_system_id": operator_system_id,
        "operator_key_id": operator_key_id,
        "reviewer_actor_id": reviewer_actor_id,
        "reviewer_system_id": reviewer_system_id,
        "reviewer_key_id": reviewer_key_id,
    }
    return _canonical(payload).encode("utf-8")


def build_pilot_exact_task_release_recovery_payload(
    state: PilotExactTaskReleaseRecoveryState,
    requested_at_utc: str,
    expires_at_utc: str,
    operator_actor_id: str,
    operator_system_id: str,
    operator_key_id: str,
    reviewer_actor_id: str,
    reviewer_system_id: str,
    reviewer_key_id: str,
) -> bytes:
    """Build exact bytes for two independent release-recovery signers."""
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
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_ARTIFACT_BYTES:
        raise PilotExactTaskReleaseRecoveryError(
            "release recovery authorization payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskReleaseRecoveryError(
            "release recovery authorization payload is invalid JSON"
        ) from exc
    required = {
        "schema",
        "recovery_policy_sha256",
        "custody_policy_sha256",
        "transaction_key_sha256",
        "recovery_state_fingerprint_sha256",
        "action",
        "durable_phase",
        "release_authorization_sha256",
        "release_intent_sha256",
        "execution_nonce_sha256",
        "development_task_sha256",
        "candidate_patch_sha256",
        "pr_intent_sha256",
        "transaction_lock_sha256",
        "tag_marker_sha256",
        "release_marker_sha256",
        "remote_release_state_sha256",
        "repository",
        "repository_id",
        "release_base_branch",
        "merge_commit_sha",
        "release_version",
        "tag_name",
        "tag_target_sha",
        "release_name",
        "release_body_sha256",
        "release_id",
        "release_node_id_sha256",
        "requested_at_utc",
        "expires_at_utc",
        "operator_actor_id",
        "operator_system_id",
        "operator_key_id",
        "reviewer_actor_id",
        "reviewer_system_id",
        "reviewer_key_id",
    }
    if (
        not isinstance(raw, dict)
        or set(raw) != required
        or raw.get("schema") != PILOT_EXACT_TASK_RELEASE_RECOVERY_PAYLOAD_SCHEMA
        or raw.get("recovery_policy_sha256")
        != pilot_exact_task_release_recovery_policy_sha256()
        or raw.get("custody_policy_sha256")
        != asymmetric_authority_key_custody_policy_sha256()
        or raw.get("action")
        not in {"create_missing_release", "finalize_existing_state"}
        or _canonical(raw).encode("utf-8") != payload
    ):
        raise PilotExactTaskReleaseRecoveryError(
            "release recovery payload fields/canonical form mismatch"
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
    if (
        type(operator_signature) is not DetachedEd25519AuthoritySignature
        or type(reviewer_signature) is not DetachedEd25519AuthoritySignature
    ):
        raise PilotExactTaskReleaseRecoveryError(
            "two detached Ed25519 release recovery signatures are required"
        )
    if (
        operator_signature.key_id == reviewer_signature.key_id
        or operator_signature.issuer_actor_id == reviewer_signature.issuer_actor_id
        or operator_signature.issuer_system_id == reviewer_signature.issuer_system_id
    ):
        raise PilotExactTaskReleaseRecoveryError(
            "release recovery signatures must be independent"
        )
    now = _utc(at_utc, name="recovery_at_utc")
    requested = _utc(claim["requested_at_utc"], name="requested_at_utc")
    expires = _utc(claim["expires_at_utc"], name="expires_at_utc")
    if not requested <= now < expires:
        raise PilotExactTaskReleaseRecoveryError(
            "release recovery authorization is not currently valid"
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
            raise PilotExactTaskReleaseRecoveryError(
                "release recovery signature binding mismatch"
            )
        signed = _utc(signature.signed_at_utc, name="signed_at_utc")
        if not requested <= signed < expires or signed > now:
            raise PilotExactTaskReleaseRecoveryError(
                "release recovery signature timestamp is outside authorization window"
            )
        try:
            verifier.verify(payload=payload, signature=signature, at_utc=at_utc)
        except AsymmetricAuthorityError as exc:
            raise PilotExactTaskReleaseRecoveryError(
                "release recovery Ed25519 verification failed"
            ) from exc
    return claim


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskReleaseRecoveryReceipt:
    recovery_ledger_root_path_sha256: str
    recovery_key_sha256: str
    recovery_authorization_payload_sha256: str
    recovery_state_fingerprint_sha256: str
    recovery_policy_sha256: str
    release_authorization_sha256: str
    release_intent_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    transaction_lock_sha256: str
    tag_marker_sha256: str | None
    release_marker_sha256: str | None
    source_durable_phase: str
    source_remote_state_class: str
    final_remote_release_state_sha256: str
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    repository: str
    repository_id: str
    release_base_branch: str
    merge_commit_sha: str
    release_version: str
    tag_name: str
    tag_target_sha: str
    release_name: str
    release_body_sha256: str
    release_id: int
    release_node_id_sha256: str
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
    exact_release_finalized: bool = True
    recovery_completed: bool = True
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
    recovery_scope: str = PILOT_EXACT_TASK_RELEASE_RECOVERY_SCOPE
    authority: str = PILOT_EXACT_TASK_RELEASE_RECOVERY_AUTHORITY
    schema: str = PILOT_EXACT_TASK_RELEASE_RECOVERY_SCHEMA

    def __post_init__(self) -> None:
        for name in (
            "recovery_ledger_root_path_sha256",
            "recovery_key_sha256",
            "recovery_authorization_payload_sha256",
            "recovery_state_fingerprint_sha256",
            "recovery_policy_sha256",
            "release_authorization_sha256",
            "release_intent_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "pr_intent_sha256",
            "transaction_lock_sha256",
            "final_remote_release_state_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
            "release_body_sha256",
            "release_node_id_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("tag_marker_sha256", "release_marker_sha256"):
            value = getattr(self, name)
            if value is not None:
                _hex64(value, name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        _hex40(self.tag_target_sha, name="tag_target_sha")
        if (
            self.schema != PILOT_EXACT_TASK_RELEASE_RECOVERY_SCHEMA
            or self.authority != PILOT_EXACT_TASK_RELEASE_RECOVERY_AUTHORITY
            or self.recovery_scope != PILOT_EXACT_TASK_RELEASE_RECOVERY_SCOPE
            or self.recovery_key_sha256 != self.execution_nonce_sha256
            or self.recovery_policy_sha256
            != pilot_exact_task_release_recovery_policy_sha256()
            or self.tag_target_sha != self.merge_commit_sha
            or self.source_durable_phase
            not in {"lock_only", "tag_marked", "release_marked"}
            or self.source_remote_state_class not in {"tag_only", "exact_existing"}
            or self.action_performed
            not in {"create_missing_release", "finalize_existing_state"}
        ):
            raise PilotExactTaskReleaseRecoveryError(
                "release recovery receipt identity/classification is invalid"
            )
        if self.action_performed == "create_missing_release":
            if (
                self.source_remote_state_class != "tag_only"
                or self.remote_write_performed is not True
            ):
                raise PilotExactTaskReleaseRecoveryError(
                    "release recovery write classification is inconsistent"
                )
        elif self.remote_write_performed is not False:
            raise PilotExactTaskReleaseRecoveryError(
                "write-free release recovery claims remote mutation"
            )
        if (
            isinstance(self.release_id, bool)
            or not isinstance(self.release_id, int)
            or self.release_id < 1
        ):
            raise PilotExactTaskReleaseRecoveryError(
                "release recovery final release ID is invalid"
            )
        _utc(self.recovered_at_utc, name="recovered_at_utc")
        required_true = (
            "durable_state_verified",
            "remote_state_verified",
            "dual_external_ed25519_authorized",
            "recovery_authority_consumed",
            "exact_release_finalized",
            "recovery_completed",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskReleaseRecoveryError(
                "release recovery completion evidence is incomplete"
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
            raise PilotExactTaskReleaseRecoveryError(
                "release recovery receipt retains forbidden authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            self.canonical_json().encode("utf-8")
        ).hexdigest()

    @property
    def recovery_authenticated(self) -> bool:
        return _get_live_release_recovery_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(
        cls,
        value: Any,
    ) -> "PilotExactTaskReleaseRecoveryReceipt":
        if (
            not isinstance(value, Mapping)
            or set(value) != set(cls.__dataclass_fields__)
        ):
            raise PilotExactTaskReleaseRecoveryError(
                "release recovery receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskReleaseRecoveryLedger:
    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path]:
        digest = _hex64(key, name="recovery_key_sha256")
        return self.root / f"{digest}.json", self.root / f".{digest}.lock"

    def acquire(
        self,
        *,
        state: PilotExactTaskReleaseRecoveryState,
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
            raise PilotExactTaskReleaseRecoveryError(
                "release recovery nonce already consumed"
            )
        payload = _canonical(
            {
                "schema": (
                    "kaliv-rsi-dc-l16-exact-task-release-recovery-lock/v1"
                ),
                "ledger_scope": PILOT_EXACT_TASK_RELEASE_RECOVERY_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "recovery_key_sha256": state.execution_nonce_sha256,
                "recovery_state_fingerprint_sha256": state.fingerprint_sha256,
                "recovery_authorization_payload_sha256": hashlib.sha256(
                    authorization_payload
                ).hexdigest(),
                "release_authorization_sha256": state.release_authorization_sha256,
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
            raise PilotExactTaskReleaseRecoveryError(
                "release recovery authority could not be durably consumed"
            ) from exc
        return payload

    def commit(
        self,
        *,
        receipt: PilotExactTaskReleaseRecoveryReceipt,
        lock_payload: bytes,
        source_state: PilotExactTaskReleaseRecoveryState,
    ) -> PilotExactTaskReleaseRecoveryReceipt:
        final, lock = self._paths(receipt.recovery_key_sha256)
        if (
            final.exists()
            or final.is_symlink()
            or _read_bytes(lock) != lock_payload
        ):
            raise PilotExactTaskReleaseRecoveryError(
                "release recovery durable state changed before finalization"
            )
        payload = receipt.canonical_json().encode("utf-8")
        try:
            create_once_file(final, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskReleaseRecoveryError(
                "release recovery receipt could not be durably published"
            ) from exc
        parsed = PilotExactTaskReleaseRecoveryReceipt.from_mapping(
            json.loads(payload.decode("utf-8"))
        )
        _mark_release_recovery_authenticated(
            parsed,
            source_state=source_state,
            final_path=final,
            final_payload=payload,
            lock_path=lock,
            lock_payload=lock_payload,
        )
        if parsed.recovery_authenticated is not True:
            raise PilotExactTaskReleaseRecoveryError(
                "release recovery lost live provenance"
            )
        return parsed


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: PilotExactTaskReleaseRecoveryReceipt,
        *,
        source_state: PilotExactTaskReleaseRecoveryState,
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
            source_state.fingerprint_sha256,
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
            receipt_ref,
            source_fingerprint,
            final_path,
            final_payload,
            lock_path,
            lock_payload,
        ) = entry
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or receipt.sha256 != digest
            or receipt.recovery_state_fingerprint_sha256 != source_fingerprint
            or _read_bytes(final_path) != final_payload
            or _read_bytes(lock_path) != lock_payload
        ):
            return None
        return MappingProxyType(
            {"source_recovery_state_fingerprint_sha256": source_fingerprint}
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_release_recovery_authenticated,
    _get_live_release_recovery_inputs,
) = _live_registry()


def _claim_matches_state(
    claim: Mapping[str, Any],
    state: PilotExactTaskReleaseRecoveryState,
) -> bool:
    return (
        claim.get("transaction_key_sha256") == state.transaction_key_sha256
        and claim.get("recovery_state_fingerprint_sha256")
        == state.fingerprint_sha256
        and claim.get("action") == state.action_required
        and claim.get("durable_phase") == state.durable_phase
        and claim.get("release_authorization_sha256")
        == state.release_authorization_sha256
        and claim.get("release_intent_sha256") == state.release_intent_sha256
        and claim.get("execution_nonce_sha256") == state.execution_nonce_sha256
        and claim.get("development_task_sha256") == state.development_task_sha256
        and claim.get("candidate_patch_sha256") == state.candidate_patch_sha256
        and claim.get("pr_intent_sha256") == state.pr_intent_sha256
        and claim.get("transaction_lock_sha256") == state.transaction_lock_sha256
        and claim.get("tag_marker_sha256") == state.tag_marker_sha256
        and claim.get("release_marker_sha256") == state.release_marker_sha256
        and claim.get("remote_release_state_sha256")
        == state.remote_release_state_sha256
        and claim.get("repository") == state.repository
        and claim.get("repository_id") == state.repository_id
        and claim.get("release_base_branch") == state.release_base_branch
        and claim.get("merge_commit_sha") == state.merge_commit_sha
        and claim.get("release_version") == state.release_version
        and claim.get("tag_name") == state.tag_name
        and claim.get("tag_target_sha") == state.tag_target_sha
        and claim.get("release_name") == state.release_name
        and claim.get("release_body_sha256") == state.release_body_sha256
        and claim.get("release_id") == state.release_id
        and claim.get("release_node_id_sha256") == state.release_node_id_sha256
    )


def _recover_verified_pilot_exact_task_release(
    *,
    authorization_payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    transaction_ledger_root: Path,
    release_authorization_ledger_root: Path,
    recovery_ledger: _PilotExactTaskReleaseRecoveryLedger,
    transport: Any,
    now_provider: Callable[[], str],
) -> PilotExactTaskReleaseRecoveryReceipt:
    verified_at = now_provider()
    claim = _verify_dual_signatures(
        payload=authorization_payload,
        operator_signature=operator_signature,
        reviewer_signature=reviewer_signature,
        verifier=verifier,
        at_utc=verified_at,
    )
    state, authorization = _observe_verified_recovery_state(
        execution_nonce_sha256=claim["execution_nonce_sha256"],
        transaction_ledger_root=transaction_ledger_root,
        release_authorization_ledger_root=release_authorization_ledger_root,
        transport=transport,
        now_provider=lambda: verified_at,
    )
    if (
        state.manual_intervention_required
        or not _claim_matches_state(claim, state)
    ):
        raise PilotExactTaskReleaseRecoveryError(
            "signed release recovery state no longer matches exact durable/remote state"
        )
    lock_payload = recovery_ledger.acquire(
        state=state,
        authorization_payload=authorization_payload,
        operator_signature=operator_signature,
        reviewer_signature=reviewer_signature,
    )
    current, current_authorization = _observe_verified_recovery_state(
        execution_nonce_sha256=state.execution_nonce_sha256,
        transaction_ledger_root=transaction_ledger_root,
        release_authorization_ledger_root=release_authorization_ledger_root,
        transport=transport,
        now_provider=now_provider,
    )
    if (
        current.fingerprint_sha256 != state.fingerprint_sha256
        or current.action_required != state.action_required
        or current_authorization.sha256 != authorization.sha256
    ):
        raise PilotExactTaskReleaseRecoveryError(
            "release recovery state changed after durable recovery lock"
        )

    remote_write_performed = False
    if current.action_required == "create_missing_release":
        if not callable(getattr(transport, "create_release", None)):
            raise PilotExactTaskReleaseRecoveryError(
                "release recovery transport cannot create missing release"
            )
        release_id, node_hash = transport.create_release(authorization)
        if (
            isinstance(release_id, bool)
            or not isinstance(release_id, int)
            or release_id < 1
        ):
            raise PilotExactTaskReleaseRecoveryError(
                "recovery release write returned invalid release ID"
            )
        _hex64(node_hash, name="release_node_id_sha256")
        remote_write_performed = True
        final_remote = _double_observe(transport, authorization)
        if (
            final_remote.remote_state_class != "exact_existing"
            or final_remote.release_id != release_id
            or final_remote.release_node_id_sha256 != node_hash
        ):
            raise PilotExactTaskReleaseRecoveryError(
                "created recovery release is not exact final remote state"
            )
    elif current.action_required == "finalize_existing_state":
        final_remote = _double_observe(transport, authorization)
        if final_remote.remote_state_class != "exact_existing":
            raise PilotExactTaskReleaseRecoveryError(
                "write-free recovery final state is no longer exact"
            )
        release_id = final_remote.release_id
        node_hash = final_remote.release_node_id_sha256
    else:
        raise PilotExactTaskReleaseRecoveryError(
            "release recovery action is not automatically executable"
        )
    assert release_id is not None and node_hash is not None

    recovered_at = now_provider()
    if _utc(recovered_at, name="recovered_at_utc") < _utc(
        current.observed_at_utc,
        name="observed_at_utc",
    ):
        raise PilotExactTaskReleaseRecoveryError(
            "system clock moved backwards during release recovery"
        )
    receipt = PilotExactTaskReleaseRecoveryReceipt(
        recovery_ledger_root_path_sha256=recovery_ledger.root_sha256,
        recovery_key_sha256=current.execution_nonce_sha256,
        recovery_authorization_payload_sha256=hashlib.sha256(
            authorization_payload
        ).hexdigest(),
        recovery_state_fingerprint_sha256=current.fingerprint_sha256,
        recovery_policy_sha256=pilot_exact_task_release_recovery_policy_sha256(),
        release_authorization_sha256=current.release_authorization_sha256,
        release_intent_sha256=current.release_intent_sha256,
        execution_nonce_sha256=current.execution_nonce_sha256,
        development_task_sha256=current.development_task_sha256,
        candidate_patch_sha256=current.candidate_patch_sha256,
        pr_intent_sha256=current.pr_intent_sha256,
        transaction_lock_sha256=current.transaction_lock_sha256,
        tag_marker_sha256=current.tag_marker_sha256,
        release_marker_sha256=current.release_marker_sha256,
        source_durable_phase=current.durable_phase,
        source_remote_state_class=current.remote_state_class,
        final_remote_release_state_sha256=final_remote.sha256,
        publisher_credential_config_sha256=(
            current.publisher_credential_config_sha256
        ),
        publisher_credential_path_sha256=(
            current.publisher_credential_path_sha256
        ),
        repository=current.repository,
        repository_id=current.repository_id,
        release_base_branch=current.release_base_branch,
        merge_commit_sha=current.merge_commit_sha,
        release_version=current.release_version,
        tag_name=current.tag_name,
        tag_target_sha=current.tag_target_sha,
        release_name=current.release_name,
        release_body_sha256=current.release_body_sha256,
        release_id=release_id,
        release_node_id_sha256=node_hash,
        action_performed=current.action_required,
        remote_write_performed=remote_write_performed,
        operator_actor_id=claim["operator_actor_id"],
        operator_system_id=claim["operator_system_id"],
        operator_key_id=claim["operator_key_id"],
        reviewer_actor_id=claim["reviewer_actor_id"],
        reviewer_system_id=claim["reviewer_system_id"],
        reviewer_key_id=claim["reviewer_key_id"],
        recovered_at_utc=recovered_at,
    )
    return recovery_ledger.commit(
        receipt=receipt,
        lock_payload=lock_payload,
        source_state=current,
    )


def _canonical_runtime():
    try:
        _require_elevated_operator()
        if os.name == "posix":
            transaction_root = _require_host_controlled_ledger_root(
                tx_boundary._POSIX_LEDGER
            )
            authorization_root = _require_host_controlled_ledger_root(
                auth_boundary._POSIX_LEDGER
            )
            recovery_root = _require_host_controlled_ledger_root(_POSIX_LEDGER)
            keyring_path = auth_boundary._POSIX_KEYRING
        elif os.name == "nt":
            transaction_root = _require_host_controlled_ledger_root(
                tx_boundary._WINDOWS_LEDGER
            )
            authorization_root = _require_host_controlled_ledger_root(
                auth_boundary._WINDOWS_LEDGER
            )
            recovery_root = _require_host_controlled_ledger_root(_WINDOWS_LEDGER)
            keyring_path = auth_boundary._WINDOWS_KEYRING
        else:
            raise PilotExactTaskReleaseRecoveryError(
                "release recovery platform is unsupported"
            )
        first_keyring = auth_boundary._read_host_authority_file(keyring_path)
        second_keyring = auth_boundary._read_host_authority_file(keyring_path)
        if first_keyring != second_keyring:
            raise PilotExactTaskReleaseRecoveryError(
                "release recovery keyring changed while being read"
            )
        verifier, _keyring_sha = auth_boundary._parse_keyring(second_keyring)
        credential, credential_digest, credential_path = (
            publication_tx_boundary._canonical_credential()
        )
        transport = _GitHubReleaseRecoveryTransport(
            credential=credential,
            credential_config_sha256=credential_digest,
            credential_path=credential_path,
        )
        return (
            transaction_root,
            authorization_root,
            _PilotExactTaskReleaseRecoveryLedger(recovery_root),
            verifier,
            transport,
        )
    except PilotExactTaskReleaseRecoveryError:
        raise
    except (PhysicalHostStateError, ValueError, TypeError, OSError) as exc:
        raise PilotExactTaskReleaseRecoveryError(
            "release recovery runtime is not host-admin controlled"
        ) from exc


def inspect_pilot_exact_task_release_recovery(
    execution_nonce_sha256: str,
) -> PilotExactTaskReleaseRecoveryState:
    """Inspect durable/remote ADR-DC-067 recovery state without mutation."""
    tx_root, auth_root, _recovery_ledger, _verifier, observer = _canonical_runtime()
    state, _authorization = _observe_verified_recovery_state(
        execution_nonce_sha256=execution_nonce_sha256,
        transaction_ledger_root=tx_root,
        release_authorization_ledger_root=auth_root,
        transport=observer,
        now_provider=_now_utc_seconds,
    )
    return state


def recover_pilot_exact_task_release(
    authorization_payload: bytes,
    operator_signature: DetachedEd25519AuthoritySignature,
    reviewer_signature: DetachedEd25519AuthoritySignature,
) -> PilotExactTaskReleaseRecoveryReceipt:
    """Recover one consumed exact release transaction without recreating its tag."""
    tx_root, auth_root, recovery_ledger, verifier, observer = _canonical_runtime()
    return _recover_verified_pilot_exact_task_release(
        authorization_payload=authorization_payload,
        operator_signature=operator_signature,
        reviewer_signature=reviewer_signature,
        verifier=verifier,
        transaction_ledger_root=tx_root,
        release_authorization_ledger_root=auth_root,
        recovery_ledger=recovery_ledger,
        transport=observer,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []
