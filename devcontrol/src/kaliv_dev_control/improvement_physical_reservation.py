"""Trusted local-main observation and durable one-time DC-L15 request reservation.

This boundary closes replay and proves that the locally observed ``main`` head
matched the SHA named by one human-signed physical-qualification request at the
time the request was consumed.  It deliberately does *not* claim that main is
frozen for the duration of a physical campaign and does not start any process.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

from .asymmetric_authority import (
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
)
from .durable_publication import (
    DurablePublicationError,
    create_once_file,
    unlink_durable,
)
from .improvement_physical_request import (
    PhysicalQualificationRequest,
    PhysicalQualificationRequestError,
    verify_physical_qualification_request,
)
from .improvement_qualification_packet import QualificationPacket
from .trusted_git_runtime_model import _has_linkish_component
from .trusted_git_runtime_runner import TrustedGitRunner
from .trusted_git_runtime_staging import TrustedGitRuntime

MAIN_OBSERVATION_SCHEMA = "kaliv-rsi-local-main-head-observation/v1"
RESERVATION_SCHEMA = "kaliv-rsi-physical-qualification-reservation/v1"
RESERVATION_AUTHORITY = "consumed-request-evidence-only"
MAIN_REF = "refs/heads/main"
_MAX_OBSERVATION_AGE = timedelta(minutes=5)
_MAX_ARTIFACT_BYTES = 256 * 1024

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PhysicalQualificationReservationError(ValueError):
    """The main-head observation or one-time reservation is invalid."""


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
        raise PhysicalQualificationReservationError(
            "physical qualification reservation is not canonical JSON"
        ) from exc


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _strict(value: Any, *, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PhysicalQualificationReservationError(f"{name} fields mismatch")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise PhysicalQualificationReservationError(f"{name} is invalid")
    return value


def _hex(value: Any, *, name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PhysicalQualificationReservationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PhysicalQualificationReservationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PhysicalQualificationReservationError(f"{name} is invalid") from exc


def _safe_root(path: Path, *, name: str) -> Path:
    root = Path(path)
    if (
        not root.is_absolute()
        or not root.is_dir()
        or _has_linkish_component(root)
    ):
        raise PhysicalQualificationReservationError(
            f"{name} must be an absolute link-free directory"
        )
    return root.resolve()


_OBSERVATION_FIELDS = {
    "schema",
    "repository",
    "ref",
    "observed_sha",
    "observed_at_utc",
    "git_runtime_manifest_sha256",
    "git_executable_sha256",
    "network_performed",
    "repository_mutated",
    "authority",
}


@dataclass(frozen=True, slots=True)
class LocalMainHeadObservation:
    repository: str
    observed_sha: str
    observed_at_utc: str
    git_runtime_manifest_sha256: str
    git_executable_sha256: str
    ref: str = MAIN_REF
    network_performed: bool = False
    repository_mutated: bool = False
    authority: str = "evidence-only"
    schema: str = MAIN_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != MAIN_OBSERVATION_SCHEMA:
            raise PhysicalQualificationReservationError(
                "main-head observation schema is unsupported"
            )
        if self.repository != "Ternedal/ModelRig" or self.ref != MAIN_REF:
            raise PhysicalQualificationReservationError(
                "main-head observation repository/ref is unsupported"
            )
        _hex(self.observed_sha, name="observed_sha", pattern=_HEX40)
        _utc(self.observed_at_utc, name="observed_at_utc")
        _hex(
            self.git_runtime_manifest_sha256,
            name="git_runtime_manifest_sha256",
            pattern=_HEX64,
        )
        _hex(
            self.git_executable_sha256,
            name="git_executable_sha256",
            pattern=_HEX64,
        )
        if (
            self.network_performed is not False
            or self.repository_mutated is not False
            or self.authority != "evidence-only"
        ):
            raise PhysicalQualificationReservationError(
                "main-head observation must remain local read-only evidence"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "LocalMainHeadObservation":
        return cls(**_strict(value, fields=_OBSERVATION_FIELDS, name="main-head observation"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "repository": self.repository,
            "ref": self.ref,
            "observed_sha": self.observed_sha,
            "observed_at_utc": self.observed_at_utc,
            "git_runtime_manifest_sha256": self.git_runtime_manifest_sha256,
            "git_executable_sha256": self.git_executable_sha256,
            "network_performed": self.network_performed,
            "repository_mutated": self.repository_mutated,
            "authority": self.authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())


class _GitReader(Protocol):
    def run(self, args: tuple[str, ...], *, cwd: Path, maximum: int, **kwargs: Any) -> bytes: ...


def _observe_with_reader(
    *,
    reader: _GitReader,
    repository_root: Path,
    repository: str,
    observed_at_utc: str,
    git_runtime_manifest_sha256: str,
    git_executable_sha256: str,
) -> LocalMainHeadObservation:
    root = _safe_root(repository_root, name="main observation repository root")
    try:
        raw = reader.run(
            ("rev-parse", "--verify", f"{MAIN_REF}^{{commit}}"),
            cwd=root,
            maximum=4096,
        )
        observed_sha = raw.decode("ascii", errors="strict").strip()
    except (UnicodeError, OSError, ValueError) as exc:
        raise PhysicalQualificationReservationError(
            "trusted local Git could not observe main head"
        ) from exc
    _hex(observed_sha, name="observed main SHA", pattern=_HEX40)
    return LocalMainHeadObservation(
        repository=repository,
        observed_sha=observed_sha,
        observed_at_utc=observed_at_utc,
        git_runtime_manifest_sha256=git_runtime_manifest_sha256,
        git_executable_sha256=git_executable_sha256,
    )


def observe_local_main_head(
    *,
    trusted_git: TrustedGitRuntime,
    repository_root: Path,
    operation_root: Path,
    observed_at_utc: str,
    repository: str = "Ternedal/ModelRig",
) -> LocalMainHeadObservation:
    """Read only ``refs/heads/main`` through the staged trusted Git runtime."""

    if not isinstance(trusted_git, TrustedGitRuntime):
        raise PhysicalQualificationReservationError(
            "main observation requires TrustedGitRuntime"
        )
    operation = _safe_root(operation_root, name="main observation operation root")
    runner = TrustedGitRunner(trusted_git, operation_root=operation)
    evidence = runner.evidence()
    observation = _observe_with_reader(
        reader=runner,
        repository_root=repository_root,
        repository=repository,
        observed_at_utc=observed_at_utc,
        git_runtime_manifest_sha256=evidence.runtime_manifest_sha256,
        git_executable_sha256=evidence.executable_sha256,
    )
    trusted_git.verify()
    return observation


_RESERVATION_FIELDS = {
    "schema",
    "ledger_id",
    "request_id",
    "request_sha256",
    "qualification_packet_sha256",
    "signature_sha256",
    "requester_actor_id",
    "requested_main_sha",
    "observed_main_sha",
    "main_observation_sha256",
    "observed_at_utc",
    "consumed_at_utc",
    "collector_actor_id",
    "approver_actor_id",
    "main_head_match_confirmed",
    "request_consumed",
    "replay_safe",
    "frozen_main_confirmed",
    "physical_campaign_completed",
    "campaign_start_authorized",
    "pilot_go_authorized",
    "activation_authorized",
    "remote_publication_authorized",
    "authority",
}


@dataclass(frozen=True, slots=True)
class PhysicalQualificationReservation:
    ledger_id: str
    request_id: str
    request_sha256: str
    qualification_packet_sha256: str
    signature_sha256: str
    requester_actor_id: str
    requested_main_sha: str
    observed_main_sha: str
    main_observation_sha256: str
    observed_at_utc: str
    consumed_at_utc: str
    collector_actor_id: str
    approver_actor_id: str
    main_head_match_confirmed: bool = True
    request_consumed: bool = True
    replay_safe: bool = True
    frozen_main_confirmed: bool = False
    physical_campaign_completed: bool = False
    campaign_start_authorized: bool = False
    pilot_go_authorized: bool = False
    activation_authorized: bool = False
    remote_publication_authorized: bool = False
    authority: str = RESERVATION_AUTHORITY
    schema: str = RESERVATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != RESERVATION_SCHEMA:
            raise PhysicalQualificationReservationError(
                "physical reservation schema is unsupported"
            )
        _identifier(self.ledger_id, name="ledger_id")
        _identifier(self.request_id, name="request_id")
        for name, value, pattern in (
            ("request_sha256", self.request_sha256, _HEX64),
            ("qualification_packet_sha256", self.qualification_packet_sha256, _HEX64),
            ("signature_sha256", self.signature_sha256, _HEX64),
            ("requested_main_sha", self.requested_main_sha, _HEX40),
            ("observed_main_sha", self.observed_main_sha, _HEX40),
            ("main_observation_sha256", self.main_observation_sha256, _HEX64),
        ):
            _hex(value, name=name, pattern=pattern)
        _identifier(self.requester_actor_id, name="requester_actor_id")
        _identifier(self.collector_actor_id, name="collector_actor_id")
        _identifier(self.approver_actor_id, name="approver_actor_id")
        observed = _utc(self.observed_at_utc, name="observed_at_utc")
        consumed = _utc(self.consumed_at_utc, name="consumed_at_utc")
        if observed > consumed or consumed - observed > _MAX_OBSERVATION_AGE:
            raise PhysicalQualificationReservationError(
                "main-head observation is future-dated or stale at consumption"
            )
        if self.requested_main_sha != self.observed_main_sha:
            raise PhysicalQualificationReservationError(
                "reservation main SHA does not match requested main SHA"
            )
        if (
            self.main_head_match_confirmed is not True
            or self.request_consumed is not True
            or self.replay_safe is not True
        ):
            raise PhysicalQualificationReservationError(
                "reservation must preserve exact-match and one-time-consume evidence"
            )
        if (
            self.frozen_main_confirmed is not False
            or self.physical_campaign_completed is not False
            or self.campaign_start_authorized is not False
            or self.pilot_go_authorized is not False
            or self.activation_authorized is not False
            or self.remote_publication_authorized is not False
            or self.authority != RESERVATION_AUTHORITY
        ):
            raise PhysicalQualificationReservationError(
                "reservation may not claim freeze, campaign, pilot, publication or activation authority"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PhysicalQualificationReservation":
        return cls(**_strict(value, fields=_RESERVATION_FIELDS, name="physical reservation"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "ledger_id": self.ledger_id,
            "request_id": self.request_id,
            "request_sha256": self.request_sha256,
            "qualification_packet_sha256": self.qualification_packet_sha256,
            "signature_sha256": self.signature_sha256,
            "requester_actor_id": self.requester_actor_id,
            "requested_main_sha": self.requested_main_sha,
            "observed_main_sha": self.observed_main_sha,
            "main_observation_sha256": self.main_observation_sha256,
            "observed_at_utc": self.observed_at_utc,
            "consumed_at_utc": self.consumed_at_utc,
            "collector_actor_id": self.collector_actor_id,
            "approver_actor_id": self.approver_actor_id,
            "main_head_match_confirmed": self.main_head_match_confirmed,
            "request_consumed": self.request_consumed,
            "replay_safe": self.replay_safe,
            "frozen_main_confirmed": self.frozen_main_confirmed,
            "physical_campaign_completed": self.physical_campaign_completed,
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


class PhysicalQualificationRequestLedger:
    """Create-once ledger; every uncertain state remains consumed fail-closed."""

    def __init__(self, *, root: Path, ledger_id: str) -> None:
        self.root = _safe_root(root, name="physical request ledger root")
        self.ledger_id = _identifier(ledger_id, name="ledger_id")

    def _paths(self, request_sha256: str) -> tuple[Path, Path, Path]:
        digest = _hex(request_sha256, name="request_sha256", pattern=_HEX64)
        return (
            self.root / f"{digest}.json",
            self.root / f".{digest}.pending.json",
            self.root / f".{digest}.lock",
        )

    def _load_final(self, path: Path) -> PhysicalQualificationReservation:
        if not path.is_file() or _has_linkish_component(path):
            raise PhysicalQualificationReservationError(
                "physical reservation final artifact is missing or unsafe"
            )
        payload = path.read_bytes()
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PhysicalQualificationReservationError(
                "physical reservation final artifact exceeds byte bound"
            )
        try:
            value = json.loads(payload.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PhysicalQualificationReservationError(
                "physical reservation final artifact is invalid JSON"
            ) from exc
        receipt = PhysicalQualificationReservation.from_mapping(value)
        if payload != receipt.canonical_json().encode("utf-8"):
            raise PhysicalQualificationReservationError(
                "physical reservation final artifact is not canonical"
            )
        if receipt.ledger_id != self.ledger_id:
            raise PhysicalQualificationReservationError(
                "physical reservation belongs to another ledger"
            )
        return receipt

    def load(self, request_sha256: str) -> PhysicalQualificationReservation:
        final, pending, lock = self._paths(request_sha256)
        if final.exists() or final.is_symlink():
            return self._load_final(final)
        if pending.exists() or pending.is_symlink() or lock.exists() or lock.is_symlink():
            raise PhysicalQualificationReservationError(
                "physical request is consumed but reservation requires recovery"
            )
        raise PhysicalQualificationReservationError(
            "physical request reservation is missing"
        )

    def consume_once(
        self,
        reservation: PhysicalQualificationReservation,
    ) -> PhysicalQualificationReservation:
        if not isinstance(reservation, PhysicalQualificationReservation):
            raise PhysicalQualificationReservationError(
                "physical reservation ledger requires reservation evidence"
            )
        if reservation.ledger_id != self.ledger_id:
            raise PhysicalQualificationReservationError(
                "physical reservation ledger ID mismatch"
            )
        payload = reservation.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PhysicalQualificationReservationError(
                "physical reservation exceeds byte bound"
            )
        final, pending, lock = self._paths(reservation.request_sha256)
        if any(path.exists() or path.is_symlink() for path in (final, pending, lock)):
            raise PhysicalQualificationReservationError(
                "physical request has already been consumed or requires recovery"
            )
        reservation_marker = _canonical(
            {
                "schema": "kaliv-rsi-physical-qualification-reservation-lock/v1",
                "ledger_id": self.ledger_id,
                "request_sha256": reservation.request_sha256,
                "reservation_sha256": reservation.sha256,
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, reservation_marker)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PhysicalQualificationReservationError(
                "physical request could not be durably reserved"
            ) from exc
        try:
            create_once_file(pending, payload)
            create_once_file(final, payload)
            verified = self._load_final(final)
            if verified.canonical_json() != reservation.canonical_json():
                raise PhysicalQualificationReservationError(
                    "physical reservation post-write verification mismatch"
                )
            unlink_durable(pending)
            unlink_durable(lock)
        except Exception as exc:
            raise PhysicalQualificationReservationError(
                "physical request consumption is durable but requires recovery"
            ) from exc
        return verified


def build_physical_qualification_reservation(
    *,
    request: PhysicalQualificationRequest,
    qualification: QualificationPacket,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    observation: LocalMainHeadObservation,
    ledger_id: str,
    consumed_at_utc: str,
) -> PhysicalQualificationReservation:
    """Reverify the human request and bind it to one fresh local-main observation."""

    if not isinstance(observation, LocalMainHeadObservation):
        raise PhysicalQualificationReservationError(
            "physical reservation requires LocalMainHeadObservation"
        )
    try:
        request_receipt = verify_physical_qualification_request(
            request=request,
            qualification=qualification,
            signature=signature,
            verifier=verifier,
            verified_at_utc=consumed_at_utc,
        )
    except PhysicalQualificationRequestError as exc:
        raise PhysicalQualificationReservationError(
            f"physical request re-verification failed: {exc}"
        ) from exc
    if observation.repository != request.repository:
        raise PhysicalQualificationReservationError(
            "main-head observation belongs to another repository"
        )
    consumed = _utc(consumed_at_utc, name="consumed_at_utc")
    observed = _utc(observation.observed_at_utc, name="observed_at_utc")
    if observed > consumed or consumed - observed > _MAX_OBSERVATION_AGE:
        raise PhysicalQualificationReservationError(
            "main-head observation is future-dated or stale at consumption"
        )
    if observation.observed_sha != request.requested_frozen_main_sha:
        raise PhysicalQualificationReservationError(
            "observed main head does not match the human-requested main SHA"
        )
    return PhysicalQualificationReservation(
        ledger_id=ledger_id,
        request_id=request.request_id,
        request_sha256=request.sha256,
        qualification_packet_sha256=qualification.sha256,
        signature_sha256=signature.sha256,
        requester_actor_id=request_receipt.requester_actor_id,
        requested_main_sha=request.requested_frozen_main_sha,
        observed_main_sha=observation.observed_sha,
        main_observation_sha256=observation.sha256,
        observed_at_utc=observation.observed_at_utc,
        consumed_at_utc=consumed_at_utc,
        collector_actor_id=request.collector_actor_id,
        approver_actor_id=request.approver_actor_id,
    )


def consume_physical_qualification_request_once(
    *,
    ledger: PhysicalQualificationRequestLedger,
    request: PhysicalQualificationRequest,
    qualification: QualificationPacket,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    observation: LocalMainHeadObservation,
    consumed_at_utc: str,
) -> PhysicalQualificationReservation:
    """Build and durably consume one request, without authorizing campaign start."""

    if not isinstance(ledger, PhysicalQualificationRequestLedger):
        raise PhysicalQualificationReservationError(
            "physical request consumption requires its dedicated ledger"
        )
    reservation = build_physical_qualification_reservation(
        request=request,
        qualification=qualification,
        signature=signature,
        verifier=verifier,
        observation=observation,
        ledger_id=ledger.ledger_id,
        consumed_at_utc=consumed_at_utc,
    )
    return ledger.consume_once(reservation)
