"""ADR-DC-049 replay-safe one-shot exact remote-publication authorization.

This boundary accepts only one exact live ADR-DC-048 remote-state observation,
fresh-revalidates both the completed local commit and the empty GitHub publication
lane, then durably reserves one host-local publication slot keyed by the original
human-signed execution nonce.

A successful live receipt authorizes only the exact deterministic remote branch,
exact commit push, and exact draft pull-request creation described by ADR-DC-047.
It performs no Git or GitHub mutation itself and never grants merge, release,
deploy, or production-activation authority.
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
from .durable_publication import DurablePublicationError, create_once_file, unlink_durable
from . import improvement_pilot_exact_task_remote_state_observation as observation_boundary
from .improvement_pilot_exact_task_remote_state_observation import (
    PILOT_EXACT_TASK_REMOTE_STATE_OBSERVATION_AUTHORITY,
    PilotExactTaskRemoteStateObservationReceipt,
)
from .improvement_pilot_exact_task_remote_publication_plan import (
    PilotExactTaskRemotePublicationPlan,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-remote-publication-authorization-receipt/v1"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_AUTHORITY = (
    "host-authorized-one-dc-l16-exact-remote-publication-only"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_LEDGER_SCOPE = (
    "canonical-host-local-v1"
)
_MAX_ARTIFACT_BYTES = 1024 * 1024
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_BRANCH = re.compile(r"^(?![./])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-remote-publication-authorization-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-remote-publication-authorization-ledger-v1"
)


class PilotExactTaskRemotePublicationAuthorizationError(ValueError):
    """Exact remote publication authority is replayed, stale, or over-broad."""


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
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "remote publication authorization is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskRemotePublicationAuthorizationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskRemotePublicationAuthorizationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskRemotePublicationAuthorizationError(
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
        raise PilotExactTaskRemotePublicationAuthorizationError(
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


def _require_live_observation(
    value: Any,
) -> tuple[
    PilotExactTaskRemoteStateObservationReceipt,
    PilotExactTaskRemotePublicationPlan,
    Mapping[str, Any],
]:
    if type(value) is not PilotExactTaskRemoteStateObservationReceipt:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "exact ADR-DC-048 remote-state observation is required"
        )
    try:
        replayed = PilotExactTaskRemoteStateObservationReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "ADR-DC-048 observation replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "ADR-DC-048 observation identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_REMOTE_STATE_OBSERVATION_AUTHORITY
        or value.observation_authenticated is not True
        or value.remote_publication_plan_authenticated is not True
        or value.remote_repository_identity_verified is not True
        or value.remote_default_branch_verified is not True
        or value.base_branch_observed is not True
        or value.base_branch_matches_exact_task_base is not True
        or value.head_branch_observed is not True
        or value.head_branch_exists is not False
        or value.head_branch_absent is not True
        or value.matching_prs_observed is not True
        or value.matching_pr_count != 0
        or value.matching_pr_absent is not True
        or value.double_observation_matched is not True
        or value.remote_state_observed is not True
        or value.publication_lane_clear is not True
        or value.integration_ready is not True
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "remote publication authorization requires one live clear ADR-DC-048 lane"
        )
    inputs = observation_boundary._get_live_remote_state_observation_inputs(value)
    if inputs is None:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "ADR-DC-048 live observation inputs are unavailable"
        )
    plan = inputs.get("remote_publication_plan")
    task = inputs.get("task")
    identity = inputs.get("local_commit_object_identity")
    if (
        type(plan) is not PilotExactTaskRemotePublicationPlan
        or task is None
        or identity is None
        or plan.plan_authenticated is not True
        or plan.sha256 != value.remote_publication_plan_sha256
        or plan.integration_readiness_sha256 != value.integration_readiness_sha256
        or plan.remote_target_config_sha256 != value.remote_target_config_sha256
        or plan.remote_repository_identity_sha256 != value.remote_repository_identity_sha256
        or plan.pr_intent_sha256 != value.pr_intent_sha256
        or plan.task_id != value.task_id
        or plan.repository != value.repository
        or plan.repository_id != value.repository_id
        or plan.base_branch != value.base_branch
        or plan.head_branch != value.head_branch
        or plan.base_sha != value.exact_task_base_sha
        or plan.predicted_commit_sha != value.predicted_commit_sha
        or getattr(task, "task_id", None) != value.task_id
        or getattr(task, "repository", None) != value.repository
        or getattr(task, "base_sha", None) != value.exact_task_base_sha
        or getattr(identity, "predicted_commit_sha", None) != value.predicted_commit_sha
    ):
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "ADR-DC-048 observation is not bound to exact live plan/task/commit"
        )
    return value, plan, inputs


def _fresh_observation(
    *,
    observation: PilotExactTaskRemoteStateObservationReceipt,
    plan: PilotExactTaskRemotePublicationPlan,
    inputs: Mapping[str, Any],
    observer: Any,
) -> str:
    if observer is None or not callable(getattr(observer, "observe", None)):
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "read-only GitHub observer is required"
        )
    try:
        observation_boundary._fresh_revalidate_local_commit(plan=plan, inputs=inputs)
        first = observation_boundary._validate_observation(plan, observer.observe(plan))
        second = observation_boundary._validate_observation(plan, observer.observe(plan))
    except Exception as exc:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "fresh exact remote publication lane revalidation failed"
        ) from exc
    if dict(first) != dict(second):
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "remote publication lane changed during authorization revalidation"
        )
    if (
        second["base_sha"] != plan.base_sha
        or second["head_exists"] is not False
        or second["matching_pr_count"] != 0
    ):
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "remote publication lane is no longer clear"
        )
    digest = observation_boundary._remote_observation_sha256(
        plan=plan,
        observation=second,
    )
    if digest != observation.remote_observation_sha256:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "fresh remote state no longer matches ADR-DC-048 observation"
        )
    live = observation_boundary._get_live_remote_state_observation_inputs(observation)
    if live is None or live.get("remote_publication_plan") is not plan:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "live ADR-DC-048 observation changed during authorization"
        )
    return digest


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
        ],
    ] = {}

    def mark(
        receipt: Any,
        observation: PilotExactTaskRemoteStateObservationReceipt,
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
            weakref.ref(observation),
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
            observation_ref,
            final_path,
            final_payload,
            lock_path,
            lock_payload,
        ) = entry
        observation = observation_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or observation is None
            or receipt.sha256 != digest
            or receipt.remote_state_observation_sha256 != observation.sha256
            or observation.observation_authenticated is not True
            or _read_bound_file(final_path) != final_payload
            or _read_bound_file(lock_path) != lock_payload
        ):
            return None
        inputs = observation_boundary._get_live_remote_state_observation_inputs(
            observation
        )
        if inputs is None:
            return None
        result = dict(inputs)
        result["remote_state_observation"] = observation
        return MappingProxyType(result)

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_remote_publication_authorization_authenticated,
    _get_live_remote_publication_authorization_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskRemotePublicationAuthorizationReceipt:
    ledger_root_path_sha256: str
    authorization_key_sha256: str
    remote_state_observation_sha256: str
    remote_publication_plan_sha256: str
    integration_readiness_sha256: str
    remote_target_config_sha256: str
    remote_repository_identity_sha256: str
    pr_intent_sha256: str
    remote_observation_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
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
    fresh_remote_observation_sha256: str
    fresh_revalidated_at_utc: str
    authorized_at_utc: str
    host_replay_guard_committed: bool = True
    remote_state_observation_authenticated: bool = True
    publication_lane_clear: bool = True
    fresh_local_commit_revalidated: bool = True
    fresh_remote_state_revalidated: bool = True
    remote_publication_authority_reserved: bool = True
    one_shot_remote_publication_required: bool = True
    exact_remote_branch_creation_authorized: bool = True
    exact_commit_push_authorized: bool = True
    exact_draft_pr_creation_authorized: bool = True
    remote_write_authorized: bool = True
    push_authorized: bool = True
    pr_mutation_authorized: bool = True
    remote_branch_created: bool = False
    exact_commit_pushed: bool = False
    draft_pr_created: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    product_pilot_started: bool = False
    ledger_scope: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_LEDGER_SCOPE
    authority: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_SCHEMA:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "remote publication authorization schema is unsupported"
            )
        if self.ledger_scope != PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_LEDGER_SCOPE:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "remote publication authorization ledger scope is unsupported"
            )
        for name in (
            "ledger_root_path_sha256",
            "authorization_key_sha256",
            "remote_state_observation_sha256",
            "remote_publication_plan_sha256",
            "integration_readiness_sha256",
            "remote_target_config_sha256",
            "remote_repository_identity_sha256",
            "pr_intent_sha256",
            "remote_observation_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "fresh_remote_observation_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("exact_task_base_sha", "predicted_commit_sha"):
            _hex40(getattr(self, name), name=name)
        if self.authorization_key_sha256 != self.execution_nonce_sha256:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "remote publication key must be the exact signed execution nonce"
            )
        if self.fresh_remote_observation_sha256 != self.remote_observation_sha256:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "fresh remote observation must equal the ADR-DC-048 observation"
            )
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise PilotExactTaskRemotePublicationAuthorizationError("task_id is invalid")
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None:
            raise PilotExactTaskRemotePublicationAuthorizationError("repository is invalid")
        if not isinstance(self.repository_id, str) or _REPOSITORY_ID.fullmatch(self.repository_id) is None:
            raise PilotExactTaskRemotePublicationAuthorizationError("repository_id is invalid")
        if self.provider != "github" or self.host != "github.com":
            raise PilotExactTaskRemotePublicationAuthorizationError("provider/host is unsupported")
        if self.remote_name != "origin" or self.base_branch != "main":
            raise PilotExactTaskRemotePublicationAuthorizationError("remote/base target is unsupported")
        _branch(self.head_branch, name="head_branch")
        fresh = _utc(self.fresh_revalidated_at_utc, name="fresh_revalidated_at_utc")
        authorized = _utc(self.authorized_at_utc, name="authorized_at_utc")
        if authorized < fresh:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "remote publication authorization predates fresh revalidation"
            )
        required_true = (
            "host_replay_guard_committed",
            "remote_state_observation_authenticated",
            "publication_lane_clear",
            "fresh_local_commit_revalidated",
            "fresh_remote_state_revalidated",
            "remote_publication_authority_reserved",
            "one_shot_remote_publication_required",
            "exact_remote_branch_creation_authorized",
            "exact_commit_push_authorized",
            "exact_draft_pr_creation_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "remote publication authorization evidence is incomplete"
            )
        forced_false = (
            "remote_branch_created",
            "exact_commit_pushed",
            "draft_pr_created",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "product_pilot_started",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "remote publication authorization cannot claim execution or higher authority"
            )
        if self.authority != PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_AUTHORITY:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "remote publication authorization authority is unsupported"
            )

    @property
    def authorization_authenticated(self) -> bool:
        return _get_live_remote_publication_authorization_inputs(self) is not None

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
    ) -> "PilotExactTaskRemotePublicationAuthorizationReceipt":
        if not isinstance(value, Mapping):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "remote publication authorization receipt must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "remote publication authorization receipt fields mismatch"
            )
        return cls(**dict(value))

    @classmethod
    def from_json(
        cls,
        text: str,
    ) -> "PilotExactTaskRemotePublicationAuthorizationReceipt":
        try:
            return cls.from_mapping(json.loads(text))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "remote publication authorization JSON is invalid"
            ) from exc

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskRemotePublicationAuthorizationLedger:
    """Permanent create-once remote-publication slot keyed by execution nonce."""

    def __init__(self, root: Path) -> None:
        self.root = _safe_ledger_root(root)
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path, Path]:
        digest = _hex64(key, name="authorization_key_sha256")
        return (
            self.root / f"{digest}.json",
            self.root / f".{digest}.pending.json",
            self.root / f".{digest}.lock",
        )

    def acquire(
        self,
        *,
        observation: PilotExactTaskRemoteStateObservationReceipt,
        plan: PilotExactTaskRemotePublicationPlan,
    ) -> bytes:
        key = plan.execution_nonce_sha256
        final, pending, lock = self._paths(key)
        if any(path.exists() or path.is_symlink() for path in (final, pending, lock)):
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "exact execution nonce already has a remote-publication slot or needs recovery"
            )
        payload = _canonical(
            {
                "schema": "kaliv-rsi-dc-l16-exact-task-remote-publication-authorization-lock/v1",
                "ledger_scope": PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "authorization_key_sha256": key,
                "remote_state_observation_sha256": observation.sha256,
                "remote_publication_plan_sha256": plan.sha256,
                "remote_target_config_sha256": plan.remote_target_config_sha256,
                "remote_repository_identity_sha256": plan.remote_repository_identity_sha256,
                "pr_intent_sha256": plan.pr_intent_sha256,
                "remote_observation_sha256": observation.remote_observation_sha256,
                "execution_nonce_sha256": plan.execution_nonce_sha256,
                "development_task_sha256": plan.development_task_sha256,
                "candidate_patch_sha256": plan.candidate_patch_sha256,
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
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "remote publication slot could not be durably reserved"
            ) from exc
        return payload

    def commit(
        self,
        *,
        receipt: PilotExactTaskRemotePublicationAuthorizationReceipt,
        observation: PilotExactTaskRemoteStateObservationReceipt,
        lock_payload: bytes,
    ) -> PilotExactTaskRemotePublicationAuthorizationReceipt:
        final, pending, lock = self._paths(receipt.authorization_key_sha256)
        if _read_bound_file(lock) != lock_payload:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "remote publication authorization marker changed before commit"
            )
        if final.exists() or final.is_symlink() or pending.exists() or pending.is_symlink():
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "remote publication authorization receipt already exists"
            )
        payload = receipt.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "remote publication authorization receipt exceeds byte bound"
            )
        try:
            create_once_file(pending, payload)
            create_once_file(final, payload)
            if _read_bound_file(final) != payload:
                raise PilotExactTaskRemotePublicationAuthorizationError(
                    "remote publication authorization receipt read-back mismatch"
                )
            parsed = PilotExactTaskRemotePublicationAuthorizationReceipt.from_mapping(
                json.loads(payload.decode("utf-8", errors="strict"))
            )
            if parsed.ledger_root_path_sha256 != self.root_sha256:
                raise PilotExactTaskRemotePublicationAuthorizationError(
                    "remote publication receipt belongs to another ledger"
                )
            unlink_durable(pending)
            if _read_bound_file(lock) != lock_payload:
                raise PilotExactTaskRemotePublicationAuthorizationError(
                    "remote publication marker changed before provenance registration"
                )
            _mark_remote_publication_authorization_authenticated(
                parsed,
                observation,
                final_path=final,
                final_payload=payload,
                lock_path=lock,
                lock_payload=lock_payload,
            )
            if parsed.authorization_authenticated is not True:
                raise PilotExactTaskRemotePublicationAuthorizationError(
                    "remote publication authorization lost live provenance"
                )
            return parsed
        except Exception as exc:
            if isinstance(exc, PilotExactTaskRemotePublicationAuthorizationError):
                raise
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "remote publication authorization is durable but requires recovery"
            ) from exc


def _authorize_verified_pilot_exact_task_remote_publication(
    *,
    remote_state_observation: PilotExactTaskRemoteStateObservationReceipt,
    ledger: _PilotExactTaskRemotePublicationAuthorizationLedger,
    observer: Any,
    now_provider: Callable[[], str],
) -> PilotExactTaskRemotePublicationAuthorizationReceipt:
    observation, plan, inputs = _require_live_observation(remote_state_observation)
    if type(ledger) is not _PilotExactTaskRemotePublicationAuthorizationLedger:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "remote publication authorization ledger is required"
        )

    fresh_digest = _fresh_observation(
        observation=observation,
        plan=plan,
        inputs=inputs,
        observer=observer,
    )
    fresh_at = now_provider()
    fresh_time = _utc(fresh_at, name="fresh_revalidated_at_utc")
    observed_time = _utc(observation.observed_at_utc, name="observed_at_utc")
    if fresh_time < observed_time:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "system clock moved backwards after ADR-DC-048 observation"
        )

    marker = ledger.acquire(observation=observation, plan=plan)

    observation_again, plan_again, after_inputs = _require_live_observation(observation)
    if observation_again is not observation or plan_again is not plan:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "live ADR-DC-048 observation changed during authorization"
        )
    fresh_digest_after = _fresh_observation(
        observation=observation,
        plan=plan,
        inputs=after_inputs,
        observer=observer,
    )
    if fresh_digest_after != fresh_digest:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "fresh remote-state identity changed after durable reservation"
        )
    authorized_at = now_provider()
    authorized_time = _utc(authorized_at, name="authorized_at_utc")
    if authorized_time < fresh_time:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "system clock moved backwards during remote publication authorization"
        )

    receipt = PilotExactTaskRemotePublicationAuthorizationReceipt(
        ledger_root_path_sha256=ledger.root_sha256,
        authorization_key_sha256=plan.execution_nonce_sha256,
        remote_state_observation_sha256=observation.sha256,
        remote_publication_plan_sha256=plan.sha256,
        integration_readiness_sha256=plan.integration_readiness_sha256,
        remote_target_config_sha256=plan.remote_target_config_sha256,
        remote_repository_identity_sha256=plan.remote_repository_identity_sha256,
        pr_intent_sha256=plan.pr_intent_sha256,
        remote_observation_sha256=observation.remote_observation_sha256,
        execution_nonce_sha256=plan.execution_nonce_sha256,
        development_task_sha256=plan.development_task_sha256,
        candidate_patch_sha256=plan.candidate_patch_sha256,
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
        fresh_remote_observation_sha256=fresh_digest_after,
        fresh_revalidated_at_utc=fresh_at,
        authorized_at_utc=authorized_at,
    )
    return ledger.commit(
        receipt=receipt,
        observation=observation,
        lock_payload=marker,
    )


def _canonical_ledger_root() -> Path:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_LEDGER
        elif os.name == "nt":
            path = _WINDOWS_LEDGER
        else:
            raise PilotExactTaskRemotePublicationAuthorizationError(
                "remote publication authorization is unsupported on this platform"
            )
        return _require_host_controlled_ledger_root(path)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "canonical remote publication authorization ledger is not host-admin controlled"
        ) from exc


def authorize_pilot_exact_task_remote_publication(
    remote_state_observation: PilotExactTaskRemoteStateObservationReceipt,
) -> PilotExactTaskRemotePublicationAuthorizationReceipt:
    """Host-pinned ADR-DC-049 entrypoint. Reserve exact publication authority only."""
    try:
        root = _canonical_ledger_root()
        ledger = _PilotExactTaskRemotePublicationAuthorizationLedger(root)
        return _authorize_verified_pilot_exact_task_remote_publication(
            remote_state_observation=remote_state_observation,
            ledger=ledger,
            observer=observation_boundary._GitHubReadOnlyObserver(),
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskRemotePublicationAuthorizationError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskRemotePublicationAuthorizationError(
            "host-controlled remote publication authorization failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_AUTHORIZATION_LEDGER_SCOPE",
    "PilotExactTaskRemotePublicationAuthorizationError",
    "PilotExactTaskRemotePublicationAuthorizationReceipt",
    "authorize_pilot_exact_task_remote_publication",
]
