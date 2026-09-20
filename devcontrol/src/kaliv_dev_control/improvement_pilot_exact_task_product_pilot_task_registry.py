"""ADR-DC-099 inert exact-scope product-pilot task registry.

Consumes one live authenticated ADR-DC-098 lineage attestation and one freshly
host-verified human GO. It narrows the human allowlist to the single task already
bound into the exact DC-L16 lineage.

This boundary registers no executable command and invokes no task. The public
production entrypoint reads the already-existing host-admin-controlled ADR-DC-035
DevelopmentTask registry, but performs no network I/O, subprocess execution,
durable write, pilot start, Git/GitHub mutation, deployment or production action.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import weakref
from typing import Any, Callable, Mapping

from . import improvement_human_pilot_decision as human_boundary
from . import improvement_pilot_exact_task_development_task_binding as task_binding_boundary
from . import _improvement_pilot_exact_task_development_task_binding_production_boundary as task_registry_host_boundary
from . import improvement_pilot_exact_task_product_pilot_lineage_attestation as lineage_boundary

PILOT_EXACT_TASK_PRODUCT_PILOT_TASK_REGISTRY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-task-registry-receipt/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_TASK_REGISTRY_AUTHORITY = (
    "host-verified-one-dc-l16-product-pilot-task-registry-only"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_TASK_REGISTRY_SCOPE = (
    "single-human-allowlisted-local-task-registry-only-v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_TASK_REGISTRY_MAX_GO_AGE_SECONDS = 60

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class PilotExactTaskProductPilotTaskRegistryError(ValueError):
    """Product-pilot task-registry evidence is stale, rebound or over-authorizing."""


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
        raise PilotExactTaskProductPilotTaskRegistryError(
            "product-pilot task-registry evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskProductPilotTaskRegistryError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskProductPilotTaskRegistryError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExactTaskProductPilotTaskRegistryError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str):
        raise PilotExactTaskProductPilotTaskRegistryError(f"{name} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PilotExactTaskProductPilotTaskRegistryError(f"{name} is invalid") from exc
    if parsed.tzinfo is None or parsed.microsecond:
        raise PilotExactTaskProductPilotTaskRegistryError(
            f"{name} must use whole timezone-aware seconds"
        )
    return parsed.astimezone(timezone.utc)


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_live_lineage(value: Any):
    if (
        type(value) is not lineage_boundary.PilotExactTaskProductPilotLineageAttestationReceipt
        or value.attestation_authenticated is not True
    ):
        raise PilotExactTaskProductPilotTaskRegistryError(
            "fresh live ADR-DC-098 lineage attestation is required"
        )
    inputs = lineage_boundary._get_live_product_pilot_lineage_inputs(value)
    if inputs is None:
        raise PilotExactTaskProductPilotTaskRegistryError(
            "ADR-DC-098 live lineage provenance is unavailable"
        )
    return value, inputs


def _require_verified_human_go(value: Any) -> human_boundary.HumanPilotDecisionProof:
    if type(value) is not human_boundary.HumanPilotDecisionProof:
        raise PilotExactTaskProductPilotTaskRegistryError(
            "exact freshly verified human pilot decision proof is required"
        )
    replayed = human_boundary.HumanPilotDecisionProof.from_mapping(value.to_dict())
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskProductPilotTaskRegistryError(
            "human pilot decision proof replay identity mismatch"
        )
    if (
        value.human_pilot_decision_recorded is not True
        or value.pilot_go_authorized is not True
        or value.decision not in {"go", "go_with_conditions"}
        or value.feature_flag_default_off is not True
        or value.product_pilot_started is not False
        or value.remote_write_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskProductPilotTaskRegistryError(
            "fresh human decision is not a positive inert product-pilot GO"
        )
    return value


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskProductPilotTaskRegistryReceipt:
    lineage_attestation_sha256: str
    fresh_human_decision_proof_sha256: str
    human_selection_proof_sha256: str
    preflight_proof_sha256: str
    repository: str
    merge_commit_sha: str
    operator_surface: str
    selected_pilot_task_id: str
    registered_task_ids: tuple[str, ...]
    host_development_task_registry_sha256: str
    development_task_id: str
    development_task_sha256: str
    fixed_command_id: str
    workspace_root_path_sha256: str
    feature_flag_name: str
    product_route: str
    task_registry_id: str
    decision_id: str
    decision_maker_actor_id: str
    decided_at_utc: str
    verified_at_utc: str
    evaluated_at_utc: str
    human_go_age_seconds: int
    lineage_authenticated: bool = True
    fresh_human_go_verified: bool = True
    exact_scope_binding_verified: bool = True
    historical_preflight_satisfied: bool = True
    host_development_task_registry_verified: bool = True
    task_registry_ready: bool = True
    executor_wired: bool = False
    runtime_preflight_satisfied: bool = False
    product_pilot_start_ready: bool = False
    product_pilot_start_authorized: bool = False
    product_pilot_started: bool = False
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
    next_boundary_authorization_required: bool = True
    registry_scope: str = PILOT_EXACT_TASK_PRODUCT_PILOT_TASK_REGISTRY_SCOPE
    authority: str = PILOT_EXACT_TASK_PRODUCT_PILOT_TASK_REGISTRY_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCT_PILOT_TASK_REGISTRY_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCT_PILOT_TASK_REGISTRY_SCHEMA
            or self.authority != PILOT_EXACT_TASK_PRODUCT_PILOT_TASK_REGISTRY_AUTHORITY
            or self.registry_scope != PILOT_EXACT_TASK_PRODUCT_PILOT_TASK_REGISTRY_SCOPE
        ):
            raise PilotExactTaskProductPilotTaskRegistryError(
                "product-pilot task-registry identity is unsupported"
            )
        for name in (
            "lineage_attestation_sha256",
            "fresh_human_decision_proof_sha256",
            "human_selection_proof_sha256",
            "preflight_proof_sha256",
            "host_development_task_registry_sha256",
            "development_task_sha256",
            "workspace_root_path_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        if self.repository != "Ternedal/ModelRig":
            raise PilotExactTaskProductPilotTaskRegistryError("repository is unsupported")
        for name in (
            "operator_surface",
            "selected_pilot_task_id",
            "feature_flag_name",
            "task_registry_id",
            "development_task_id",
            "fixed_command_id",
            "decision_id",
            "decision_maker_actor_id",
        ):
            _identifier(getattr(self, name), name=name)
        if (
            not isinstance(self.product_route, str)
            or not self.product_route.startswith("/")
            or "\x00" in self.product_route
            or len(self.product_route.encode("utf-8")) > 512
        ):
            raise PilotExactTaskProductPilotTaskRegistryError("product_route is invalid")
        if self.registered_task_ids != (self.selected_pilot_task_id,):
            raise PilotExactTaskProductPilotTaskRegistryError(
                "task registry must contain exactly the selected human-allowlisted task"
            )
        decided = _utc(self.decided_at_utc, name="decided_at_utc")
        verified = _utc(self.verified_at_utc, name="verified_at_utc")
        evaluated = _utc(self.evaluated_at_utc, name="evaluated_at_utc")
        age = int((evaluated - verified).total_seconds())
        if (
            verified < decided
            or evaluated < verified
            or type(self.human_go_age_seconds) is not int
            or self.human_go_age_seconds != age
            or not 0 <= age <= PILOT_EXACT_TASK_PRODUCT_PILOT_TASK_REGISTRY_MAX_GO_AGE_SECONDS
        ):
            raise PilotExactTaskProductPilotTaskRegistryError(
                "fresh human GO is outside the task-registry freshness window"
            )
        required_true = (
            "lineage_authenticated",
            "fresh_human_go_verified",
            "exact_scope_binding_verified",
            "historical_preflight_satisfied",
            "host_development_task_registry_verified",
            "task_registry_ready",
            "next_boundary_authorization_required",
        )
        forced_false = (
            "executor_wired",
            "runtime_preflight_satisfied",
            "product_pilot_start_ready",
            "product_pilot_start_authorized",
            "product_pilot_started",
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
            raise PilotExactTaskProductPilotTaskRegistryError(
                "product-pilot task-registry lacks required evidence"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskProductPilotTaskRegistryError(
                "product-pilot task-registry grants forbidden authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def registry_authenticated(self) -> bool:
        return _get_live_product_pilot_task_registry_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        result = {name: getattr(self, name) for name in self.__dataclass_fields__}
        result["registered_task_ids"] = list(self.registered_task_ids)
        return result

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductPilotTaskRegistryError(
                "product-pilot task-registry fields mismatch"
            )
        data = dict(value)
        tasks = data.get("registered_task_ids")
        if not isinstance(tasks, list):
            raise PilotExactTaskProductPilotTaskRegistryError(
                "registered_task_ids must be an array"
            )
        data["registered_task_ids"] = tuple(tasks)
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: PilotExactTaskProductPilotTaskRegistryReceipt,
        *,
        lineage: lineage_boundary.PilotExactTaskProductPilotLineageAttestationReceipt,
        human_go: human_boundary.HumanPilotDecisionProof,
        development_task: Any,
        host_registry_sha256: str,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            lineage,
            human_go,
            development_task,
            host_registry_sha256,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, lineage, human_go, development_task, host_registry_sha256 = entry
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or receipt.sha256 != digest
            or lineage.attestation_authenticated is not True
            or lineage.sha256 != receipt.lineage_attestation_sha256
            or human_go.sha256 != receipt.fresh_human_decision_proof_sha256
            or host_registry_sha256 != receipt.host_development_task_registry_sha256
            or task_binding_boundary._task_sha256(development_task)
            != receipt.development_task_sha256
            or development_task.task_id != receipt.development_task_id
            or development_task.allowed_command_ids != (receipt.fixed_command_id,)
        ):
            return None
        return {
            "lineage_attestation": lineage,
            "fresh_human_go": human_go,
            "development_task": development_task,
            "host_development_task_registry_sha256": host_registry_sha256,
        }

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_product_pilot_task_registry_authenticated,
    _get_live_product_pilot_task_registry_inputs,
) = _live_registry()


def _build_verified_product_pilot_task_registry(
    *,
    lineage_attestation: lineage_boundary.PilotExactTaskProductPilotLineageAttestationReceipt,
    fresh_human_decision_proof: human_boundary.HumanPilotDecisionProof,
    registry_payload: bytes,
    now_provider: Callable[[], str],
) -> PilotExactTaskProductPilotTaskRegistryReceipt:
    lineage, live = _require_live_lineage(lineage_attestation)
    human_go = _require_verified_human_go(fresh_human_decision_proof)
    try:
        host_registry_sha256, host_registry_entries = (
            task_binding_boundary._parse_registry_payload(registry_payload)
        )
    except Exception as exc:
        raise PilotExactTaskProductPilotTaskRegistryError(
            "existing ADR-DC-035 host DevelopmentTask registry is invalid"
        ) from exc

    preflight = live["preflight"]
    candidate = live["candidate"]
    requirements = preflight.attestation.packet.preflight_requirements
    if (
        preflight.preflight_satisfied is not True
        or preflight.attestation.all_checks_satisfied is not True
    ):
        raise PilotExactTaskProductPilotTaskRegistryError(
            "historical ADR-DC-023 preflight is not fully satisfied"
        )

    checks = (
        ("repository", human_go.repository, lineage.repository),
        ("repository/preflight", human_go.repository, requirements.repository),
        ("operator_surface", human_go.operator_surface, lineage.operator_surface),
        ("operator_surface/preflight", human_go.operator_surface, requirements.operator_surface),
        ("workspace", human_go.workspace_root_path_sha256, lineage.workspace_root_path_sha256),
        ("workspace/preflight", human_go.workspace_root_path_sha256, requirements.workspace_root_path_sha256),
        ("campaign_id", human_go.campaign_id, requirements.campaign_id),
        ("task_id", human_go.task_id, requirements.source_task_id),
        ("task_sha256", human_go.task_sha256, requirements.source_task_sha256),
        ("base_sha", human_go.base_sha, requirements.base_sha),
        ("requested_main_sha", human_go.requested_main_sha, requirements.requested_main_sha),
        ("local_commits_allowed", human_go.local_commits_allowed, requirements.local_commits_allowed),
        ("candidate-local-commits", human_go.local_commits_allowed, candidate.local_commits_allowed),
    )
    mismatch = next((name for name, left, right in checks if left != right), None)
    if mismatch is not None:
        raise PilotExactTaskProductPilotTaskRegistryError(
            f"fresh human GO scope does not match exact lineage: {mismatch}"
        )
    if (
        lineage.selected_pilot_task_id not in human_go.allowed_task_ids
        or lineage.selected_pilot_task_id != requirements.selected_pilot_task_id
        or lineage.selected_pilot_task_id != candidate.selected_pilot_task_id
    ):
        raise PilotExactTaskProductPilotTaskRegistryError(
            "selected pilot task is outside fresh human allowlist or exact lineage"
        )

    try:
        development_task = host_registry_entries[lineage.selected_pilot_task_id]
    except KeyError as exc:
        raise PilotExactTaskProductPilotTaskRegistryError(
            "selected pilot task is absent from the existing ADR-DC-035 host registry"
        ) from exc
    if (
        development_task.repository != lineage.repository
        or development_task.base_sha != requirements.base_sha
        or len(development_task.allowed_command_ids) != 1
        or development_task.required_tests != development_task.allowed_command_ids
    ):
        raise PilotExactTaskProductPilotTaskRegistryError(
            "ADR-DC-035 host registry task does not match exact pilot scope"
        )
    development_task_sha256 = task_binding_boundary._task_sha256(development_task)
    fixed_command_id = development_task.allowed_command_ids[0]

    evaluated_at = now_provider()
    evaluated = _utc(evaluated_at, name="evaluated_at_utc")
    decided = _utc(human_go.decided_at_utc, name="decided_at_utc")
    verified = _utc(human_go.verified_at_utc, name="verified_at_utc")
    lineage_time = _utc(lineage.attested_at_utc, name="lineage_attested_at_utc")
    if decided < lineage_time:
        raise PilotExactTaskProductPilotTaskRegistryError(
            "fresh human GO predates exact post-production lineage attestation"
        )
    age = int((evaluated - verified).total_seconds())
    if (
        evaluated < verified
        or age < 0
        or age > PILOT_EXACT_TASK_PRODUCT_PILOT_TASK_REGISTRY_MAX_GO_AGE_SECONDS
    ):
        raise PilotExactTaskProductPilotTaskRegistryError(
            "fresh human GO is stale for product-pilot task registry"
        )

    receipt = PilotExactTaskProductPilotTaskRegistryReceipt(
        lineage_attestation_sha256=lineage.sha256,
        fresh_human_decision_proof_sha256=human_go.sha256,
        human_selection_proof_sha256=lineage.human_selection_proof_sha256,
        preflight_proof_sha256=lineage.preflight_proof_sha256,
        repository=lineage.repository,
        merge_commit_sha=lineage.merge_commit_sha,
        operator_surface=lineage.operator_surface,
        selected_pilot_task_id=lineage.selected_pilot_task_id,
        registered_task_ids=(lineage.selected_pilot_task_id,),
        host_development_task_registry_sha256=host_registry_sha256,
        development_task_id=development_task.task_id,
        development_task_sha256=development_task_sha256,
        fixed_command_id=fixed_command_id,
        workspace_root_path_sha256=lineage.workspace_root_path_sha256,
        feature_flag_name=lineage.feature_flag_name,
        product_route=lineage.product_route,
        task_registry_id=candidate.task_registry_id,
        decision_id=human_go.decision_id,
        decision_maker_actor_id=human_go.decision_maker_actor_id,
        decided_at_utc=human_go.decided_at_utc,
        verified_at_utc=human_go.verified_at_utc,
        evaluated_at_utc=evaluated_at,
        human_go_age_seconds=age,
    )
    _mark_product_pilot_task_registry_authenticated(
        receipt,
        lineage=lineage,
        human_go=human_go,
        development_task=development_task,
        host_registry_sha256=host_registry_sha256,
    )
    if receipt.registry_authenticated is not True:
        raise PilotExactTaskProductPilotTaskRegistryError(
            "product-pilot task-registry receipt lost live provenance"
        )
    return receipt


def build_pilot_exact_task_product_pilot_task_registry(
    *,
    lineage_attestation: lineage_boundary.PilotExactTaskProductPilotLineageAttestationReceipt,
    completion_proof: Any,
    human_pilot_decision: human_boundary.HumanPilotDecision,
    human_pilot_decision_signature: Any,
) -> PilotExactTaskProductPilotTaskRegistryReceipt:
    """Build a single-task inert registry from a fresh host-verified human GO."""
    fresh_go = human_boundary.verify_human_pilot_decision(
        completion_proof=completion_proof,
        decision=human_pilot_decision,
        signature=human_pilot_decision_signature,
        verifier=None,
    )
    try:
        registry_payload = task_registry_host_boundary._read_host_controlled_registry()
    except Exception as exc:
        raise PilotExactTaskProductPilotTaskRegistryError(
            "canonical ADR-DC-035 host DevelopmentTask registry is unavailable"
        ) from exc
    return _build_verified_product_pilot_task_registry(
        lineage_attestation=lineage_attestation,
        fresh_human_decision_proof=fresh_go,
        registry_payload=registry_payload,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_PRODUCT_PILOT_TASK_REGISTRY_SCHEMA",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_TASK_REGISTRY_AUTHORITY",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_TASK_REGISTRY_SCOPE",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_TASK_REGISTRY_MAX_GO_AGE_SECONDS",
    "PilotExactTaskProductPilotTaskRegistryError",
    "PilotExactTaskProductPilotTaskRegistryReceipt",
    "build_pilot_exact_task_product_pilot_task_registry",
]
