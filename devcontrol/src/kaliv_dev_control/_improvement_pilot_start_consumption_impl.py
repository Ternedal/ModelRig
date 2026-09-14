"""Crash-durable one-shot consumption of one verified DC-L16 pilot-start authorization.

ADR-DC-025 burns one already-verified ADR-DC-024 start intent in a host-local
replay ledger and emits a receipt.  Consumption is deliberately not execution:
it does not register commands, enable product code, execute a task, create a
commit, mutate Git/GitHub, or grant remote/production authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .durable_publication import DurablePublicationError, create_once_file, unlink_durable
from .improvement_pilot_start_authorization import (
    PILOT_START_AUTHORIZATION_PROOF_AUTHORITY,
    PilotStartAuthorizationProof,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_START_CONSUMPTION_RECEIPT_SCHEMA = (
    "kaliv-rsi-dc-l16-pilot-start-consumption-receipt/v1"
)
PILOT_START_CONSUMPTION_RESERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-pilot-start-consumption-reservation/v1"
)
PILOT_START_CONSUMPTION_AUTHORITY = (
    "verified-host-local-dc-l16-pilot-start-consumption-only"
)
PILOT_START_CONSUMPTION_LEDGER_ID = "rsi-pilot-start-consumption-v1"
_MAX_RECEIPT_BYTES = 4 * 1024 * 1024
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_RECEIPT_FIELDS = {
    "schema",
    "authorization_proof",
    "authorization_proof_sha256",
    "authorization_sha256",
    "authorization_signature_sha256",
    "preflight_proof_sha256",
    "attestation_sha256",
    "packet_sha256",
    "selection_proof_sha256",
    "candidate_proof_sha256",
    "requirements_sha256",
    "trial_scope_sha256",
    "start_nonce_sha256",
    "repository",
    "base_sha",
    "requested_main_sha",
    "trial_id",
    "operator_surface",
    "selected_pilot_task_id",
    "workspace_root_path_sha256",
    "local_commits_allowed",
    "ledger_id",
    "consumed_at_utc",
    "host_local_replay_guard_committed",
    "global_replay_safe",
    "one_shot_start_required",
    "start_consumed",
    "pilot_start_authorized",
    "pilot_execution_authorized",
    "integration_ready",
    "product_pilot_started",
    "local_commit_authorized",
    "remote_write_authorized",
    "push_authorized",
    "pr_mutation_authorized",
    "merge_authorized",
    "release_authorized",
    "deploy_authorized",
    "production_activation_authorized",
    "authority",
}


class PilotStartConsumptionError(ValueError):
    """Pilot-start consumption is stale, replayed, malformed or over-authorizing."""


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
        raise PilotStartConsumptionError("pilot-start consumption is not canonical JSON") from exc


def _strict(value: Any, *, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PilotStartConsumptionError(f"{name} fields mismatch")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise PilotStartConsumptionError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotStartConsumptionError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotStartConsumptionError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotStartConsumptionError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_authorized_proof(value: Any) -> PilotStartAuthorizationProof:
    if type(value) is not PilotStartAuthorizationProof:
        raise PilotStartConsumptionError("exact PilotStartAuthorizationProof is required")
    if (
        value.authority != PILOT_START_AUTHORIZATION_PROOF_AUTHORITY
        or value.one_shot_start_required is not True
        or value.start_consumed is not False
        or value.pilot_start_authorized is not True
        or value.integration_ready is not False
        or value.product_pilot_started is not False
        or value.local_commit_authorized is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotStartConsumptionError(
            "pilot-start consumption requires inert verified ADR-DC-024 authority"
        )
    try:
        replayed = PilotStartAuthorizationProof.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotStartConsumptionError(
            "pilot-start authorization proof replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotStartConsumptionError("pilot-start authorization proof replay identity mismatch")
    return value


def _receipt_binding(proof: PilotStartAuthorizationProof) -> dict[str, Any]:
    auth = proof.authorization
    return {
        "authorization_proof_sha256": proof.sha256,
        "authorization_sha256": proof.authorization_sha256,
        "authorization_signature_sha256": proof.signature_sha256,
        "preflight_proof_sha256": proof.preflight_proof_sha256,
        "attestation_sha256": proof.attestation_sha256,
        "packet_sha256": proof.packet_sha256,
        "selection_proof_sha256": proof.selection_proof_sha256,
        "candidate_proof_sha256": proof.candidate_proof_sha256,
        "requirements_sha256": proof.requirements_sha256,
        "trial_scope_sha256": proof.trial_scope_sha256,
        "start_nonce_sha256": proof.start_nonce_sha256,
        "repository": auth.repository,
        "base_sha": auth.base_sha,
        "requested_main_sha": auth.requested_main_sha,
        "trial_id": auth.trial_id,
        "operator_surface": auth.operator_surface,
        "selected_pilot_task_id": auth.selected_pilot_task_id,
        "workspace_root_path_sha256": auth.workspace_root_path_sha256,
        "local_commits_allowed": auth.local_commits_allowed,
    }


@dataclass(frozen=True, slots=True)
class PilotStartConsumptionReceipt:
    authorization_proof: PilotStartAuthorizationProof
    authorization_proof_sha256: str
    authorization_sha256: str
    authorization_signature_sha256: str
    preflight_proof_sha256: str
    attestation_sha256: str
    packet_sha256: str
    selection_proof_sha256: str
    candidate_proof_sha256: str
    requirements_sha256: str
    trial_scope_sha256: str
    start_nonce_sha256: str
    repository: str
    base_sha: str
    requested_main_sha: str
    trial_id: str
    operator_surface: str
    selected_pilot_task_id: str
    workspace_root_path_sha256: str
    local_commits_allowed: bool
    ledger_id: str
    consumed_at_utc: str
    host_local_replay_guard_committed: bool = True
    global_replay_safe: bool = False
    one_shot_start_required: bool = True
    start_consumed: bool = True
    pilot_start_authorized: bool = True
    pilot_execution_authorized: bool = False
    integration_ready: bool = False
    product_pilot_started: bool = False
    local_commit_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_START_CONSUMPTION_AUTHORITY
    schema: str = PILOT_START_CONSUMPTION_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_START_CONSUMPTION_RECEIPT_SCHEMA:
            raise PilotStartConsumptionError("pilot-start consumption receipt schema unsupported")
        proof = _require_authorized_proof(self.authorization_proof)
        for name in (
            "authorization_proof_sha256",
            "authorization_sha256",
            "authorization_signature_sha256",
            "preflight_proof_sha256",
            "attestation_sha256",
            "packet_sha256",
            "selection_proof_sha256",
            "candidate_proof_sha256",
            "requirements_sha256",
            "trial_scope_sha256",
            "start_nonce_sha256",
            "workspace_root_path_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _identifier(self.ledger_id, name="ledger_id")
        for name in ("trial_id", "operator_surface", "selected_pilot_task_id"):
            _identifier(getattr(self, name), name=name)
        if self.repository != "Ternedal/ModelRig":
            raise PilotStartConsumptionError("repository is unsupported")
        if type(self.local_commits_allowed) is not bool:
            raise PilotStartConsumptionError("local_commits_allowed must be boolean")
        expected = _receipt_binding(proof)
        mismatch = next(
            (name for name, item in expected.items() if getattr(self, name) != item),
            None,
        )
        if mismatch is not None:
            raise PilotStartConsumptionError(f"pilot-start consumption binding mismatch: {mismatch}")
        consumed = _utc(self.consumed_at_utc, name="consumed_at_utc")
        verified = _utc(proof.verified_at_utc, name="authorization verified_at_utc")
        expires = _utc(proof.authorization.expires_at_utc, name="authorization expires_at_utc")
        if consumed < verified or consumed > expires:
            raise PilotStartConsumptionError(
                "pilot-start consumption must occur after verification and before expiry"
            )
        if (
            self.host_local_replay_guard_committed is not True
            or self.global_replay_safe is not False
            or self.one_shot_start_required is not True
            or self.start_consumed is not True
            or self.pilot_start_authorized is not True
            or self.pilot_execution_authorized is not False
            or self.integration_ready is not False
            or self.product_pilot_started is not False
            or self.local_commit_authorized is not False
            or self.remote_write_authorized is not False
            or self.push_authorized is not False
            or self.pr_mutation_authorized is not False
            or self.merge_authorized is not False
            or self.release_authorized is not False
            or self.deploy_authorized is not False
            or self.production_activation_authorized is not False
            or self.authority != PILOT_START_CONSUMPTION_AUTHORITY
        ):
            raise PilotStartConsumptionError("pilot-start consumption authority boundary invalid")

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotStartConsumptionReceipt":
        data = dict(_strict(value, fields=_RECEIPT_FIELDS, name="pilot-start consumption receipt"))
        if not isinstance(data.get("authorization_proof"), Mapping):
            raise PilotStartConsumptionError("authorization_proof must be an object")
        try:
            data["authorization_proof"] = PilotStartAuthorizationProof.from_mapping(
                data["authorization_proof"]
            )
        except Exception as exc:
            raise PilotStartConsumptionError(
                "nested pilot-start authorization proof is invalid"
            ) from exc
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "authorization_proof": self.authorization_proof.to_dict(),
            "authorization_proof_sha256": self.authorization_proof_sha256,
            "authorization_sha256": self.authorization_sha256,
            "authorization_signature_sha256": self.authorization_signature_sha256,
            "preflight_proof_sha256": self.preflight_proof_sha256,
            "attestation_sha256": self.attestation_sha256,
            "packet_sha256": self.packet_sha256,
            "selection_proof_sha256": self.selection_proof_sha256,
            "candidate_proof_sha256": self.candidate_proof_sha256,
            "requirements_sha256": self.requirements_sha256,
            "trial_scope_sha256": self.trial_scope_sha256,
            "start_nonce_sha256": self.start_nonce_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "requested_main_sha": self.requested_main_sha,
            "trial_id": self.trial_id,
            "operator_surface": self.operator_surface,
            "selected_pilot_task_id": self.selected_pilot_task_id,
            "workspace_root_path_sha256": self.workspace_root_path_sha256,
            "local_commits_allowed": self.local_commits_allowed,
            "ledger_id": self.ledger_id,
            "consumed_at_utc": self.consumed_at_utc,
            "host_local_replay_guard_committed": self.host_local_replay_guard_committed,
            "global_replay_safe": self.global_replay_safe,
            "one_shot_start_required": self.one_shot_start_required,
            "start_consumed": self.start_consumed,
            "pilot_start_authorized": self.pilot_start_authorized,
            "pilot_execution_authorized": self.pilot_execution_authorized,
            "integration_ready": self.integration_ready,
            "product_pilot_started": self.product_pilot_started,
            "local_commit_authorized": self.local_commit_authorized,
            "remote_write_authorized": self.remote_write_authorized,
            "push_authorized": self.push_authorized,
            "pr_mutation_authorized": self.pr_mutation_authorized,
            "merge_authorized": self.merge_authorized,
            "release_authorized": self.release_authorized,
            "deploy_authorized": self.deploy_authorized,
            "production_activation_authorized": self.production_activation_authorized,
            "authority": self.authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class PilotStartConsumptionLedger:
    """Host-local one-shot ledger; any crash uncertainty keeps the nonce consumed."""

    def __init__(self, *, root: Path, ledger_id: str = PILOT_START_CONSUMPTION_LEDGER_ID) -> None:
        candidate = Path(root)
        if (
            not candidate.is_absolute()
            or not candidate.is_dir()
            or _has_linkish_component(candidate)
        ):
            raise PilotStartConsumptionError(
                "pilot-start consumption ledger root must be an absolute link-free directory"
            )
        self._root = candidate.resolve()
        self._ledger_id = _identifier(ledger_id, name="ledger_id")

    @property
    def ledger_id(self) -> str:
        return self._ledger_id

    def _paths(self, nonce: str) -> tuple[Path, Path, Path]:
        token = _hex64(nonce, name="start_nonce_sha256")
        return (
            self._root / f"{token}.json",
            self._root / f".{token}.pending.json",
            self._root / f".{token}.lock",
        )

    def _load_receipt(self, path: Path) -> PilotStartConsumptionReceipt:
        candidate = Path(path)
        if not candidate.is_file() or candidate.is_symlink():
            raise PilotStartConsumptionError("pilot-start consumption receipt is missing or unsafe")
        payload = candidate.read_bytes()
        if not payload or len(payload) > _MAX_RECEIPT_BYTES:
            raise PilotStartConsumptionError("pilot-start consumption receipt size is invalid")
        try:
            value = json.loads(payload.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PilotStartConsumptionError("pilot-start consumption receipt is invalid JSON") from exc
        receipt = PilotStartConsumptionReceipt.from_mapping(value)
        if payload != receipt.canonical_json().encode("utf-8"):
            raise PilotStartConsumptionError("pilot-start consumption receipt is not canonical")
        if receipt.ledger_id != self._ledger_id:
            raise PilotStartConsumptionError("pilot-start consumption receipt belongs to another ledger")
        return receipt

    def consume_once(
        self,
        *,
        proof: PilotStartAuthorizationProof,
        consumed_at_utc: str,
    ) -> PilotStartConsumptionReceipt:
        authorized = _require_authorized_proof(proof)
        binding = _receipt_binding(authorized)
        receipt = PilotStartConsumptionReceipt(
            authorization_proof=authorized,
            **binding,
            ledger_id=self._ledger_id,
            consumed_at_utc=consumed_at_utc,
        )
        payload = receipt.canonical_json().encode("utf-8")
        if len(payload) > _MAX_RECEIPT_BYTES:
            raise PilotStartConsumptionError("pilot-start consumption receipt exceeds byte bound")
        final, pending, lock = self._paths(authorized.start_nonce_sha256)
        if any(path.exists() or path.is_symlink() for path in (final, pending, lock)):
            raise PilotStartConsumptionError(
                "pilot-start nonce is already consumed or requires explicit recovery"
            )
        reservation = _canonical(
            {
                "schema": PILOT_START_CONSUMPTION_RESERVATION_SCHEMA,
                "ledger_id": self._ledger_id,
                "authorization_proof_sha256": authorized.sha256,
                "authorization_sha256": authorized.authorization_sha256,
                "start_nonce_sha256": authorized.start_nonce_sha256,
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, reservation)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotStartConsumptionError(
                "pilot-start nonce is already consumed or could not be durably reserved"
            ) from exc
        try:
            create_once_file(pending, payload)
            create_once_file(final, payload)
            verified = self._load_receipt(final)
            if verified != receipt or verified.sha256 != receipt.sha256:
                raise PilotStartConsumptionError("pilot-start final receipt identity mismatch")
            unlink_durable(pending)
            unlink_durable(lock)
        except Exception as exc:
            raise PilotStartConsumptionError(
                "pilot-start authorization is durably consumed but receipt requires explicit recovery"
            ) from exc
        return receipt

    def load(self, start_nonce_sha256: str) -> PilotStartConsumptionReceipt:
        final, pending, lock = self._paths(start_nonce_sha256)
        if final.exists():
            return self._load_receipt(final)
        if pending.exists() or lock.exists() or pending.is_symlink() or lock.is_symlink():
            raise PilotStartConsumptionError(
                "pilot-start authorization is consumed but has no usable final receipt"
            )
        raise PilotStartConsumptionError("pilot-start consumption receipt is missing")


def _consume_pilot_start_authorization(
    *,
    proof: PilotStartAuthorizationProof,
    ledger: PilotStartConsumptionLedger,
    now_provider: Callable[[], str],
) -> PilotStartConsumptionReceipt:
    if type(ledger) is not PilotStartConsumptionLedger:
        raise PilotStartConsumptionError("exact PilotStartConsumptionLedger is required")
    consumed_at = now_provider()
    _utc(consumed_at, name="pilot-start consumption time")
    return ledger.consume_once(proof=proof, consumed_at_utc=consumed_at)


def consume_pilot_start_authorization(
    *,
    proof: PilotStartAuthorizationProof,
    ledger: PilotStartConsumptionLedger | None = None,
) -> PilotStartConsumptionReceipt:
    """Injectable compatibility seam replaced by the production facade."""
    if ledger is None:
        raise PilotStartConsumptionError(
            "pilot-start consumption ledger is unavailable outside production facade"
        )
    return _consume_pilot_start_authorization(
        proof=proof,
        ledger=ledger,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_START_CONSUMPTION_RECEIPT_SCHEMA",
    "PILOT_START_CONSUMPTION_RESERVATION_SCHEMA",
    "PILOT_START_CONSUMPTION_AUTHORITY",
    "PILOT_START_CONSUMPTION_LEDGER_ID",
    "PilotStartConsumptionError",
    "PilotStartConsumptionReceipt",
    "PilotStartConsumptionLedger",
    "consume_pilot_start_authorization",
]
