"""Replay-safe consumption boundary for one exact ADR-DC-024 DC-L16 start intent.

This module burns one verified human pilot-start authorization into a durable,
host-local create-once marker and returns a receipt.  Consumption is deliberately
not product execution: no command registry, executor, local commit, remote write,
merge, release, deploy or production activation authority is granted here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
    _require_host_controlled_ledger_root,
)
from .durable_publication import DurablePublicationError, create_once_file
from . import improvement_pilot_start_authorization as start_auth

PILOT_START_CONSUMPTION_RECEIPT_SCHEMA = (
    "kaliv-rsi-dc-l16-pilot-start-consumption-receipt/v1"
)
PILOT_START_CONSUMPTION_RECEIPT_AUTHORITY = (
    "consumed-dc-l16-pilot-start-intent-only"
)
PILOT_START_CONSUMPTION_LEDGER_SCOPE = "canonical-host-local-v1"
_MAX_RECEIPT_BYTES = 256 * 1024

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_RECEIPT_FIELDS = {
    "schema",
    "consumption_id_sha256",
    "authorization_proof_sha256",
    "authorization_sha256",
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
    "consumed_at_utc",
    "ledger_scope",
    "host_replay_guard_committed",
    "global_replay_safe",
    "one_shot_start_required",
    "start_consumed",
    "integration_ready",
    "pilot_start_authorized",
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
    """Pilot-start consumption is malformed, stale, replayed or unsafe."""


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
        raise PilotStartConsumptionError(
            "pilot-start consumption is not canonical JSON"
        ) from exc


def _strict(value: Any, *, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PilotStartConsumptionError(f"{name} fields mismatch")
    return value


def _hex(value: Any, *, name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
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
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotStartConsumptionError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _require_verified_start_proof(
    value: Any,
) -> start_auth.PilotStartAuthorizationProof:
    if type(value) is not start_auth.PilotStartAuthorizationProof:
        raise PilotStartConsumptionError(
            "exact PilotStartAuthorizationProof is required"
        )
    if (
        value.authority != start_auth.PILOT_START_AUTHORIZATION_PROOF_AUTHORITY
        or value.one_shot_start_required is not True
        or value.start_consumed is not False
        or value.integration_ready is not False
        or value.pilot_start_authorized is not True
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
            "pilot-start consumption requires one unconsumed ADR-DC-024 proof"
        )
    try:
        replayed = start_auth.PilotStartAuthorizationProof.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotStartConsumptionError(
            "pilot-start proof replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotStartConsumptionError(
            "pilot-start proof replay identity mismatch"
        )
    return value


def _consumption_id(proof: start_auth.PilotStartAuthorizationProof) -> str:
    material = (
        proof.sha256
        + "\n"
        + proof.authorization_sha256
        + "\n"
        + proof.start_nonce_sha256
    ).encode("ascii")
    return hashlib.sha256(material).hexdigest()


def _marker_path(
    ledger_root: Path,
    proof: start_auth.PilotStartAuthorizationProof,
) -> Path:
    return Path(ledger_root) / f"{_consumption_id(proof)}.json"


def _read_exact_regular_file(path: Path, *, maximum: int) -> bytes | None:
    candidate = Path(path)
    if (
        not candidate.is_absolute()
        or not isinstance(maximum, int)
        or isinstance(maximum, bool)
        or maximum < 1
    ):
        return None
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(candidate, flags)
    except OSError:
        return None
    try:
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_nlink != 1
            or observed.st_size < 1
            or observed.st_size > maximum
        ):
            return None
        remaining = observed.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            return None
        return b"".join(chunks)
    except OSError:
        return None
    finally:
        os.close(descriptor)


@dataclass(frozen=True, slots=True)
class PilotStartConsumptionReceipt:
    consumption_id_sha256: str
    authorization_proof_sha256: str
    authorization_sha256: str
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
    consumed_at_utc: str
    ledger_scope: str = PILOT_START_CONSUMPTION_LEDGER_SCOPE
    host_replay_guard_committed: bool = True
    global_replay_safe: bool = False
    one_shot_start_required: bool = True
    start_consumed: bool = True
    integration_ready: bool = False
    pilot_start_authorized: bool = False
    product_pilot_started: bool = False
    local_commit_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_START_CONSUMPTION_RECEIPT_AUTHORITY
    schema: str = PILOT_START_CONSUMPTION_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_START_CONSUMPTION_RECEIPT_SCHEMA:
            raise PilotStartConsumptionError(
                "pilot-start consumption receipt schema is unsupported"
            )
        for name, value, pattern in (
            ("consumption_id_sha256", self.consumption_id_sha256, _HEX64),
            ("authorization_proof_sha256", self.authorization_proof_sha256, _HEX64),
            ("authorization_sha256", self.authorization_sha256, _HEX64),
            ("preflight_proof_sha256", self.preflight_proof_sha256, _HEX64),
            ("attestation_sha256", self.attestation_sha256, _HEX64),
            ("packet_sha256", self.packet_sha256, _HEX64),
            ("selection_proof_sha256", self.selection_proof_sha256, _HEX64),
            ("candidate_proof_sha256", self.candidate_proof_sha256, _HEX64),
            ("requirements_sha256", self.requirements_sha256, _HEX64),
            ("trial_scope_sha256", self.trial_scope_sha256, _HEX64),
            ("start_nonce_sha256", self.start_nonce_sha256, _HEX64),
            ("base_sha", self.base_sha, _HEX40),
            ("requested_main_sha", self.requested_main_sha, _HEX40),
            ("workspace_root_path_sha256", self.workspace_root_path_sha256, _HEX64),
        ):
            _hex(value, name=name, pattern=pattern)
        for name, value in (
            ("trial_id", self.trial_id),
            ("operator_surface", self.operator_surface),
            ("selected_pilot_task_id", self.selected_pilot_task_id),
        ):
            _identifier(value, name=name)
        if self.repository != "Ternedal/ModelRig":
            raise PilotStartConsumptionError("repository is unsupported")
        if type(self.local_commits_allowed) is not bool:
            raise PilotStartConsumptionError(
                "local_commits_allowed must be boolean"
            )
        _utc(self.consumed_at_utc, name="consumed_at_utc")
        if self.ledger_scope != PILOT_START_CONSUMPTION_LEDGER_SCOPE:
            raise PilotStartConsumptionError(
                "pilot-start consumption ledger scope is invalid"
            )
        if (
            self.host_replay_guard_committed is not True
            or self.global_replay_safe is not False
            or self.one_shot_start_required is not True
            or self.start_consumed is not True
            or self.integration_ready is not False
            or self.pilot_start_authorized is not False
            or self.product_pilot_started is not False
            or self.local_commit_authorized is not False
            or self.remote_write_authorized is not False
            or self.push_authorized is not False
            or self.pr_mutation_authorized is not False
            or self.merge_authorized is not False
            or self.release_authorized is not False
            or self.deploy_authorized is not False
            or self.production_activation_authorized is not False
            or self.authority != PILOT_START_CONSUMPTION_RECEIPT_AUTHORITY
        ):
            raise PilotStartConsumptionError(
                "pilot-start consumption receipt authority boundary is invalid"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotStartConsumptionReceipt":
        return cls(
            **dict(
                _strict(
                    value,
                    fields=_RECEIPT_FIELDS,
                    name="pilot-start consumption receipt",
                )
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "consumption_id_sha256": self.consumption_id_sha256,
            "authorization_proof_sha256": self.authorization_proof_sha256,
            "authorization_sha256": self.authorization_sha256,
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
            "consumed_at_utc": self.consumed_at_utc,
            "ledger_scope": self.ledger_scope,
            "host_replay_guard_committed": self.host_replay_guard_committed,
            "global_replay_safe": self.global_replay_safe,
            "one_shot_start_required": self.one_shot_start_required,
            "start_consumed": self.start_consumed,
            "integration_ready": self.integration_ready,
            "pilot_start_authorized": self.pilot_start_authorized,
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


def _build_receipt(
    *,
    proof: start_auth.PilotStartAuthorizationProof,
    consumed_at_utc: str,
) -> PilotStartConsumptionReceipt:
    authorization = proof.authorization
    return PilotStartConsumptionReceipt(
        consumption_id_sha256=_consumption_id(proof),
        authorization_proof_sha256=proof.sha256,
        authorization_sha256=proof.authorization_sha256,
        preflight_proof_sha256=proof.preflight_proof_sha256,
        attestation_sha256=proof.attestation_sha256,
        packet_sha256=proof.packet_sha256,
        selection_proof_sha256=proof.selection_proof_sha256,
        candidate_proof_sha256=proof.candidate_proof_sha256,
        requirements_sha256=proof.requirements_sha256,
        trial_scope_sha256=proof.trial_scope_sha256,
        start_nonce_sha256=proof.start_nonce_sha256,
        repository=authorization.repository,
        base_sha=authorization.base_sha,
        requested_main_sha=authorization.requested_main_sha,
        trial_id=authorization.trial_id,
        operator_surface=authorization.operator_surface,
        selected_pilot_task_id=authorization.selected_pilot_task_id,
        workspace_root_path_sha256=authorization.workspace_root_path_sha256,
        local_commits_allowed=authorization.local_commits_allowed,
        consumed_at_utc=consumed_at_utc,
    )


def _consume_verified_pilot_start_authorization_once(
    *,
    proof: start_auth.PilotStartAuthorizationProof,
    ledger_root: Path,
    now_provider: Callable[[], str],
) -> PilotStartConsumptionReceipt:
    """Deterministic test seam: burn one already-verified proof exactly once."""
    verified = _require_verified_start_proof(proof)
    root = Path(ledger_root)
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise PilotStartConsumptionError(
            "pilot-start consumption ledger root must be an existing absolute directory"
        )

    consumed_at_utc = now_provider()
    consumed = _utc(consumed_at_utc, name="consumed_at_utc")
    verified_at = _utc(verified.verified_at_utc, name="verified_at_utc")
    authorized_at = _utc(
        verified.authorization.authorized_at_utc,
        name="authorized_at_utc",
    )
    expires_at = _utc(
        verified.authorization.expires_at_utc,
        name="expires_at_utc",
    )
    if consumed < verified_at or consumed < authorized_at or consumed > expires_at:
        raise PilotStartConsumptionError(
            "pilot-start authorization is not valid at consumption time"
        )

    receipt = _build_receipt(proof=verified, consumed_at_utc=consumed_at_utc)
    payload = receipt.canonical_json().encode("utf-8")
    if len(payload) > _MAX_RECEIPT_BYTES:
        raise PilotStartConsumptionError(
            "pilot-start consumption receipt exceeds the byte budget"
        )
    marker = _marker_path(root, verified)
    try:
        create_once_file(marker, payload)
    except FileExistsError as exc:
        raise PilotStartConsumptionError(
            "pilot-start authorization was already consumed or its replay marker exists"
        ) from exc
    except DurablePublicationError as exc:
        raise PilotStartConsumptionError(
            "pilot-start replay marker could not be durably published"
        ) from exc

    readback = _read_exact_regular_file(marker, maximum=_MAX_RECEIPT_BYTES)
    if readback != payload:
        # The marker is intentionally not removed. A failed post-publication
        # readback burns this authorization fail-closed instead of making replay
        # possible after an ambiguous local durability event.
        raise PilotStartConsumptionError(
            "pilot-start replay marker readback mismatch; authorization remains consumed"
        )
    return receipt


def _canonical_pilot_start_ledger_root() -> Path:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            candidate = Path(
                "/var/lib/modelrig/devcontrol/rsi-pilot-start-ledger-v1"
            )
        elif os.name == "nt":
            candidate = Path(
                r"C:\Program Files\ModelRig\DevControl\state\rsi-pilot-start-ledger-v1"
            )
        else:
            raise PilotStartConsumptionError(
                "pilot-start consumption is unsupported on this platform"
            )
        return _require_host_controlled_ledger_root(candidate)
    except PhysicalHostStateError as exc:
        raise PilotStartConsumptionError(
            "canonical pilot-start replay ledger is unavailable or not host controlled"
        ) from exc


def consume_pilot_start_authorization_once(
    *,
    preflight_proof: Any,
    authorization: Any,
    signature: Any,
    preflight_signature: Any,
) -> PilotStartConsumptionReceipt:
    """Freshly verify ADR-023/024 authority, then irreversibly consume it once."""
    # Production does not accept a caller-supplied serialized proof as authority.
    # Re-verification is intentionally delegated to ADR-024's host-pinned facade,
    # which itself fresh-verifies the detached ADR-023 preflight signature.
    try:
        proof = start_auth.verify_pilot_start_authorization(
            preflight_proof=preflight_proof,
            authorization=authorization,
            signature=signature,
            preflight_signature=preflight_signature,
        )
    except (ValueError, TypeError, AttributeError) as exc:
        raise PilotStartConsumptionError(
            "fresh pilot-start authorization verification failed"
        ) from exc

    return _consume_verified_pilot_start_authorization_once(
        proof=proof,
        ledger_root=_canonical_pilot_start_ledger_root(),
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_START_CONSUMPTION_RECEIPT_SCHEMA",
    "PILOT_START_CONSUMPTION_RECEIPT_AUTHORITY",
    "PILOT_START_CONSUMPTION_LEDGER_SCOPE",
    "PilotStartConsumptionError",
    "PilotStartConsumptionReceipt",
    "consume_pilot_start_authorization_once",
]
