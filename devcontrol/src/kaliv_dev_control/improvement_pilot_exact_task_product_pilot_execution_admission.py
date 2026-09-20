"""ADR-DC-104 product-pilot post-start execution admission.

This boundary does not execute a task. It accepts only one authenticated
completed product-pilot start state:

* a live ADR-DC-102 start transaction receipt; or
* a live ADR-DC-103 recovery receipt classified completed_verified.

It then re-reads the canonical host-admin-controlled ADR-DC-035 DevelopmentTask
registry and requires the exact same registry identity, selected task,
DevelopmentTask digest and single fixed command recorded by the completed start.

A positive receipt authorizes only the next executor-capability bridge. It does
not authorize execution-plan materialization, task execution, local commits,
remote writes or any GitHub/release/deploy/production mutation.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from . import improvement_pilot_exact_task_development_task_binding as task_binding_boundary
from . import _improvement_pilot_exact_task_development_task_binding_production_boundary as task_registry_host_boundary
from . import improvement_pilot_exact_task_product_pilot_start_authorization as start_authorization_boundary
from . import improvement_pilot_exact_task_product_pilot_start_transaction as start_transaction_boundary
from . import improvement_pilot_exact_task_product_pilot_start_recovery as start_recovery_boundary

PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_ADMISSION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-execution-admission-receipt/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_ADMISSION_AUTHORITY = (
    "host-revalidated-product-pilot-executor-bridge-admission-only"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_ADMISSION_SCOPE = (
    "completed-start-to-existing-tier-a-executor-bridge-only-v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_ADMISSION_MAX_SOURCE_AGE_SECONDS = 60

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")


class PilotExactTaskProductPilotExecutionAdmissionError(ValueError):
    """Completed start state cannot safely admit executor-capability materialization."""


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
        raise PilotExactTaskProductPilotExecutionAdmissionError(
            "product-pilot execution admission is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskProductPilotExecutionAdmissionError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskProductPilotExecutionAdmissionError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExactTaskProductPilotExecutionAdmissionError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str):
        raise PilotExactTaskProductPilotExecutionAdmissionError(f"{name} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PilotExactTaskProductPilotExecutionAdmissionError(
            f"{name} is invalid"
        ) from exc
    if parsed.tzinfo is None or parsed.microsecond:
        raise PilotExactTaskProductPilotExecutionAdmissionError(
            f"{name} must use whole timezone-aware seconds"
        )
    return parsed.astimezone(timezone.utc)


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _require_completed_start_source(value: Any):
    if type(value) is start_transaction_boundary.PilotExactTaskProductPilotStartTransactionReceipt:
        if (
            value.transaction_authenticated is not True
            or value.product_pilot_start_authorized is not True
            or value.product_pilot_started is not True
            or value.start_receipt_issued is not True
            or value.task_execution_authorized is not False
            or value.local_commit_authorized is not False
            or value.remote_write_authorized is not False
            or value.production_activation_authorized is not False
            or value.next_boundary_execution_authorization_required is not True
            or value.nonce_reusable is not False
        ):
            raise PilotExactTaskProductPilotExecutionAdmissionError(
                "live completed ADR-DC-102 start receipt is required"
            )
        live = start_transaction_boundary._get_live_start_transaction_inputs(value)
        if live is None:
            raise PilotExactTaskProductPilotExecutionAdmissionError(
                "ADR-DC-102 live start provenance is unavailable"
            )
        authorization = live.get("product_pilot_start_authorization")
        auth_live = (
            start_authorization_boundary._get_live_product_pilot_start_authorization_inputs(
                authorization
            )
            if authorization is not None
            else None
        )
        readiness = auth_live.get("product_pilot_start_readiness") if auth_live else None
        if (
            readiness is None
            or readiness.readiness_authenticated is not True
            or readiness.sha256 != value.product_pilot_start_readiness_sha256
        ):
            raise PilotExactTaskProductPilotExecutionAdmissionError(
                "ADR-DC-102 no longer retains live readiness-v2 provenance"
            )
        return "start_transaction", value, value, value.started_at_utc

    if type(value) is start_recovery_boundary.PilotExactTaskProductPilotStartRecoveryReceipt:
        if (
            value.recovery_authenticated is not True
            or value.recovery_state_class != "completed_verified"
            or value.start_receipt_verified is not True
            or value.product_pilot_started is not True
            or value.manual_intervention_required is not False
            or value.task_execution_authorized is not False
            or value.local_commit_authorized is not False
            or value.remote_write_authorized is not False
            or value.production_activation_authorized is not False
            or value.next_boundary_execution_authorization_required is not True
            or value.nonce_reusable is not False
        ):
            raise PilotExactTaskProductPilotExecutionAdmissionError(
                "live completed ADR-DC-103 recovery receipt is required"
            )
        live = start_recovery_boundary._get_live_recovery_inputs(value)
        start_receipt = live.get("recovered_start_transaction") if live else None
        if (
            type(start_receipt)
            is not start_transaction_boundary.PilotExactTaskProductPilotStartTransactionReceipt
            or start_receipt.sha256 != value.recovered_start_transaction_receipt_sha256
            or start_receipt.product_pilot_started is not True
            or start_receipt.task_execution_authorized is not False
            or start_receipt.remote_write_authorized is not False
        ):
            raise PilotExactTaskProductPilotExecutionAdmissionError(
                "ADR-DC-103 recovered start receipt is unavailable or inconsistent"
            )
        return "completed_recovery", value, start_receipt, value.recovered_at_utc

    raise PilotExactTaskProductPilotExecutionAdmissionError(
        "exact live ADR-DC-102 start or completed ADR-DC-103 recovery is required"
    )


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskProductPilotExecutionAdmissionReceipt:
    start_state_source_type: str
    start_state_source_sha256: str
    start_transaction_receipt_sha256: str
    product_pilot_start_authorization_sha256: str
    product_pilot_start_readiness_sha256: str
    product_pilot_start_requirements_sha256: str
    product_pilot_lineage_attestation_sha256: str
    product_pilot_task_registry_receipt_sha256: str
    product_pilot_runtime_preflight_receipt_sha256: str
    fresh_human_decision_proof_sha256: str
    host_development_task_registry_sha256: str
    development_task_id: str
    development_task_sha256: str
    development_task_base_sha: str
    fixed_command_id: str
    repository: str
    repository_id: str
    merge_commit_sha: str
    product_pilot_id: str
    operator_surface: str
    selected_pilot_task_id: str
    workspace_root_path_sha256: str
    feature_flag_name: str
    product_route: str
    source_completed_at_utc: str
    admitted_at_utc: str
    source_age_seconds: int
    start_state_authenticated: bool = True
    host_development_task_registry_reverified: bool = True
    exact_development_task_reverified: bool = True
    single_fixed_command_reverified: bool = True
    exact_workspace_scope_bound: bool = True
    fresh_runtime_revalidation_required: bool = True
    fresh_workspace_snapshot_required: bool = True
    executor_capability_materialization_authorized: bool = True
    execution_plan_materialization_authorized: bool = False
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
    next_boundary_executor_capability_required: bool = True
    admission_scope: str = PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_ADMISSION_SCOPE
    authority: str = PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_ADMISSION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_ADMISSION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_ADMISSION_SCHEMA
            or self.authority != PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_ADMISSION_AUTHORITY
            or self.admission_scope != PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_ADMISSION_SCOPE
        ):
            raise PilotExactTaskProductPilotExecutionAdmissionError(
                "product-pilot execution admission identity is unsupported"
            )
        if self.start_state_source_type not in {"start_transaction", "completed_recovery"}:
            raise PilotExactTaskProductPilotExecutionAdmissionError(
                "execution admission start-state source type is unsupported"
            )
        for name in (
            "start_state_source_sha256",
            "start_transaction_receipt_sha256",
            "product_pilot_start_authorization_sha256",
            "product_pilot_start_readiness_sha256",
            "product_pilot_start_requirements_sha256",
            "product_pilot_lineage_attestation_sha256",
            "product_pilot_task_registry_receipt_sha256",
            "product_pilot_runtime_preflight_receipt_sha256",
            "fresh_human_decision_proof_sha256",
            "host_development_task_registry_sha256",
            "development_task_sha256",
            "workspace_root_path_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.development_task_base_sha, name="development_task_base_sha")
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.product_pilot_id
            != start_authorization_boundary.PRODUCT_PILOT_ID
        ):
            raise PilotExactTaskProductPilotExecutionAdmissionError(
                "product-pilot execution admission repository/pilot identity is invalid"
            )
        for name in (
            "development_task_id",
            "fixed_command_id",
            "operator_surface",
            "selected_pilot_task_id",
            "feature_flag_name",
        ):
            _identifier(getattr(self, name), name=name)
        if (
            not isinstance(self.product_route, str)
            or not self.product_route.startswith("/")
            or "\x00" in self.product_route
        ):
            raise PilotExactTaskProductPilotExecutionAdmissionError(
                "execution admission product route is invalid"
            )
        source_time = _utc(self.source_completed_at_utc, name="source_completed_at_utc")
        admitted = _utc(self.admitted_at_utc, name="admitted_at_utc")
        age = int((admitted - source_time).total_seconds())
        if (
            admitted < source_time
            or type(self.source_age_seconds) is not int
            or self.source_age_seconds != age
            or not 0 <= age
            <= PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_ADMISSION_MAX_SOURCE_AGE_SECONDS
        ):
            raise PilotExactTaskProductPilotExecutionAdmissionError(
                "completed product-pilot start state is stale for execution admission"
            )
        required_true = (
            "start_state_authenticated",
            "host_development_task_registry_reverified",
            "exact_development_task_reverified",
            "single_fixed_command_reverified",
            "exact_workspace_scope_bound",
            "fresh_runtime_revalidation_required",
            "fresh_workspace_snapshot_required",
            "executor_capability_materialization_authorized",
            "next_boundary_executor_capability_required",
        )
        forced_false = (
            "execution_plan_materialization_authorized",
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
            raise PilotExactTaskProductPilotExecutionAdmissionError(
                "execution admission lacks mandatory evidence"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskProductPilotExecutionAdmissionError(
                "execution admission grants premature execution/mutation authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def admission_authenticated(self) -> bool:
        return _get_live_execution_admission_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductPilotExecutionAdmissionError(
                "product-pilot execution admission fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: PilotExactTaskProductPilotExecutionAdmissionReceipt,
        *,
        start_state: Any,
        start_transaction: start_transaction_boundary.PilotExactTaskProductPilotStartTransactionReceipt,
        development_task: Any,
        registry_payload_sha256: str,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            start_state,
            start_transaction,
            development_task,
            registry_payload_sha256,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        (
            pid,
            digest,
            receipt_ref,
            start_state,
            start_transaction,
            development_task,
            registry_payload_sha256,
        ) = entry
        if pid != os.getpid() or receipt_ref() is not receipt or receipt.sha256 != digest:
            return None
        try:
            source_type, source_again, tx_again, _source_time = _require_completed_start_source(
                start_state
            )
            if (
                source_again is not start_state
                or tx_again.sha256 != start_transaction.sha256
                or source_type != receipt.start_state_source_type
                or registry_payload_sha256 != receipt.host_development_task_registry_sha256
                or task_binding_boundary._task_sha256(development_task)
                != receipt.development_task_sha256
                or development_task.task_id != receipt.development_task_id
                or development_task.base_sha != receipt.development_task_base_sha
                or development_task.allowed_command_ids != (receipt.fixed_command_id,)
            ):
                return None
        except Exception:
            return None
        return {
            "start_state": start_state,
            "start_transaction": start_transaction,
            "development_task": development_task,
            "host_development_task_registry_sha256": registry_payload_sha256,
        }

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_execution_admission_authenticated, _get_live_execution_admission_inputs = _live_registry()


def _build_verified_product_pilot_execution_admission(
    *,
    start_state: Any,
    registry_payload: bytes,
    now_provider: Callable[[], str],
) -> PilotExactTaskProductPilotExecutionAdmissionReceipt:
    source_type, source, start_transaction, source_completed_at = (
        _require_completed_start_source(start_state)
    )
    try:
        registry_sha256, entries = task_binding_boundary._parse_registry_payload(
            registry_payload
        )
    except Exception as exc:
        raise PilotExactTaskProductPilotExecutionAdmissionError(
            "canonical ADR-DC-035 DevelopmentTask registry is invalid"
        ) from exc
    if registry_sha256 != start_transaction.host_development_task_registry_sha256:
        raise PilotExactTaskProductPilotExecutionAdmissionError(
            "host DevelopmentTask registry changed since product-pilot start"
        )
    try:
        development_task = entries[start_transaction.selected_pilot_task_id]
    except KeyError as exc:
        raise PilotExactTaskProductPilotExecutionAdmissionError(
            "started product-pilot task is absent from the host DevelopmentTask registry"
        ) from exc
    development_task_sha256 = task_binding_boundary._task_sha256(development_task)
    if (
        development_task_sha256 != start_transaction.development_task_sha256
        or development_task.repository != start_transaction.repository
        or development_task.allowed_command_ids != (start_transaction.fixed_command_id,)
        or development_task.required_tests != development_task.allowed_command_ids
    ):
        raise PilotExactTaskProductPilotExecutionAdmissionError(
            "host DevelopmentTask no longer matches the completed product-pilot start"
        )

    admitted_at = now_provider()
    source_time = _utc(source_completed_at, name="source_completed_at_utc")
    admitted = _utc(admitted_at, name="admitted_at_utc")
    age = int((admitted - source_time).total_seconds())
    if (
        admitted < source_time
        or age < 0
        or age
        > PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_ADMISSION_MAX_SOURCE_AGE_SECONDS
    ):
        raise PilotExactTaskProductPilotExecutionAdmissionError(
            "completed product-pilot start state is stale for execution admission"
        )

    receipt = PilotExactTaskProductPilotExecutionAdmissionReceipt(
        start_state_source_type=source_type,
        start_state_source_sha256=source.sha256,
        start_transaction_receipt_sha256=start_transaction.sha256,
        product_pilot_start_authorization_sha256=(
            start_transaction.product_pilot_start_authorization_sha256
        ),
        product_pilot_start_readiness_sha256=(
            start_transaction.product_pilot_start_readiness_sha256
        ),
        product_pilot_start_requirements_sha256=(
            start_transaction.product_pilot_start_requirements_sha256
        ),
        product_pilot_lineage_attestation_sha256=(
            start_transaction.product_pilot_lineage_attestation_sha256
        ),
        product_pilot_task_registry_receipt_sha256=(
            start_transaction.product_pilot_task_registry_receipt_sha256
        ),
        product_pilot_runtime_preflight_receipt_sha256=(
            start_transaction.product_pilot_runtime_preflight_receipt_sha256
        ),
        fresh_human_decision_proof_sha256=(
            start_transaction.fresh_human_decision_proof_sha256
        ),
        host_development_task_registry_sha256=registry_sha256,
        development_task_id=development_task.task_id,
        development_task_sha256=development_task_sha256,
        development_task_base_sha=development_task.base_sha,
        fixed_command_id=start_transaction.fixed_command_id,
        repository=start_transaction.repository,
        repository_id=start_transaction.repository_id,
        merge_commit_sha=start_transaction.merge_commit_sha,
        product_pilot_id=start_transaction.product_pilot_id,
        operator_surface=start_transaction.operator_surface,
        selected_pilot_task_id=start_transaction.selected_pilot_task_id,
        workspace_root_path_sha256=start_transaction.workspace_root_path_sha256,
        feature_flag_name=start_transaction.feature_flag_name,
        product_route=start_transaction.product_route,
        source_completed_at_utc=source_completed_at,
        admitted_at_utc=admitted_at,
        source_age_seconds=age,
    )
    _mark_execution_admission_authenticated(
        receipt,
        start_state=source,
        start_transaction=start_transaction,
        development_task=development_task,
        registry_payload_sha256=registry_sha256,
    )
    if receipt.admission_authenticated is not True:
        raise PilotExactTaskProductPilotExecutionAdmissionError(
            "product-pilot execution admission lost live provenance"
        )
    return receipt


def admit_pilot_exact_task_product_pilot_execution(
    start_state: Any,
) -> PilotExactTaskProductPilotExecutionAdmissionReceipt:
    """Admit one completed product-pilot start to the executor-capability bridge."""
    try:
        registry_payload = task_registry_host_boundary._read_host_controlled_registry()
    except Exception as exc:
        raise PilotExactTaskProductPilotExecutionAdmissionError(
            "canonical host DevelopmentTask registry is unavailable"
        ) from exc
    return _build_verified_product_pilot_execution_admission(
        start_state=start_state,
        registry_payload=registry_payload,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_ADMISSION_SCHEMA",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_ADMISSION_AUTHORITY",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_ADMISSION_SCOPE",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_EXECUTION_ADMISSION_MAX_SOURCE_AGE_SECONDS",
    "PilotExactTaskProductPilotExecutionAdmissionError",
    "PilotExactTaskProductPilotExecutionAdmissionReceipt",
    "admit_pilot_exact_task_product_pilot_execution",
]
