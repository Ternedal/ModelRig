"""End-to-end signed-evidence -> staging -> captured Tier-A execution proof.

A statically linked helper begins only in the separate operator runtime root.
The public runtime stages it into the signed workspace and proves, on real
Windows, strict inherited handles, separate concurrent stdout/stderr drains,
full-stream hashes, bounded prefixes, deterministic truncation and timeout Job
Object cleanup. No external network is used.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
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
from kaliv_dev_control.runtime_staging import TrustedRuntimeStager  # noqa: E402
from kaliv_dev_control.tier_a_execution import (  # noqa: E402
    LeasedCatalogMaterializer,
    TIER_A_APPLICATION_ENVIRONMENT,
    TierAExecutionTimeout,
    build_tier_a_launch_plan,
    run_verified_tier_a_command,
    tier_a_toolhost_sha256,
    workspace_root_authority_sha256,
)

passed = failed = 0
BURST_COMMAND = "modelrig.tier-a.capture-burst"
TIMEOUT_COMMAND = "modelrig.tier-a.capture-timeout"
OUTPUT_BUDGET = 4096
CHUNK_BYTES = 4096
CHUNK_COUNT = 64
EXPECTED_STDOUT = b"STDOUT-BEGIN\n" + (b"A" * CHUNK_BYTES * CHUNK_COUNT)
EXPECTED_STDERR = b"STDERR-BEGIN\n" + (b"B" * CHUNK_BYTES * CHUNK_COUNT)
TIMEOUT_MARKER = b"BEFORE-TIMEOUT\n"


def check(condition, message):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def build_static_capture_helper(destination: Path) -> Path:
    """Compile the deterministic fixture with the hosted MSVC toolchain."""

    source = ROOT / "tests" / "support" / "windows_capture_helper.c"
    program_files_x86 = os.environ.get(
        "ProgramFiles(x86)", r"C:\Program Files (x86)"
    )
    vswhere = (
        Path(program_files_x86)
        / "Microsoft Visual Studio"
        / "Installer"
        / "vswhere.exe"
    )
    if not source.is_file() or not vswhere.is_file():
        raise RuntimeError("MSVC source or vswhere.exe is missing")
    discovered = subprocess.run(
        [
            str(vswhere),
            "-latest",
            "-products",
            "*",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property",
            "installationPath",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    installations = discovered.stdout.strip().splitlines()
    if discovered.returncode != 0 or not installations:
        raise RuntimeError(
            "Visual Studio C++ toolchain not found: "
            + discovered.stderr.strip()[-400:]
        )
    devcmd = Path(installations[-1]) / "Common7" / "Tools" / "VsDevCmd.bat"
    if not devcmd.is_file():
        raise RuntimeError("VsDevCmd.bat is missing")

    build_dir = Path(tempfile.mkdtemp(prefix="kaliv-capture-build-"))
    script = build_dir / "build-capture-helper.cmd"
    script.write_text(
        "@echo off\r\n"
        f'call "{devcmd}" -no_logo -arch=x64 -host_arch=x64\r\n'
        "if errorlevel 1 exit /b %errorlevel%\r\n"
        f'cl /nologo /O2 /MT /W4 /WX "{source}" '
        f'/Fe:"{destination}"\r\n'
        "exit /b %errorlevel%\r\n",
        encoding="ascii",
    )
    built = subprocess.run(
        ["cmd.exe", "/d", "/c", str(script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if built.returncode != 0 or not destination.is_file():
        raise RuntimeError(
            "static capture helper build failed:\n"
            + (built.stdout + "\n" + built.stderr)[-1600:]
        )
    return destination.resolve()


base_sha = "a" * 40
started = "2026-08-03T18:00:00Z"
completed = "2026-08-03T18:10:00Z"
secret = b"slice-10c-windows-test-secret-01"
key_id = "slice-10c-windows-test-key"

parent = Path(tempfile.mkdtemp(prefix="kaliv-tier-a-capture-"))
trusted_runtime_root = parent / "trusted-runtime"
workspace = parent / "workspace"
evidence_root = parent / "evidence"
trusted_runtime_root.mkdir()
workspace.mkdir()
evidence_root.mkdir()
source_executable = build_static_capture_helper(
    trusted_runtime_root / "capture-helper.exe"
)
executable_hash = hashlib.sha256(source_executable.read_bytes()).hexdigest()
check(
    source_executable.is_file(),
    "exact static helper is held in the separate operator runtime root",
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
            BURST_COMMAND,
            "capture-helper",
            ("burst",),
            ".",
            30,
            catalog_env,
        ),
        ProjectCommandSpec(
            TIMEOUT_COMMAND,
            "capture-helper",
            ("sleep",),
            ".",
            1,
            catalog_env,
        ),
    )
)
toolchain = Toolchain(
    (
        ToolBinding(
            "capture-helper",
            str(source_executable),
            executable_hash,
        ),
    )
)
task = DevelopmentTask.from_mapping(
    {
        "schema": "kaliv-development-task/v1",
        "task_id": "A10C_WINDOWS",
        "repository": "Ternedal/ModelRig",
        "base_sha": base_sha,
        "goal": "Prove bounded native Tier-A output and timeout cleanup.",
        "acceptance_criteria": [
            "Both streams are fully hashed and only bounded prefixes retained.",
            "Timeout cleanup reaches EOF without leaking the process tree."
        ],
        "risk": "low",
        "allowed_paths": ["devcontrol/**"],
        "protected_paths": ["devcontrol/secrets/**"],
        "allowed_command_ids": [BURST_COMMAND, TIMEOUT_COMMAND],
        "required_tests": [BURST_COMMAND, TIMEOUT_COMMAND],
        "budget": {
            "max_changed_files": 20,
            "max_added_lines": 5000,
            "max_deleted_lines": 5000,
            "max_attempts": 2,
            "max_runtime_seconds": 120,
            "max_output_bytes": OUTPUT_BUDGET,
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
            ("slice10c:" + name.value).encode("utf-8")
        ).hexdigest(),
        detail=f"CI fixture for {name.value}",
        observed_at=completed,
    )
    for name in ProbeName
)
report = WindowsIsolationPhysicalReport(
    report_id="slice-10c-windows-kernel-proof",
    task_id=task.task_id,
    task_sha256=task_sha,
    repository=task.repository,
    base_sha=task.base_sha,
    catalog_sha256=catalog.sha256,
    toolchain_sha256=toolchain.sha256,
    rig_id="github-windows-server-2025",
    rig_fingerprint_sha256="1" * 64,
    candidate_version="slice-10c-ci",
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
    now=lambda: datetime(2026, 8, 3, 18, 15, tzinfo=timezone.utc),
)

# Structural inspection uses one plan, while the public call below must reverify,
# restage/recheck and rebuild independently before it receives launch authority.
leased = LeasedCatalogMaterializer(catalog, verifier).materialize(
    task, toolchain, attestation
)
stager = TrustedRuntimeStager(trusted_runtime_root.resolve(), workspace.resolve())
staging_receipt = stager.stage(leased, task, BURST_COMMAND)
staged_leased = stager.bind_for_launch(
    staging_receipt,
    leased,
    task,
    BURST_COMMAND,
)
plan = build_tier_a_launch_plan(
    staged_leased,
    task,
    BURST_COMMAND,
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
    plan.max_output_bytes == OUTPUT_BUDGET,
    "launch plan binds the exact signed task output budget",
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

burst_result = run_verified_tier_a_command(
    task,
    catalog,
    toolchain,
    attestation,
    verifier,
    BURST_COMMAND,
    trusted_runtime_root=trusted_runtime_root.resolve(),
    workspace_root=workspace.resolve(),
    control_plane_root=ROOT,
    source_env=dict(os.environ),
    process_memory_bytes=128 * 1024 * 1024,
    active_process_limit=1,
)
check(
    burst_result.returncode == 0 and burst_result.passed,
    "freshly verified burst command exits successfully through Tier-A",
)
check(
    burst_result.plan_sha256 == plan.sha256
    and burst_result.lease_sha256 == leased.lease.sha256
    and burst_result.signed_report_sha256 == signed_hash,
    "execution result remains bound to plan, lease and signed report",
)
check(
    burst_result.stdout.total_bytes == len(EXPECTED_STDOUT)
    and burst_result.stderr.total_bytes == len(EXPECTED_STDERR),
    "both native streams are drained completely beyond pipe-buffer size",
)
check(
    burst_result.stdout.sha256 == hashlib.sha256(EXPECTED_STDOUT).hexdigest()
    and burst_result.stderr.sha256 == hashlib.sha256(EXPECTED_STDERR).hexdigest(),
    "full stdout and stderr receive deterministic SHA-256 identities",
)
check(
    burst_result.stdout.captured == EXPECTED_STDOUT[: OUTPUT_BUDGET // 2]
    and burst_result.stderr.captured == EXPECTED_STDERR[: OUTPUT_BUDGET // 2],
    "only deterministic per-stream prefixes are retained",
)
check(
    burst_result.captured_output_bytes == OUTPUT_BUDGET
    and burst_result.output_truncated
    and burst_result.stdout.truncated
    and burst_result.stderr.truncated,
    "combined retained bytes never exceed the signed output budget",
)

try:
    run_verified_tier_a_command(
        task,
        catalog,
        toolchain,
        attestation,
        verifier,
        TIMEOUT_COMMAND,
        trusted_runtime_root=trusted_runtime_root.resolve(),
        workspace_root=workspace.resolve(),
        control_plane_root=ROOT,
        source_env=dict(os.environ),
        process_memory_bytes=128 * 1024 * 1024,
        active_process_limit=1,
    )
except TierAExecutionTimeout as exc:
    timeout_result = exc.result
    check(True, "timeout is surfaced as a typed execution-evidence failure")
    check(
        timeout_result.timed_out and not timeout_result.passed,
        "timeout result can never claim a passing command",
    )
    check(
        timeout_result.stdout.captured == TIMEOUT_MARKER
        and timeout_result.stdout.sha256
        == hashlib.sha256(TIMEOUT_MARKER).hexdigest(),
        "output emitted before timeout is preserved and fully hashed",
    )
    check(
        timeout_result.stderr.total_bytes == 0
        and not timeout_result.output_truncated,
        "timeout cleanup reaches deterministic EOF on both streams",
    )
    check(
        timeout_result.duration_ms >= 900,
        "timeout result records the enforced wall-clock boundary",
    )
except Exception as exc:
    check(False, f"timeout produced the wrong failure type: {exc!r}")
else:
    check(False, "sleeping helper was not terminated by the fixed timeout")

print(f"\n===== WINDOWS CATALOG TIER-A: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
