"""ADR-DC-102 replay-safe one-shot product-pilot start transaction.

Consumes exactly one live authenticated ADR-DC-097 product-pilot start
authorization into a separate host-admin-controlled create-once ledger.

A successful transaction may set product_pilot_started=true and issue the final
start receipt. It deliberately does not authorize or execute the selected task,
does not enable a feature flag, performs no subprocess or network I/O, and
grants no Git/GitHub/release/deploy/production mutation authority.

A crash after durable reservation but before receipt publication leaves the
lock in place and fails closed. Recovery is a separate later boundary.
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
from typing import Any, Callable, Mapping

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
    _require_host_controlled_ledger_root,
)
from ._improvement_pilot_start_consumption_impl import _path_sha256
from .durable_publication import DurablePublicationError, create_once_file
from . import improvement_pilot_exact_task_product_pilot_start_authorization as authorization_boundary

PILOT_EXACT_TASK_PRODUCT_PILOT_START_TRANSACTION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-start-transaction-receipt/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_START_TRANSACTION_AUTHORITY = (
    "host-consumed-one-dc-l16-exact-product-pilot-start-only"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_START_TRANSACTION_SCOPE = (
    "one-shot-product-pilot-session-start-receipt-only-v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_START_TRANSACTION_LEDGER_SCOPE = (
    "canonical-host-local-v1"
)

_MAX_FILE_BYTES = 1024 * 1024
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")

_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-product-pilot-start-transaction-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-product-pilot-start-transaction-ledger-v1"
)


class PilotExactTaskProductPilotStartTransactionError(ValueError):
    """Product-pilot start transaction is stale, replayed or over-authorizing."""


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
        raise PilotExactTaskProductPilotStartTransactionError(
            "product-pilot start transaction evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskProductPilotStartTransactionError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskProductPilotStartTransactionError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExactTaskProductPilotStartTransactionError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str):
        raise PilotExactTaskProductPilotStartTransactionError(f"{name} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PilotExactTaskProductPilotStartTransactionError(
            f"{name} is invalid"
        ) from exc
    if parsed.tzinfo is None or parsed.microsecond:
        raise PilotExactTaskProductPilotStartTransactionError(
            f"{name} must use whole timezone-aware seconds"
        )
    return parsed.astimezone(timezone.utc)


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _read_bound(path: Path) -> bytes | None:
    try:
        payload = path.read_bytes()
    except OSError:
        return None
    if not payload or len(payload) > _MAX_FILE_BYTES:
        return None
    return payload


def _require_live_authorization(value: Any):
    if (
        type(value)
        is not authorization_boundary.PilotExactTaskProductPilotStartAuthorizationReceipt
        or value.authorization_authenticated is not True
        or value.host_product_pilot_start_guard_committed is not True
        or value.product_pilot_start_readiness_authenticated is not True
        or value.product_pilot_start_intent_bound is not True
        or value.dual_external_ed25519_authorized is not True
        or value.product_pilot_start_authorized is not True
        or value.product_pilot_started is not False
        or value.remote_write_authorized is not False
        or value.production_activation_authorized is not False
        or value.nonce_reusable is not False
    ):
        raise PilotExactTaskProductPilotStartTransactionError(
            "fresh live inert ADR-DC-097 authorization receipt is required"
        )
    live = authorization_boundary._get_live_product_pilot_start_authorization_inputs(
        value
    )
    if live is None:
        raise PilotExactTaskProductPilotStartTransactionError(
            "ADR-DC-097 live authorization provenance is unavailable"
        )
    readiness = live.get("product_pilot_start_readiness")
    if (
        readiness is None
        or readiness.readiness_authenticated is not True
        or readiness.product_pilot_start_ready is not True
        or readiness.product_pilot_start_authorized is not False
        or readiness.product_pilot_started is not False
        or readiness.product_pilot_runtime_preflight_receipt_sha256 is None
        or readiness.product_pilot_task_registry_receipt_sha256 is None
    ):
        raise PilotExactTaskProductPilotStartTransactionError(
            "ADR-DC-097 no longer retains authenticated readiness-v2 provenance"
        )
    return value, readiness


def _transaction_key(
    authorization: authorization_boundary.PilotExactTaskProductPilotStartAuthorizationReceipt,
) -> str:
    payload = {
        "schema": "kaliv-rsi-dc-l16-exact-task-product-pilot-start-transaction-key/v1",
        "product_pilot_start_authorization_sha256": authorization.sha256,
        "product_pilot_start_intent_sha256": (
            authorization.product_pilot_start_intent_sha256
        ),
        "product_pilot_start_readiness_sha256": (
            authorization.product_pilot_start_readiness_sha256
        ),
        "repository": authorization.repository,
        "repository_id": authorization.repository_id,
        "merge_commit_sha": authorization.merge_commit_sha,
        "product_pilot_id": authorization.product_pilot_id,
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskProductPilotStartTransactionReceipt:
    transaction_ledger_root_path_sha256: str
    transaction_key_sha256: str
    product_pilot_start_authorization_sha256: str
    product_pilot_start_intent_sha256: str
    product_pilot_start_readiness_sha256: str
    product_pilot_start_requirements_sha256: str
    product_pilot_lineage_attestation_sha256: str
    product_pilot_task_registry_receipt_sha256: str
    product_pilot_runtime_preflight_receipt_sha256: str
    fresh_human_decision_proof_sha256: str
    host_development_task_registry_sha256: str
    development_task_sha256: str
    post_production_activation_attestation_sha256: str
    production_activation_candidate_sha256: str
    repository: str
    repository_id: str
    merge_commit_sha: str
    promotion_git_sha: str
    product_pilot_id: str
    operator_surface: str
    selected_pilot_task_id: str
    workspace_root_path_sha256: str
    feature_flag_name: str
    product_route: str
    fixed_command_id: str
    authorization_reserved_at_utc: str
    authorization_expires_at_utc: str
    start_reserved_at_utc: str
    started_at_utc: str
    host_start_transaction_guard_committed: bool = True
    product_pilot_start_authorization_authenticated: bool = True
    readiness_v2_authenticated: bool = True
    fresh_human_go_bound: bool = True
    task_registry_ready: bool = True
    runtime_preflight_satisfied: bool = True
    one_shot_start_consumed: bool = True
    start_receipt_issued: bool = True
    product_pilot_start_authorized: bool = True
    product_pilot_started: bool = True
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
    next_boundary_execution_authorization_required: bool = True
    transaction_scope: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_TRANSACTION_SCOPE
    ledger_scope: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_TRANSACTION_LEDGER_SCOPE
    authority: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_TRANSACTION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_TRANSACTION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCT_PILOT_START_TRANSACTION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PRODUCT_PILOT_START_TRANSACTION_AUTHORITY
            or self.transaction_scope
            != PILOT_EXACT_TASK_PRODUCT_PILOT_START_TRANSACTION_SCOPE
            or self.ledger_scope
            != PILOT_EXACT_TASK_PRODUCT_PILOT_START_TRANSACTION_LEDGER_SCOPE
        ):
            raise PilotExactTaskProductPilotStartTransactionError(
                "product-pilot start transaction identity is unsupported"
            )
        for name in (
            "transaction_ledger_root_path_sha256",
            "transaction_key_sha256",
            "product_pilot_start_authorization_sha256",
            "product_pilot_start_intent_sha256",
            "product_pilot_start_readiness_sha256",
            "product_pilot_start_requirements_sha256",
            "product_pilot_lineage_attestation_sha256",
            "product_pilot_task_registry_receipt_sha256",
            "product_pilot_runtime_preflight_receipt_sha256",
            "fresh_human_decision_proof_sha256",
            "host_development_task_registry_sha256",
            "development_task_sha256",
            "post_production_activation_attestation_sha256",
            "production_activation_candidate_sha256",
            "workspace_root_path_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        _hex40(self.promotion_git_sha, name="promotion_git_sha")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.product_pilot_id != authorization_boundary.PRODUCT_PILOT_ID
        ):
            raise PilotExactTaskProductPilotStartTransactionError(
                "product-pilot start transaction repository/pilot identity is invalid"
            )
        for name in (
            "operator_surface",
            "selected_pilot_task_id",
            "feature_flag_name",
            "fixed_command_id",
        ):
            _identifier(getattr(self, name), name=name)
        if (
            not isinstance(self.product_route, str)
            or not self.product_route.startswith("/")
            or "\x00" in self.product_route
            or len(self.product_route.encode("utf-8")) > 512
        ):
            raise PilotExactTaskProductPilotStartTransactionError(
                "product route is invalid"
            )
        auth_reserved = _utc(
            self.authorization_reserved_at_utc,
            name="authorization_reserved_at_utc",
        )
        auth_expires = _utc(
            self.authorization_expires_at_utc,
            name="authorization_expires_at_utc",
        )
        start_reserved = _utc(
            self.start_reserved_at_utc,
            name="start_reserved_at_utc",
        )
        started = _utc(self.started_at_utc, name="started_at_utc")
        if not auth_reserved <= start_reserved <= started < auth_expires:
            raise PilotExactTaskProductPilotStartTransactionError(
                "product-pilot start transaction timing is invalid"
            )

        required_true = (
            "host_start_transaction_guard_committed",
            "product_pilot_start_authorization_authenticated",
            "readiness_v2_authenticated",
            "fresh_human_go_bound",
            "task_registry_ready",
            "runtime_preflight_satisfied",
            "one_shot_start_consumed",
            "start_receipt_issued",
            "product_pilot_start_authorized",
            "product_pilot_started",
            "next_boundary_execution_authorization_required",
        )
        forced_false = (
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
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskProductPilotStartTransactionError(
                "product-pilot start transaction lacks mandatory evidence"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskProductPilotStartTransactionError(
                "product-pilot start transaction grants forbidden execution/mutation authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def transaction_authenticated(self) -> bool:
        return _get_live_start_transaction_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductPilotStartTransactionError(
                "product-pilot start transaction receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskProductPilotStartTransactionLedger:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root_sha256 = _path_sha256(self.root)

    def _paths(self, key: str) -> tuple[Path, Path]:
        _hex64(key, name="transaction_key_sha256")
        return self.root / f"{key}.json", self.root / f"{key}.lock.json"

    def acquire(
        self,
        *,
        authorization: authorization_boundary.PilotExactTaskProductPilotStartAuthorizationReceipt,
        readiness: Any,
        key: str,
    ) -> bytes:
        final, lock = self._paths(key)
        if final.exists() or final.is_symlink() or lock.exists() or lock.is_symlink():
            raise PilotExactTaskProductPilotStartTransactionError(
                "product-pilot start authorization was already consumed or needs recovery"
            )
        lock_payload = _canonical(
            {
                "schema": "kaliv-rsi-dc-l16-exact-task-product-pilot-start-transaction-lock/v1",
                "ledger_scope": PILOT_EXACT_TASK_PRODUCT_PILOT_START_TRANSACTION_LEDGER_SCOPE,
                "ledger_root_path_sha256": self.root_sha256,
                "transaction_key_sha256": key,
                "product_pilot_start_authorization_sha256": authorization.sha256,
                "product_pilot_start_intent_sha256": (
                    authorization.product_pilot_start_intent_sha256
                ),
                "product_pilot_start_readiness_sha256": readiness.sha256,
                "product_pilot_runtime_preflight_receipt_sha256": (
                    readiness.product_pilot_runtime_preflight_receipt_sha256
                ),
                "repository": authorization.repository,
                "repository_id": authorization.repository_id,
                "merge_commit_sha": authorization.merge_commit_sha,
                "product_pilot_id": authorization.product_pilot_id,
            }
        ).encode("utf-8")
        try:
            create_once_file(lock, lock_payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskProductPilotStartTransactionError(
                "product-pilot start could not be durably reserved"
            ) from exc
        return lock_payload

    def commit(
        self,
        *,
        receipt: PilotExactTaskProductPilotStartTransactionReceipt,
        lock_payload: bytes,
        authorization: authorization_boundary.PilotExactTaskProductPilotStartAuthorizationReceipt,
    ) -> PilotExactTaskProductPilotStartTransactionReceipt:
        final, lock = self._paths(receipt.transaction_key_sha256)
        if final.exists() or final.is_symlink() or _read_bound(lock) != lock_payload:
            raise PilotExactTaskProductPilotStartTransactionError(
                "durable product-pilot start reservation changed"
            )
        payload = receipt.canonical_json().encode("utf-8")
        try:
            create_once_file(final, payload)
        except (FileExistsError, DurablePublicationError) as exc:
            raise PilotExactTaskProductPilotStartTransactionError(
                "product-pilot start receipt could not be durably published"
            ) from exc
        parsed = PilotExactTaskProductPilotStartTransactionReceipt.from_mapping(
            json.loads(payload.decode("utf-8"))
        )
        _mark_start_transaction_authenticated(
            parsed,
            authorization=authorization,
            final_path=final,
            final_payload=payload,
            lock_path=lock,
            lock_payload=lock_payload,
        )
        if parsed.transaction_authenticated is not True:
            raise PilotExactTaskProductPilotStartTransactionError(
                "product-pilot start receipt lost live provenance"
            )
        return parsed


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: PilotExactTaskProductPilotStartTransactionReceipt,
        *,
        authorization: authorization_boundary.PilotExactTaskProductPilotStartAuthorizationReceipt,
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
            weakref.ref(authorization),
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
            authorization_ref,
            final_path,
            final_payload,
            lock_path,
            lock_payload,
        ) = entry
        authorization = authorization_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or receipt.sha256 != digest
            or authorization is None
            or authorization.authorization_authenticated is not True
            or authorization.sha256 != receipt.product_pilot_start_authorization_sha256
            or _read_bound(final_path) != final_payload
            or _read_bound(lock_path) != lock_payload
        ):
            return None
        return {"product_pilot_start_authorization": authorization}

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_start_transaction_authenticated,
    _get_live_start_transaction_inputs,
) = _live_registry()


def _execute_verified_pilot_exact_task_product_pilot_start(
    *,
    authorization_receipt: authorization_boundary.PilotExactTaskProductPilotStartAuthorizationReceipt,
    ledger: _PilotExactTaskProductPilotStartTransactionLedger,
    now_provider: Callable[[], str],
) -> PilotExactTaskProductPilotStartTransactionReceipt:
    authorization, readiness = _require_live_authorization(authorization_receipt)
    reserved_at = _now = now_provider()
    reserved = _utc(reserved_at, name="start_reserved_at_utc")
    expires = _utc(authorization.expires_at_utc, name="authorization_expires_at_utc")
    auth_reserved = _utc(
        authorization.reserved_at_utc,
        name="authorization_reserved_at_utc",
    )
    if not auth_reserved <= reserved < expires:
        raise PilotExactTaskProductPilotStartTransactionError(
            "ADR-DC-097 authorization is not valid at start reservation"
        )

    key = _transaction_key(authorization)
    lock_payload = ledger.acquire(
        authorization=authorization,
        readiness=readiness,
        key=key,
    )

    authorization_again, readiness_again = _require_live_authorization(authorization)
    if authorization_again is not authorization or readiness_again is not readiness:
        raise PilotExactTaskProductPilotStartTransactionError(
            "product-pilot start authority changed after durable reservation"
        )
    started_at = now_provider()
    started = _utc(started_at, name="started_at_utc")
    if not reserved <= started < expires:
        raise PilotExactTaskProductPilotStartTransactionError(
            "ADR-DC-097 authorization expired after durable start reservation"
        )

    receipt = PilotExactTaskProductPilotStartTransactionReceipt(
        transaction_ledger_root_path_sha256=ledger.root_sha256,
        transaction_key_sha256=key,
        product_pilot_start_authorization_sha256=authorization.sha256,
        product_pilot_start_intent_sha256=(
            authorization.product_pilot_start_intent_sha256
        ),
        product_pilot_start_readiness_sha256=readiness.sha256,
        product_pilot_start_requirements_sha256=(
            readiness.product_pilot_start_requirements_sha256
        ),
        product_pilot_lineage_attestation_sha256=(
            readiness.product_pilot_lineage_attestation_sha256
        ),
        product_pilot_task_registry_receipt_sha256=(
            readiness.product_pilot_task_registry_receipt_sha256
        ),
        product_pilot_runtime_preflight_receipt_sha256=(
            readiness.product_pilot_runtime_preflight_receipt_sha256
        ),
        fresh_human_decision_proof_sha256=(
            readiness.fresh_human_decision_proof_sha256
        ),
        host_development_task_registry_sha256=(
            readiness.host_development_task_registry_sha256
        ),
        development_task_sha256=readiness.development_task_sha256,
        post_production_activation_attestation_sha256=(
            readiness.post_production_activation_attestation_sha256
        ),
        production_activation_candidate_sha256=(
            readiness.production_activation_candidate_sha256
        ),
        repository=authorization.repository,
        repository_id=authorization.repository_id,
        merge_commit_sha=authorization.merge_commit_sha,
        promotion_git_sha=authorization.promotion_git_sha,
        product_pilot_id=authorization.product_pilot_id,
        operator_surface=readiness.operator_surface,
        selected_pilot_task_id=readiness.selected_pilot_task_id,
        workspace_root_path_sha256=readiness.workspace_root_path_sha256,
        feature_flag_name=readiness.feature_flag_name,
        product_route=readiness.product_route,
        fixed_command_id=readiness.fixed_command_id,
        authorization_reserved_at_utc=authorization.reserved_at_utc,
        authorization_expires_at_utc=authorization.expires_at_utc,
        start_reserved_at_utc=reserved_at,
        started_at_utc=started_at,
    )
    return ledger.commit(
        receipt=receipt,
        lock_payload=lock_payload,
        authorization=authorization,
    )


def _canonical_ledger() -> _PilotExactTaskProductPilotStartTransactionLedger:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            root = _POSIX_LEDGER
        elif os.name == "nt":
            root = _WINDOWS_LEDGER
        else:
            raise PilotExactTaskProductPilotStartTransactionError(
                "product-pilot start transaction platform is unsupported"
            )
        _require_host_controlled_ledger_root(root)
        return _PilotExactTaskProductPilotStartTransactionLedger(root)
    except PilotExactTaskProductPilotStartTransactionError:
        raise
    except (PhysicalHostStateError, OSError, ValueError, TypeError) as exc:
        raise PilotExactTaskProductPilotStartTransactionError(
            "product-pilot start transaction ledger is not host-admin controlled"
        ) from exc


def execute_pilot_exact_task_product_pilot_start(
    authorization_receipt: authorization_boundary.PilotExactTaskProductPilotStartAuthorizationReceipt,
) -> PilotExactTaskProductPilotStartTransactionReceipt:
    """Consume one ADR-DC-097 authorization and issue one inert start receipt."""
    return _execute_verified_pilot_exact_task_product_pilot_start(
        authorization_receipt=authorization_receipt,
        ledger=_canonical_ledger(),
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []
