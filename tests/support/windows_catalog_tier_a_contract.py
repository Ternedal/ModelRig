"""End-to-end signed-evidence -> staging -> Tier-A AppContainer proof.

The probe binds a custom immutable catalog entry to an operator-controlled copy
of Windows' curl.exe outside the approved workspace. The public runtime stages
that exact binary into the signed workspace, re-verifies the receipt and launches
only through the fresh-verification API. No external network is used.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "devcontrol" / "src"))
sys.path.insert(0, str(ROOT / "worker"))

from app.windows_tier_a import (  # noqa: E402
    WINDOWS_TIER_A_APPLICATION_ENVIRONMENT,
    appcontainer_environment,
)
from kaliv_dev_control.catalog import (  # noqa: E402
    IsolationAttestation,
    IsolationBoundary,
    ModelRigCommandCatalog,
    NetworkMode,
    ProjectCommandSpec,
    ToolBinding,
    Toolchain,
)
from kaliv_dev_control.contract import DevelopmentTask  # noqa: E402
from kaliv_dev_control.physical_isolation import (  # noqa: E402
    HmacIsolationReportSigner,
    PhysicalProbeResult,
    ProbeName,
    WindowsIsolationPhysicalReport,
    WindowsPhysicalIsolationVerifier,
    write_signed_report,
)
from kaliv_dev_control.runtime_staging import (  # noqa: E402
    TrustedRuntimeStager,
)
from kaliv_dev_control.tier_a_execution import (  # noqa: E402
    LeasedCatalogMaterializer,
    TIER_A_APPLICATION_ENVIRONMENT,
    build_tier_a_launch_plan,
    run_verified_tier_a_command,
    tier_a_toolhost_sha256,
    workspace_root_authority_sha256,
)

passed = failed = 0


def check(condition, message):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


base_sha = "a" * 40
started = "2026-08-03T14:00:00Z"
completed = "2026-08-03T14:10:00Z"
secret = b"slice-10b-windows-test-secret-01"
key_id = "slice-10b-windows-test-key"

parent = Path(tempfile.mkdtemp(prefix="kaliv-tier-a-catalog-"))
trusted_runtime_root = parent / "trusted-runtime"
workspace = parent / "workspace"
evidence_root = parent / "evidence"
trusted_runtime_root.mkdir()
workspace.mkdir()
evidence_root.mkdir()

system_curl = shutil.which("curl.exe")
if not system_curl or not Path(system_curl).is_file():
    check(False, "Windows curl.exe is available")
    raise SystemExit(1)
source_executable = trusted_runtime_root / "curl.exe"
shutil.copy2(system_curl, source_executable)
executable_hash = hashlib.sha256(source_executable.read_bytes()).hexdigest()
check(
    source_executable.is_file(),
    "exact tool executable is held in the separate operator runtime root",
)
check(
    not any(workspace.iterdir()),
    "signed workspace starts without a caller-prestaged executable",
)

catalog_env = {
    "CI": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
}
catalog = ModelRigCommandCatalog(
    (
        ProjectCommandSpec(
            "modelrig.tier-a.windows-proof",
            "curl",
            ("--version",),
            ".",
            30,
            catalog_env,
        ),
    )
)
toolchain = Toolchain(
    (
        ToolBinding(
            "curl",
            str(source_executable.resolve()),
            executable_hash,
        ),
    )
)
task = DevelopmentTask.from_mapping(
    {
        "schema": "kaliv-development-task/v1",
        "task_id": "A10B_WINDOWS",
        "repository": "Ternedal/ModelRig",
        "base_sha": base_sha,
        "goal": "Prove staging-bound Tier-A command launch on Windows.",
        "acceptance_criteria": [
            "The fixed operator runtime is staged and exits successfully."
        ],
        "risk": "low",
        "allowed_paths": ["devcontrol/**"],
        "protected_paths": ["devcontrol/secrets/**"],
        "allowed_command_ids": ["modelrig.tier-a.windows-proof"],
        "required_tests": ["modelrig.tier-a.windows-proof"],
        "budget": {
            "max_changed_files": 20,
            "max_added_lines": 5000,
            "max_deleted_lines": 5000,
            "max_attempts": 2,
            "max_runtime_seconds": 120,
            "max_output_bytes": 1000000,
        },
        "merge_authority": "human",
    }
)
task_sha = hashlib.sha256(task.canonical_json().encode("utf-8")).hexdigest()

probes = tuple(
    PhysicalProbeResult(
        name=name,
        passed=True,
        receipt_sha256=hashlib.sha256(
            ("slice10b:" + name.value).encode("utf-8")
        ).hexdigest(),
        detail=f"CI fixture for {name.value}",
        observed_at=completed,
    )
    for name in ProbeName
)
report = WindowsIsolationPhysicalReport(
    report_id="slice-10b-windows-kernel-proof",
    task_id=task.task_id,
    task_sha256=task_sha,
    repository=task.repository,
    base_sha=task.base_sha,
    catalog_sha256=catalog.sha256,
    toolchain_sha256=toolchain.sha256,
    rig_id="github-windows-server-2025",
    rig_fingerprint_sha256="1" * 64,
    candidate_version="slice-10b-ci",
    windows_build="GitHub Windows Server 2025",
    toolhost_sha256=tier_a_toolhost_sha256(ROOT),
    workspace_root_sha256=workspace_root_authority_sha256(workspace),
    collected_by="github-actions-collector",
    approved_by="github-actions-test-approver",
    started_at=started,
    completed_at=completed,
    boot_marker_before_sha256="2" * 64,
    boot_marker_after_sha256="3" * 64,
    boundary=IsolationBoundary.OS_ISOLATED,
    network_mode=NetworkMode.DENY,
    probes=probes,
)
signed = HmacIsolationReportSigner(key_id, secret).sign(report)
signed_path = (evidence_root / "signed-report.json").resolve()
signed_hash = write_signed_report(signed_path, signed)
attestation = IsolationAttestation(
    task_id=task.task_id,
    task_sha256=task_sha,
    repository=task.repository,
    base_sha=task.base_sha,
    catalog_sha256=catalog.sha256,
    toolchain_sha256=toolchain.sha256,
    boundary=IsolationBoundary.OS_ISOLATED,
    network_mode=NetworkMode.DENY,
    evidence_sha256=(signed_hash,),
)
verifier = WindowsPhysicalIsolationVerifier(
    evidence_root.resolve(),
    {key_id: secret},
    max_age=timedelta(days=366),
    now=lambda: datetime(2026, 8, 3, 14, 15, tzinfo=timezone.utc),
)

# Structural assertions inspect the issued receipt/plan, but execution below does
# not consume this plan. The public runtime must verify, stage and rebuild again.
leased = LeasedCatalogMaterializer(catalog, verifier).materialize(
    task, toolchain, attestation
)
stager = TrustedRuntimeStager(trusted_runtime_root.resolve(), workspace.resolve())
staging_receipt = stager.stage(
    leased,
    task,
    "modelrig.tier-a.windows-proof",
)
staged_leased = stager.bind_for_launch(
    staging_receipt,
    leased,
    task,
    "modelrig.tier-a.windows-proof",
)
plan = build_tier_a_launch_plan(
    staged_leased,
    task,
    "modelrig.tier-a.windows-proof",
    workspace_root=workspace.resolve(),
    control_plane_root=ROOT,
)
check(
    plan.signed_report_sha256 == signed_hash,
    "launch plan retains the exact signed physical report hash",
)
check(
    plan.lease_sha256 == leased.lease.sha256,
    "launch plan retains the immutable execution lease hash",
)
check(
    Path(plan.argv[0]).is_relative_to(workspace.resolve()),
    "launch plan executable is the receipt-verified workspace copy",
)
check(
    Path(plan.argv[0]).read_bytes() == source_executable.read_bytes(),
    "staged launch bytes equal the operator-bound source bytes",
)
check(
    dict(WINDOWS_TIER_A_APPLICATION_ENVIRONMENT)
    == dict(TIER_A_APPLICATION_ENVIRONMENT),
    "catalog and worker agree on the exact reviewed application environment",
)
filtered = appcontainer_environment(
    dict(os.environ),
    application_env=catalog_env,
)
check(filtered["CI"] == "1", "reviewed catalog environment reaches Tier-A")
check(
    "GITHUB_TOKEN" not in filtered and "ACTIONS_RUNTIME_TOKEN" not in filtered,
    "parent credentials remain excluded from the Tier-A environment",
)

exit_code = run_verified_tier_a_command(
    task,
    catalog,
    toolchain,
    attestation,
    verifier,
    "modelrig.tier-a.windows-proof",
    trusted_runtime_root=trusted_runtime_root.resolve(),
    workspace_root=workspace.resolve(),
    control_plane_root=ROOT,
    source_env=dict(os.environ),
    process_memory_bytes=128 * 1024 * 1024,
    active_process_limit=1,
)
check(
    exit_code == 0,
    f"freshly reverified and staged command exits through Tier-A (exit={exit_code})",
)

print(f"\n===== WINDOWS CATALOG TIER-A: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
