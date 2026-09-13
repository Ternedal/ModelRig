"""Live continuous-main freeze proof for one DC-L15 physical campaign.

ADR-DC-013 closes only ``continuous_main_freeze_confirmation``. A freeze lease
is process-local, identity-bound authority that must be armed before runner
execution begins and remain live through the post-campaign evidence and exact
runner execution-binding steps. The final proof is serializable evidence; the
lease is intentionally not.

The generic implementation keeps watcher/observer seams private for adversarial
tests. The public production facade replaces them with the host-controlled
Trusted-Git reader and the OS-backed Git-ref watcher.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from .improvement_physical_campaign_admission import PhysicalCampaignAdmission
from .improvement_physical_campaign_execution_binding import (
    PhysicalCampaignExecutionProof,
)
from .improvement_physical_reservation import LocalMainHeadObservation

MAIN_FREEZE_PROOF_SCHEMA = "kaliv-rsi-physical-campaign-main-freeze-proof/v1"
MAIN_FREEZE_PROOF_AUTHORITY = "verified-continuous-main-freeze-only"
REMAINING_COMPLETION_GATES = (
    "dc_l14_independent_human_verdict",
    "human_pilot_go_decision",
)
_MAX_ARM_DELAY = timedelta(minutes=2)
_MAX_FREEZE_DURATION = timedelta(hours=1)
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PhysicalCampaignMainFreezeError(ValueError):
    """The live continuous-main freeze boundary is absent, stale or over-authorizing."""


class _Watcher(Protocol):
    @property
    def backend(self) -> str: ...

    @property
    def scope(self) -> tuple[str, ...]: ...

    def arm(self) -> None: ...

    def clean(self) -> bool: ...

    def close(self) -> None: ...


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
        raise PhysicalCampaignMainFreezeError(
            "physical campaign main-freeze proof is not canonical JSON"
        ) from exc


def _hex(value: Any, *, name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PhysicalCampaignMainFreezeError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise PhysicalCampaignMainFreezeError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PhysicalCampaignMainFreezeError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PhysicalCampaignMainFreezeError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _path_sha256(path: Path) -> str:
    return hashlib.sha256(os.fsencode(os.fspath(Path(path).resolve()))).hexdigest()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PhysicalCampaignMainFreezeLease:
    """Process-local live watcher capability. It is deliberately not serializable."""

    admission_sha256: str
    campaign_id: str
    task_id: str
    task_sha256: str
    repository: str
    base_sha: str
    requested_main_sha: str
    freeze_started_at_utc: str
    start_observation_sha256: str
    start_observed_main_sha: str
    repository_root_path_sha256: str
    git_runtime_manifest_sha256: str
    git_executable_sha256: str
    watch_backend: str
    watch_scope: tuple[str, ...]
    _watcher: Any = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        for name, value, pattern in (
            ("admission_sha256", self.admission_sha256, _HEX64),
            ("task_sha256", self.task_sha256, _HEX64),
            ("base_sha", self.base_sha, _HEX40),
            ("requested_main_sha", self.requested_main_sha, _HEX40),
            ("start_observation_sha256", self.start_observation_sha256, _HEX64),
            ("start_observed_main_sha", self.start_observed_main_sha, _HEX40),
            ("repository_root_path_sha256", self.repository_root_path_sha256, _HEX64),
            ("git_runtime_manifest_sha256", self.git_runtime_manifest_sha256, _HEX64),
            ("git_executable_sha256", self.git_executable_sha256, _HEX64),
        ):
            _hex(value, name=name, pattern=pattern)
        _identifier(self.campaign_id, name="campaign_id")
        if not isinstance(self.task_id, str) or not 1 <= len(self.task_id) <= 64:
            raise PhysicalCampaignMainFreezeError("task_id is invalid")
        if self.repository != "Ternedal/ModelRig":
            raise PhysicalCampaignMainFreezeError("repository is unsupported")
        _utc(self.freeze_started_at_utc, name="freeze_started_at_utc")
        if self.start_observed_main_sha != self.requested_main_sha:
            raise PhysicalCampaignMainFreezeError("freeze start main does not match requested main")
        if self.watch_backend not in {"inotify", "ReadDirectoryChangesW"}:
            raise PhysicalCampaignMainFreezeError("main-freeze watcher backend is unsupported")
        if (
            not isinstance(self.watch_scope, tuple)
            or not self.watch_scope
            or tuple(sorted(set(self.watch_scope))) != self.watch_scope
        ):
            raise PhysicalCampaignMainFreezeError("main-freeze watcher scope is invalid")
        if self._watcher is None:
            raise PhysicalCampaignMainFreezeError("main-freeze watcher is unavailable")

    def _identity_dict(self) -> dict[str, Any]:
        return {
            "admission_sha256": self.admission_sha256,
            "campaign_id": self.campaign_id,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "requested_main_sha": self.requested_main_sha,
            "freeze_started_at_utc": self.freeze_started_at_utc,
            "start_observation_sha256": self.start_observation_sha256,
            "start_observed_main_sha": self.start_observed_main_sha,
            "repository_root_path_sha256": self.repository_root_path_sha256,
            "git_runtime_manifest_sha256": self.git_runtime_manifest_sha256,
            "git_executable_sha256": self.git_executable_sha256,
            "watch_backend": self.watch_backend,
            "watch_scope": list(self.watch_scope),
        }

    @property
    def identity_sha256(self) -> str:
        return hashlib.sha256(_canonical(self._identity_dict()).encode("utf-8")).hexdigest()

    @property
    def transaction_authenticated(self) -> bool:
        return _lease_is_live(self)


_LEASES: dict[int, tuple[int, str, weakref.ReferenceType[PhysicalCampaignMainFreezeLease]]] = {}


def _register_lease(lease: PhysicalCampaignMainFreezeLease) -> None:
    identity = id(lease)

    def discard(reference: Any, *, identity: int = identity) -> None:
        entry = _LEASES.get(identity)
        if entry is not None and entry[2] is reference:
            _LEASES.pop(identity, None)

    _LEASES[identity] = (
        os.getpid(),
        lease.identity_sha256,
        weakref.ref(lease, discard),
    )


def _lease_is_live(lease: Any) -> bool:
    if type(lease) is not PhysicalCampaignMainFreezeLease:
        return False
    entry = _LEASES.get(id(lease))
    if entry is None:
        return False
    pid, digest, reference = entry
    if pid != os.getpid() or reference() is not lease:
        return False
    try:
        return lease.identity_sha256 == digest
    except (AttributeError, TypeError, ValueError):
        return False


def _consume_lease(lease: Any) -> None:
    if type(lease) is PhysicalCampaignMainFreezeLease:
        _LEASES.pop(id(lease), None)


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_LEASES.clear)


_PROOF_FIELDS = {
    "schema",
    "admission_sha256",
    "execution_proof_sha256",
    "evidence_snapshot_sha256",
    "campaign_id",
    "task_id",
    "task_sha256",
    "repository",
    "base_sha",
    "requested_main_sha",
    "freeze_started_at_utc",
    "freeze_finalized_at_utc",
    "start_observation_sha256",
    "end_observation_sha256",
    "start_observed_main_sha",
    "end_observed_main_sha",
    "repository_root_path_sha256",
    "git_runtime_manifest_sha256",
    "git_executable_sha256",
    "watch_backend",
    "watch_scope",
    "exact_main_ref_history_monitored",
    "loose_main_ref_mutation_absent",
    "packed_refs_mutation_absent",
    "watcher_loss_absent",
    "main_sha_stable",
    "runner_execution_binding_proven",
    "continuous_main_freeze_proven",
    "physical_campaign_completed",
    "dc_l15_complete",
    "dc_l14_independent_human_verdict_required",
    "human_pilot_go_required",
    "pilot_go_authorized",
    "activation_authorized",
    "remote_publication_authorized",
    "remaining_completion_gates",
    "authority",
}


@dataclass(frozen=True, slots=True)
class PhysicalCampaignMainFreezeProof:
    admission_sha256: str
    execution_proof_sha256: str
    evidence_snapshot_sha256: str
    campaign_id: str
    task_id: str
    task_sha256: str
    repository: str
    base_sha: str
    requested_main_sha: str
    freeze_started_at_utc: str
    freeze_finalized_at_utc: str
    start_observation_sha256: str
    end_observation_sha256: str
    start_observed_main_sha: str
    end_observed_main_sha: str
    repository_root_path_sha256: str
    git_runtime_manifest_sha256: str
    git_executable_sha256: str
    watch_backend: str
    watch_scope: tuple[str, ...]
    exact_main_ref_history_monitored: bool = True
    loose_main_ref_mutation_absent: bool = True
    packed_refs_mutation_absent: bool = True
    watcher_loss_absent: bool = True
    main_sha_stable: bool = True
    runner_execution_binding_proven: bool = True
    continuous_main_freeze_proven: bool = True
    physical_campaign_completed: bool = False
    dc_l15_complete: bool = False
    dc_l14_independent_human_verdict_required: bool = True
    human_pilot_go_required: bool = True
    pilot_go_authorized: bool = False
    activation_authorized: bool = False
    remote_publication_authorized: bool = False
    remaining_completion_gates: tuple[str, ...] = REMAINING_COMPLETION_GATES
    authority: str = MAIN_FREEZE_PROOF_AUTHORITY
    schema: str = MAIN_FREEZE_PROOF_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != MAIN_FREEZE_PROOF_SCHEMA:
            raise PhysicalCampaignMainFreezeError("main-freeze proof schema is unsupported")
        for name, value, pattern in (
            ("admission_sha256", self.admission_sha256, _HEX64),
            ("execution_proof_sha256", self.execution_proof_sha256, _HEX64),
            ("evidence_snapshot_sha256", self.evidence_snapshot_sha256, _HEX64),
            ("task_sha256", self.task_sha256, _HEX64),
            ("base_sha", self.base_sha, _HEX40),
            ("requested_main_sha", self.requested_main_sha, _HEX40),
            ("start_observation_sha256", self.start_observation_sha256, _HEX64),
            ("end_observation_sha256", self.end_observation_sha256, _HEX64),
            ("start_observed_main_sha", self.start_observed_main_sha, _HEX40),
            ("end_observed_main_sha", self.end_observed_main_sha, _HEX40),
            ("repository_root_path_sha256", self.repository_root_path_sha256, _HEX64),
            ("git_runtime_manifest_sha256", self.git_runtime_manifest_sha256, _HEX64),
            ("git_executable_sha256", self.git_executable_sha256, _HEX64),
        ):
            _hex(value, name=name, pattern=pattern)
        _identifier(self.campaign_id, name="campaign_id")
        if not isinstance(self.task_id, str) or not 1 <= len(self.task_id) <= 64:
            raise PhysicalCampaignMainFreezeError("task_id is invalid")
        if self.repository != "Ternedal/ModelRig":
            raise PhysicalCampaignMainFreezeError("repository is unsupported")
        started = _utc(self.freeze_started_at_utc, name="freeze_started_at_utc")
        finalized = _utc(self.freeze_finalized_at_utc, name="freeze_finalized_at_utc")
        if finalized <= started or finalized - started > _MAX_FREEZE_DURATION:
            raise PhysicalCampaignMainFreezeError("main-freeze proof duration is invalid")
        if (
            self.start_observed_main_sha != self.requested_main_sha
            or self.end_observed_main_sha != self.requested_main_sha
        ):
            raise PhysicalCampaignMainFreezeError("main-freeze proof main SHA is not stable")
        if self.watch_backend not in {"inotify", "ReadDirectoryChangesW"}:
            raise PhysicalCampaignMainFreezeError("main-freeze proof watcher backend is unsupported")
        if (
            not isinstance(self.watch_scope, tuple)
            or not self.watch_scope
            or tuple(sorted(set(self.watch_scope))) != self.watch_scope
        ):
            raise PhysicalCampaignMainFreezeError("main-freeze proof watcher scope is invalid")
        if (
            self.exact_main_ref_history_monitored is not True
            or self.loose_main_ref_mutation_absent is not True
            or self.packed_refs_mutation_absent is not True
            or self.watcher_loss_absent is not True
            or self.main_sha_stable is not True
            or self.runner_execution_binding_proven is not True
            or self.continuous_main_freeze_proven is not True
            or self.physical_campaign_completed is not False
            or self.dc_l15_complete is not False
            or self.dc_l14_independent_human_verdict_required is not True
            or self.human_pilot_go_required is not True
            or self.pilot_go_authorized is not False
            or self.activation_authorized is not False
            or self.remote_publication_authorized is not False
            or self.remaining_completion_gates != REMAINING_COMPLETION_GATES
            or self.authority != MAIN_FREEZE_PROOF_AUTHORITY
        ):
            raise PhysicalCampaignMainFreezeError("main-freeze proof authority boundary is invalid")

    @classmethod
    def from_mapping(cls, value: Any) -> "PhysicalCampaignMainFreezeProof":
        if not isinstance(value, Mapping) or set(value) != _PROOF_FIELDS:
            raise PhysicalCampaignMainFreezeError("main-freeze proof fields mismatch")
        kwargs = dict(value)
        scope = kwargs.get("watch_scope")
        remaining = kwargs.get("remaining_completion_gates")
        if not isinstance(scope, list) or not isinstance(remaining, list):
            raise PhysicalCampaignMainFreezeError("main-freeze proof arrays are invalid")
        kwargs["watch_scope"] = tuple(scope)
        kwargs["remaining_completion_gates"] = tuple(remaining)
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "admission_sha256": self.admission_sha256,
            "execution_proof_sha256": self.execution_proof_sha256,
            "evidence_snapshot_sha256": self.evidence_snapshot_sha256,
            "campaign_id": self.campaign_id,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "requested_main_sha": self.requested_main_sha,
            "freeze_started_at_utc": self.freeze_started_at_utc,
            "freeze_finalized_at_utc": self.freeze_finalized_at_utc,
            "start_observation_sha256": self.start_observation_sha256,
            "end_observation_sha256": self.end_observation_sha256,
            "start_observed_main_sha": self.start_observed_main_sha,
            "end_observed_main_sha": self.end_observed_main_sha,
            "repository_root_path_sha256": self.repository_root_path_sha256,
            "git_runtime_manifest_sha256": self.git_runtime_manifest_sha256,
            "git_executable_sha256": self.git_executable_sha256,
            "watch_backend": self.watch_backend,
            "watch_scope": list(self.watch_scope),
            "exact_main_ref_history_monitored": self.exact_main_ref_history_monitored,
            "loose_main_ref_mutation_absent": self.loose_main_ref_mutation_absent,
            "packed_refs_mutation_absent": self.packed_refs_mutation_absent,
            "watcher_loss_absent": self.watcher_loss_absent,
            "main_sha_stable": self.main_sha_stable,
            "runner_execution_binding_proven": self.runner_execution_binding_proven,
            "continuous_main_freeze_proven": self.continuous_main_freeze_proven,
            "physical_campaign_completed": self.physical_campaign_completed,
            "dc_l15_complete": self.dc_l15_complete,
            "dc_l14_independent_human_verdict_required": self.dc_l14_independent_human_verdict_required,
            "human_pilot_go_required": self.human_pilot_go_required,
            "pilot_go_authorized": self.pilot_go_authorized,
            "activation_authorized": self.activation_authorized,
            "remote_publication_authorized": self.remote_publication_authorized,
            "remaining_completion_gates": list(self.remaining_completion_gates),
            "authority": self.authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _validate_observation(
    observation: LocalMainHeadObservation,
    *,
    admission: PhysicalCampaignAdmission,
    observed_at_utc: str,
    repository_root_path_sha256: str,
    git_runtime_manifest_sha256: str,
    git_executable_sha256: str,
) -> None:
    if type(observation) is not LocalMainHeadObservation:
        raise PhysicalCampaignMainFreezeError("main-freeze observation type is invalid")
    if (
        observation.repository != admission.repository
        or observation.repository_root_path_sha256 != repository_root_path_sha256
        or observation.observed_sha != admission.requested_main_sha
        or observation.observed_at_utc != observed_at_utc
        or observation.git_runtime_manifest_sha256 != git_runtime_manifest_sha256
        or observation.git_executable_sha256 != git_executable_sha256
        or observation.network_performed is not False
        or observation.repository_mutated is not False
    ):
        raise PhysicalCampaignMainFreezeError(
            "main-freeze observation is not exactly bound to admission/runtime"
        )


def _begin_physical_campaign_main_freeze(
    *,
    admission: PhysicalCampaignAdmission,
    admission_authenticated: bool,
    repository_root: Path,
    git_runtime_manifest_sha256: str,
    git_executable_sha256: str,
    watcher_factory: Callable[[Path], _Watcher],
    observe_main: Callable[[str], LocalMainHeadObservation],
    now_provider: Callable[[], str] = _now_utc_seconds,
) -> PhysicalCampaignMainFreezeLease:
    if type(admission) is not PhysicalCampaignAdmission:
        raise PhysicalCampaignMainFreezeError("main-freeze begin requires exact campaign admission")
    if admission_authenticated is not True:
        raise PhysicalCampaignMainFreezeError("main-freeze begin requires live authenticated admission")
    root = Path(repository_root).resolve()
    root_sha = _path_sha256(root)
    if root_sha != admission.repository_root_path_sha256:
        raise PhysicalCampaignMainFreezeError("main-freeze repository root does not match admission")
    if (
        git_runtime_manifest_sha256 != admission.git_runtime_manifest_sha256
        or git_executable_sha256 != admission.git_executable_sha256
    ):
        raise PhysicalCampaignMainFreezeError("main-freeze Git runtime does not match admission")

    watcher = watcher_factory(root)
    armed = False
    try:
        watcher.arm()
        armed = True
        if not watcher.clean():
            raise PhysicalCampaignMainFreezeError("main-freeze watcher changed while arming")
        started_at = now_provider()
        admitted = _utc(admission.admitted_at_utc, name="admitted_at_utc")
        started = _utc(started_at, name="freeze_started_at_utc")
        if started < admitted or started - admitted > _MAX_ARM_DELAY:
            raise PhysicalCampaignMainFreezeError("main-freeze watcher was armed too late")
        observation = observe_main(started_at)
        if not watcher.clean():
            raise PhysicalCampaignMainFreezeError("main changed while freeze start was observed")
        _validate_observation(
            observation,
            admission=admission,
            observed_at_utc=started_at,
            repository_root_path_sha256=root_sha,
            git_runtime_manifest_sha256=git_runtime_manifest_sha256,
            git_executable_sha256=git_executable_sha256,
        )
        scope = tuple(sorted(set(watcher.scope)))
        lease = PhysicalCampaignMainFreezeLease(
            admission_sha256=admission.sha256,
            campaign_id=admission.campaign_id,
            task_id=admission.task_id,
            task_sha256=admission.task_sha256,
            repository=admission.repository,
            base_sha=admission.base_sha,
            requested_main_sha=admission.requested_main_sha,
            freeze_started_at_utc=started_at,
            start_observation_sha256=observation.sha256,
            start_observed_main_sha=observation.observed_sha,
            repository_root_path_sha256=root_sha,
            git_runtime_manifest_sha256=git_runtime_manifest_sha256,
            git_executable_sha256=git_executable_sha256,
            watch_backend=watcher.backend,
            watch_scope=scope,
            _watcher=watcher,
        )
        _register_lease(lease)
        return lease
    except BaseException:
        if armed:
            try:
                watcher.close()
            except Exception:
                pass
        raise


def _execution_proof_matches(
    lease: PhysicalCampaignMainFreezeLease,
    proof: PhysicalCampaignExecutionProof,
) -> None:
    if type(proof) is not PhysicalCampaignExecutionProof:
        raise PhysicalCampaignMainFreezeError("main-freeze finalization requires exact execution proof")
    if (
        proof.admission_sha256 != lease.admission_sha256
        or proof.campaign_id != lease.campaign_id
        or proof.task_id != lease.task_id
        or proof.task_sha256 != lease.task_sha256
        or proof.repository != lease.repository
        or proof.base_sha != lease.base_sha
        or proof.requested_main_sha != lease.requested_main_sha
        or proof.runner_execution_binding_proven is not True
        or proof.continuous_main_freeze_proven is not False
        or proof.physical_campaign_completed is not False
        or proof.dc_l15_complete is not False
        or proof.pilot_go_authorized is not False
        or proof.activation_authorized is not False
        or proof.remote_publication_authorized is not False
    ):
        raise PhysicalCampaignMainFreezeError(
            "execution proof is not exactly bound to the live main-freeze lease"
        )


def _finalize_physical_campaign_main_freeze(
    *,
    lease: PhysicalCampaignMainFreezeLease,
    execution_proof: PhysicalCampaignExecutionProof,
    observe_main: Callable[[str], LocalMainHeadObservation],
    now_provider: Callable[[], str] = _now_utc_seconds,
) -> PhysicalCampaignMainFreezeProof:
    if not _lease_is_live(lease):
        raise PhysicalCampaignMainFreezeError("main-freeze lease is not live transaction authority")
    _execution_proof_matches(lease, execution_proof)
    watcher = lease._watcher
    try:
        started = _utc(lease.freeze_started_at_utc, name="freeze_started_at_utc")
        execution_started = _utc(
            execution_proof.execution_started_at_utc,
            name="execution_started_at_utc",
        )
        execution_completed = _utc(
            execution_proof.execution_completed_at_utc,
            name="execution_completed_at_utc",
        )
        verified = _utc(execution_proof.verified_at_utc, name="verified_at_utc")
        finalized_at = now_provider()
        finalized = _utc(finalized_at, name="freeze_finalized_at_utc")
        if not (started <= execution_started < execution_completed <= verified <= finalized):
            raise PhysicalCampaignMainFreezeError(
                "execution interval is not enclosed by the live main-freeze lease"
            )
        if finalized - started > _MAX_FREEZE_DURATION:
            raise PhysicalCampaignMainFreezeError("main-freeze lease exceeded its maximum duration")
        if not watcher.clean():
            raise PhysicalCampaignMainFreezeError("main-freeze watcher observed a Git ref mutation")
        observation = observe_main(finalized_at)
        if not watcher.clean():
            raise PhysicalCampaignMainFreezeError(
                "main changed while freeze finalization was observed"
            )
        if (
            observation.repository != lease.repository
            or observation.repository_root_path_sha256 != lease.repository_root_path_sha256
            or observation.observed_sha != lease.requested_main_sha
            or observation.observed_at_utc != finalized_at
            or observation.git_runtime_manifest_sha256 != lease.git_runtime_manifest_sha256
            or observation.git_executable_sha256 != lease.git_executable_sha256
            or observation.network_performed is not False
            or observation.repository_mutated is not False
        ):
            raise PhysicalCampaignMainFreezeError(
                "main-freeze final observation is not exactly bound to the lease"
            )
        return PhysicalCampaignMainFreezeProof(
            admission_sha256=lease.admission_sha256,
            execution_proof_sha256=execution_proof.sha256,
            evidence_snapshot_sha256=execution_proof.evidence_snapshot_sha256,
            campaign_id=lease.campaign_id,
            task_id=lease.task_id,
            task_sha256=lease.task_sha256,
            repository=lease.repository,
            base_sha=lease.base_sha,
            requested_main_sha=lease.requested_main_sha,
            freeze_started_at_utc=lease.freeze_started_at_utc,
            freeze_finalized_at_utc=finalized_at,
            start_observation_sha256=lease.start_observation_sha256,
            end_observation_sha256=observation.sha256,
            start_observed_main_sha=lease.start_observed_main_sha,
            end_observed_main_sha=observation.observed_sha,
            repository_root_path_sha256=lease.repository_root_path_sha256,
            git_runtime_manifest_sha256=lease.git_runtime_manifest_sha256,
            git_executable_sha256=lease.git_executable_sha256,
            watch_backend=lease.watch_backend,
            watch_scope=lease.watch_scope,
        )
    finally:
        _consume_lease(lease)
        try:
            watcher.close()
        except Exception:
            pass


def _abort_physical_campaign_main_freeze(
    *,
    lease: PhysicalCampaignMainFreezeLease,
) -> None:
    if type(lease) is not PhysicalCampaignMainFreezeLease:
        raise PhysicalCampaignMainFreezeError("main-freeze abort requires exact lease")
    _consume_lease(lease)
    try:
        lease._watcher.close()
    except Exception as exc:
        raise PhysicalCampaignMainFreezeError("main-freeze watcher could not be closed") from exc


def begin_physical_campaign_main_freeze(*, trusted_git: Any, admission: PhysicalCampaignAdmission) -> PhysicalCampaignMainFreezeLease:
    del trusted_git, admission
    raise PhysicalCampaignMainFreezeError("production main-freeze boundary is not installed")


def finalize_physical_campaign_main_freeze(
    *,
    trusted_git: Any,
    lease: PhysicalCampaignMainFreezeLease,
    execution_proof: PhysicalCampaignExecutionProof,
) -> PhysicalCampaignMainFreezeProof:
    del trusted_git, lease, execution_proof
    raise PhysicalCampaignMainFreezeError("production main-freeze boundary is not installed")


def abort_physical_campaign_main_freeze(*, lease: PhysicalCampaignMainFreezeLease) -> None:
    _abort_physical_campaign_main_freeze(lease=lease)


__all__: list[str] = []
