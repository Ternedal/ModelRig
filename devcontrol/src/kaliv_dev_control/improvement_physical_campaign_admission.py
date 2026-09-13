"""Authenticated one-shot admission for one manual DC-L15 physical campaign.

This is the first RSI boundary allowed to say ``campaign_start_authorized=true``.
That authority is deliberately narrow. A caller must present the exact live
transaction-authenticated reservation returned by the ADR-DC-009 consume
transaction plus a separate human-signed exact runner authorization. Caller-owned
authority inputs are snapshotted into exact local value objects, the staged Git
runtime is copied into a transaction-private runtime, and the public path derives
host/repository/clock state itself before re-reading ``refs/heads/main`` and the
exact signed runner bytes.

Persisted admission bytes are replay/recovery evidence only. Deserializing them
never recreates transaction authority. Transaction provenance is held in a
process-local weakref registry bound to exact object identity, canonical digest,
originating PID, and the exact current bytes of both the final admission and its
permanent replay marker. This module does not execute the runner, run a probe,
prove continuous main freeze, complete DC-L15, grant pilot GO, or grant
publication/merge/release/deploy/activation authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import weakref
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping

from .asymmetric_authority import (
    AsymmetricAuthorityError,
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
)
from .catalog import IsolationBoundary, NetworkMode
from .durable_publication import (
    DurablePublicationError,
    create_once_file,
    remove_tree_durable,
    unlink_durable,
)
from .improvement_candidate_snapshot import CandidateSnapshotReceipt
from .improvement_physical_reservation import (
    PhysicalQualificationReservation,
    _canonical_host_state_root,
    _canonical_repository_root,
    _ensure_link_free_directory,
    _now_utc_seconds,
    _path_sha256,
    _read_bound_file,
    observe_local_main_head,
)
from .improvement_qualification_packet import QualificationPacket
from .physical_isolation import REPORT_SCHEMA, REQUIRED_PROBES, _stable_regular_read
from .trusted_git_runtime_model import _has_linkish_component
from .trusted_git_runtime_staging import TrustedGitRuntime, stage_trusted_git_runtime

RUNNER_AUTHORIZATION_SCHEMA = "kaliv-rsi-physical-campaign-runner-authorization/v1"
RUNNER_AUTHORIZATION_AUTHORITY = "human-signed-runner-pin-only"
RUNNER_AUTHORIZATION_SCOPE = "dc-l15-single-campaign-runner-pin"
RUNNER_AUTHORIZATION_ISSUER_SYSTEM_ID = "kaliv-rsi-dc-l15-runner-authority-v1"
CAMPAIGN_ADMISSION_SCHEMA = "kaliv-rsi-physical-campaign-admission/v1"
CAMPAIGN_ADMISSION_AUTHORITY = "single-physical-campaign-start-only"
CAMPAIGN_LEDGER_SCOPE = "canonical-host-local-v1"
HOST_SCOPE_SCHEMA = "kaliv-rsi-physical-host-scope/v1"
_MAX_AUTHORIZATION_WINDOW = timedelta(minutes=15)
_MAX_RESERVATION_AGE = timedelta(minutes=15)
_MAX_MAIN_OBSERVATION_AGE = timedelta(minutes=1)
_MAX_ARTIFACT_BYTES = 256 * 1024
# Keep this exactly within physical_isolation._stable_regular_read's hardened
# maximum. Admission must narrow to the established reader boundary, never widen it.
_MAX_RUNNER_BYTES = 16_000_000

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


class PhysicalCampaignAdmissionError(ValueError):
    """The requested DC-L15 campaign admission is not authentic or bounded."""


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
        raise PhysicalCampaignAdmissionError(
            "physical campaign admission is not canonical JSON"
        ) from exc


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _strict(value: Any, *, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PhysicalCampaignAdmissionError(f"{name} fields mismatch")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise PhysicalCampaignAdmissionError(f"{name} is invalid")
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
        raise PhysicalCampaignAdmissionError(f"{name} is invalid")
    return value


def _hex(value: Any, *, name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PhysicalCampaignAdmissionError(f"{name} is invalid")
    return value


def _integer(value: Any, *, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise PhysicalCampaignAdmissionError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PhysicalCampaignAdmissionError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PhysicalCampaignAdmissionError(f"{name} is invalid") from exc


def _runner_relative_path(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value.encode("utf-8")) > 512
        or "\\" in value
        or "\x00" in value
        or ":" in value
    ):
        raise PhysicalCampaignAdmissionError("runner_relative_path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or value != path.as_posix():
        raise PhysicalCampaignAdmissionError("runner_relative_path is invalid")
    parts = path.parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise PhysicalCampaignAdmissionError("runner_relative_path is invalid")
    for part in parts:
        if part.endswith((".", " ")):
            raise PhysicalCampaignAdmissionError("runner_relative_path is invalid")
        device = part.split(".", 1)[0].casefold()
        if device in _WINDOWS_RESERVED:
            raise PhysicalCampaignAdmissionError("runner_relative_path is invalid")
    return value


def _required_probe_names() -> tuple[str, ...]:
    return tuple(probe.value for probe in REQUIRED_PROBES)


def _canonical_campaign_ledger_root() -> Path:
    return _ensure_link_free_directory(
        _canonical_host_state_root() / "rsi-physical-campaign-admission-ledger-v1",
        name="canonical physical campaign admission ledger",
    )


def _canonical_campaign_operation_root() -> Path:
    return _ensure_link_free_directory(
        _canonical_host_state_root() / "rsi-physical-campaign-git-operation-v1",
        name="canonical physical campaign Git operation root",
    )


def _transaction_identity_registry():
    """Bind live provenance to identity, contents, process and exact replay markers."""

    references: dict[int, tuple[int, str, Path, bytes, Path, bytes, Any]] = {}

    def mark(
        value: Any,
        *,
        final_path: Path,
        final_payload: bytes,
        lock_path: Path,
        lock_payload: bytes,
    ) -> None:
        if (
            _read_bound_file(final_path, maximum=_MAX_ARTIFACT_BYTES) != final_payload
            or _read_bound_file(lock_path, maximum=_MAX_ARTIFACT_BYTES) != lock_payload
        ):
            raise PhysicalCampaignAdmissionError(
                "campaign admission replay markers changed before provenance registration"
            )
        identity = id(value)
        origin_pid = os.getpid()
        authenticated_sha256 = value.sha256

        def discard(reference: Any, *, identity: int = identity) -> None:
            entry = references.get(identity)
            if entry is not None and entry[6] is reference:
                references.pop(identity, None)

        references[identity] = (
            origin_pid,
            authenticated_sha256,
            Path(final_path),
            bytes(final_payload),
            Path(lock_path),
            bytes(lock_payload),
            weakref.ref(value, discard),
        )

    def contains(value: Any) -> bool:
        entry = references.get(id(value))
        if entry is None:
            return False
        (
            origin_pid,
            authenticated_sha256,
            final_path,
            final_payload,
            lock_path,
            lock_payload,
            reference,
        ) = entry
        if origin_pid != os.getpid() or reference() is not value:
            return False
        try:
            if value.sha256 != authenticated_sha256:
                return False
        except (AttributeError, TypeError, ValueError):
            return False
        return (
            _read_bound_file(final_path, maximum=_MAX_ARTIFACT_BYTES) == final_payload
            and _read_bound_file(lock_path, maximum=_MAX_ARTIFACT_BYTES) == lock_payload
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=references.clear)

    return mark, contains


_mark_admission_transaction_authenticated, _is_admission_transaction_authenticated = (
    _transaction_identity_registry()
)


def reservation_host_scope_sha256(reservation: PhysicalQualificationReservation) -> str:
    """Hash the parent reservation's host-local scope without claiming global identity."""

    if not isinstance(reservation, PhysicalQualificationReservation):
        raise PhysicalCampaignAdmissionError("host scope requires reservation evidence")
    value = {
        "schema": HOST_SCOPE_SCHEMA,
        "ledger_scope": reservation.ledger_scope,
        "ledger_root_path_sha256": reservation.ledger_root_path_sha256,
        "repository_root_path_sha256": reservation.repository_root_path_sha256,
        "snapshot_receipt_sha256": reservation.snapshot_receipt_sha256,
        "git_runtime_manifest_sha256": reservation.git_runtime_manifest_sha256,
        "git_executable_sha256": reservation.git_executable_sha256,
        "request_sha256": reservation.request_sha256,
    }
    return _sha256_text(_canonical(value))


_RUNNER_AUTH_FIELDS = {
    "schema",
    "authorization_id",
    "reservation_sha256",
    "host_scope_sha256",
    "request_sha256",
    "qualification_packet_sha256",
    "snapshot_receipt_sha256",
    "campaign_id",
    "proposal_id",
    "task_id",
    "task_sha256",
    "repository",
    "base_sha",
    "requested_main_sha",
    "runner_relative_path",
    "runner_sha256",
    "runner_bytes",
    "required_operator_actor_id",
    "required_approver_actor_id",
    "required_report_schema",
    "required_boundary",
    "required_network_mode",
    "required_probes",
    "authorized_at_utc",
    "expires_at_utc",
    "automatic_start",
    "pilot_go_authorized",
    "activation_authorized",
    "remote_publication_authorized",
    "authority",
    "scope",
}


@dataclass(frozen=True, slots=True)
class PhysicalCampaignRunnerAuthorization:
    authorization_id: str
    reservation_sha256: str
    host_scope_sha256: str
    request_sha256: str
    qualification_packet_sha256: str
    snapshot_receipt_sha256: str
    campaign_id: str
    proposal_id: str
    task_id: str
    task_sha256: str
    repository: str
    base_sha: str
    requested_main_sha: str
    runner_relative_path: str
    runner_sha256: str
    runner_bytes: int
    required_operator_actor_id: str
    required_approver_actor_id: str
    authorized_at_utc: str
    expires_at_utc: str
    required_probes: tuple[str, ...] = _required_probe_names()
    required_report_schema: str = REPORT_SCHEMA
    required_boundary: str = IsolationBoundary.OS_ISOLATED.value
    required_network_mode: str = NetworkMode.DENY.value
    automatic_start: bool = False
    pilot_go_authorized: bool = False
    activation_authorized: bool = False
    remote_publication_authorized: bool = False
    authority: str = RUNNER_AUTHORIZATION_AUTHORITY
    scope: str = RUNNER_AUTHORIZATION_SCOPE
    schema: str = RUNNER_AUTHORIZATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != RUNNER_AUTHORIZATION_SCHEMA:
            raise PhysicalCampaignAdmissionError("runner authorization schema is unsupported")
        _identifier(self.authorization_id, name="authorization_id")
        _identifier(self.campaign_id, name="campaign_id")
        for name, value, pattern in (
            ("reservation_sha256", self.reservation_sha256, _HEX64),
            ("host_scope_sha256", self.host_scope_sha256, _HEX64),
            ("request_sha256", self.request_sha256, _HEX64),
            ("qualification_packet_sha256", self.qualification_packet_sha256, _HEX64),
            ("snapshot_receipt_sha256", self.snapshot_receipt_sha256, _HEX64),
            ("task_sha256", self.task_sha256, _HEX64),
            ("base_sha", self.base_sha, _HEX40),
            ("requested_main_sha", self.requested_main_sha, _HEX40),
            ("runner_sha256", self.runner_sha256, _HEX64),
        ):
            _hex(value, name=name, pattern=pattern)
        if self.repository != "Ternedal/ModelRig":
            raise PhysicalCampaignAdmissionError("runner authorization repository is unsupported")
        if not isinstance(self.proposal_id, str) or not self.proposal_id:
            raise PhysicalCampaignAdmissionError("proposal_id is invalid")
        if not isinstance(self.task_id, str) or not self.task_id:
            raise PhysicalCampaignAdmissionError("task_id is invalid")
        _runner_relative_path(self.runner_relative_path)
        _integer(self.runner_bytes, name="runner_bytes", low=1, high=_MAX_RUNNER_BYTES)
        operator = _actor(self.required_operator_actor_id, name="required_operator_actor_id")
        approver = _actor(self.required_approver_actor_id, name="required_approver_actor_id")
        if operator == approver:
            raise PhysicalCampaignAdmissionError(
                "runner authorization operator and approver must be different actors"
            )
        authorized = _utc(self.authorized_at_utc, name="authorized_at_utc")
        expires = _utc(self.expires_at_utc, name="expires_at_utc")
        if expires <= authorized or expires - authorized > _MAX_AUTHORIZATION_WINDOW:
            raise PhysicalCampaignAdmissionError("runner authorization validity window is invalid")
        if self.required_report_schema != REPORT_SCHEMA:
            raise PhysicalCampaignAdmissionError("runner authorization report schema is unsupported")
        if self.required_boundary != IsolationBoundary.OS_ISOLATED.value:
            raise PhysicalCampaignAdmissionError("runner authorization must require OS isolation")
        if self.required_network_mode != NetworkMode.DENY.value:
            raise PhysicalCampaignAdmissionError("runner authorization must require network deny")
        if self.required_probes != _required_probe_names():
            raise PhysicalCampaignAdmissionError(
                "runner authorization must require the exact DC-L15 probe set"
            )
        if (
            self.automatic_start is not False
            or self.pilot_go_authorized is not False
            or self.activation_authorized is not False
            or self.remote_publication_authorized is not False
            or self.authority != RUNNER_AUTHORIZATION_AUTHORITY
            or self.scope != RUNNER_AUTHORIZATION_SCOPE
        ):
            raise PhysicalCampaignAdmissionError(
                "runner authorization authority/scope is invalid"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PhysicalCampaignRunnerAuthorization":
        data = _strict(value, fields=_RUNNER_AUTH_FIELDS, name="runner authorization")
        probes = data["required_probes"]
        if not isinstance(probes, list):
            raise PhysicalCampaignAdmissionError(
                "runner authorization required_probes must be an array"
            )
        kwargs = dict(data)
        kwargs["required_probes"] = tuple(probes)
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "authorization_id": self.authorization_id,
            "reservation_sha256": self.reservation_sha256,
            "host_scope_sha256": self.host_scope_sha256,
            "request_sha256": self.request_sha256,
            "qualification_packet_sha256": self.qualification_packet_sha256,
            "snapshot_receipt_sha256": self.snapshot_receipt_sha256,
            "campaign_id": self.campaign_id,
            "proposal_id": self.proposal_id,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "requested_main_sha": self.requested_main_sha,
            "runner_relative_path": self.runner_relative_path,
            "runner_sha256": self.runner_sha256,
            "runner_bytes": self.runner_bytes,
            "required_operator_actor_id": self.required_operator_actor_id,
            "required_approver_actor_id": self.required_approver_actor_id,
            "required_report_schema": self.required_report_schema,
            "required_boundary": self.required_boundary,
            "required_network_mode": self.required_network_mode,
            "required_probes": list(self.required_probes),
            "authorized_at_utc": self.authorized_at_utc,
            "expires_at_utc": self.expires_at_utc,
            "automatic_start": self.automatic_start,
            "pilot_go_authorized": self.pilot_go_authorized,
            "activation_authorized": self.activation_authorized,
            "remote_publication_authorized": self.remote_publication_authorized,
            "authority": self.authority,
            "scope": self.scope,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())


_ADMISSION_FIELDS = {
    "schema",
    "ledger_scope",
    "ledger_root_path_sha256",
    "host_scope_sha256",
    "reservation_sha256",
    "request_sha256",
    "qualification_packet_sha256",
    "snapshot_receipt_sha256",
    "runner_authorization_sha256",
    "runner_authorization_signature_sha256",
    "runner_authorizer_actor_id",
    "campaign_id",
    "proposal_id",
    "task_id",
    "task_sha256",
    "repository",
    "base_sha",
    "requested_main_sha",
    "pre_start_observation_sha256",
    "pre_start_observed_at_utc",
    "admitted_at_utc",
    "repository_root_path_sha256",
    "git_runtime_manifest_sha256",
    "git_executable_sha256",
    "runner_relative_path",
    "runner_sha256",
    "runner_bytes",
    "required_operator_actor_id",
    "required_approver_actor_id",
    "required_report_schema",
    "required_boundary",
    "required_network_mode",
    "required_probes",
    "human_runner_pin_verified",
    "host_admission_guard_committed",
    "manual_operator_required",
    "single_campaign_only",
    "automatic_start",
    "campaign_start_authorized",
    "physical_campaign_completed",
    "post_campaign_main_observation_required",
    "frozen_main_confirmed",
    "global_replay_safe",
    "pilot_go_authorized",
    "activation_authorized",
    "remote_publication_authorized",
    "authority",
    "merge_authority",
}


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PhysicalCampaignAdmission:
    """Parsed admission data; live provenance binds identity, digest, process and markers."""

    ledger_root_path_sha256: str
    host_scope_sha256: str
    reservation_sha256: str
    request_sha256: str
    qualification_packet_sha256: str
    snapshot_receipt_sha256: str
    runner_authorization_sha256: str
    runner_authorization_signature_sha256: str
    runner_authorizer_actor_id: str
    campaign_id: str
    proposal_id: str
    task_id: str
    task_sha256: str
    repository: str
    base_sha: str
    requested_main_sha: str
    pre_start_observation_sha256: str
    pre_start_observed_at_utc: str
    admitted_at_utc: str
    repository_root_path_sha256: str
    git_runtime_manifest_sha256: str
    git_executable_sha256: str
    runner_relative_path: str
    runner_sha256: str
    runner_bytes: int
    required_operator_actor_id: str
    required_approver_actor_id: str
    required_probes: tuple[str, ...]
    ledger_scope: str = CAMPAIGN_LEDGER_SCOPE
    required_report_schema: str = REPORT_SCHEMA
    required_boundary: str = IsolationBoundary.OS_ISOLATED.value
    required_network_mode: str = NetworkMode.DENY.value
    human_runner_pin_verified: bool = True
    host_admission_guard_committed: bool = True
    manual_operator_required: bool = True
    single_campaign_only: bool = True
    automatic_start: bool = False
    campaign_start_authorized: bool = True
    physical_campaign_completed: bool = False
    post_campaign_main_observation_required: bool = True
    frozen_main_confirmed: bool = False
    global_replay_safe: bool = False
    pilot_go_authorized: bool = False
    activation_authorized: bool = False
    remote_publication_authorized: bool = False
    authority: str = CAMPAIGN_ADMISSION_AUTHORITY
    merge_authority: str = "human"
    schema: str = CAMPAIGN_ADMISSION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != CAMPAIGN_ADMISSION_SCHEMA or self.ledger_scope != CAMPAIGN_LEDGER_SCOPE:
            raise PhysicalCampaignAdmissionError(
                "campaign admission schema/ledger scope is unsupported"
            )
        for name, value, pattern in (
            ("ledger_root_path_sha256", self.ledger_root_path_sha256, _HEX64),
            ("host_scope_sha256", self.host_scope_sha256, _HEX64),
            ("reservation_sha256", self.reservation_sha256, _HEX64),
            ("request_sha256", self.request_sha256, _HEX64),
            ("qualification_packet_sha256", self.qualification_packet_sha256, _HEX64),
            ("snapshot_receipt_sha256", self.snapshot_receipt_sha256, _HEX64),
            ("runner_authorization_sha256", self.runner_authorization_sha256, _HEX64),
            (
                "runner_authorization_signature_sha256",
                self.runner_authorization_signature_sha256,
                _HEX64,
            ),
            ("task_sha256", self.task_sha256, _HEX64),
            ("base_sha", self.base_sha, _HEX40),
            ("requested_main_sha", self.requested_main_sha, _HEX40),
            ("pre_start_observation_sha256", self.pre_start_observation_sha256, _HEX64),
            ("repository_root_path_sha256", self.repository_root_path_sha256, _HEX64),
            ("git_runtime_manifest_sha256", self.git_runtime_manifest_sha256, _HEX64),
            ("git_executable_sha256", self.git_executable_sha256, _HEX64),
            ("runner_sha256", self.runner_sha256, _HEX64),
        ):
            _hex(value, name=name, pattern=pattern)
        _identifier(self.campaign_id, name="campaign_id")
        if self.repository != "Ternedal/ModelRig":
            raise PhysicalCampaignAdmissionError(
                "campaign admission repository is unsupported"
            )
        if not isinstance(self.proposal_id, str) or not self.proposal_id:
            raise PhysicalCampaignAdmissionError("proposal_id is invalid")
        if not isinstance(self.task_id, str) or not self.task_id:
            raise PhysicalCampaignAdmissionError("task_id is invalid")
        _actor(self.runner_authorizer_actor_id, name="runner_authorizer_actor_id")
        operator = _actor(self.required_operator_actor_id, name="required_operator_actor_id")
        approver = _actor(self.required_approver_actor_id, name="required_approver_actor_id")
        if operator == approver:
            raise PhysicalCampaignAdmissionError(
                "campaign operator and approver must be different actors"
            )
        _runner_relative_path(self.runner_relative_path)
        _integer(self.runner_bytes, name="runner_bytes", low=1, high=_MAX_RUNNER_BYTES)
        observed = _utc(self.pre_start_observed_at_utc, name="pre_start_observed_at_utc")
        admitted = _utc(self.admitted_at_utc, name="admitted_at_utc")
        if observed > admitted or admitted - observed > _MAX_MAIN_OBSERVATION_AGE:
            raise PhysicalCampaignAdmissionError(
                "pre-start main observation is future-dated or stale"
            )
        if self.required_report_schema != REPORT_SCHEMA:
            raise PhysicalCampaignAdmissionError(
                "campaign admission report schema is unsupported"
            )
        if self.required_boundary != IsolationBoundary.OS_ISOLATED.value:
            raise PhysicalCampaignAdmissionError(
                "campaign admission must require OS isolation"
            )
        if self.required_network_mode != NetworkMode.DENY.value:
            raise PhysicalCampaignAdmissionError(
                "campaign admission must require network deny"
            )
        if self.required_probes != _required_probe_names():
            raise PhysicalCampaignAdmissionError(
                "campaign admission must require the exact DC-L15 probe set"
            )
        if (
            self.human_runner_pin_verified is not True
            or self.host_admission_guard_committed is not True
            or self.manual_operator_required is not True
            or self.single_campaign_only is not True
            or self.automatic_start is not False
            or self.campaign_start_authorized is not True
            or self.physical_campaign_completed is not False
            or self.post_campaign_main_observation_required is not True
            or self.frozen_main_confirmed is not False
            or self.global_replay_safe is not False
            or self.pilot_go_authorized is not False
            or self.activation_authorized is not False
            or self.remote_publication_authorized is not False
            or self.authority != CAMPAIGN_ADMISSION_AUTHORITY
            or self.merge_authority != "human"
        ):
            raise PhysicalCampaignAdmissionError(
                "campaign admission authority boundary is invalid"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PhysicalCampaignAdmission":
        """Parse schema-valid evidence without granting transaction provenance."""

        data = _strict(value, fields=_ADMISSION_FIELDS, name="physical campaign admission")
        probes = data["required_probes"]
        if not isinstance(probes, list):
            raise PhysicalCampaignAdmissionError(
                "campaign admission required_probes must be an array"
            )
        kwargs = dict(data)
        kwargs["required_probes"] = tuple(probes)
        return cls(**kwargs)

    @property
    def transaction_authenticated(self) -> bool:
        """True only while identity, PID, contents and exact replay markers remain bound."""

        return _is_admission_transaction_authenticated(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "ledger_scope": self.ledger_scope,
            "ledger_root_path_sha256": self.ledger_root_path_sha256,
            "host_scope_sha256": self.host_scope_sha256,
            "reservation_sha256": self.reservation_sha256,
            "request_sha256": self.request_sha256,
            "qualification_packet_sha256": self.qualification_packet_sha256,
            "snapshot_receipt_sha256": self.snapshot_receipt_sha256,
            "runner_authorization_sha256": self.runner_authorization_sha256,
            "runner_authorization_signature_sha256": self.runner_authorization_signature_sha256,
            "runner_authorizer_actor_id": self.runner_authorizer_actor_id,
            "campaign_id": self.campaign_id,
            "proposal_id": self.proposal_id,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "requested_main_sha": self.requested_main_sha,
            "pre_start_observation_sha256": self.pre_start_observation_sha256,
            "pre_start_observed_at_utc": self.pre_start_observed_at_utc,
            "admitted_at_utc": self.admitted_at_utc,
            "repository_root_path_sha256": self.repository_root_path_sha256,
            "git_runtime_manifest_sha256": self.git_runtime_manifest_sha256,
            "git_executable_sha256": self.git_executable_sha256,
            "runner_relative_path": self.runner_relative_path,
            "runner_sha256": self.runner_sha256,
            "runner_bytes": self.runner_bytes,
            "required_operator_actor_id": self.required_operator_actor_id,
            "required_approver_actor_id": self.required_approver_actor_id,
            "required_report_schema": self.required_report_schema,
            "required_boundary": self.required_boundary,
            "required_network_mode": self.required_network_mode,
            "required_probes": list(self.required_probes),
            "human_runner_pin_verified": self.human_runner_pin_verified,
            "host_admission_guard_committed": self.host_admission_guard_committed,
            "manual_operator_required": self.manual_operator_required,
            "single_campaign_only": self.single_campaign_only,
            "automatic_start": self.automatic_start,
            "campaign_start_authorized": self.campaign_start_authorized,
            "physical_campaign_completed": self.physical_campaign_completed,
            "post_campaign_main_observation_required": self.post_campaign_main_observation_required,
            "frozen_main_confirmed": self.frozen_main_confirmed,
            "global_replay_safe": self.global_replay_safe,
            "pilot_go_authorized": self.pilot_go_authorized,
            "activation_authorized": self.activation_authorized,
            "remote_publication_authorized": self.remote_publication_authorized,
            "authority": self.authority,
            "merge_authority": self.merge_authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())


class _PhysicalCampaignAdmissionLedger:
    """Private host-local create-once state; loads never recreate authority."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        if (
            not self.root.is_absolute()
            or not self.root.is_dir()
            or _has_linkish_component(self.root)
        ):
            raise PhysicalCampaignAdmissionError(
                "physical campaign admission ledger root is unsafe"
            )
        self.root = self.root.resolve()
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, reservation_sha256: str) -> tuple[Path, Path, Path]:
        digest = _hex(reservation_sha256, name="reservation_sha256", pattern=_HEX64)
        return (
            self.root / f"{digest}.json",
            self.root / f".{digest}.pending.json",
            self.root / f".{digest}.lock",
        )

    def _lock_payload(self, reservation_sha256: str) -> bytes:
        digest = _hex(reservation_sha256, name="reservation_sha256", pattern=_HEX64)
        return _canonical(
            {
                "schema": "kaliv-rsi-physical-campaign-admission-lock/v1",
                "ledger_scope": CAMPAIGN_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "reservation_sha256": digest,
            }
        ).encode("utf-8")

    def acquire_lock(self, reservation_sha256: str) -> None:
        final, pending, lock = self._paths(reservation_sha256)
        if any(path.exists() or path.is_symlink() for path in (final, pending, lock)):
            raise PhysicalCampaignAdmissionError(
                "authenticated reservation already has a host-local campaign admission or requires recovery"
            )
        marker = self._lock_payload(reservation_sha256)
        try:
            create_once_file(lock, marker)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PhysicalCampaignAdmissionError(
                "campaign admission could not be durably reserved"
            ) from exc

    def _load_final(
        self,
        path: Path,
        *,
        expected_payload: bytes | None = None,
    ) -> PhysicalCampaignAdmission:
        if not path.is_file() or _has_linkish_component(path):
            raise PhysicalCampaignAdmissionError(
                "campaign admission final artifact is missing or unsafe"
            )
        payload = path.read_bytes()
        if not payload or len(payload) > _MAX_ARTIFACT_BYTES:
            raise PhysicalCampaignAdmissionError(
                "campaign admission final artifact size is invalid"
            )
        if expected_payload is not None and payload != expected_payload:
            raise PhysicalCampaignAdmissionError(
                "campaign admission final read-back does not match committed payload"
            )
        try:
            value = json.loads(payload.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PhysicalCampaignAdmissionError(
                "campaign admission final artifact is invalid JSON"
            ) from exc
        admission = PhysicalCampaignAdmission.from_mapping(value)
        if payload != admission.canonical_json().encode("utf-8"):
            raise PhysicalCampaignAdmissionError(
                "campaign admission final artifact is not canonical"
            )
        if admission.ledger_root_path_sha256 != self.root_sha256:
            raise PhysicalCampaignAdmissionError(
                "campaign admission belongs to another host ledger root"
            )
        return admission

    def load(self, reservation_sha256: str) -> PhysicalCampaignAdmission:
        final, pending, lock = self._paths(reservation_sha256)
        if final.exists() or final.is_symlink():
            return self._load_final(final)
        if pending.exists() or pending.is_symlink() or lock.exists() or lock.is_symlink():
            raise PhysicalCampaignAdmissionError(
                "campaign admission is host-locally consumed but requires recovery"
            )
        raise PhysicalCampaignAdmissionError(
            "campaign admission is missing from canonical host ledger"
        )

    def commit_locked_mapping(
        self,
        *,
        reservation_sha256: str,
        mapping: Mapping[str, Any],
    ) -> PhysicalCampaignAdmission:
        final, pending, lock = self._paths(reservation_sha256)
        lock_payload = self._lock_payload(reservation_sha256)
        if _read_bound_file(lock, maximum=_MAX_ARTIFACT_BYTES) != lock_payload:
            raise PhysicalCampaignAdmissionError(
                "campaign admission replay marker is missing after host-local consumption"
            )
        if final.exists() or final.is_symlink() or pending.exists() or pending.is_symlink():
            raise PhysicalCampaignAdmissionError(
                "campaign admission commit state already exists"
            )
        payload = _canonical(mapping).encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PhysicalCampaignAdmissionError(
                "campaign admission exceeds byte bound"
            )
        try:
            create_once_file(pending, payload)
            create_once_file(final, payload)
            self._load_final(final, expected_payload=payload)
            unlink_durable(pending)
            # The create-once lock is deliberately permanent after commit. It is
            # the replay marker, not temporary cleanup state.
            verified = self._load_final(final, expected_payload=payload)
            if _read_bound_file(lock, maximum=_MAX_ARTIFACT_BYTES) != lock_payload:
                raise PhysicalCampaignAdmissionError(
                    "campaign admission replay marker changed before provenance registration"
                )
            _mark_admission_transaction_authenticated(
                verified,
                final_path=final,
                final_payload=payload,
                lock_path=lock,
                lock_payload=lock_payload,
            )
            if verified.transaction_authenticated is not True:
                raise PhysicalCampaignAdmissionError(
                    "campaign admission lost replay provenance before return"
                )
            return verified
        except Exception as exc:
            raise PhysicalCampaignAdmissionError(
                "campaign admission is durably host-consumed but requires recovery"
            ) from exc


def _snapshot_trusted_git_runtime(
    trusted_git: TrustedGitRuntime,
    *,
    operation_root: Path,
) -> tuple[TrustedGitRuntime, Path]:
    """Copy a verified caller runtime into one transaction-private runtime tree."""

    if type(trusted_git) is not TrustedGitRuntime:
        raise PhysicalCampaignAdmissionError(
            "campaign admission requires exact TrustedGitRuntime"
        )
    snapshot_root: Path | None = None
    try:
        operation = Path(operation_root)
        if (
            not operation.is_absolute()
            or not operation.is_dir()
            or _has_linkish_component(operation)
        ):
            raise PhysicalCampaignAdmissionError(
                "campaign admission Git operation root is unsafe"
            )
        operation = operation.resolve()
        source_root = Path(os.fspath(trusted_git.transaction_root)).resolve()
        source_runtime = TrustedGitRuntime(source_root)
        snapshot_root = Path(
            tempfile.mkdtemp(prefix=".rsi-campaign-runtime-", dir=operation)
        ).resolve()
        if _has_linkish_component(snapshot_root):
            raise PhysicalCampaignAdmissionError(
                "campaign admission private Git runtime snapshot root is unsafe"
            )
        if os.name == "posix":
            os.chmod(snapshot_root, 0o700)
            observed = snapshot_root.stat()
            if (
                (hasattr(os, "geteuid") and observed.st_uid != os.geteuid())
                or stat.S_IMODE(observed.st_mode) & 0o077
            ):
                raise PhysicalCampaignAdmissionError(
                    "campaign admission private Git runtime snapshot is not process-private"
                )
        staged_root = stage_trusted_git_runtime(
            source_runtime.receipt.manifest,
            source_root=source_runtime.runtime_root,
            staging_root=snapshot_root,
        )
        snapshot_runtime = TrustedGitRuntime(staged_root)
        if (
            snapshot_runtime.receipt.manifest.sha256
            != source_runtime.receipt.manifest.sha256
        ):
            raise PhysicalCampaignAdmissionError(
                "campaign admission private Git runtime snapshot identity changed"
            )
        snapshot_runtime.verify()
        return snapshot_runtime, snapshot_root
    except PhysicalCampaignAdmissionError:
        if snapshot_root is not None and snapshot_root.exists():
            try:
                remove_tree_durable(snapshot_root)
            except DurablePublicationError:
                pass
        raise
    except (AttributeError, OSError, TypeError, ValueError, DurablePublicationError) as exc:
        if snapshot_root is not None and snapshot_root.exists():
            try:
                remove_tree_durable(snapshot_root)
            except DurablePublicationError:
                pass
        raise PhysicalCampaignAdmissionError(
            "campaign admission Trusted Git runtime could not be privately snapshotted"
        ) from exc


def _snapshot_authority_inputs(
    *,
    reservation: PhysicalQualificationReservation,
    qualification: QualificationPacket,
    snapshot_receipt: CandidateSnapshotReceipt,
    runner_authorization: PhysicalCampaignRunnerAuthorization,
    runner_signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
) -> tuple[
    str,
    PhysicalQualificationReservation,
    QualificationPacket,
    CandidateSnapshotReceipt,
    PhysicalCampaignRunnerAuthorization,
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
]:
    """Freeze caller-owned authority data while preserving live reservation authority."""

    if type(reservation) is not PhysicalQualificationReservation:
        raise PhysicalCampaignAdmissionError(
            "campaign admission requires exact PhysicalQualificationReservation"
        )
    if reservation.transaction_authenticated is not True:
        raise PhysicalCampaignAdmissionError(
            "campaign admission requires the transaction-authenticated reservation object"
        )
    if type(qualification) is not QualificationPacket:
        raise PhysicalCampaignAdmissionError(
            "campaign admission requires exact QualificationPacket"
        )
    if type(snapshot_receipt) is not CandidateSnapshotReceipt:
        raise PhysicalCampaignAdmissionError(
            "campaign admission requires exact CandidateSnapshotReceipt"
        )
    if type(runner_authorization) is not PhysicalCampaignRunnerAuthorization:
        raise PhysicalCampaignAdmissionError(
            "campaign admission requires exact runner authorization"
        )
    if type(runner_signature) is not DetachedEd25519AuthoritySignature:
        raise PhysicalCampaignAdmissionError(
            "campaign admission requires exact detached runner signature"
        )
    if type(verifier) is not Ed25519AuthorityVerifier:
        raise PhysicalCampaignAdmissionError(
            "campaign admission requires exact Ed25519AuthorityVerifier"
        )

    authenticated_reservation_sha = reservation.sha256
    try:
        reservation_snapshot = PhysicalQualificationReservation.from_mapping(
            json.loads(reservation.canonical_json())
        )
        qualification_snapshot = QualificationPacket.from_json(
            qualification.canonical_json()
        )
        snapshot_snapshot = CandidateSnapshotReceipt(
            **json.loads(snapshot_receipt.canonical_json())
        )
        authorization_snapshot = PhysicalCampaignRunnerAuthorization.from_mapping(
            json.loads(runner_authorization.canonical_json())
        )
        signature_snapshot = DetachedEd25519AuthoritySignature.from_mapping(
            json.loads(runner_signature.canonical_json())
        )

        trusted_keys: dict[str, TrustedEd25519AuthorityKey] = {}
        source_keys = verifier._trusted_keys
        minimum_epoch = verifier._minimum_keyring_epoch
        if not isinstance(source_keys, dict):
            raise TypeError("authority verifier keyring is not concrete")
        for key_id, key in source_keys.items():
            if type(key) is not TrustedEd25519AuthorityKey:
                raise TypeError("authority verifier contains overridable key type")
            trusted_keys[key_id] = TrustedEd25519AuthorityKey.from_mapping(
                json.loads(key.canonical_json())
            )
        verifier_snapshot = Ed25519AuthorityVerifier(
            trusted_keys,
            minimum_keyring_epoch=minimum_epoch,
        )
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PhysicalCampaignAdmissionError(
            "campaign admission authority inputs could not be snapshotted"
        ) from exc

    if (
        reservation_snapshot.sha256 != authenticated_reservation_sha
        or reservation.transaction_authenticated is not True
        or reservation.sha256 != authenticated_reservation_sha
    ):
        raise PhysicalCampaignAdmissionError(
            "transaction-authenticated reservation changed while being snapshotted"
        )

    return (
        authenticated_reservation_sha,
        reservation_snapshot,
        qualification_snapshot,
        snapshot_snapshot,
        authorization_snapshot,
        signature_snapshot,
        verifier_snapshot,
    )


def _require_live_reservation(
    reservation: PhysicalQualificationReservation,
    authenticated_reservation_sha: str,
) -> None:
    if (
        type(reservation) is not PhysicalQualificationReservation
        or reservation.transaction_authenticated is not True
        or reservation.sha256 != authenticated_reservation_sha
    ):
        raise PhysicalCampaignAdmissionError(
            "transaction-authenticated reservation changed during admission"
        )


def _require_chain_binding(
    *,
    reservation: PhysicalQualificationReservation,
    qualification: QualificationPacket,
    snapshot_receipt: CandidateSnapshotReceipt,
    require_transaction: bool,
) -> None:
    if type(reservation) is not PhysicalQualificationReservation:
        raise PhysicalCampaignAdmissionError(
            "campaign admission requires exact reservation evidence"
        )
    if require_transaction and reservation.transaction_authenticated is not True:
        raise PhysicalCampaignAdmissionError(
            "campaign admission requires the transaction-authenticated reservation object"
        )
    if type(qualification) is not QualificationPacket:
        raise PhysicalCampaignAdmissionError(
            "campaign admission requires exact qualification evidence"
        )
    if type(snapshot_receipt) is not CandidateSnapshotReceipt:
        raise PhysicalCampaignAdmissionError(
            "campaign admission requires exact CandidateSnapshotReceipt"
        )
    if qualification.sha256 != reservation.qualification_packet_sha256:
        raise PhysicalCampaignAdmissionError(
            "qualification packet does not match authenticated reservation"
        )
    if (
        snapshot_receipt.sha256 != reservation.snapshot_receipt_sha256
        or snapshot_receipt.sha256 != qualification.snapshot_receipt_sha256
        or snapshot_receipt.materialization_receipt_sha256
        != qualification.materialization_receipt_sha256
        or snapshot_receipt.task_sha256 != qualification.task_sha256
        or snapshot_receipt.candidate_commit_sha != qualification.candidate_commit_sha
        or snapshot_receipt.candidate_tree_sha != qualification.candidate_tree_sha
    ):
        raise PhysicalCampaignAdmissionError(
            "snapshot receipt is not bound to the qualification chain"
        )
    if (
        snapshot_receipt.git_runtime_manifest_sha256
        != reservation.git_runtime_manifest_sha256
        or snapshot_receipt.git_executable_sha256
        != reservation.git_executable_sha256
    ):
        raise PhysicalCampaignAdmissionError(
            "reservation Trusted-Git identity differs from signed snapshot"
        )


def build_physical_campaign_runner_authorization(
    *,
    reservation: PhysicalQualificationReservation,
    qualification: QualificationPacket,
    snapshot_receipt: CandidateSnapshotReceipt,
    authorization_id: str,
    campaign_id: str,
    runner_relative_path: str,
    runner_sha256: str,
    runner_bytes: int,
    authorized_at_utc: str,
    expires_at_utc: str,
) -> PhysicalCampaignRunnerAuthorization:
    """Build the non-authoritative payload a separate human authority may sign."""

    _require_chain_binding(
        reservation=reservation,
        qualification=qualification,
        snapshot_receipt=snapshot_receipt,
        require_transaction=False,
    )
    return PhysicalCampaignRunnerAuthorization(
        authorization_id=authorization_id,
        reservation_sha256=reservation.sha256,
        host_scope_sha256=reservation_host_scope_sha256(reservation),
        request_sha256=reservation.request_sha256,
        qualification_packet_sha256=qualification.sha256,
        snapshot_receipt_sha256=snapshot_receipt.sha256,
        campaign_id=campaign_id,
        proposal_id=qualification.proposal_id,
        task_id=qualification.task_id,
        task_sha256=qualification.task_sha256,
        repository=qualification.repository,
        base_sha=qualification.base_sha,
        requested_main_sha=reservation.requested_main_sha,
        runner_relative_path=_runner_relative_path(runner_relative_path),
        runner_sha256=runner_sha256,
        runner_bytes=runner_bytes,
        required_operator_actor_id=reservation.collector_actor_id,
        required_approver_actor_id=reservation.approver_actor_id,
        authorized_at_utc=authorized_at_utc,
        expires_at_utc=expires_at_utc,
    )


def _require_observation(
    *,
    reservation: PhysicalQualificationReservation,
    observation: Any,
    now_utc: str,
) -> None:
    if observation.repository != "Ternedal/ModelRig":
        raise PhysicalCampaignAdmissionError(
            "pre-start main observation belongs to another repository"
        )
    if observation.observed_sha != reservation.requested_main_sha:
        raise PhysicalCampaignAdmissionError(
            "pre-start main head does not match the human-requested main SHA"
        )
    if observation.repository_root_path_sha256 != reservation.repository_root_path_sha256:
        raise PhysicalCampaignAdmissionError(
            "pre-start observation belongs to another repository root"
        )
    if (
        observation.git_runtime_manifest_sha256
        != reservation.git_runtime_manifest_sha256
        or observation.git_executable_sha256 != reservation.git_executable_sha256
    ):
        raise PhysicalCampaignAdmissionError(
            "pre-start Trusted-Git identity changed"
        )
    current = _utc(now_utc, name="trusted admission time")
    observed = _utc(observation.observed_at_utc, name="pre_start_observed_at_utc")
    if observed > current or current - observed > _MAX_MAIN_OBSERVATION_AGE:
        raise PhysicalCampaignAdmissionError(
            "pre-start main observation is future-dated or stale"
        )
    consumed = _utc(
        reservation.consumed_at_utc,
        name="reservation.consumed_at_utc",
    )
    if consumed > current or current - consumed > _MAX_RESERVATION_AGE:
        raise PhysicalCampaignAdmissionError(
            "transaction-authenticated reservation is stale at admission"
        )


def _require_runner_authorization_binding(
    *,
    authorization: PhysicalCampaignRunnerAuthorization,
    reservation: PhysicalQualificationReservation,
    qualification: QualificationPacket,
    snapshot_receipt: CandidateSnapshotReceipt,
) -> None:
    expected = {
        "reservation_sha256": reservation.sha256,
        "host_scope_sha256": reservation_host_scope_sha256(reservation),
        "request_sha256": reservation.request_sha256,
        "qualification_packet_sha256": qualification.sha256,
        "snapshot_receipt_sha256": snapshot_receipt.sha256,
        "proposal_id": qualification.proposal_id,
        "task_id": qualification.task_id,
        "task_sha256": qualification.task_sha256,
        "repository": qualification.repository,
        "base_sha": qualification.base_sha,
        "requested_main_sha": reservation.requested_main_sha,
        "required_operator_actor_id": reservation.collector_actor_id,
        "required_approver_actor_id": reservation.approver_actor_id,
    }
    actual = {name: getattr(authorization, name) for name in expected}
    if actual != expected:
        raise PhysicalCampaignAdmissionError(
            "runner authorization is not bound to the authenticated reservation/qualification chain"
        )


def _verify_runner_authorization_at(
    *,
    authorization: PhysicalCampaignRunnerAuthorization,
    reservation: PhysicalQualificationReservation,
    qualification: QualificationPacket,
    snapshot_receipt: CandidateSnapshotReceipt,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    at_utc: str,
) -> str:
    if type(authorization) is not PhysicalCampaignRunnerAuthorization:
        raise PhysicalCampaignAdmissionError(
            "campaign admission requires exact runner authorization"
        )
    if type(signature) is not DetachedEd25519AuthoritySignature:
        raise PhysicalCampaignAdmissionError(
            "campaign admission requires exact detached runner signature"
        )
    if type(verifier) is not Ed25519AuthorityVerifier:
        raise PhysicalCampaignAdmissionError(
            "campaign admission requires exact Ed25519AuthorityVerifier"
        )
    _require_runner_authorization_binding(
        authorization=authorization,
        reservation=reservation,
        qualification=qualification,
        snapshot_receipt=snapshot_receipt,
    )
    if signature.issuer_system_id != RUNNER_AUTHORIZATION_ISSUER_SYSTEM_ID:
        raise PhysicalCampaignAdmissionError(
            "runner authorization signature is from another authority system"
        )
    current = _utc(at_utc, name="runner authorization verification time")
    authorized = _utc(authorization.authorized_at_utc, name="authorized_at_utc")
    expires = _utc(authorization.expires_at_utc, name="expires_at_utc")
    signed = _utc(signature.signed_at_utc, name="signature.signed_at_utc")
    if signed < authorized or signed > expires:
        raise PhysicalCampaignAdmissionError(
            "runner authorization signature is outside authorization window"
        )
    if current < authorized or current > expires:
        raise PhysicalCampaignAdmissionError(
            "runner authorization is not currently valid"
        )
    payload = authorization.canonical_json().encode("utf-8")
    try:
        verifier.verify(payload=payload, signature=signature, at_utc=at_utc)
    except AsymmetricAuthorityError as exc:
        raise PhysicalCampaignAdmissionError(
            f"runner authorization authority verification failed: {exc}"
        ) from exc
    return signature.issuer_actor_id


def _verify_runner_file(
    *,
    repository_root: Path,
    authorization: PhysicalCampaignRunnerAuthorization,
) -> None:
    root = Path(repository_root)
    if not root.is_absolute() or not root.is_dir() or _has_linkish_component(root):
        raise PhysicalCampaignAdmissionError(
            "authorized physical campaign repository root is unsafe"
        )
    root = root.resolve()
    relative = _runner_relative_path(authorization.runner_relative_path)
    path = root.joinpath(*PurePosixPath(relative).parts)
    try:
        resolved_parent = path.parent.resolve(strict=True)
    except OSError as exc:
        raise PhysicalCampaignAdmissionError(
            "authorized runner parent does not exist"
        ) from exc
    try:
        resolved_parent.relative_to(root)
    except ValueError as exc:
        raise PhysicalCampaignAdmissionError(
            "authorized runner escapes repository root"
        ) from exc
    try:
        raw, _ = _stable_regular_read(
            path,
            maximum=_MAX_RUNNER_BYTES,
            name="authorized physical campaign runner",
        )
    except Exception as exc:
        raise PhysicalCampaignAdmissionError(
            "authorized physical campaign runner cannot be read safely"
        ) from exc
    if len(raw) != authorization.runner_bytes:
        raise PhysicalCampaignAdmissionError(
            "authorized physical campaign runner byte count changed"
        )
    if _sha256_bytes(raw) != authorization.runner_sha256:
        raise PhysicalCampaignAdmissionError(
            "authorized physical campaign runner hash changed"
        )


def _admission_mapping(
    *,
    ledger: _PhysicalCampaignAdmissionLedger,
    reservation: PhysicalQualificationReservation,
    qualification: QualificationPacket,
    snapshot_receipt: CandidateSnapshotReceipt,
    authorization: PhysicalCampaignRunnerAuthorization,
    signature: DetachedEd25519AuthoritySignature,
    authorizer_actor_id: str,
    observation: Any,
    admitted_at_utc: str,
) -> dict[str, Any]:
    return {
        "schema": CAMPAIGN_ADMISSION_SCHEMA,
        "ledger_scope": CAMPAIGN_LEDGER_SCOPE,
        "ledger_root_path_sha256": ledger.root_sha256,
        "host_scope_sha256": reservation_host_scope_sha256(reservation),
        "reservation_sha256": reservation.sha256,
        "request_sha256": reservation.request_sha256,
        "qualification_packet_sha256": qualification.sha256,
        "snapshot_receipt_sha256": snapshot_receipt.sha256,
        "runner_authorization_sha256": authorization.sha256,
        "runner_authorization_signature_sha256": signature.sha256,
        "runner_authorizer_actor_id": authorizer_actor_id,
        "campaign_id": authorization.campaign_id,
        "proposal_id": qualification.proposal_id,
        "task_id": qualification.task_id,
        "task_sha256": qualification.task_sha256,
        "repository": qualification.repository,
        "base_sha": qualification.base_sha,
        "requested_main_sha": reservation.requested_main_sha,
        "pre_start_observation_sha256": observation.sha256,
        "pre_start_observed_at_utc": observation.observed_at_utc,
        "admitted_at_utc": admitted_at_utc,
        "repository_root_path_sha256": observation.repository_root_path_sha256,
        "git_runtime_manifest_sha256": observation.git_runtime_manifest_sha256,
        "git_executable_sha256": observation.git_executable_sha256,
        "runner_relative_path": authorization.runner_relative_path,
        "runner_sha256": authorization.runner_sha256,
        "runner_bytes": authorization.runner_bytes,
        "required_operator_actor_id": reservation.collector_actor_id,
        "required_approver_actor_id": reservation.approver_actor_id,
        "required_report_schema": authorization.required_report_schema,
        "required_boundary": authorization.required_boundary,
        "required_network_mode": authorization.required_network_mode,
        "required_probes": list(authorization.required_probes),
        "human_runner_pin_verified": True,
        "host_admission_guard_committed": True,
        "manual_operator_required": True,
        "single_campaign_only": True,
        "automatic_start": False,
        "campaign_start_authorized": True,
        "physical_campaign_completed": False,
        "post_campaign_main_observation_required": True,
        "frozen_main_confirmed": False,
        "global_replay_safe": False,
        "pilot_go_authorized": False,
        "activation_authorized": False,
        "remote_publication_authorized": False,
        "authority": CAMPAIGN_ADMISSION_AUTHORITY,
        "merge_authority": "human",
    }


def _issue_physical_campaign_admission_once(
    *,
    ledger_root: Path,
    trusted_git: TrustedGitRuntime,
    repository_root: Path,
    operation_root: Path,
    reservation: PhysicalQualificationReservation,
    qualification: QualificationPacket,
    snapshot_receipt: CandidateSnapshotReceipt,
    runner_authorization: PhysicalCampaignRunnerAuthorization,
    runner_signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_provider: Callable[[], str],
) -> PhysicalCampaignAdmission:
    """Private injectable transaction for production wiring and deterministic tests."""

    (
        authenticated_reservation_sha,
        reservation_snapshot,
        qualification_snapshot,
        snapshot_snapshot,
        authorization_snapshot,
        signature_snapshot,
        verifier_snapshot,
    ) = _snapshot_authority_inputs(
        reservation=reservation,
        qualification=qualification,
        snapshot_receipt=snapshot_receipt,
        runner_authorization=runner_authorization,
        runner_signature=runner_signature,
        verifier=verifier,
    )
    trusted_runtime, runtime_snapshot_root = _snapshot_trusted_git_runtime(
        trusted_git,
        operation_root=operation_root,
    )
    _require_chain_binding(
        reservation=reservation_snapshot,
        qualification=qualification_snapshot,
        snapshot_receipt=snapshot_snapshot,
        require_transaction=False,
    )
    ledger = _PhysicalCampaignAdmissionLedger(ledger_root)
    transaction_succeeded = False
    try:
        preflight_at = now_provider()
        _utc(preflight_at, name="trusted campaign preflight time")
        _verify_runner_authorization_at(
            authorization=authorization_snapshot,
            reservation=reservation_snapshot,
            qualification=qualification_snapshot,
            snapshot_receipt=snapshot_snapshot,
            signature=signature_snapshot,
            verifier=verifier_snapshot,
            at_utc=preflight_at,
        )
        observation = observe_local_main_head(
            trusted_git=trusted_runtime,
            repository_root=repository_root,
            operation_root=operation_root,
            observed_at_utc=preflight_at,
            repository=qualification_snapshot.repository,
        )
        _require_observation(
            reservation=reservation_snapshot,
            observation=observation,
            now_utc=preflight_at,
        )
        _verify_runner_file(
            repository_root=repository_root,
            authorization=authorization_snapshot,
        )
        _require_live_reservation(reservation, authenticated_reservation_sha)

        ledger.acquire_lock(authenticated_reservation_sha)
        try:
            observed_at = now_provider()
            _utc(observed_at, name="trusted post-lock campaign observation time")
            observation = observe_local_main_head(
                trusted_git=trusted_runtime,
                repository_root=repository_root,
                operation_root=operation_root,
                observed_at_utc=observed_at,
                repository=qualification_snapshot.repository,
            )
            _require_observation(
                reservation=reservation_snapshot,
                observation=observation,
                now_utc=observed_at,
            )
            _verify_runner_file(
                repository_root=repository_root,
                authorization=authorization_snapshot,
            )

            admitted_at = now_provider()
            _utc(admitted_at, name="trusted campaign admission time")
            _require_observation(
                reservation=reservation_snapshot,
                observation=observation,
                now_utc=admitted_at,
            )
            authorizer_actor_id = _verify_runner_authorization_at(
                authorization=authorization_snapshot,
                reservation=reservation_snapshot,
                qualification=qualification_snapshot,
                snapshot_receipt=snapshot_snapshot,
                signature=signature_snapshot,
                verifier=verifier_snapshot,
                at_utc=admitted_at,
            )
            _verify_runner_file(
                repository_root=repository_root,
                authorization=authorization_snapshot,
            )
            _require_live_reservation(reservation, authenticated_reservation_sha)
            mapping = _admission_mapping(
                ledger=ledger,
                reservation=reservation_snapshot,
                qualification=qualification_snapshot,
                snapshot_receipt=snapshot_snapshot,
                authorization=authorization_snapshot,
                signature=signature_snapshot,
                authorizer_actor_id=authorizer_actor_id,
                observation=observation,
                admitted_at_utc=admitted_at,
            )
            result = ledger.commit_locked_mapping(
                reservation_sha256=authenticated_reservation_sha,
                mapping=mapping,
            )
            transaction_succeeded = True
            return result
        except PhysicalCampaignAdmissionError:
            raise
        except Exception as exc:
            raise PhysicalCampaignAdmissionError(
                "campaign admission is durably host-consumed but requires recovery"
            ) from exc
    finally:
        try:
            remove_tree_durable(runtime_snapshot_root)
        except DurablePublicationError as exc:
            if transaction_succeeded:
                raise PhysicalCampaignAdmissionError(
                    "campaign admission committed but private Git runtime cleanup failed closed"
                ) from exc


def issue_physical_campaign_admission_once(
    *,
    trusted_git: TrustedGitRuntime,
    reservation: PhysicalQualificationReservation,
    qualification: QualificationPacket,
    snapshot_receipt: CandidateSnapshotReceipt,
    runner_authorization: PhysicalCampaignRunnerAuthorization,
    runner_signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
) -> PhysicalCampaignAdmission:
    """Issue one host-local manual campaign admission without executing the runner.

    Callers cannot provide observation evidence, wall-clock time, repository or
    operation roots, ledger state, campaign/operator identity, or runner path/hash
    outside the separately human-signed runner authorization. Caller-owned runtime
    bytes are copied into a transaction-private staged runtime and authority inputs
    are reconstructed into exact local objects before use. Live admission authority
    remains true only while its exact final receipt and permanent replay marker
    remain present byte-for-byte.
    """

    return _issue_physical_campaign_admission_once(
        ledger_root=_canonical_campaign_ledger_root(),
        trusted_git=trusted_git,
        repository_root=_canonical_repository_root(),
        operation_root=_canonical_campaign_operation_root(),
        reservation=reservation,
        qualification=qualification,
        snapshot_receipt=snapshot_receipt,
        runner_authorization=runner_authorization,
        runner_signature=runner_signature,
        verifier=verifier,
        now_provider=_now_utc_seconds,
    )
