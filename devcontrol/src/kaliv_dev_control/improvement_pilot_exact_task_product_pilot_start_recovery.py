"""ADR-DC-103 write-free recovery for ADR-DC-102 product-pilot start state.

Recovery never retries or completes a start transaction. It reads the canonical
host-controlled ADR-DC-097 authorization ledger and ADR-DC-102 transaction
ledger, double-observes them around a separate create-once recovery lock, and
classifies exactly one transaction key as:

* completed_verified: the exact canonical ADR-DC-102 final receipt exists; or
* reserved_not_started: the exact ADR-DC-102 lock exists but no final receipt.

ADR-DC-102 performs no product/task side effect before final receipt publication,
so lock-only state is conservatively not-started and requires a new authority
path rather than replay. No transaction file is altered or backfilled.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
    _require_host_controlled_ledger_root,
)
from ._improvement_pilot_start_consumption_impl import _path_sha256
from .durable_publication import DurablePublicationError, create_once_file
from . import improvement_pilot_exact_task_product_pilot_start_authorization as auth_boundary
from . import improvement_pilot_exact_task_product_pilot_start_transaction as tx_boundary

PILOT_EXACT_TASK_PRODUCT_PILOT_START_RECOVERY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-start-recovery-receipt/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_START_RECOVERY_AUTHORITY = (
    "host-classified-dc-l16-product-pilot-start-recovery-only"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_START_RECOVERY_SCOPE = (
    "write-free-product-pilot-start-ledger-recovery-classification-v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_START_RECOVERY_LEDGER_SCOPE = "canonical-host-local-v1"

_TRANSACTION_LOCK_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-start-transaction-lock/v1"
)
_AUTHORIZATION_LOCK_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-start-authorization-lock/v1"
)
_MAX_BYTES = 1024 * 1024
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")

_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-product-pilot-start-recovery-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-product-pilot-start-recovery-ledger-v1"
)

_TRANSACTION_LOCK_FIELDS = frozenset(
    {
        "schema",
        "ledger_scope",
        "ledger_root_path_sha256",
        "transaction_key_sha256",
        "product_pilot_start_authorization_sha256",
        "product_pilot_start_intent_sha256",
        "product_pilot_start_readiness_sha256",
        "product_pilot_runtime_preflight_receipt_sha256",
        "repository",
        "repository_id",
        "merge_commit_sha",
        "product_pilot_id",
    }
)


class PilotExactTaskProductPilotStartRecoveryError(ValueError):
    """Durable product-pilot start state is unavailable or inconsistent."""


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
        raise PilotExactTaskProductPilotStartRecoveryError(
            "product-pilot start recovery evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskProductPilotStartRecoveryError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskProductPilotStartRecoveryError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str):
        raise PilotExactTaskProductPilotStartRecoveryError(f"{name} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PilotExactTaskProductPilotStartRecoveryError(f"{name} is invalid") from exc
    if parsed.tzinfo is None or parsed.microsecond:
        raise PilotExactTaskProductPilotStartRecoveryError(
            f"{name} must use whole timezone-aware seconds"
        )
    return parsed.astimezone(timezone.utc)


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _read_regular(path: Path, *, name: str) -> bytes:
    try:
        info = path.lstat()
    except OSError as exc:
        raise PilotExactTaskProductPilotStartRecoveryError(
            f"{name} is unavailable"
        ) from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise PilotExactTaskProductPilotStartRecoveryError(
            f"{name} must be a non-symlink regular file"
        )
    if info.st_size <= 0 or info.st_size > _MAX_BYTES:
        raise PilotExactTaskProductPilotStartRecoveryError(
            f"{name} size is invalid"
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise PilotExactTaskProductPilotStartRecoveryError(
            f"{name} is unreadable"
        ) from exc


def _canonical_object(path: Path, *, name: str) -> tuple[dict[str, Any], bytes]:
    raw = _read_regular(path, name=name)
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskProductPilotStartRecoveryError(
            f"{name} is invalid JSON"
        ) from exc
    if (
        not isinstance(value, dict)
        or _canonical(value).encode("utf-8") != raw
    ):
        raise PilotExactTaskProductPilotStartRecoveryError(
            f"{name} is not exact canonical JSON"
        )
    return value, raw


@dataclass(frozen=True, slots=True)
class _StartRecoveryObservation:
    transaction_key_sha256: str
    transaction_lock_sha256: str
    product_pilot_start_authorization_sha256: str
    product_pilot_start_intent_sha256: str
    product_pilot_start_readiness_sha256: str
    authorization_ledger_root_path_sha256: str
    transaction_ledger_root_path_sha256: str
    repository: str
    repository_id: str
    merge_commit_sha: str
    product_pilot_id: str
    recovery_state_class: str
    recovered_start_transaction_receipt_sha256: str | None
    transaction_lock_verified: bool = True
    durable_start_authorization_verified: bool = True
    start_receipt_verified: bool = False

    def __post_init__(self) -> None:
        for name in (
            "transaction_key_sha256",
            "transaction_lock_sha256",
            "product_pilot_start_authorization_sha256",
            "product_pilot_start_intent_sha256",
            "product_pilot_start_readiness_sha256",
            "authorization_ledger_root_path_sha256",
            "transaction_ledger_root_path_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.product_pilot_id != auth_boundary.PRODUCT_PILOT_ID
        ):
            raise PilotExactTaskProductPilotStartRecoveryError(
                "recovery observation identity is invalid"
            )
        if self.recovery_state_class == "completed_verified":
            if (
                self.recovered_start_transaction_receipt_sha256 is None
                or self.start_receipt_verified is not True
            ):
                raise PilotExactTaskProductPilotStartRecoveryError(
                    "completed recovery observation lacks final receipt"
                )
            _hex64(
                self.recovered_start_transaction_receipt_sha256,
                name="recovered_start_transaction_receipt_sha256",
            )
        elif self.recovery_state_class == "reserved_not_started":
            if (
                self.recovered_start_transaction_receipt_sha256 is not None
                or self.start_receipt_verified is not False
            ):
                raise PilotExactTaskProductPilotStartRecoveryError(
                    "lock-only recovery observation claims a final receipt"
                )
        else:
            raise PilotExactTaskProductPilotStartRecoveryError(
                "recovery state class is unsupported"
            )
        if (
            self.transaction_lock_verified is not True
            or self.durable_start_authorization_verified is not True
        ):
            raise PilotExactTaskProductPilotStartRecoveryError(
                "recovery observation lacks durable authority evidence"
            )

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict()).encode("utf-8")).hexdigest()


def _observe(
    *,
    transaction_key_sha256: str,
    transaction_ledger: tx_boundary._PilotExactTaskProductPilotStartTransactionLedger,
    authorization_ledger: auth_boundary._PilotExactTaskProductPilotStartAuthorizationLedger,
) -> tuple[
    _StartRecoveryObservation,
    auth_boundary.PilotExactTaskProductPilotStartAuthorizationReceipt,
    tx_boundary.PilotExactTaskProductPilotStartTransactionReceipt | None,
]:
    key = _hex64(transaction_key_sha256, name="transaction_key_sha256")
    final_path, lock_path = transaction_ledger._paths(key)
    lock, lock_raw = _canonical_object(lock_path, name="ADR-DC-102 transaction lock")
    if (
        set(lock) != _TRANSACTION_LOCK_FIELDS
        or lock.get("schema") != _TRANSACTION_LOCK_SCHEMA
        or lock.get("ledger_scope")
        != tx_boundary.PILOT_EXACT_TASK_PRODUCT_PILOT_START_TRANSACTION_LEDGER_SCOPE
        or lock.get("ledger_root_path_sha256") != transaction_ledger.root_sha256
        or lock.get("transaction_key_sha256") != key
    ):
        raise PilotExactTaskProductPilotStartRecoveryError(
            "ADR-DC-102 transaction lock is not exact"
        )
    for name in (
        "ledger_root_path_sha256",
        "transaction_key_sha256",
        "product_pilot_start_authorization_sha256",
        "product_pilot_start_intent_sha256",
        "product_pilot_start_readiness_sha256",
        "product_pilot_runtime_preflight_receipt_sha256",
    ):
        _hex64(lock.get(name), name=name)
    _hex40(lock.get("merge_commit_sha"), name="merge_commit_sha")

    auth_key = lock["product_pilot_start_intent_sha256"]
    auth_final_path, auth_lock_path = authorization_ledger._paths(auth_key)
    auth_raw = _read_regular(auth_final_path, name="ADR-DC-097 authorization receipt")
    auth_lock, auth_lock_raw = _canonical_object(
        auth_lock_path, name="ADR-DC-097 authorization lock"
    )
    try:
        authorization = (
            auth_boundary.PilotExactTaskProductPilotStartAuthorizationReceipt.from_mapping(
                json.loads(auth_raw.decode("utf-8", errors="strict"))
            )
        )
    except (UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise PilotExactTaskProductPilotStartRecoveryError(
            "durable ADR-DC-097 authorization receipt is invalid"
        ) from exc
    if (
        authorization.canonical_json().encode("utf-8") != auth_raw
        or authorization.sha256 != lock["product_pilot_start_authorization_sha256"]
        or authorization.product_pilot_start_intent_sha256 != auth_key
        or authorization.product_pilot_start_readiness_sha256
        != lock["product_pilot_start_readiness_sha256"]
        or authorization.repository != lock["repository"]
        or authorization.repository_id != lock["repository_id"]
        or authorization.merge_commit_sha != lock["merge_commit_sha"]
        or authorization.product_pilot_id != lock["product_pilot_id"]
        or not isinstance(auth_lock, dict)
        or auth_lock.get("schema") != _AUTHORIZATION_LOCK_SCHEMA
        or auth_lock.get("ledger_scope")
        != auth_boundary.PILOT_EXACT_TASK_PRODUCT_PILOT_START_AUTHORIZATION_LEDGER_SCOPE
        or auth_lock.get("ledger_root_path_sha256") != authorization_ledger.root_sha256
        or auth_lock.get("product_pilot_start_key_sha256") != auth_key
        or auth_lock.get("product_pilot_start_readiness_sha256")
        != authorization.product_pilot_start_readiness_sha256
        or not auth_lock_raw
    ):
        raise PilotExactTaskProductPilotStartRecoveryError(
            "durable ADR-DC-097 evidence does not match ADR-DC-102 lock"
        )

    recovered = None
    recovered_sha = None
    start_verified = False
    state_class = "reserved_not_started"
    if final_path.exists() or final_path.is_symlink():
        raw = _read_regular(final_path, name="ADR-DC-102 start receipt")
        try:
            recovered = tx_boundary.PilotExactTaskProductPilotStartTransactionReceipt.from_mapping(
                json.loads(raw.decode("utf-8", errors="strict"))
            )
        except (UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
            raise PilotExactTaskProductPilotStartRecoveryError(
                "durable ADR-DC-102 start receipt is invalid"
            ) from exc
        if (
            recovered.canonical_json().encode("utf-8") != raw
            or recovered.transaction_key_sha256 != key
            or recovered.transaction_ledger_root_path_sha256
            != transaction_ledger.root_sha256
            or recovered.product_pilot_start_authorization_sha256
            != authorization.sha256
            or recovered.product_pilot_start_intent_sha256 != auth_key
            or recovered.product_pilot_start_readiness_sha256
            != authorization.product_pilot_start_readiness_sha256
            or recovered.repository != authorization.repository
            or recovered.repository_id != authorization.repository_id
            or recovered.merge_commit_sha != authorization.merge_commit_sha
            or recovered.product_pilot_id != authorization.product_pilot_id
            or recovered.product_pilot_started is not True
            or recovered.task_execution_authorized is not False
        ):
            raise PilotExactTaskProductPilotStartRecoveryError(
                "durable ADR-DC-102 final receipt does not match transaction lock"
            )
        recovered_sha = recovered.sha256
        start_verified = True
        state_class = "completed_verified"

    observation = _StartRecoveryObservation(
        transaction_key_sha256=key,
        transaction_lock_sha256=hashlib.sha256(lock_raw).hexdigest(),
        product_pilot_start_authorization_sha256=authorization.sha256,
        product_pilot_start_intent_sha256=authorization.product_pilot_start_intent_sha256,
        product_pilot_start_readiness_sha256=authorization.product_pilot_start_readiness_sha256,
        authorization_ledger_root_path_sha256=authorization_ledger.root_sha256,
        transaction_ledger_root_path_sha256=transaction_ledger.root_sha256,
        repository=authorization.repository,
        repository_id=authorization.repository_id,
        merge_commit_sha=authorization.merge_commit_sha,
        product_pilot_id=authorization.product_pilot_id,
        recovery_state_class=state_class,
        recovered_start_transaction_receipt_sha256=recovered_sha,
        start_receipt_verified=start_verified,
    )
    return observation, authorization, recovered


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskProductPilotStartRecoveryReceipt:
    recovery_ledger_root_path_sha256: str
    recovery_key_sha256: str
    recovery_observation_sha256: str
    transaction_key_sha256: str
    transaction_lock_sha256: str
    transaction_ledger_root_path_sha256: str
    product_pilot_start_authorization_sha256: str
    authorization_ledger_root_path_sha256: str
    product_pilot_start_intent_sha256: str
    product_pilot_start_readiness_sha256: str
    repository: str
    repository_id: str
    merge_commit_sha: str
    product_pilot_id: str
    recovery_state_class: str
    recovered_start_transaction_receipt_sha256: str | None
    first_observed_at_utc: str
    second_observed_at_utc: str
    recovered_at_utc: str
    transaction_lock_verified: bool = True
    durable_start_authorization_verified: bool = True
    double_observation_matched: bool = True
    recovery_classification_verified: bool = True
    start_receipt_verified: bool = False
    product_pilot_start_authorized: bool = False
    product_pilot_started: bool = False
    reserved_start_not_started: bool = False
    manual_intervention_required: bool = False
    task_execution_authorized: bool = False
    local_commit_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    nonce_reusable: bool = False
    next_boundary_execution_authorization_required: bool = False
    recovery_scope: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_RECOVERY_SCOPE
    ledger_scope: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_RECOVERY_LEDGER_SCOPE
    authority: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_RECOVERY_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_RECOVERY_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCT_PILOT_START_RECOVERY_SCHEMA
            or self.authority != PILOT_EXACT_TASK_PRODUCT_PILOT_START_RECOVERY_AUTHORITY
            or self.recovery_scope != PILOT_EXACT_TASK_PRODUCT_PILOT_START_RECOVERY_SCOPE
            or self.ledger_scope != PILOT_EXACT_TASK_PRODUCT_PILOT_START_RECOVERY_LEDGER_SCOPE
        ):
            raise PilotExactTaskProductPilotStartRecoveryError(
                "product-pilot start recovery identity is unsupported"
            )
        for name in (
            "recovery_ledger_root_path_sha256",
            "recovery_key_sha256",
            "recovery_observation_sha256",
            "transaction_key_sha256",
            "transaction_lock_sha256",
            "transaction_ledger_root_path_sha256",
            "product_pilot_start_authorization_sha256",
            "authorization_ledger_root_path_sha256",
            "product_pilot_start_intent_sha256",
            "product_pilot_start_readiness_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.product_pilot_id != auth_boundary.PRODUCT_PILOT_ID
        ):
            raise PilotExactTaskProductPilotStartRecoveryError(
                "recovery receipt repository/pilot identity is invalid"
            )
        first = _utc(self.first_observed_at_utc, name="first_observed_at_utc")
        second = _utc(self.second_observed_at_utc, name="second_observed_at_utc")
        recovered = _utc(self.recovered_at_utc, name="recovered_at_utc")
        if not first <= second <= recovered:
            raise PilotExactTaskProductPilotStartRecoveryError(
                "recovery receipt timing is invalid"
            )
        required_true = (
            "transaction_lock_verified",
            "durable_start_authorization_verified",
            "double_observation_matched",
            "recovery_classification_verified",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskProductPilotStartRecoveryError(
                "recovery receipt lacks durable evidence"
            )

        if self.recovery_state_class == "completed_verified":
            if (
                self.recovered_start_transaction_receipt_sha256 is None
                or self.start_receipt_verified is not True
                or self.product_pilot_started is not True
                or self.reserved_start_not_started is not False
                or self.manual_intervention_required is not False
                or self.next_boundary_execution_authorization_required is not True
            ):
                raise PilotExactTaskProductPilotStartRecoveryError(
                    "completed start recovery projection is inconsistent"
                )
            _hex64(
                self.recovered_start_transaction_receipt_sha256,
                name="recovered_start_transaction_receipt_sha256",
            )
        elif self.recovery_state_class == "reserved_not_started":
            if (
                self.recovered_start_transaction_receipt_sha256 is not None
                or self.start_receipt_verified is not False
                or self.product_pilot_started is not False
                or self.reserved_start_not_started is not True
                or self.manual_intervention_required is not True
                or self.next_boundary_execution_authorization_required is not False
            ):
                raise PilotExactTaskProductPilotStartRecoveryError(
                    "lock-only start recovery projection is inconsistent"
                )
        else:
            raise PilotExactTaskProductPilotStartRecoveryError(
                "recovery state class is unsupported"
            )

        forced_false = (
            "product_pilot_start_authorized",
            "task_execution_authorized",
            "local_commit_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskProductPilotStartRecoveryError(
                "recovery receipt grants forbidden reusable authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def recovery_authenticated(self) -> bool:
        return _get_live_recovery_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductPilotStartRecoveryError(
                "product-pilot start recovery receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskProductPilotStartRecoveryLedger:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path]:
        _hex64(key, name="recovery_key_sha256")
        return self.root / f"{key}.json", self.root / f"{key}.lock.json"

    def acquire(self, observation: _StartRecoveryObservation) -> bytes:
        key = observation.transaction_key_sha256
        final, lock = self._paths(key)
        if final.exists() or final.is_symlink() or lock.exists() or lock.is_symlink():
            raise PilotExactTaskProductPilotStartRecoveryError(
                "product-pilot start recovery was already consumed"
            )
        payload = _canonical(
            {
                "schema": "kaliv-rsi-dc-l16-exact-task-product-pilot-start-recovery-lock/v1",
                "ledger_scope": PILOT_EXACT_TASK_PRODUCT_PILOT_START_RECOVERY_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "recovery_key_sha256": key,
                "recovery_observation_sha256": observation.sha256,
                "transaction_lock_sha256": observation.transaction_lock_sha256,
                "product_pilot_start_authorization_sha256": (
                    observation.product_pilot_start_authorization_sha256
                ),
                "recovery_state_class": observation.recovery_state_class,
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskProductPilotStartRecoveryError(
                "product-pilot start recovery could not be durably reserved"
            ) from exc
        return payload

    def commit(
        self,
        *,
        receipt: PilotExactTaskProductPilotStartRecoveryReceipt,
        lock_payload: bytes,
        recovered_transaction: (
            tx_boundary.PilotExactTaskProductPilotStartTransactionReceipt | None
        ),
    ) -> PilotExactTaskProductPilotStartRecoveryReceipt:
        final, lock = self._paths(receipt.recovery_key_sha256)
        if final.exists() or final.is_symlink() or _read_regular(
            lock, name="start recovery lock"
        ) != lock_payload:
            raise PilotExactTaskProductPilotStartRecoveryError(
                "durable product-pilot start recovery reservation changed"
            )
        payload = receipt.canonical_json().encode("utf-8")
        try:
            create_once_file(final, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskProductPilotStartRecoveryError(
                "product-pilot start recovery receipt could not be published"
            ) from exc
        parsed = PilotExactTaskProductPilotStartRecoveryReceipt.from_mapping(
            json.loads(payload.decode("utf-8"))
        )
        _mark_recovery_authenticated(
            parsed,
            final_path=final,
            final_payload=payload,
            lock_path=lock,
            lock_payload=lock_payload,
            recovered_transaction=recovered_transaction,
        )
        if parsed.recovery_authenticated is not True:
            raise PilotExactTaskProductPilotStartRecoveryError(
                "product-pilot start recovery lost live provenance"
            )
        return parsed


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: PilotExactTaskProductPilotStartRecoveryReceipt,
        *,
        final_path: Path,
        final_payload: bytes,
        lock_path: Path,
        lock_payload: bytes,
        recovered_transaction: (
            tx_boundary.PilotExactTaskProductPilotStartTransactionReceipt | None
        ),
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            final_path,
            final_payload,
            lock_path,
            lock_payload,
            recovered_transaction,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        (
            pid,
            digest,
            receipt_ref,
            final_path,
            final_payload,
            lock_path,
            lock_payload,
            recovered_transaction,
        ) = entry
        try:
            current_final = _read_regular(final_path, name="recovery receipt")
            current_lock = _read_regular(lock_path, name="recovery lock")
        except PilotExactTaskProductPilotStartRecoveryError:
            return None
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or receipt.sha256 != digest
            or current_final != final_payload
            or current_lock != lock_payload
        ):
            return None
        return {"recovered_start_transaction": recovered_transaction}

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_recovery_authenticated, _get_live_recovery_inputs = _live_registry()


def _recover_verified_pilot_exact_task_product_pilot_start(
    *,
    transaction_key_sha256: str,
    transaction_ledger: tx_boundary._PilotExactTaskProductPilotStartTransactionLedger,
    authorization_ledger: auth_boundary._PilotExactTaskProductPilotStartAuthorizationLedger,
    recovery_ledger: _PilotExactTaskProductPilotStartRecoveryLedger,
    now_provider: Callable[[], str],
) -> PilotExactTaskProductPilotStartRecoveryReceipt:
    first, _authorization, recovered_first = _observe(
        transaction_key_sha256=transaction_key_sha256,
        transaction_ledger=transaction_ledger,
        authorization_ledger=authorization_ledger,
    )
    first_at = now_provider()
    _utc(first_at, name="first_observed_at_utc")
    lock_payload = recovery_ledger.acquire(first)

    second, _authorization_again, recovered_second = _observe(
        transaction_key_sha256=transaction_key_sha256,
        transaction_ledger=transaction_ledger,
        authorization_ledger=authorization_ledger,
    )
    second_at = now_provider()
    if _utc(second_at, name="second_observed_at_utc") < _utc(
        first_at, name="first_observed_at_utc"
    ):
        raise PilotExactTaskProductPilotStartRecoveryError(
            "recovery observation clock moved backwards"
        )
    if second != first or second.sha256 != first.sha256:
        raise PilotExactTaskProductPilotStartRecoveryError(
            "product-pilot start durable state changed during recovery"
        )
    if (
        (recovered_first is None) != (recovered_second is None)
        or (
            recovered_first is not None
            and recovered_second is not None
            and recovered_first.sha256 != recovered_second.sha256
        )
    ):
        raise PilotExactTaskProductPilotStartRecoveryError(
            "recovered start receipt changed during recovery"
        )

    recovered_at = now_provider()
    if _utc(recovered_at, name="recovered_at_utc") < _utc(
        second_at, name="second_observed_at_utc"
    ):
        raise PilotExactTaskProductPilotStartRecoveryError(
            "recovery completion clock moved backwards"
        )
    completed = first.recovery_state_class == "completed_verified"
    receipt = PilotExactTaskProductPilotStartRecoveryReceipt(
        recovery_ledger_root_path_sha256=recovery_ledger.root_sha256,
        recovery_key_sha256=first.transaction_key_sha256,
        recovery_observation_sha256=first.sha256,
        transaction_key_sha256=first.transaction_key_sha256,
        transaction_lock_sha256=first.transaction_lock_sha256,
        transaction_ledger_root_path_sha256=first.transaction_ledger_root_path_sha256,
        product_pilot_start_authorization_sha256=(
            first.product_pilot_start_authorization_sha256
        ),
        authorization_ledger_root_path_sha256=(
            first.authorization_ledger_root_path_sha256
        ),
        product_pilot_start_intent_sha256=first.product_pilot_start_intent_sha256,
        product_pilot_start_readiness_sha256=first.product_pilot_start_readiness_sha256,
        repository=first.repository,
        repository_id=first.repository_id,
        merge_commit_sha=first.merge_commit_sha,
        product_pilot_id=first.product_pilot_id,
        recovery_state_class=first.recovery_state_class,
        recovered_start_transaction_receipt_sha256=(
            first.recovered_start_transaction_receipt_sha256
        ),
        first_observed_at_utc=first_at,
        second_observed_at_utc=second_at,
        recovered_at_utc=recovered_at,
        start_receipt_verified=completed,
        product_pilot_started=completed,
        reserved_start_not_started=not completed,
        manual_intervention_required=not completed,
        next_boundary_execution_authorization_required=completed,
    )
    return recovery_ledger.commit(
        receipt=receipt,
        lock_payload=lock_payload,
        recovered_transaction=recovered_second,
    )


def _canonical_ledgers() -> tuple[
    tx_boundary._PilotExactTaskProductPilotStartTransactionLedger,
    auth_boundary._PilotExactTaskProductPilotStartAuthorizationLedger,
    _PilotExactTaskProductPilotStartRecoveryLedger,
]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            tx_root = tx_boundary._POSIX_LEDGER
            auth_root = auth_boundary._POSIX_LEDGER
            recovery_root = _POSIX_LEDGER
        elif os.name == "nt":
            tx_root = tx_boundary._WINDOWS_LEDGER
            auth_root = auth_boundary._WINDOWS_LEDGER
            recovery_root = _WINDOWS_LEDGER
        else:
            raise PilotExactTaskProductPilotStartRecoveryError(
                "product-pilot start recovery platform is unsupported"
            )
        for root in (tx_root, auth_root, recovery_root):
            _require_host_controlled_ledger_root(root)
        return (
            tx_boundary._PilotExactTaskProductPilotStartTransactionLedger(tx_root),
            auth_boundary._PilotExactTaskProductPilotStartAuthorizationLedger(auth_root),
            _PilotExactTaskProductPilotStartRecoveryLedger(recovery_root),
        )
    except PilotExactTaskProductPilotStartRecoveryError:
        raise
    except (PhysicalHostStateError, OSError, ValueError, TypeError) as exc:
        raise PilotExactTaskProductPilotStartRecoveryError(
            "product-pilot start recovery ledgers are not host-admin controlled"
        ) from exc


def recover_pilot_exact_task_product_pilot_start(
    transaction_key_sha256: str,
) -> PilotExactTaskProductPilotStartRecoveryReceipt:
    """Classify durable ADR-DC-102 state without retrying or backfilling start."""
    transaction_ledger, authorization_ledger, recovery_ledger = _canonical_ledgers()
    return _recover_verified_pilot_exact_task_product_pilot_start(
        transaction_key_sha256=transaction_key_sha256,
        transaction_ledger=transaction_ledger,
        authorization_ledger=authorization_ledger,
        recovery_ledger=recovery_ledger,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []
