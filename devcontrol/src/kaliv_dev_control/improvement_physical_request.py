"""Human-signed request boundary before any DC-L15 physical execution.

This module can prove that a human requested one bounded DC-L15 qualification
campaign against a named prospective frozen-main SHA.  It deliberately cannot
prove that main is actually frozen, consume the request, start a process, run a
probe, publish anything, or authorize pilot/activation.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .asymmetric_authority import (
    AsymmetricAuthorityError,
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
)
from .improvement_qualification_packet import (
    MISSING_PHYSICAL_GATES,
    QualificationPacket,
)
from .physical_isolation import (
    REPORT_SCHEMA,
    REQUIRED_PROBES,
    IsolationBoundary,
    NetworkMode,
)

PHYSICAL_REQUEST_SCHEMA = "kaliv-rsi-physical-qualification-request/v1"
PHYSICAL_REQUEST_RECEIPT_SCHEMA = (
    "kaliv-rsi-physical-qualification-request-verification/v1"
)
PHYSICAL_REQUEST_ISSUER_SYSTEM_ID = "kaliv-rsi-dc-l15-request-authority-v1"
PHYSICAL_REQUEST_AUTHORITY = "human-signed-request-only"
PHYSICAL_REQUEST_SCOPE = "dc-l15-physical-validation-request-only"
PHYSICAL_REQUEST_RECEIPT_AUTHORITY = "verified-request-evidence-only"
_MAX_REQUEST_WINDOW = timedelta(hours=24)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PhysicalQualificationRequestError(ValueError):
    """The physical qualification request or its signature is invalid."""


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
        raise PhysicalQualificationRequestError(
            "physical qualification request is not canonical JSON"
        ) from exc


def _strict(value: Any, *, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PhysicalQualificationRequestError(f"{name} fields mismatch")
    return value


def _text(value: Any, *, name: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\x00" in value
        or len(value.encode("utf-8")) > maximum
    ):
        raise PhysicalQualificationRequestError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    text = _text(value, name=name, maximum=128)
    if _IDENTIFIER.fullmatch(text) is None:
        raise PhysicalQualificationRequestError(f"{name} is invalid")
    return text


def _actor(value: Any, *, name: str) -> str:
    text = _text(value, name=name, maximum=128)
    if _ACTOR.fullmatch(text) is None:
        raise PhysicalQualificationRequestError(f"{name} is invalid")
    return text


def _hex(value: Any, *, name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PhysicalQualificationRequestError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PhysicalQualificationRequestError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PhysicalQualificationRequestError(f"{name} is invalid") from exc


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _required_probe_names() -> tuple[str, ...]:
    return tuple(probe.value for probe in REQUIRED_PROBES)


_REQUEST_FIELDS = {
    "schema",
    "request_id",
    "qualification_packet_sha256",
    "proposal_id",
    "repository",
    "candidate_commit_sha",
    "candidate_tree_sha",
    "candidate_eval_sha256",
    "requested_frozen_main_sha",
    "required_report_schema",
    "required_boundary",
    "required_network_mode",
    "required_probes",
    "collector_actor_id",
    "approver_actor_id",
    "requested_at_utc",
    "expires_at_utc",
    "authority",
    "scope",
    "automatic_start",
    "pilot_authority",
    "activation_authority",
    "remote_publication_authority",
    "exact_frozen_main_confirmed",
    "physical_evidence_present",
}


@dataclass(frozen=True, slots=True)
class PhysicalQualificationRequest:
    request_id: str
    qualification_packet_sha256: str
    proposal_id: str
    repository: str
    candidate_commit_sha: str
    candidate_tree_sha: str
    candidate_eval_sha256: str
    requested_frozen_main_sha: str
    collector_actor_id: str
    approver_actor_id: str
    requested_at_utc: str
    expires_at_utc: str
    required_probes: tuple[str, ...] = _required_probe_names()
    required_report_schema: str = REPORT_SCHEMA
    required_boundary: str = IsolationBoundary.OS_ISOLATED.value
    required_network_mode: str = NetworkMode.DENY.value
    authority: str = PHYSICAL_REQUEST_AUTHORITY
    scope: str = PHYSICAL_REQUEST_SCOPE
    automatic_start: bool = False
    pilot_authority: bool = False
    activation_authority: bool = False
    remote_publication_authority: bool = False
    exact_frozen_main_confirmed: bool = False
    physical_evidence_present: bool = False
    schema: str = PHYSICAL_REQUEST_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PHYSICAL_REQUEST_SCHEMA:
            raise PhysicalQualificationRequestError("physical request schema is unsupported")
        _identifier(self.request_id, name="request_id")
        _identifier(self.proposal_id, name="proposal_id")
        if self.repository != "Ternedal/ModelRig":
            raise PhysicalQualificationRequestError("physical request repository is invalid")
        _hex(
            self.qualification_packet_sha256,
            name="qualification_packet_sha256",
            pattern=_HEX64,
        )
        _hex(self.candidate_commit_sha, name="candidate_commit_sha", pattern=_HEX40)
        _hex(self.candidate_tree_sha, name="candidate_tree_sha", pattern=_HEX40)
        _hex(self.candidate_eval_sha256, name="candidate_eval_sha256", pattern=_HEX64)
        _hex(
            self.requested_frozen_main_sha,
            name="requested_frozen_main_sha",
            pattern=_HEX40,
        )
        collector = _actor(self.collector_actor_id, name="collector_actor_id")
        approver = _actor(self.approver_actor_id, name="approver_actor_id")
        if collector == approver:
            raise PhysicalQualificationRequestError(
                "physical collector and approver must be different actors"
            )
        requested = _utc(self.requested_at_utc, name="requested_at_utc")
        expires = _utc(self.expires_at_utc, name="expires_at_utc")
        if expires <= requested or expires - requested > _MAX_REQUEST_WINDOW:
            raise PhysicalQualificationRequestError(
                "physical qualification request validity window is invalid"
            )
        if self.required_report_schema != REPORT_SCHEMA:
            raise PhysicalQualificationRequestError(
                "physical request report schema is unsupported"
            )
        if self.required_boundary != IsolationBoundary.OS_ISOLATED.value:
            raise PhysicalQualificationRequestError(
                "physical request must require OS isolation"
            )
        if self.required_network_mode != NetworkMode.DENY.value:
            raise PhysicalQualificationRequestError(
                "physical request must require network deny"
            )
        if self.required_probes != _required_probe_names():
            raise PhysicalQualificationRequestError(
                "physical request must require the exact DC-L15 probe set"
            )
        if self.authority != PHYSICAL_REQUEST_AUTHORITY or self.scope != PHYSICAL_REQUEST_SCOPE:
            raise PhysicalQualificationRequestError(
                "physical request authority/scope is unsupported"
            )
        if (
            self.automatic_start is not False
            or self.pilot_authority is not False
            or self.activation_authority is not False
            or self.remote_publication_authority is not False
            or self.exact_frozen_main_confirmed is not False
            or self.physical_evidence_present is not False
        ):
            raise PhysicalQualificationRequestError(
                "physical request may not claim execution, freeze, evidence, pilot, publication or activation authority"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PhysicalQualificationRequest":
        data = _strict(value, fields=_REQUEST_FIELDS, name="physical qualification request")
        probes = data["required_probes"]
        if not isinstance(probes, list):
            raise PhysicalQualificationRequestError("required_probes must be an array")
        kwargs = dict(data)
        kwargs["required_probes"] = tuple(probes)
        return cls(**kwargs)

    @classmethod
    def from_json(cls, text: str) -> "PhysicalQualificationRequest":
        try:
            value = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise PhysicalQualificationRequestError(
                "physical qualification request JSON is invalid"
            ) from exc
        return cls.from_mapping(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "request_id": self.request_id,
            "qualification_packet_sha256": self.qualification_packet_sha256,
            "proposal_id": self.proposal_id,
            "repository": self.repository,
            "candidate_commit_sha": self.candidate_commit_sha,
            "candidate_tree_sha": self.candidate_tree_sha,
            "candidate_eval_sha256": self.candidate_eval_sha256,
            "requested_frozen_main_sha": self.requested_frozen_main_sha,
            "required_report_schema": self.required_report_schema,
            "required_boundary": self.required_boundary,
            "required_network_mode": self.required_network_mode,
            "required_probes": list(self.required_probes),
            "collector_actor_id": self.collector_actor_id,
            "approver_actor_id": self.approver_actor_id,
            "requested_at_utc": self.requested_at_utc,
            "expires_at_utc": self.expires_at_utc,
            "authority": self.authority,
            "scope": self.scope,
            "automatic_start": self.automatic_start,
            "pilot_authority": self.pilot_authority,
            "activation_authority": self.activation_authority,
            "remote_publication_authority": self.remote_publication_authority,
            "exact_frozen_main_confirmed": self.exact_frozen_main_confirmed,
            "physical_evidence_present": self.physical_evidence_present,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())


_RECEIPT_FIELDS = {
    "schema",
    "request_id",
    "request_sha256",
    "qualification_packet_sha256",
    "signature_sha256",
    "requester_actor_id",
    "requested_frozen_main_sha",
    "collector_actor_id",
    "approver_actor_id",
    "required_probes",
    "verified_at_utc",
    "human_request_verified",
    "exact_frozen_main_confirmed",
    "physical_campaign_completed",
    "request_consumed",
    "replay_guard_required",
    "campaign_start_authorized",
    "pilot_go_authorized",
    "activation_authorized",
    "remote_publication_authorized",
    "authority",
}


@dataclass(frozen=True, slots=True)
class PhysicalQualificationRequestReceipt:
    request_id: str
    request_sha256: str
    qualification_packet_sha256: str
    signature_sha256: str
    requester_actor_id: str
    requested_frozen_main_sha: str
    collector_actor_id: str
    approver_actor_id: str
    required_probes: tuple[str, ...]
    verified_at_utc: str
    human_request_verified: bool = True
    exact_frozen_main_confirmed: bool = False
    physical_campaign_completed: bool = False
    request_consumed: bool = False
    replay_guard_required: bool = True
    campaign_start_authorized: bool = False
    pilot_go_authorized: bool = False
    activation_authorized: bool = False
    remote_publication_authorized: bool = False
    authority: str = PHYSICAL_REQUEST_RECEIPT_AUTHORITY
    schema: str = PHYSICAL_REQUEST_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PHYSICAL_REQUEST_RECEIPT_SCHEMA:
            raise PhysicalQualificationRequestError(
                "physical request receipt schema is unsupported"
            )
        _identifier(self.request_id, name="request_id")
        for name, value, pattern in (
            ("request_sha256", self.request_sha256, _HEX64),
            ("qualification_packet_sha256", self.qualification_packet_sha256, _HEX64),
            ("signature_sha256", self.signature_sha256, _HEX64),
            ("requested_frozen_main_sha", self.requested_frozen_main_sha, _HEX40),
        ):
            _hex(value, name=name, pattern=pattern)
        _actor(self.requester_actor_id, name="requester_actor_id")
        collector = _actor(self.collector_actor_id, name="collector_actor_id")
        approver = _actor(self.approver_actor_id, name="approver_actor_id")
        if collector == approver:
            raise PhysicalQualificationRequestError(
                "physical collector and approver must be different actors"
            )
        _utc(self.verified_at_utc, name="verified_at_utc")
        if self.required_probes != _required_probe_names():
            raise PhysicalQualificationRequestError(
                "physical request receipt probe set is invalid"
            )
        if self.authority != PHYSICAL_REQUEST_RECEIPT_AUTHORITY:
            raise PhysicalQualificationRequestError(
                "physical request receipt authority is unsupported"
            )
        if self.human_request_verified is not True or self.replay_guard_required is not True:
            raise PhysicalQualificationRequestError(
                "physical request receipt must preserve verification/replay requirements"
            )
        if (
            self.exact_frozen_main_confirmed is not False
            or self.physical_campaign_completed is not False
            or self.request_consumed is not False
            or self.campaign_start_authorized is not False
            or self.pilot_go_authorized is not False
            or self.activation_authorized is not False
            or self.remote_publication_authorized is not False
        ):
            raise PhysicalQualificationRequestError(
                "request verification may not claim campaign, pilot, publication or activation completion/authority"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PhysicalQualificationRequestReceipt":
        data = _strict(value, fields=_RECEIPT_FIELDS, name="physical request receipt")
        probes = data["required_probes"]
        if not isinstance(probes, list):
            raise PhysicalQualificationRequestError("receipt required_probes must be an array")
        kwargs = dict(data)
        kwargs["required_probes"] = tuple(probes)
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "request_id": self.request_id,
            "request_sha256": self.request_sha256,
            "qualification_packet_sha256": self.qualification_packet_sha256,
            "signature_sha256": self.signature_sha256,
            "requester_actor_id": self.requester_actor_id,
            "requested_frozen_main_sha": self.requested_frozen_main_sha,
            "collector_actor_id": self.collector_actor_id,
            "approver_actor_id": self.approver_actor_id,
            "required_probes": list(self.required_probes),
            "verified_at_utc": self.verified_at_utc,
            "human_request_verified": self.human_request_verified,
            "exact_frozen_main_confirmed": self.exact_frozen_main_confirmed,
            "physical_campaign_completed": self.physical_campaign_completed,
            "request_consumed": self.request_consumed,
            "replay_guard_required": self.replay_guard_required,
            "campaign_start_authorized": self.campaign_start_authorized,
            "pilot_go_authorized": self.pilot_go_authorized,
            "activation_authorized": self.activation_authorized,
            "remote_publication_authorized": self.remote_publication_authorized,
            "authority": self.authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())


def build_physical_qualification_request(
    *,
    qualification: QualificationPacket,
    request_id: str,
    requested_frozen_main_sha: str,
    collector_actor_id: str,
    approver_actor_id: str,
    requested_at_utc: str,
    expires_at_utc: str,
) -> PhysicalQualificationRequest:
    """Create the unsigned payload a separate human authority may sign.

    This is request construction only.  It neither signs nor starts anything.
    """

    if not isinstance(qualification, QualificationPacket):
        raise PhysicalQualificationRequestError(
            "physical request requires QualificationPacket"
        )
    if (
        qualification.software_chain_complete is not True
        or qualification.ready_for_human_go is not False
        or qualification.activation_authorized is not False
        or qualification.automatic_activation is not False
        or qualification.remote_publication_authorized is not False
        or qualification.missing_physical_gates != MISSING_PHYSICAL_GATES
    ):
        raise PhysicalQualificationRequestError(
            "qualification packet is not at the pre-physical stop boundary"
        )
    return PhysicalQualificationRequest(
        request_id=request_id,
        qualification_packet_sha256=qualification.sha256,
        proposal_id=qualification.proposal_id,
        repository=qualification.repository,
        candidate_commit_sha=qualification.candidate_commit_sha,
        candidate_tree_sha=qualification.candidate_tree_sha,
        candidate_eval_sha256=qualification.candidate_eval_sha256,
        requested_frozen_main_sha=requested_frozen_main_sha,
        collector_actor_id=collector_actor_id,
        approver_actor_id=approver_actor_id,
        requested_at_utc=requested_at_utc,
        expires_at_utc=expires_at_utc,
    )


def verify_physical_qualification_request(
    *,
    request: PhysicalQualificationRequest,
    qualification: QualificationPacket,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    verified_at_utc: str,
) -> PhysicalQualificationRequestReceipt:
    """Verify a human request, but deliberately do not authorize campaign start."""

    if not isinstance(request, PhysicalQualificationRequest):
        raise PhysicalQualificationRequestError(
            "physical request verification requires PhysicalQualificationRequest"
        )
    if not isinstance(qualification, QualificationPacket):
        raise PhysicalQualificationRequestError(
            "physical request verification requires QualificationPacket"
        )
    if not isinstance(signature, DetachedEd25519AuthoritySignature):
        raise PhysicalQualificationRequestError(
            "physical request verification requires detached Ed25519 signature"
        )
    if not isinstance(verifier, Ed25519AuthorityVerifier):
        raise PhysicalQualificationRequestError(
            "physical request verification requires Ed25519AuthorityVerifier"
        )
    if signature.issuer_system_id != PHYSICAL_REQUEST_ISSUER_SYSTEM_ID:
        raise PhysicalQualificationRequestError(
            "physical request signature is from another authority system"
        )
    if (
        request.qualification_packet_sha256 != qualification.sha256
        or request.proposal_id != qualification.proposal_id
        or request.repository != qualification.repository
        or request.candidate_commit_sha != qualification.candidate_commit_sha
        or request.candidate_tree_sha != qualification.candidate_tree_sha
        or request.candidate_eval_sha256 != qualification.candidate_eval_sha256
    ):
        raise PhysicalQualificationRequestError(
            "physical request is not bound to qualification packet"
        )

    requested_at = _utc(request.requested_at_utc, name="requested_at_utc")
    expires_at = _utc(request.expires_at_utc, name="expires_at_utc")
    verified_at = _utc(verified_at_utc, name="verified_at_utc")
    signed_at = _utc(signature.signed_at_utc, name="signature.signed_at_utc")
    if signed_at < requested_at:
        raise PhysicalQualificationRequestError(
            "physical request signature predates the request"
        )
    if verified_at > expires_at:
        raise PhysicalQualificationRequestError(
            "physical qualification request has expired"
        )

    payload = request.canonical_json().encode("utf-8")
    try:
        verifier.verify(payload=payload, signature=signature, at_utc=verified_at_utc)
    except AsymmetricAuthorityError as exc:
        raise PhysicalQualificationRequestError(
            f"physical request authority verification failed: {exc}"
        ) from exc

    return PhysicalQualificationRequestReceipt(
        request_id=request.request_id,
        request_sha256=request.sha256,
        qualification_packet_sha256=qualification.sha256,
        signature_sha256=signature.sha256,
        requester_actor_id=signature.issuer_actor_id,
        requested_frozen_main_sha=request.requested_frozen_main_sha,
        collector_actor_id=request.collector_actor_id,
        approver_actor_id=request.approver_actor_id,
        required_probes=request.required_probes,
        verified_at_utc=verified_at_utc,
    )
