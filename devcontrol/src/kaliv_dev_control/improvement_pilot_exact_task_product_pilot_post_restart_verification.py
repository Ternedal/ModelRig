"""ADR-DC-112 fresh post-restart verification of a completed ADR-DC-108 run.

Consumes only a live ADR-DC-111 completed recovery resolution. The original
ADR-DC-108 process-local execution authority is deliberately not restored.

Instead this boundary independently re-establishes:
* the exact durable final ADR-DC-108 receipt under its permanent execution lock;
* the current host-admin-controlled Tier-A profile for the same task hash;
* the same signed physical isolation report and Tier-A lease used by execution;
* the same workspace path authority and control-plane toolhost;
* the same Trusted-Git runtime evidence; and
* a fresh read-only Git snapshot equal to Tier-A's recorded post-execution state.

No command is launched and no Git or ledger mutation is performed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from . import improvement_pilot_exact_task_product_pilot_execution as execution_boundary
from . import improvement_pilot_exact_task_product_pilot_execution_recovery as recovery_boundary
from . import improvement_pilot_exact_task_product_pilot_execution_recovery_resolution as resolution_boundary
from . import _improvement_pilot_exact_task_executor_capability_production_boundary as executor_production
from ._tier_a_lease import TierAExecutionLease
from ._tier_a_path_authority import workspace_root_authority_sha256
from .tier_a_authority import tier_a_toolhost_sha256
from .tier_a_command_receipt import GitWorkspaceSnapshot
from .trusted_git_runtime_runner import TrustedGitRunner
from .runtime_closure_builder import VERSION_CHECK_COMMAND_ID

PILOT_EXACT_TASK_PRODUCT_PILOT_POST_RESTART_VERIFICATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-post-restart-verification/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_POST_RESTART_VERIFICATION_AUTHORITY = (
    "fresh-host-post-restart-execution-verification-only"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_POST_RESTART_VERIFICATION_SCOPE = (
    "completed-durable-execution-fresh-host-verification-v1"
)

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_GIT_OUTPUT_BYTES = 32 * 1024 * 1024


class PilotExactTaskProductPilotPostRestartVerificationError(ValueError):
    """Recovered execution cannot be safely verified against the current host."""


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
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "post-restart verification is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            f"{name} is invalid"
        )
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            f"{name} is invalid"
        )
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            f"{name} is invalid"
        )
    return value


def _require_live_completed_resolution(value: Any):
    if (
        type(value)
        is not resolution_boundary.PilotExactTaskProductPilotExecutionRecoveryResolutionReceipt
        or value.resolution_authenticated is not True
        or value.source_recovery_state_class != "completed_verified"
        or value.resolution_class != resolution_boundary.RESOLUTION_COMPLETED
        or value.recovered_execution_receipt_sha256 is None
        or value.completed_execution_evidence_available is not True
        or value.post_restart_verification_required is not True
        or value.manual_intervention_required is not False
        or value.retry_authorized is not False
        or value.task_execution_authorized is not False
        or value.local_commit_authorized is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.nonce_reusable is not False
        or value.next_boundary_post_restart_verification_required is not True
        or value.next_boundary_manual_resolution_required is not False
        or value.fixed_command_id != VERSION_CHECK_COMMAND_ID
    ):
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "live completed ADR-DC-111 resolution is required"
        )
    live = resolution_boundary._get_live_recovery_resolution_inputs(value)
    if live is None:
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "ADR-DC-111 live recovery-resolution provenance is unavailable"
        )
    ledger = live.get("ledger")
    if type(ledger) is not execution_boundary._PilotExactTaskProductPilotExecutionLedger:
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "ADR-DC-111 no longer exposes the exact durable execution ledger"
        )
    return value, live, ledger


def _load_completed_execution(
    source: resolution_boundary.PilotExactTaskProductPilotExecutionRecoveryResolutionReceipt,
    ledger: execution_boundary._PilotExactTaskProductPilotExecutionLedger,
) -> execution_boundary.PilotExactTaskProductPilotExecutionReceipt:
    first = recovery_boundary._observe(
        execution_nonce_sha256=source.execution_nonce_sha256,
        ledger=ledger,
    )
    second = recovery_boundary._observe(
        execution_nonce_sha256=source.execution_nonce_sha256,
        ledger=ledger,
    )
    if (
        first != second
        or first.sha256 != second.sha256
        or first.recovery_state_class != "completed_verified"
        or first.final_receipt_verified is not True
        or first.pending_receipt_verified is not False
        or first.recovered_execution_receipt_sha256
        != source.recovered_execution_receipt_sha256
        or first.execution_plan_sha256 != source.execution_plan_sha256
        or first.workspace_snapshot_receipt_sha256
        != source.workspace_snapshot_receipt_sha256
        or first.executor_capability_sha256 != source.executor_capability_sha256
        or first.execution_admission_sha256 != source.execution_admission_sha256
        or first.development_task_sha256 != source.development_task_sha256
        or first.workspace_snapshot_sha256 != source.workspace_snapshot_sha256
        or first.fixed_command_id != source.fixed_command_id
    ):
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "durable completed execution state no longer matches ADR-DC-111"
        )

    final_path, pending_path, lock_path = ledger._paths(source.execution_nonce_sha256)
    if pending_path.exists() or pending_path.is_symlink():
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "pending ADR-DC-108 receipt appeared after completed recovery"
        )
    lock_raw = recovery_boundary._read_regular(
        lock_path,
        name="ADR-DC-108 execution lock",
    )
    lock = recovery_boundary._canonical_object(
        lock_raw,
        name="ADR-DC-108 execution lock",
    )
    final_raw = recovery_boundary._read_regular(
        final_path,
        name="ADR-DC-108 final receipt",
    )
    receipt = recovery_boundary._validate_receipt(
        final_raw,
        lock=lock,
        ledger_root_sha256=ledger.root_sha256,
        name="ADR-DC-108 final receipt",
    )
    if (
        receipt.sha256 != source.recovered_execution_receipt_sha256
        or receipt.execution_nonce_sha256 != source.execution_nonce_sha256
        or receipt.execution_plan_sha256 != source.execution_plan_sha256
        or receipt.workspace_snapshot_receipt_sha256
        != source.workspace_snapshot_receipt_sha256
        or receipt.executor_capability_sha256 != source.executor_capability_sha256
        or receipt.execution_admission_sha256 != source.execution_admission_sha256
        or receipt.development_task_sha256 != source.development_task_sha256
        or receipt.workspace_snapshot_sha256 != source.workspace_snapshot_sha256
        or receipt.fixed_command_id != source.fixed_command_id
    ):
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "recovered ADR-DC-108 receipt identity mismatch"
        )
    return receipt


def _git_read(
    runner: TrustedGitRunner,
    workspace: Path,
    *args: str,
    maximum: int = _MAX_GIT_OUTPUT_BYTES,
) -> bytes:
    try:
        return runner.run(
            tuple(args),
            cwd=workspace,
            maximum=maximum,
            timeout_seconds=120,
        )
    except Exception as exc:
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "fresh Trusted-Git evidence read failed"
        ) from exc


def _capture_workspace(
    *,
    runner: TrustedGitRunner,
    workspace_root: Path,
) -> GitWorkspaceSnapshot:
    raw = Path(workspace_root)
    if not raw.is_absolute():
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "host-resolved workspace must be absolute"
        )
    workspace = Path(os.path.realpath(os.path.abspath(raw)))
    if not workspace.is_dir() or not (workspace / ".git").exists():
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "host-resolved workspace is not an existing Git worktree"
        )
    top = _git_read(
        runner,
        workspace,
        "rev-parse",
        "--show-toplevel",
        maximum=2_000_000,
    ).decode("utf-8", errors="strict").strip()
    if os.path.normcase(os.path.realpath(top)) != os.path.normcase(os.fspath(workspace)):
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "Trusted-Git top-level does not match host-resolved workspace"
        )
    head = _git_read(
        runner,
        workspace,
        "rev-parse",
        "HEAD",
        maximum=4096,
    ).decode("ascii", errors="strict").strip()
    staged = _git_read(
        runner,
        workspace,
        "diff",
        "--cached",
        "--binary",
        "--full-index",
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--",
    )
    unstaged = _git_read(
        runner,
        workspace,
        "diff",
        "--binary",
        "--full-index",
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--",
    )
    untracked = _git_read(
        runner,
        workspace,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
    )
    paths = tuple(path for path in untracked.split(b"\0") if path)
    return GitWorkspaceSnapshot(
        head_sha=head,
        staged_patch_sha256=hashlib.sha256(staged).hexdigest(),
        staged_patch_bytes=len(staged),
        unstaged_patch_sha256=hashlib.sha256(unstaged).hexdigest(),
        unstaged_patch_bytes=len(unstaged),
        untracked_paths_sha256=hashlib.sha256(untracked).hexdigest(),
        untracked_path_count=len(paths),
    )


def _collect_fresh_host_evidence(
    *,
    execution_receipt: execution_boundary.PilotExactTaskProductPilotExecutionReceipt,
    resolver: Callable[..., Mapping[str, Any]],
) -> dict[str, Any]:
    try:
        inputs = resolver(
            development_task_sha256=execution_receipt.development_task_sha256,
        )
    except Exception as exc:
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "host-controlled Tier-A profile cannot be resolved after restart"
        ) from exc
    if not isinstance(inputs, Mapping):
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "host-controlled Tier-A resolver returned invalid inputs"
        )

    required = {
        "catalog",
        "toolchain",
        "isolation_attestation",
        "physical_verifier",
        "signed_runtime_closure",
        "runtime_closure_verifier",
        "trusted_runtime_root",
        "git_runner",
        "workspace_root",
        "control_plane_root",
    }
    if set(inputs) != required:
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "host-controlled Tier-A resolver input set changed"
        )

    command = execution_receipt.tier_a_command_receipt
    result = command.tier_a_result
    attestation = inputs["isolation_attestation"]
    physical_verifier = inputs["physical_verifier"]
    if (
        getattr(attestation, "task_id", None) != execution_receipt.development_task_id
        or getattr(attestation, "task_sha256", None)
        != execution_receipt.development_task_sha256
        or getattr(attestation, "base_sha", None)
        != execution_receipt.development_task_base_sha
        or getattr(attestation, "catalog_sha256", None)
        != getattr(inputs["catalog"], "sha256", None)
        or getattr(attestation, "toolchain_sha256", None)
        != getattr(inputs["toolchain"], "sha256", None)
        or result.signed_report_sha256
        not in tuple(getattr(attestation, "evidence_sha256", ()))
    ):
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "host-resolved isolation attestation is not the execution authority"
        )

    try:
        physical_verifier.verify(attestation)
        candidates = physical_verifier._load_candidates(
            set(attestation.evidence_sha256)
        )
    except Exception as exc:
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "signed physical isolation authority could not be revalidated"
        ) from exc
    if len(candidates) != 1 or candidates[0].sha256 != result.signed_report_sha256:
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "current host profile is not bound to the exact execution physical report"
        )
    signed_report = candidates[0]
    try:
        lease = TierAExecutionLease.from_signed_report(attestation, signed_report)
    except Exception as exc:
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "execution physical report cannot reproduce the Tier-A lease"
        ) from exc
    if lease.sha256 != result.lease_sha256:
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "current host profile does not reproduce the execution Tier-A lease"
        )

    workspace_root = Path(inputs["workspace_root"])
    control_plane_root = Path(inputs["control_plane_root"])
    try:
        workspace_authority = workspace_root_authority_sha256(workspace_root)
        toolhost = tier_a_toolhost_sha256(control_plane_root)
    except Exception as exc:
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "current workspace/toolhost authority could not be hashed"
        ) from exc
    if (
        workspace_authority != lease.workspace_root_sha256
        or toolhost != lease.toolhost_sha256
    ):
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "current workspace or toolhost differs from signed execution authority"
        )

    runner = inputs["git_runner"]
    if type(runner) is not TrustedGitRunner:
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "host resolver did not return the exact Trusted-Git runner"
        )
    try:
        runtime_before = runner.evidence()
        fresh = _capture_workspace(
            runner=runner,
            workspace_root=workspace_root,
        )
        runtime_after = runner.evidence()
    except PilotExactTaskProductPilotPostRestartVerificationError:
        raise
    except Exception as exc:
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "fresh post-restart Git verification failed"
        ) from exc
    if (
        runtime_before.sha256 != runtime_after.sha256
        or runtime_before.sha256 != command.git_runtime.sha256
    ):
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "Trusted-Git runtime differs from execution-time evidence"
        )

    expected = (
        command.workspace_reset
        if command.workspace_reset_performed
        else command.workspace_after
    )
    if expected is None:
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "execution receipt lacks expected post-execution workspace evidence"
        )
    if (
        fresh.sha256 != expected.sha256
        or fresh.head_sha != execution_receipt.development_task_base_sha
        or fresh.has_unstaged_or_untracked
    ):
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "current workspace does not match exact execution post-state"
        )

    if execution_receipt.task_execution_passed:
        if (
            execution_receipt.recovery_required
            or command.workspace_reset_performed
            or not command.workspace_unchanged
            or fresh.sha256 != execution_receipt.workspace_snapshot_sha256
        ):
            raise PilotExactTaskProductPilotPostRestartVerificationError(
                "passing recovered execution did not preserve planned workspace"
            )
        recovery_verified = False
    else:
        if not execution_receipt.recovery_required:
            raise PilotExactTaskProductPilotPostRestartVerificationError(
                "failed recovered execution lacks recovery requirement"
            )
        if command.workspace_reset_performed:
            reset = command.workspace_reset
            if (
                reset is None
                or reset.staged_patch_bytes != 0
                or reset.unstaged_patch_bytes != 0
                or reset.untracked_path_count != 0
            ):
                raise PilotExactTaskProductPilotPostRestartVerificationError(
                    "recovered Tier-A reset evidence is not exact-base clean"
                )
        elif not command.workspace_unchanged:
            raise PilotExactTaskProductPilotPostRestartVerificationError(
                "failed execution changed workspace without reset evidence"
            )
        recovery_verified = True

    return {
        "execution_receipt": execution_receipt,
        "fresh_snapshot": fresh,
        "expected_snapshot": expected,
        "git_runtime_sha256": runtime_before.sha256,
        "signed_report_sha256": signed_report.sha256,
        "lease_sha256": lease.sha256,
        "workspace_authority_sha256": workspace_authority,
        "toolhost_sha256": toolhost,
        "execution_outcome_passed": execution_receipt.task_execution_passed,
        "recovery_verified": recovery_verified,
    }


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskProductPilotPostRestartVerificationReceipt:
    recovery_resolution_sha256: str
    recovery_receipt_sha256: str
    execution_receipt_sha256: str
    execution_nonce_sha256: str
    execution_plan_sha256: str
    development_task_id: str
    development_task_sha256: str
    development_task_base_sha: str
    fixed_command_id: str
    tier_a_command_receipt_sha256: str
    signed_report_sha256: str
    lease_sha256: str
    workspace_authority_sha256: str
    toolhost_sha256: str
    git_runtime_evidence_sha256: str
    expected_post_execution_workspace_snapshot_sha256: str
    post_restart_workspace_snapshot_sha256: str
    post_restart_workspace_snapshot: GitWorkspaceSnapshot
    execution_outcome_passed: bool
    recovery_verified: bool
    recovery_resolution_authenticated: bool = True
    durable_execution_receipt_verified: bool = True
    host_executor_profile_revalidated: bool = True
    physical_report_revalidated: bool = True
    tier_a_lease_revalidated: bool = True
    workspace_authority_revalidated: bool = True
    control_plane_toolhost_revalidated: bool = True
    trusted_git_runtime_revalidated: bool = True
    post_restart_workspace_verified: bool = True
    execution_nonce_consumed: bool = True
    product_pilot_execution_closed: bool = True
    first_product_pilot_task_closed: bool = True
    manual_intervention_required: bool = False
    retry_authorized: bool = False
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
    next_boundary_stack_consolidation_required: bool = True
    verification_scope: str = (
        PILOT_EXACT_TASK_PRODUCT_PILOT_POST_RESTART_VERIFICATION_SCOPE
    )
    authority: str = PILOT_EXACT_TASK_PRODUCT_PILOT_POST_RESTART_VERIFICATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCT_PILOT_POST_RESTART_VERIFICATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCT_PILOT_POST_RESTART_VERIFICATION_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PRODUCT_PILOT_POST_RESTART_VERIFICATION_AUTHORITY
            or self.verification_scope
            != PILOT_EXACT_TASK_PRODUCT_PILOT_POST_RESTART_VERIFICATION_SCOPE
        ):
            raise PilotExactTaskProductPilotPostRestartVerificationError(
                "post-restart verification identity is unsupported"
            )
        for field in (
            "recovery_resolution_sha256",
            "recovery_receipt_sha256",
            "execution_receipt_sha256",
            "execution_nonce_sha256",
            "execution_plan_sha256",
            "development_task_sha256",
            "tier_a_command_receipt_sha256",
            "signed_report_sha256",
            "lease_sha256",
            "workspace_authority_sha256",
            "toolhost_sha256",
            "git_runtime_evidence_sha256",
            "expected_post_execution_workspace_snapshot_sha256",
            "post_restart_workspace_snapshot_sha256",
        ):
            _hex64(getattr(self, field), name=field)
        _hex40(self.development_task_base_sha, name="development_task_base_sha")
        _identifier(self.development_task_id, name="development_task_id")
        _identifier(self.fixed_command_id, name="fixed_command_id")
        if self.fixed_command_id != VERSION_CHECK_COMMAND_ID:
            raise PilotExactTaskProductPilotPostRestartVerificationError(
                "post-restart verification command is not the reviewed version check"
            )
        if type(self.post_restart_workspace_snapshot) is not GitWorkspaceSnapshot:
            raise PilotExactTaskProductPilotPostRestartVerificationError(
                "canonical post-restart workspace snapshot is required"
            )
        if (
            self.post_restart_workspace_snapshot.sha256
            != self.post_restart_workspace_snapshot_sha256
            or self.post_restart_workspace_snapshot_sha256
            != self.expected_post_execution_workspace_snapshot_sha256
            or self.post_restart_workspace_snapshot.head_sha
            != self.development_task_base_sha
            or self.post_restart_workspace_snapshot.has_unstaged_or_untracked
        ):
            raise PilotExactTaskProductPilotPostRestartVerificationError(
                "post-restart workspace receipt is inconsistent"
            )
        for field in (
            "execution_outcome_passed",
            "recovery_verified",
            "recovery_resolution_authenticated",
            "durable_execution_receipt_verified",
            "host_executor_profile_revalidated",
            "physical_report_revalidated",
            "tier_a_lease_revalidated",
            "workspace_authority_revalidated",
            "control_plane_toolhost_revalidated",
            "trusted_git_runtime_revalidated",
            "post_restart_workspace_verified",
            "execution_nonce_consumed",
            "product_pilot_execution_closed",
            "first_product_pilot_task_closed",
            "manual_intervention_required",
            "retry_authorized",
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
            "next_boundary_stack_consolidation_required",
        ):
            if type(getattr(self, field)) is not bool:
                raise PilotExactTaskProductPilotPostRestartVerificationError(
                    f"{field} must be boolean"
                )
        required_true = (
            "recovery_resolution_authenticated",
            "durable_execution_receipt_verified",
            "host_executor_profile_revalidated",
            "physical_report_revalidated",
            "tier_a_lease_revalidated",
            "workspace_authority_revalidated",
            "control_plane_toolhost_revalidated",
            "trusted_git_runtime_revalidated",
            "post_restart_workspace_verified",
            "execution_nonce_consumed",
            "product_pilot_execution_closed",
            "first_product_pilot_task_closed",
            "next_boundary_stack_consolidation_required",
        )
        if any(getattr(self, field) is not True for field in required_true):
            raise PilotExactTaskProductPilotPostRestartVerificationError(
                "post-restart verification lacks mandatory closure evidence"
            )
        forced_false = (
            "manual_intervention_required",
            "retry_authorized",
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
        if any(getattr(self, field) is not False for field in forced_false):
            raise PilotExactTaskProductPilotPostRestartVerificationError(
                "post-restart verification grants forbidden authority"
            )
        if self.execution_outcome_passed and self.recovery_verified:
            raise PilotExactTaskProductPilotPostRestartVerificationError(
                "passing execution cannot claim recovery"
            )
        if not self.execution_outcome_passed and not self.recovery_verified:
            raise PilotExactTaskProductPilotPostRestartVerificationError(
                "failed execution cannot close without verified recovery"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def verification_authenticated(self) -> bool:
        return _get_live_post_restart_verification_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        result = {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "post_restart_workspace_snapshot"
        }
        result["post_restart_workspace_snapshot"] = (
            self.post_restart_workspace_snapshot.to_dict()
        )
        return result

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductPilotPostRestartVerificationError(
                "post-restart verification fields mismatch"
            )
        raw = dict(value)
        try:
            raw["post_restart_workspace_snapshot"] = GitWorkspaceSnapshot.from_mapping(
                raw["post_restart_workspace_snapshot"]
            )
        except Exception as exc:
            raise PilotExactTaskProductPilotPostRestartVerificationError(
                "post-restart workspace snapshot is invalid"
            ) from exc
        return cls(**raw)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: PilotExactTaskProductPilotPostRestartVerificationReceipt,
        *,
        resolution: resolution_boundary.PilotExactTaskProductPilotExecutionRecoveryResolutionReceipt,
        resolver: Callable[..., Mapping[str, Any]],
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            resolution,
            resolver,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, resolution, resolver = entry
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or receipt.sha256 != digest
            or resolution.sha256 != receipt.recovery_resolution_sha256
            or resolution.resolution_authenticated is not True
        ):
            return None
        try:
            source, _live, ledger = _require_live_completed_resolution(resolution)
            execution = _load_completed_execution(source, ledger)
            fresh = _collect_fresh_host_evidence(
                execution_receipt=execution,
                resolver=resolver,
            )
        except Exception:
            return None
        checks = (
            (execution.sha256, receipt.execution_receipt_sha256),
            (fresh["signed_report_sha256"], receipt.signed_report_sha256),
            (fresh["lease_sha256"], receipt.lease_sha256),
            (fresh["workspace_authority_sha256"], receipt.workspace_authority_sha256),
            (fresh["toolhost_sha256"], receipt.toolhost_sha256),
            (fresh["git_runtime_sha256"], receipt.git_runtime_evidence_sha256),
            (
                fresh["expected_snapshot"].sha256,
                receipt.expected_post_execution_workspace_snapshot_sha256,
            ),
            (
                fresh["fresh_snapshot"].sha256,
                receipt.post_restart_workspace_snapshot_sha256,
            ),
            (fresh["execution_outcome_passed"], receipt.execution_outcome_passed),
            (fresh["recovery_verified"], receipt.recovery_verified),
        )
        if any(left != right for left, right in checks):
            return None
        result = dict(fresh)
        result["resolution"] = source
        return result

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_post_restart_verification_authenticated,
    _get_live_post_restart_verification_inputs,
) = _live_registry()


def _verify_pilot_exact_task_product_pilot_post_restart(
    *,
    recovery_resolution: resolution_boundary.PilotExactTaskProductPilotExecutionRecoveryResolutionReceipt,
    resolver: Callable[..., Mapping[str, Any]],
) -> PilotExactTaskProductPilotPostRestartVerificationReceipt:
    source, _live, ledger = _require_live_completed_resolution(recovery_resolution)
    execution = _load_completed_execution(source, ledger)
    fresh = _collect_fresh_host_evidence(
        execution_receipt=execution,
        resolver=resolver,
    )
    receipt = PilotExactTaskProductPilotPostRestartVerificationReceipt(
        recovery_resolution_sha256=source.sha256,
        recovery_receipt_sha256=source.recovery_receipt_sha256,
        execution_receipt_sha256=execution.sha256,
        execution_nonce_sha256=execution.execution_nonce_sha256,
        execution_plan_sha256=execution.execution_plan_sha256,
        development_task_id=execution.development_task_id,
        development_task_sha256=execution.development_task_sha256,
        development_task_base_sha=execution.development_task_base_sha,
        fixed_command_id=execution.fixed_command_id,
        tier_a_command_receipt_sha256=execution.tier_a_command_receipt_sha256,
        signed_report_sha256=fresh["signed_report_sha256"],
        lease_sha256=fresh["lease_sha256"],
        workspace_authority_sha256=fresh["workspace_authority_sha256"],
        toolhost_sha256=fresh["toolhost_sha256"],
        git_runtime_evidence_sha256=fresh["git_runtime_sha256"],
        expected_post_execution_workspace_snapshot_sha256=(
            fresh["expected_snapshot"].sha256
        ),
        post_restart_workspace_snapshot_sha256=fresh["fresh_snapshot"].sha256,
        post_restart_workspace_snapshot=fresh["fresh_snapshot"],
        execution_outcome_passed=fresh["execution_outcome_passed"],
        recovery_verified=fresh["recovery_verified"],
    )
    _mark_post_restart_verification_authenticated(
        receipt,
        resolution=source,
        resolver=resolver,
    )
    if receipt.verification_authenticated is not True:
        raise PilotExactTaskProductPilotPostRestartVerificationError(
            "post-restart verification lost live host provenance"
        )
    return receipt


def verify_pilot_exact_task_product_pilot_post_restart(
    recovery_resolution: resolution_boundary.PilotExactTaskProductPilotExecutionRecoveryResolutionReceipt,
) -> PilotExactTaskProductPilotPostRestartVerificationReceipt:
    """Freshly verify completed durable execution against current host authority."""
    return _verify_pilot_exact_task_product_pilot_post_restart(
        recovery_resolution=recovery_resolution,
        resolver=executor_production._resolve_host_executor_materialization_inputs,
    )


__all__ = [
    "PILOT_EXACT_TASK_PRODUCT_PILOT_POST_RESTART_VERIFICATION_SCHEMA",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_POST_RESTART_VERIFICATION_AUTHORITY",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_POST_RESTART_VERIFICATION_SCOPE",
    "PilotExactTaskProductPilotPostRestartVerificationError",
    "PilotExactTaskProductPilotPostRestartVerificationReceipt",
    "verify_pilot_exact_task_product_pilot_post_restart",
]
