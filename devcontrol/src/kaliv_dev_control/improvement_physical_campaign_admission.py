"""One-shot manual DC-L15 campaign admission after request reservation.

The reservation layer proves that one human-signed request was consumed while
local ``refs/heads/main`` matched the requested SHA.  This module may derive one
manual campaign-start admission only after a second fresh trusted observation of
the same local repository.  It does not run probes, does not prove continuous
main freeze and does not grant pilot, publication, merge, release or activation
authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from .catalog import IsolationBoundary, NetworkMode
from .durable_publication import DurablePublicationError, create_once_file
from .improvement_physical_reservation import (
    LocalMainHeadObservation,
    PhysicalQualificationReservation,
)
from .improvement_qualification_packet import QualificationPacket
from .physical_isolation import REPORT_SCHEMA, REQUIRED_PROBES
from .trusted_git_runtime_model import _has_linkish_component

CAMPAIGN_ADMISSION_SCHEMA = "kaliv-rsi-physical-campaign-admission/v1"
CAMPAIGN_ADMISSION_AUTHORITY = "single-physical-campaign-start-only"
_MAX_PRE_START_OBSERVATION_AGE = timedelta(minutes=1)
_MAX_RESERVATION_TO_ADMISSION_AGE = timedelta(minutes=15)
_MAX_ARTIFACT_BYTES = 256 * 1024

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PhysicalCampaignAdmissionError(ValueError):
    """The consumed request cannot authorize this physical campaign start."""


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


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PhysicalCampaignAdmissionError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PhysicalCampaignAdmissionError(f"{name} is invalid") from exc


def _safe_root(path: Path, *, name: str) -> Path:
    root = Path(path)
    if not root.is_absolute() or not root.is_dir() or _has_linkish_component(root):
        raise PhysicalCampaignAdmissionError(
            f"{name} must be an absolute link-free directory"
        )
    return root.resolve()


def _required_probe_names() -> tuple[str, ...]:
    return tuple(probe.value for probe in REQUIRED_PROBES)


_ADMISSION_FIELDS = {
    "schema",
    "admission_id",
    "campaign_id",
    "reservation_sha256",
    "request_id",
    "request_sha256",
    "request_signature_sha256",
    "requester_actor_id",
    "qualification_packet_sha256",
    "proposal_id",
    "task_id",
    "task_sha256",
    "repository",
    "base_sha",
    "requested_main_sha",
    "reservation_observation_sha256",
    "pre_start_observation_sha256",
    "repository_root_path_sha256",
    "git_runtime_manifest_sha256",
    "git_executable_sha256",
    "reservation_consumed_at_utc",
    "pre_start_observed_at_utc",
    "admitted_at_utc",
    "collector_actor_id",
    "approver_actor_id",
    "operator_actor_id",
    "required_report_schema",
    "required_boundary",
    "required_network_mode",
    "required_probes",
    "manual_operator_required",
    "single_campaign_only",
    "automatic_start",
    "campaign_start_authorized",
    "physical_campaign_completed",
    "post_campaign_main_observation_required",
    "frozen_main_confirmed",
    "pilot_go_authorized",
    "activation_authorized",
    "remote_publication_authorized",
    "authority",
    "merge_authority",
}


@dataclass(frozen=True, slots=True)
class PhysicalCampaignAdmission:
    admission_id: str
    campaign_id: str
    reservation_sha256: str
    request_id: str
    request_sha256: str
    request_signature_sha256: str
    requester_actor_id: str
    qualification_packet_sha256: str
    proposal_id: str
    task_id: str
    task_sha256: str
    repository: str
    base_sha: str
    requested_main_sha: str
    reservation_observation_sha256: str
    pre_start_observation_sha256: str
    repository_root_path_sha256: str
    git_runtime_manifest_sha256: str
    git_executable_sha256: str
    reservation_consumed_at_utc: str
    pre_start_observed_at_utc: str
    admitted_at_utc: str
    collector_actor_id: str
    approver_actor_id: str
    operator_actor_id: str
    required_probes: tuple[str, ...]
    required_report_schema: str = REPORT_SCHEMA
    required_boundary: str = IsolationBoundary.OS_ISOLATED.value
    required_network_mode: str = NetworkMode.DENY.value
    manual_operator_required: bool = True
    single_campaign_only: bool = True
    automatic_start: bool = False
    campaign_start_authorized: bool = True
    physical_campaign_completed: bool = False
    post_campaign_main_observation_required: bool = True
    frozen_main_confirmed: bool = False
    pilot_go_authorized: bool = False
    activation_authorized: bool = False
    remote_publication_authorized: bool = False
    authority: str = CAMPAIGN_ADMISSION_AUTHORITY
    merge_authority: str = "human"
    schema: str = CAMPAIGN_ADMISSION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != CAMPAIGN_ADMISSION_SCHEMA:
            raise PhysicalCampaignAdmissionError("campaign admission schema is unsupported")
        for name in ("admission_id", "campaign_id", "request_id"):
            _identifier(getattr(self, name), name=name)
        for name, value, pattern in (
            ("reservation_sha256", self.reservation_sha256, _HEX64),
            ("request_sha256", self.request_sha256, _HEX64),
            ("request_signature_sha256", self.request_signature_sha256, _HEX64),
            ("qualification_packet_sha256", self.qualification_packet_sha256, _HEX64),
            ("task_sha256", self.task_sha256, _HEX64),
            ("base_sha", self.base_sha, _HEX40),
            ("requested_main_sha", self.requested_main_sha, _HEX40),
            ("reservation_observation_sha256", self.reservation_observation_sha256, _HEX64),
            ("pre_start_observation_sha256", self.pre_start_observation_sha256, _HEX64),
            ("repository_root_path_sha256", self.repository_root_path_sha256, _HEX64),
            ("git_runtime_manifest_sha256", self.git_runtime_manifest_sha256, _HEX64),
            ("git_executable_sha256", self.git_executable_sha256, _HEX64),
        ):
            _hex(value, name=name, pattern=pattern)
        if self.repository != "Ternedal/ModelRig":
            raise PhysicalCampaignAdmissionError("campaign admission repository is unsupported")
        if not isinstance(self.proposal_id, str) or not self.proposal_id:
            raise PhysicalCampaignAdmissionError("proposal_id is invalid")
        if not isinstance(self.task_id, str) or not self.task_id:
            raise PhysicalCampaignAdmissionError("task_id is invalid")
        requester = _actor(self.requester_actor_id, name="requester_actor_id")
        collector = _actor(self.collector_actor_id, name="collector_actor_id")
        approver = _actor(self.approver_actor_id, name="approver_actor_id")
        operator = _actor(self.operator_actor_id, name="operator_actor_id")
        if collector == approver:
            raise PhysicalCampaignAdmissionError("collector and approver must remain different actors")
        if operator != collector:
            raise PhysicalCampaignAdmissionError(
                "campaign operator must be the human-requested collector"
            )
        if not requester:
            raise PhysicalCampaignAdmissionError("requester actor is invalid")
        consumed = _utc(self.reservation_consumed_at_utc, name="reservation_consumed_at_utc")
        observed = _utc(self.pre_start_observed_at_utc, name="pre_start_observed_at_utc")
        admitted = _utc(self.admitted_at_utc, name="admitted_at_utc")
        if observed < consumed or admitted < observed:
            raise PhysicalCampaignAdmissionError(
                "campaign admission timestamps are out of order"
            )
        if admitted - observed > _MAX_PRE_START_OBSERVATION_AGE:
            raise PhysicalCampaignAdmissionError(
                "pre-start main observation is stale at campaign admission"
            )
        if admitted - consumed > _MAX_RESERVATION_TO_ADMISSION_AGE:
            raise PhysicalCampaignAdmissionError(
                "consumed request reservation is stale at campaign admission"
            )
        if self.required_report_schema != REPORT_SCHEMA:
            raise PhysicalCampaignAdmissionError("campaign report schema is unsupported")
        if self.required_boundary != IsolationBoundary.OS_ISOLATED.value:
            raise PhysicalCampaignAdmissionError("campaign must require OS isolation")
        if self.required_network_mode != NetworkMode.DENY.value:
            raise PhysicalCampaignAdmissionError("campaign must require network deny")
        if self.required_probes != _required_probe_names():
            raise PhysicalCampaignAdmissionError(
                "campaign admission must require the exact DC-L15 probe set"
            )
        if (
            self.manual_operator_required is not True
            or self.single_campaign_only is not True
            or self.automatic_start is not False
            or self.campaign_start_authorized is not True
            or self.physical_campaign_completed is not False
            or self.post_campaign_main_observation_required is not True
            or self.frozen_main_confirmed is not False
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
        data = _strict(value, fields=_ADMISSION_FIELDS, name="physical campaign admission")
        probes = data["required_probes"]
        if not isinstance(probes, list):
            raise PhysicalCampaignAdmissionError("required_probes must be an array")
        kwargs = dict(data)
        kwargs["required_probes"] = tuple(probes)
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "admission_id": self.admission_id,
            "campaign_id": self.campaign_id,
            "reservation_sha256": self.reservation_sha256,
            "request_id": self.request_id,
            "request_sha256": self.request_sha256,
            "request_signature_sha256": self.request_signature_sha256,
            "requester_actor_id": self.requester_actor_id,
            "qualification_packet_sha256": self.qualification_packet_sha256,
            "proposal_id": self.proposal_id,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "requested_main_sha": self.requested_main_sha,
            "reservation_observation_sha256": self.reservation_observation_sha256,
            "pre_start_observation_sha256": self.pre_start_observation_sha256,
            "repository_root_path_sha256": self.repository_root_path_sha256,
            "git_runtime_manifest_sha256": self.git_runtime_manifest_sha256,
            "git_executable_sha256": self.git_executable_sha256,
            "reservation_consumed_at_utc": self.reservation_consumed_at_utc,
            "pre_start_observed_at_utc": self.pre_start_observed_at_utc,
            "admitted_at_utc": self.admitted_at_utc,
            "collector_actor_id": self.collector_actor_id,
            "approver_actor_id": self.approver_actor_id,
            "operator_actor_id": self.operator_actor_id,
            "required_report_schema": self.required_report_schema,
            "required_boundary": self.required_boundary,
            "required_network_mode": self.required_network_mode,
            "required_probes": list(self.required_probes),
            "manual_operator_required": self.manual_operator_required,
            "single_campaign_only": self.single_campaign_only,
            "automatic_start": self.automatic_start,
            "campaign_start_authorized": self.campaign_start_authorized,
            "physical_campaign_completed": self.physical_campaign_completed,
            "post_campaign_main_observation_required": self.post_campaign_main_observation_required,
            "frozen_main_confirmed": self.frozen_main_confirmed,
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


class PhysicalCampaignAdmissionLedger:
    """Durably issue at most one campaign admission per consumed reservation."""

    def __init__(self, *, root: Path) -> None:
        self.root = _safe_root(root, name="physical campaign admission ledger root")

    def _path(self, reservation_sha256: str) -> Path:
        digest = _hex(reservation_sha256, name="reservation_sha256", pattern=_HEX64)
        return self.root / f"{digest}.campaign-admission.json"

    def load(self, reservation_sha256: str) -> PhysicalCampaignAdmission:
        path = self._path(reservation_sha256)
        if not path.is_file() or _has_linkish_component(path):
            raise PhysicalCampaignAdmissionError("physical campaign admission is missing or unsafe")
        payload = path.read_bytes()
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PhysicalCampaignAdmissionError("physical campaign admission exceeds byte bound")
        try:
            value = json.loads(payload.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PhysicalCampaignAdmissionError("physical campaign admission is invalid JSON") from exc
        admission = PhysicalCampaignAdmission.from_mapping(value)
        if payload != admission.canonical_json().encode("utf-8"):
            raise PhysicalCampaignAdmissionError("physical campaign admission is not canonical")
        if admission.reservation_sha256 != reservation_sha256:
            raise PhysicalCampaignAdmissionError("physical campaign admission reservation binding changed")
        return admission

    def issue_once(self, admission: PhysicalCampaignAdmission) -> PhysicalCampaignAdmission:
        if not isinstance(admission, PhysicalCampaignAdmission):
            raise PhysicalCampaignAdmissionError("campaign admission ledger requires admission evidence")
        payload = admission.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PhysicalCampaignAdmissionError("physical campaign admission exceeds byte bound")
        path = self._path(admission.reservation_sha256)
        if path.exists() or path.is_symlink():
            raise PhysicalCampaignAdmissionError(
                "consumed request reservation already has a campaign admission"
            )
        try:
            create_once_file(path, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PhysicalCampaignAdmissionError(
                "physical campaign admission could not be durably issued"
            ) from exc
        loaded = self.load(admission.reservation_sha256)
        if loaded.canonical_json() != admission.canonical_json():
            raise PhysicalCampaignAdmissionError(
                "physical campaign admission post-write verification mismatch"
            )
        return loaded


def build_physical_campaign_admission(
    *,
    reservation: PhysicalQualificationReservation,
    qualification: QualificationPacket,
    reservation_observation: LocalMainHeadObservation,
    pre_start_observation: LocalMainHeadObservation,
    admission_id: str,
    campaign_id: str,
    operator_actor_id: str,
    admitted_at_utc: str,
) -> PhysicalCampaignAdmission:
    """Derive one manual campaign-start authority from exact prior evidence."""

    if not isinstance(reservation, PhysicalQualificationReservation):
        raise PhysicalCampaignAdmissionError("campaign admission requires reservation evidence")
    if not isinstance(qualification, QualificationPacket):
        raise PhysicalCampaignAdmissionError("campaign admission requires qualification evidence")
    if not isinstance(reservation_observation, LocalMainHeadObservation):
        raise PhysicalCampaignAdmissionError("campaign admission requires reservation observation")
    if not isinstance(pre_start_observation, LocalMainHeadObservation):
        raise PhysicalCampaignAdmissionError("campaign admission requires pre-start observation")
    if qualification.sha256 != reservation.qualification_packet_sha256:
        raise PhysicalCampaignAdmissionError(
            "campaign admission qualification packet does not match reservation"
        )
    if reservation_observation.sha256 != reservation.main_observation_sha256:
        raise PhysicalCampaignAdmissionError(
            "reservation observation does not match consumed reservation"
        )
    if reservation_observation.observed_sha != reservation.requested_main_sha:
        raise PhysicalCampaignAdmissionError(
            "reservation observation no longer proves the requested main SHA"
        )
    if pre_start_observation.repository != qualification.repository:
        raise PhysicalCampaignAdmissionError(
            "pre-start observation belongs to another repository"
        )
    if pre_start_observation.observed_sha != reservation.requested_main_sha:
        raise PhysicalCampaignAdmissionError(
            "pre-start main head does not match the human-requested main SHA"
        )
    if (
        pre_start_observation.repository_root_path_sha256
        != reservation_observation.repository_root_path_sha256
    ):
        raise PhysicalCampaignAdmissionError(
            "pre-start observation belongs to another local repository root"
        )
    if (
        pre_start_observation.git_runtime_manifest_sha256
        != reservation_observation.git_runtime_manifest_sha256
        or pre_start_observation.git_executable_sha256
        != reservation_observation.git_executable_sha256
    ):
        raise PhysicalCampaignAdmissionError(
            "trusted Git identity changed between reservation and campaign admission"
        )
    if reservation.requested_main_sha != reservation.observed_main_sha:
        raise PhysicalCampaignAdmissionError("reservation main binding is invalid")
    return PhysicalCampaignAdmission(
        admission_id=admission_id,
        campaign_id=campaign_id,
        reservation_sha256=reservation.sha256,
        request_id=reservation.request_id,
        request_sha256=reservation.request_sha256,
        request_signature_sha256=reservation.signature_sha256,
        requester_actor_id=reservation.requester_actor_id,
        qualification_packet_sha256=qualification.sha256,
        proposal_id=qualification.proposal_id,
        task_id=qualification.task_id,
        task_sha256=qualification.task_sha256,
        repository=qualification.repository,
        base_sha=qualification.base_sha,
        requested_main_sha=reservation.requested_main_sha,
        reservation_observation_sha256=reservation_observation.sha256,
        pre_start_observation_sha256=pre_start_observation.sha256,
        repository_root_path_sha256=pre_start_observation.repository_root_path_sha256,
        git_runtime_manifest_sha256=pre_start_observation.git_runtime_manifest_sha256,
        git_executable_sha256=pre_start_observation.git_executable_sha256,
        reservation_consumed_at_utc=reservation.consumed_at_utc,
        pre_start_observed_at_utc=pre_start_observation.observed_at_utc,
        admitted_at_utc=admitted_at_utc,
        collector_actor_id=reservation.collector_actor_id,
        approver_actor_id=reservation.approver_actor_id,
        operator_actor_id=operator_actor_id,
        required_probes=_required_probe_names(),
    )


def issue_physical_campaign_admission_once(
    *,
    ledger: PhysicalCampaignAdmissionLedger,
    reservation: PhysicalQualificationReservation,
    qualification: QualificationPacket,
    reservation_observation: LocalMainHeadObservation,
    pre_start_observation: LocalMainHeadObservation,
    admission_id: str,
    campaign_id: str,
    operator_actor_id: str,
    admitted_at_utc: str,
) -> PhysicalCampaignAdmission:
    """Issue one durable admission without invoking the physical runner."""

    if not isinstance(ledger, PhysicalCampaignAdmissionLedger):
        raise PhysicalCampaignAdmissionError(
            "campaign admission issuance requires its dedicated ledger"
        )
    admission = build_physical_campaign_admission(
        reservation=reservation,
        qualification=qualification,
        reservation_observation=reservation_observation,
        pre_start_observation=pre_start_observation,
        admission_id=admission_id,
        campaign_id=campaign_id,
        operator_actor_id=operator_actor_id,
        admitted_at_utc=admitted_at_utc,
    )
    return ledger.issue_once(admission)
