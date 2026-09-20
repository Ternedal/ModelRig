"""ADR-DC-095 read-only post-production activation attestation.

Normalizes exactly one durable production activation completion source:
- a completed ADR-DC-093 production activation transaction; or
- an ADR-DC-094 write-free recovery classified as ``exact_activated``.

The exact physical host state is then observed twice through ADR-DC-094's
existing production-state observer. Both observations must independently prove
the same exact activated machine state and must remain bound to the durable
completion evidence.

This boundary performs no production mutation, restart, receipt publication,
GitHub/deployment/release write, or durable attestation write. All reusable
mutation authority remains false.
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
from . import improvement_pilot_exact_task_production_activation_recovery as recovery_boundary
from . import improvement_pilot_exact_task_production_activation_transaction as tx_boundary

PILOT_EXACT_TASK_POST_PRODUCTION_ACTIVATION_ATTESTATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-post-production-activation-attestation-receipt/v1"
)
PILOT_EXACT_TASK_POST_PRODUCTION_ACTIVATION_ATTESTATION_AUTHORITY = (
    "host-attested-one-dc-l16-exact-post-production-activation-state-only"
)
PILOT_EXACT_TASK_POST_PRODUCTION_ACTIVATION_ATTESTATION_SCOPE = (
    "read-only-exact-post-production-activation-verification-v1"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")


class PilotExactTaskPostProductionActivationAttestationError(ValueError):
    """Durable production completion or current activated state is untrustworthy."""


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPostProductionActivationAttestationError(
            "post-production activation evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskPostProductionActivationAttestationError(
            f"{name} is invalid"
        )
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskPostProductionActivationAttestationError(
            f"{name} is invalid"
        )
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str):
        raise PilotExactTaskPostProductionActivationAttestationError(
            f"{name} is invalid"
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PilotExactTaskPostProductionActivationAttestationError(
            f"{name} is invalid"
        ) from exc
    if parsed.tzinfo is None:
        raise PilotExactTaskPostProductionActivationAttestationError(
            f"{name} lacks timezone"
        )
    return parsed.astimezone(timezone.utc)


def _utc_seconds(value: Any, *, name: str) -> str:
    parsed = _utc(value, name=name)
    if parsed.microsecond:
        raise PilotExactTaskPostProductionActivationAttestationError(
            f"{name} must use whole UTC seconds"
        )
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _read_regular(path: Path, *, label: str) -> bytes:
    try:
        info = path.lstat()
    except OSError as exc:
        raise PilotExactTaskPostProductionActivationAttestationError(
            f"{label} is unavailable"
        ) from exc
    if path.is_symlink() or not path.is_file() or info.st_size <= 0:
        raise PilotExactTaskPostProductionActivationAttestationError(
            f"{label} must be a non-empty regular file"
        )
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PilotExactTaskPostProductionActivationAttestationError(
            f"{label} is unreadable"
        ) from exc
    if len(raw) > 8_000_000:
        raise PilotExactTaskPostProductionActivationAttestationError(
            f"{label} is too large"
        )
    return raw


def _read_canonical_object(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    raw = _read_regular(path, label=label)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPostProductionActivationAttestationError(
            f"{label} is invalid JSON"
        ) from exc
    if (
        not isinstance(value, dict)
        or _canonical(value).encode("utf-8") != raw
    ):
        raise PilotExactTaskPostProductionActivationAttestationError(
            f"{label} is not exact canonical JSON"
        )
    return value, raw


@dataclass(frozen=True, slots=True)
class _CompletionEvidence:
    completion_source: str
    source_receipt_sha256: str
    transaction_lock_sha256: str
    recovery_ledger_root_path_sha256: str | None
    recovery_lock_sha256: str | None
    production_activation_authorization_sha256: str
    production_activation_candidate_sha256: str
    production_activation_transaction_config_sha256: str
    pre_activation_evidence_sha256: str
    environment_before_sha256: str
    environment_after_sha256: str
    output_dir_path_sha256: str
    production_preflight_sha256: str
    machine_production_receipt_sha256: str
    repository: str
    repository_id: str
    merge_commit_sha: str
    promotion_git_sha: str
    source_completed_at_utc: str
    source_path: Path
    source_payload: bytes
    recovery_lock_path: Path | None
    recovery_lock_payload: bytes | None

    def __post_init__(self) -> None:
        if self.completion_source not in {"transaction", "recovery"}:
            raise PilotExactTaskPostProductionActivationAttestationError(
                "production activation completion source is unsupported"
            )
        for name in (
            "source_receipt_sha256",
            "transaction_lock_sha256",
            "production_activation_authorization_sha256",
            "production_activation_candidate_sha256",
            "production_activation_transaction_config_sha256",
            "pre_activation_evidence_sha256",
            "environment_before_sha256",
            "environment_after_sha256",
            "output_dir_path_sha256",
            "production_preflight_sha256",
            "machine_production_receipt_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in (
            "recovery_ledger_root_path_sha256",
            "recovery_lock_sha256",
        ):
            value = getattr(self, name)
            if value is not None:
                _hex64(value, name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        _hex40(self.promotion_git_sha, name="promotion_git_sha")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskPostProductionActivationAttestationError(
                "production activation completion projection is invalid"
            )
        _utc(self.source_completed_at_utc, name="source_completed_at_utc")
        if self.completion_source == "transaction":
            if (
                self.recovery_ledger_root_path_sha256 is not None
                or self.recovery_lock_sha256 is not None
                or self.recovery_lock_path is not None
                or self.recovery_lock_payload is not None
            ):
                raise PilotExactTaskPostProductionActivationAttestationError(
                    "normal production completion carries recovery provenance"
                )
        elif (
            self.recovery_ledger_root_path_sha256 is None
            or self.recovery_lock_sha256 is None
            or self.recovery_lock_path is None
            or self.recovery_lock_payload is None
        ):
            raise PilotExactTaskPostProductionActivationAttestationError(
                "recovered production completion lacks recovery provenance"
            )


def _load_transaction_lock_for_attestation(
    *,
    key: str,
    transaction_config: tx_boundary.PilotExactTaskProductionActivationTransactionConfig,
    transaction_ledger: tx_boundary._PilotExactTaskProductionActivationTransactionLedger,
) -> tuple[dict[str, Any], Path, bytes, str]:
    candidate = _hex64(key, name="production_activation_key_sha256")
    _final, lock_path = transaction_ledger._paths(candidate)
    raw_object, raw = _read_canonical_object(
        lock_path,
        label="ADR-DC-093 production activation transaction lock",
    )
    if set(raw_object) != recovery_boundary._TRANSACTION_LOCK_FIELDS:
        raise PilotExactTaskPostProductionActivationAttestationError(
            "ADR-DC-093 transaction lock fields mismatch"
        )
    lock_sha = hashlib.sha256(raw).hexdigest()
    expected_output = (
        Path(transaction_config.output_root).resolve() / candidate
    )
    if (
        raw_object.get("schema") != recovery_boundary._TRANSACTION_LOCK_SCHEMA
        or raw_object.get("ledger_scope")
        != tx_boundary.PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_TRANSACTION_LEDGER_SCOPE
        or raw_object.get("ledger_root_path_sha256") != transaction_ledger.root_sha256
        or raw_object.get("production_activation_key_sha256") != candidate
        or raw_object.get("production_activation_candidate_sha256") != candidate
        or raw_object.get("production_activation_transaction_config_sha256")
        != transaction_config.sha256
        or raw_object.get("repository") != transaction_config.repository
        or raw_object.get("repository_id") != transaction_config.repository_id
        or raw_object.get("output_dir_path_sha256")
        != recovery_boundary._path_digest(expected_output)
    ):
        raise PilotExactTaskPostProductionActivationAttestationError(
            "ADR-DC-093 transaction lock differs from host-pinned transaction"
        )
    for name in (
        "production_activation_authorization_sha256",
        "pre_activation_evidence_sha256",
        "environment_before_sha256",
        "output_dir_path_sha256",
    ):
        _hex64(raw_object.get(name), name=name)
    _hex40(raw_object.get("merge_commit_sha"), name="merge_commit_sha")
    _hex40(raw_object.get("promotion_head_sha"), name="promotion_head_sha")
    _utc(raw_object.get("locked_at_utc"), name="transaction_locked_at_utc")
    return raw_object, lock_path, raw, lock_sha


def _load_completion(
    *,
    key: str,
    transaction_config: tx_boundary.PilotExactTaskProductionActivationTransactionConfig,
    transaction_ledger: tx_boundary._PilotExactTaskProductionActivationTransactionLedger,
    recovery_ledger: recovery_boundary._PilotExactTaskProductionActivationRecoveryLedger,
) -> tuple[_CompletionEvidence, dict[str, Any], Path, bytes]:
    candidate = _hex64(key, name="production_activation_key_sha256")
    tx_final, _tx_lock = transaction_ledger._paths(candidate)
    recovery_final, recovery_lock = recovery_ledger._paths(candidate)

    tx_present = tx_final.exists() or tx_final.is_symlink()
    recovery_present = recovery_final.exists() or recovery_final.is_symlink()
    recovery_lock_present = recovery_lock.exists() or recovery_lock.is_symlink()

    if tx_present == recovery_present:
        raise PilotExactTaskPostProductionActivationAttestationError(
            "post-production activation source must be exactly one durable completion"
        )
    if tx_present and recovery_lock_present:
        raise PilotExactTaskPostProductionActivationAttestationError(
            "normal production completion collides with consumed recovery state"
        )
    if recovery_present and not recovery_lock_present:
        raise PilotExactTaskPostProductionActivationAttestationError(
            "recovered production completion lacks its durable recovery lock"
        )

    lock, lock_path, lock_payload, lock_sha = _load_transaction_lock_for_attestation(
        key=candidate,
        transaction_config=transaction_config,
        transaction_ledger=transaction_ledger,
    )

    if tx_present:
        raw, payload = _read_canonical_object(
            tx_final,
            label="ADR-DC-093 final production activation transaction receipt",
        )
        try:
            receipt = tx_boundary.PilotExactTaskProductionActivationTransactionReceipt.from_mapping(
                raw
            )
        except Exception as exc:
            raise PilotExactTaskPostProductionActivationAttestationError(
                "ADR-DC-093 final production activation receipt is invalid"
            ) from exc
        required = (
            receipt.production_activation_transaction_ledger_root_path_sha256
            == transaction_ledger.root_sha256
            and receipt.production_activation_key_sha256 == candidate
            and receipt.production_activation_candidate_sha256 == candidate
            and receipt.production_activation_transaction_config_sha256
            == transaction_config.sha256
            and receipt.production_activation_transaction_lock_sha256 == lock_sha
            and receipt.production_activation_authorization_sha256
            == lock["production_activation_authorization_sha256"]
            and receipt.pre_activation_evidence_sha256
            == lock["pre_activation_evidence_sha256"]
            and receipt.environment_before_sha256 == lock["environment_before_sha256"]
            and receipt.output_dir_path_sha256 == lock["output_dir_path_sha256"]
            and receipt.merge_commit_sha == lock["merge_commit_sha"]
            and receipt.promotion_git_sha == lock["promotion_head_sha"]
            and receipt.production_activation_completed is True
            and receipt.production_activation is True
            and receipt.production_machine_receipt_verified is True
            and receipt.production_activation_authorized is False
            and receipt.remote_write_authorized is False
            and receipt.nonce_reusable is False
        )
        if not required:
            raise PilotExactTaskPostProductionActivationAttestationError(
                "ADR-DC-093 final receipt is not exact durable activation completion"
            )
        completion = _CompletionEvidence(
            completion_source="transaction",
            source_receipt_sha256=receipt.sha256,
            transaction_lock_sha256=lock_sha,
            recovery_ledger_root_path_sha256=None,
            recovery_lock_sha256=None,
            production_activation_authorization_sha256=(
                receipt.production_activation_authorization_sha256
            ),
            production_activation_candidate_sha256=candidate,
            production_activation_transaction_config_sha256=transaction_config.sha256,
            pre_activation_evidence_sha256=receipt.pre_activation_evidence_sha256,
            environment_before_sha256=receipt.environment_before_sha256,
            environment_after_sha256=receipt.environment_after_sha256,
            output_dir_path_sha256=receipt.output_dir_path_sha256,
            production_preflight_sha256=receipt.production_preflight_sha256,
            machine_production_receipt_sha256=receipt.machine_production_receipt_sha256,
            repository=receipt.repository,
            repository_id=receipt.repository_id,
            merge_commit_sha=receipt.merge_commit_sha,
            promotion_git_sha=receipt.promotion_git_sha,
            source_completed_at_utc=_utc_seconds(
                receipt.controller_completed_at_utc,
                name="source_completed_at_utc",
            ),
            source_path=tx_final,
            source_payload=payload,
            recovery_lock_path=None,
            recovery_lock_payload=None,
        )
        return completion, lock, lock_path, lock_payload

    raw, payload = _read_canonical_object(
        recovery_final,
        label="ADR-DC-094 final production activation recovery receipt",
    )
    recovery_lock_object, recovery_lock_payload = _read_canonical_object(
        recovery_lock,
        label="ADR-DC-094 production activation recovery lock",
    )
    try:
        receipt = recovery_boundary.PilotExactTaskProductionActivationRecoveryReceipt.from_mapping(
            raw
        )
    except Exception as exc:
        raise PilotExactTaskPostProductionActivationAttestationError(
            "ADR-DC-094 production activation recovery receipt is invalid"
        ) from exc
    recovery_lock_sha = hashlib.sha256(recovery_lock_payload).hexdigest()
    if (
        receipt.production_activation_recovery_ledger_root_path_sha256
        != recovery_ledger.root_sha256
        or receipt.production_activation_recovery_key_sha256 != candidate
        or receipt.production_activation_candidate_sha256 != candidate
        or receipt.production_activation_transaction_ledger_root_path_sha256
        != transaction_ledger.root_sha256
        or receipt.production_activation_transaction_lock_sha256 != lock_sha
        or receipt.production_activation_recovery_lock_sha256 != recovery_lock_sha
        or receipt.production_activation_transaction_config_sha256
        != transaction_config.sha256
        or receipt.production_activation_authorization_sha256
        != lock["production_activation_authorization_sha256"]
        or receipt.pre_activation_evidence_sha256
        != lock["pre_activation_evidence_sha256"]
        or receipt.environment_before_sha256 != lock["environment_before_sha256"]
        or receipt.output_dir_path_sha256 != lock["output_dir_path_sha256"]
        or receipt.merge_commit_sha != lock["merge_commit_sha"]
        or receipt.promotion_git_sha != lock["promotion_head_sha"]
        or receipt.recovery_state_class != "exact_activated"
        or receipt.production_activation_observed is not True
        or receipt.preflight_receipt_verified is not True
        or receipt.machine_production_receipt_verified is not True
        or receipt.required_switches_active is not True
        or receipt.environment_matches_pre_activation is not False
        or receipt.manual_intervention_required is not False
        or receipt.production_activation_authorized is not False
        or receipt.remote_write_authorized is not False
        or receipt.nonce_reusable is not False
        or set(recovery_lock_object)
        != {
            "schema",
            "ledger_scope",
            "ledger_root_path_sha256",
            "production_activation_recovery_key_sha256",
            "production_activation_transaction_lock_sha256",
            "recovery_observation_sha256",
            "recovery_state_class",
            "observed_at_utc",
        }
        or recovery_lock_object.get("schema") != recovery_boundary._RECOVERY_LOCK_SCHEMA
        or recovery_lock_object.get("ledger_scope")
        != recovery_boundary.PILOT_EXACT_TASK_PRODUCTION_ACTIVATION_RECOVERY_LEDGER_SCOPE
        or recovery_lock_object.get("ledger_root_path_sha256")
        != recovery_ledger.root_sha256
        or recovery_lock_object.get("production_activation_recovery_key_sha256")
        != candidate
        or recovery_lock_object.get("production_activation_transaction_lock_sha256")
        != lock_sha
        or recovery_lock_object.get("recovery_state_class") != "exact_activated"
    ):
        raise PilotExactTaskPostProductionActivationAttestationError(
            "ADR-DC-094 recovery is not exact durable activated completion"
        )
    if (
        receipt.production_preflight_observed_sha256 is None
        or receipt.machine_production_receipt_observed_sha256 is None
    ):
        raise PilotExactTaskPostProductionActivationAttestationError(
            "ADR-DC-094 exact activation lacks machine receipt identities"
        )
    completion = _CompletionEvidence(
        completion_source="recovery",
        source_receipt_sha256=receipt.sha256,
        transaction_lock_sha256=lock_sha,
        recovery_ledger_root_path_sha256=recovery_ledger.root_sha256,
        recovery_lock_sha256=recovery_lock_sha,
        production_activation_authorization_sha256=(
            receipt.production_activation_authorization_sha256
        ),
        production_activation_candidate_sha256=candidate,
        production_activation_transaction_config_sha256=transaction_config.sha256,
        pre_activation_evidence_sha256=receipt.pre_activation_evidence_sha256,
        environment_before_sha256=receipt.environment_before_sha256,
        environment_after_sha256=receipt.environment_observed_sha256,
        output_dir_path_sha256=receipt.output_dir_path_sha256,
        production_preflight_sha256=receipt.production_preflight_observed_sha256,
        machine_production_receipt_sha256=(
            receipt.machine_production_receipt_observed_sha256
        ),
        repository=receipt.repository,
        repository_id=receipt.repository_id,
        merge_commit_sha=receipt.merge_commit_sha,
        promotion_git_sha=receipt.promotion_git_sha,
        source_completed_at_utc=_utc_seconds(
            receipt.recovery_completed_at_utc,
            name="source_completed_at_utc",
        ),
        source_path=recovery_final,
        source_payload=payload,
        recovery_lock_path=recovery_lock,
        recovery_lock_payload=recovery_lock_payload,
    )
    return completion, lock, lock_path, lock_payload


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPostProductionActivationAttestationReceipt:
    production_activation_completion_source: str
    production_activation_source_receipt_sha256: str
    production_activation_transaction_ledger_root_path_sha256: str
    production_activation_transaction_lock_sha256: str
    production_activation_recovery_ledger_root_path_sha256: str | None
    production_activation_recovery_lock_sha256: str | None
    production_activation_authorization_sha256: str
    production_activation_candidate_sha256: str
    production_activation_transaction_config_sha256: str
    pre_activation_evidence_sha256: str
    environment_before_sha256: str
    environment_after_sha256: str
    output_dir_path_sha256: str
    output_state_sha256: str
    production_preflight_sha256: str
    machine_production_receipt_sha256: str
    repository: str
    repository_id: str
    merge_commit_sha: str
    promotion_git_sha: str
    source_completed_at_utc: str
    first_observed_at_utc: str
    second_observed_at_utc: str
    production_activation: bool = True
    production_activation_attested: bool = True
    durable_completion_verified: bool = True
    transaction_lock_authenticated: bool = True
    double_observation_matched: bool = True
    preflight_receipt_verified: bool = True
    machine_production_receipt_verified: bool = True
    required_switches_active: bool = True
    environment_matches_post_activation: bool = True
    manual_intervention_required: bool = False
    promotion_gate_execution_authorized: bool = False
    production_env_mutation_authorized: bool = False
    appliance_restart_authorized: bool = False
    production_receipt_write_authorized: bool = False
    production_activation_authorized: bool = False
    success_deployment_status_authorized: bool = False
    deployment_status_mutation_authorized: bool = False
    deployment_mutation_authorized: bool = False
    deploy_authorized: bool = False
    remote_write_authorized: bool = False
    release_authorized: bool = False
    tag_write_authorized: bool = False
    release_mutation_authorized: bool = False
    merge_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    product_pilot_started: bool = False
    nonce_reusable: bool = False
    attestation_scope: str = PILOT_EXACT_TASK_POST_PRODUCTION_ACTIVATION_ATTESTATION_SCOPE
    authority: str = PILOT_EXACT_TASK_POST_PRODUCTION_ACTIVATION_ATTESTATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_POST_PRODUCTION_ACTIVATION_ATTESTATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_POST_PRODUCTION_ACTIVATION_ATTESTATION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_POST_PRODUCTION_ACTIVATION_ATTESTATION_AUTHORITY
            or self.attestation_scope
            != PILOT_EXACT_TASK_POST_PRODUCTION_ACTIVATION_ATTESTATION_SCOPE
        ):
            raise PilotExactTaskPostProductionActivationAttestationError(
                "post-production attestation identity is unsupported"
            )
        if self.production_activation_completion_source not in {
            "transaction",
            "recovery",
        }:
            raise PilotExactTaskPostProductionActivationAttestationError(
                "post-production completion source is unsupported"
            )
        for name in (
            "production_activation_source_receipt_sha256",
            "production_activation_transaction_ledger_root_path_sha256",
            "production_activation_transaction_lock_sha256",
            "production_activation_authorization_sha256",
            "production_activation_candidate_sha256",
            "production_activation_transaction_config_sha256",
            "pre_activation_evidence_sha256",
            "environment_before_sha256",
            "environment_after_sha256",
            "output_dir_path_sha256",
            "output_state_sha256",
            "production_preflight_sha256",
            "machine_production_receipt_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in (
            "production_activation_recovery_ledger_root_path_sha256",
            "production_activation_recovery_lock_sha256",
        ):
            value = getattr(self, name)
            if value is not None:
                _hex64(value, name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        _hex40(self.promotion_git_sha, name="promotion_git_sha")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.environment_before_sha256 == self.environment_after_sha256
        ):
            raise PilotExactTaskPostProductionActivationAttestationError(
                "post-production attestation projection is invalid"
            )
        source_completed = _utc(
            self.source_completed_at_utc,
            name="source_completed_at_utc",
        )
        first = _utc(self.first_observed_at_utc, name="first_observed_at_utc")
        second = _utc(self.second_observed_at_utc, name="second_observed_at_utc")
        if first < source_completed or second < first:
            raise PilotExactTaskPostProductionActivationAttestationError(
                "post-production attestation timestamps are invalid"
            )
        if self.production_activation_completion_source == "transaction":
            if (
                self.production_activation_recovery_ledger_root_path_sha256 is not None
                or self.production_activation_recovery_lock_sha256 is not None
            ):
                raise PilotExactTaskPostProductionActivationAttestationError(
                    "normal completion carries recovery evidence"
                )
        elif (
            self.production_activation_recovery_ledger_root_path_sha256 is None
            or self.production_activation_recovery_lock_sha256 is None
        ):
            raise PilotExactTaskPostProductionActivationAttestationError(
                "recovered completion lacks recovery evidence"
            )
        required_true = (
            "production_activation",
            "production_activation_attested",
            "durable_completion_verified",
            "transaction_lock_authenticated",
            "double_observation_matched",
            "preflight_receipt_verified",
            "machine_production_receipt_verified",
            "required_switches_active",
            "environment_matches_post_activation",
        )
        forced_false = (
            "manual_intervention_required",
            "promotion_gate_execution_authorized",
            "production_env_mutation_authorized",
            "appliance_restart_authorized",
            "production_receipt_write_authorized",
            "production_activation_authorized",
            "success_deployment_status_authorized",
            "deployment_status_mutation_authorized",
            "deployment_mutation_authorized",
            "deploy_authorized",
            "remote_write_authorized",
            "release_authorized",
            "tag_write_authorized",
            "release_mutation_authorized",
            "merge_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "product_pilot_started",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPostProductionActivationAttestationError(
                "post-production attestation lacks exact activated-state proof"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPostProductionActivationAttestationError(
                "post-production attestation retains forbidden mutation authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def attestation_authenticated(self) -> bool:
        return _get_live_attestation_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskPostProductionActivationAttestationError(
                "post-production attestation fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: PilotExactTaskPostProductionActivationAttestationReceipt,
        *,
        source_path: Path,
        source_payload: bytes,
        transaction_lock_path: Path,
        transaction_lock_payload: bytes,
        recovery_lock_path: Path | None,
        recovery_lock_payload: bytes | None,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            source_path,
            source_payload,
            transaction_lock_path,
            transaction_lock_payload,
            recovery_lock_path,
            recovery_lock_payload,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        (
            pid,
            digest,
            receipt_ref,
            source_path,
            source_payload,
            transaction_lock_path,
            transaction_lock_payload,
            recovery_lock_path,
            recovery_lock_payload,
        ) = entry
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or receipt.sha256 != digest
        ):
            return None
        try:
            if (
                source_path.read_bytes() != source_payload
                or transaction_lock_path.read_bytes() != transaction_lock_payload
            ):
                return None
            if recovery_lock_path is not None:
                if (
                    recovery_lock_payload is None
                    or recovery_lock_path.read_bytes() != recovery_lock_payload
                ):
                    return None
        except OSError:
            return None
        return MappingProxyType(
            {
                "source_path": source_path,
                "transaction_lock_path": transaction_lock_path,
                "recovery_lock_path": recovery_lock_path,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_attestation_authenticated, _get_live_attestation_inputs = _live_registry()


def _attest_verified_pilot_exact_task_post_production_activation(
    *,
    production_activation_key_sha256: str,
    transaction_config: tx_boundary.PilotExactTaskProductionActivationTransactionConfig,
    transaction_ledger: tx_boundary._PilotExactTaskProductionActivationTransactionLedger,
    recovery_ledger: recovery_boundary._PilotExactTaskProductionActivationRecoveryLedger,
    now_provider: Callable[[], str],
) -> PilotExactTaskPostProductionActivationAttestationReceipt:
    if type(transaction_config) is not tx_boundary.PilotExactTaskProductionActivationTransactionConfig:
        raise PilotExactTaskPostProductionActivationAttestationError(
            "exact ADR-DC-093 transaction config is required"
        )
    completion, lock, lock_path, lock_payload = _load_completion(
        key=production_activation_key_sha256,
        transaction_config=transaction_config,
        transaction_ledger=transaction_ledger,
        recovery_ledger=recovery_ledger,
    )

    first_at = _utc_seconds(now_provider(), name="first_observed_at_utc")
    if _utc(first_at, name="first_observed_at_utc") < _utc(
        completion.source_completed_at_utc,
        name="source_completed_at_utc",
    ):
        raise PilotExactTaskPostProductionActivationAttestationError(
            "post-production observation predates durable completion"
        )
    first = recovery_boundary._observe_lock_only_state(
        lock=lock,
        transaction_config=transaction_config,
    )
    second_at = _utc_seconds(now_provider(), name="second_observed_at_utc")
    if _utc(second_at, name="second_observed_at_utc") < _utc(
        first_at, name="first_observed_at_utc"
    ):
        raise PilotExactTaskPostProductionActivationAttestationError(
            "post-production observation clock moved backwards"
        )
    second = recovery_boundary._observe_lock_only_state(
        lock=lock,
        transaction_config=transaction_config,
    )
    if first != second:
        raise PilotExactTaskPostProductionActivationAttestationError(
            "post-production activated state changed between observations"
        )
    if (
        first.recovery_state_class != "exact_activated"
        or first.production_activation_observed is not True
        or first.preflight_receipt_verified is not True
        or first.machine_production_receipt_verified is not True
        or first.required_switches_active is not True
        or first.environment_matches_pre_activation is not False
        or first.manual_intervention_required is not False
        or first.environment_observed_sha256 != completion.environment_after_sha256
        or first.production_preflight_observed_sha256
        != completion.production_preflight_sha256
        or first.machine_production_receipt_observed_sha256
        != completion.machine_production_receipt_sha256
    ):
        raise PilotExactTaskPostProductionActivationAttestationError(
            "current host does not prove the exact durable production activation"
        )
    if (
        completion.completion_source == "recovery"
        and first.output_state_sha256
        != recovery_boundary.PilotExactTaskProductionActivationRecoveryReceipt.from_mapping(
            json.loads(completion.source_payload.decode("utf-8"))
        ).output_state_sha256
    ):
        raise PilotExactTaskPostProductionActivationAttestationError(
            "recovered activated output state differs from durable recovery evidence"
        )

    receipt = PilotExactTaskPostProductionActivationAttestationReceipt(
        production_activation_completion_source=completion.completion_source,
        production_activation_source_receipt_sha256=completion.source_receipt_sha256,
        production_activation_transaction_ledger_root_path_sha256=(
            transaction_ledger.root_sha256
        ),
        production_activation_transaction_lock_sha256=completion.transaction_lock_sha256,
        production_activation_recovery_ledger_root_path_sha256=(
            completion.recovery_ledger_root_path_sha256
        ),
        production_activation_recovery_lock_sha256=completion.recovery_lock_sha256,
        production_activation_authorization_sha256=(
            completion.production_activation_authorization_sha256
        ),
        production_activation_candidate_sha256=(
            completion.production_activation_candidate_sha256
        ),
        production_activation_transaction_config_sha256=(
            completion.production_activation_transaction_config_sha256
        ),
        pre_activation_evidence_sha256=completion.pre_activation_evidence_sha256,
        environment_before_sha256=completion.environment_before_sha256,
        environment_after_sha256=completion.environment_after_sha256,
        output_dir_path_sha256=completion.output_dir_path_sha256,
        output_state_sha256=first.output_state_sha256,
        production_preflight_sha256=completion.production_preflight_sha256,
        machine_production_receipt_sha256=(
            completion.machine_production_receipt_sha256
        ),
        repository=completion.repository,
        repository_id=completion.repository_id,
        merge_commit_sha=completion.merge_commit_sha,
        promotion_git_sha=completion.promotion_git_sha,
        source_completed_at_utc=completion.source_completed_at_utc,
        first_observed_at_utc=first_at,
        second_observed_at_utc=second_at,
    )
    _mark_attestation_authenticated(
        receipt,
        source_path=completion.source_path,
        source_payload=completion.source_payload,
        transaction_lock_path=lock_path,
        transaction_lock_payload=lock_payload,
        recovery_lock_path=completion.recovery_lock_path,
        recovery_lock_payload=completion.recovery_lock_payload,
    )
    if receipt.attestation_authenticated is not True:
        raise PilotExactTaskPostProductionActivationAttestationError(
            "post-production attestation lost live durable provenance"
        )
    return receipt


def _canonical_runtime() -> tuple[
    tx_boundary.PilotExactTaskProductionActivationTransactionConfig,
    tx_boundary._PilotExactTaskProductionActivationTransactionLedger,
    recovery_boundary._PilotExactTaskProductionActivationRecoveryLedger,
]:
    try:
        _require_elevated_operator()
        if os.name != "nt":
            raise PilotExactTaskPostProductionActivationAttestationError(
                "post-production attestation must run on the physical Windows appliance"
            )
        config, _config_sha = tx_boundary._read_host_config(tx_boundary._WINDOWS_CONFIG)
        _require_host_controlled_ledger_root(tx_boundary._WINDOWS_LEDGER)
        _require_host_controlled_ledger_root(recovery_boundary._WINDOWS_LEDGER)
        return (
            config,
            tx_boundary._PilotExactTaskProductionActivationTransactionLedger(
                tx_boundary._WINDOWS_LEDGER
            ),
            recovery_boundary._PilotExactTaskProductionActivationRecoveryLedger(
                recovery_boundary._WINDOWS_LEDGER
            ),
        )
    except PilotExactTaskPostProductionActivationAttestationError:
        raise
    except (PhysicalHostStateError, ValueError, TypeError, OSError) as exc:
        raise PilotExactTaskPostProductionActivationAttestationError(
            "post-production attestation runtime is not host-admin controlled"
        ) from exc


def attest_pilot_exact_task_post_production_activation(
    production_activation_key_sha256: str,
) -> PilotExactTaskPostProductionActivationAttestationReceipt:
    """Attest one durable exact production activation without mutation."""
    config, transaction_ledger, recovery_ledger = _canonical_runtime()
    return _attest_verified_pilot_exact_task_post_production_activation(
        production_activation_key_sha256=production_activation_key_sha256,
        transaction_config=config,
        transaction_ledger=transaction_ledger,
        recovery_ledger=recovery_ledger,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []
