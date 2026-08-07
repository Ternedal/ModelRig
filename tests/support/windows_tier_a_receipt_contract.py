"""Real-Windows end-to-end proof for the Git-aware Tier-A command receipt."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "devcontrol" / "src"))
sys.path.insert(0, str(ROOT / "worker"))

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
from kaliv_dev_control.tier_a_execution import (  # noqa: E402
    HmacRuntimeClosureSigner,
    LeasedCatalogMaterializer,
    RuntimeClosureFile,
    RuntimeClosureManifest,
    RuntimeClosureVerifier,
    TierACommandReceipt,
    run_single_verified_tier_a_command_with_receipt,
    tier_a_toolhost_sha256,
    trusted_runtime_root_sha256,
    workspace_root_authority_sha256,
)
from kaliv_dev_control.trusted_git_runtime import (  # noqa: E402
    TrustedGitRunner,
    TrustedGitRuntime,
    capture_trusted_git_runtime_manifest,
    stage_trusted_git_runtime,
)

COMMAND_ID = "modelrig.tier-a.receipt-probe"
TOOL_ID = "receipt-helper"
OUTPUT_BUDGET = 4096
REPORT_KEY_ID = "slice-10g-windows-report-key"
REPORT_SECRET = b"slice-10g-windows-report-secret-01"
CLOSURE_KEY_ID = "slice-10g-windows-closure-key"
CLOSURE_SECRET = b"slice-10g-windows-closure-secret-1"
passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def build_trusted_git_runner(parent: Path) -> TrustedGitRunner:
    discovered = shutil.which("git")
    if discovered is None:
        raise RuntimeError("Git for Windows is unavailable")
    installed = Path(discovered).resolve()
    exec_path_result = subprocess.run(
        [str(installed), "--exec-path"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if exec_path_result.returncode != 0:
        raise RuntimeError(
            "Git exec-path discovery failed: " + exec_path_result.stderr[-800:]
        )
    exec_path = Path(exec_path_result.stdout.strip()).resolve()
    mingw_root = exec_path.parent.parent
    runtime_executable = mingw_root / "bin" / "git.exe"
    if not runtime_executable.is_file() or not exec_path.is_dir():
        raise RuntimeError("Git for Windows runtime layout is unsupported")

    source = parent / "git-runtime-source"
    shutil.copytree(mingw_root / "bin", source / "bin")
    shutil.copytree(exec_path, source / "libexec" / "git-core")
    manifest = capture_trusted_git_runtime_manifest(
        source.resolve(),
        executable_relative_path="bin/git.exe",
        exec_path_relative_path="libexec/git-core",
        path_relative_directories=("bin", "libexec/git-core"),
    )
    staging = parent / "git-runtime-staging"
    operation = parent / "git-runtime-operation"
    staging.mkdir()
    operation.mkdir()
    transaction = stage_trusted_git_runtime(
        manifest,
        source_root=source.resolve(),
        staging_root=staging.resolve(),
    )
    return TrustedGitRunner(
        TrustedGitRuntime(transaction.resolve()),
        operation_root=operation.resolve(),
    )


def run_git(runner: TrustedGitRunner, workspace: Path, *args: str) -> str:
    return runner.run(
        tuple(args),
        cwd=workspace,
        maximum=32 * 1024 * 1024,
        timeout_seconds=120,
    ).decode("utf-8", errors="strict").strip()


def build_static_helper(destination: Path) -> Path:
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
        timeout=120,
    )
    installations = discovered.stdout.strip().splitlines()
    if discovered.returncode != 0 or not installations:
        raise RuntimeError(
            "Visual Studio C++ toolchain not found: "
            + discovered.stderr.strip()[-400:]
        )
    devcmd = Path(installations[-1]) / "Common7" / "Tools" / "VsDevCmd.bat"
    build_dir = Path(tempfile.mkdtemp(prefix="kaliv-receipt-build-"))
    script = build_dir / "build-receipt-helper.cmd"
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
        timeout=300,
    )
    if built.returncode != 0 or not destination.is_file():
        raise RuntimeError(
            "static receipt helper build failed:\n"
            + (built.stdout + "\n" + built.stderr)[-1600:]
        )
    return destination.resolve()


parent = Path(tempfile.mkdtemp(prefix="kaliv-tier-a-receipt-"))
git_runner = build_trusted_git_runner(parent)
trusted_runtime_root = parent / "trusted-runtime"
workspace = parent / "workspace"
evidence_root = parent / "evidence"
trusted_runtime_root.mkdir()
workspace.mkdir()
evidence_root.mkdir()

source_executable = build_static_helper(trusted_runtime_root / "receipt-helper.exe")
executable_bytes = source_executable.read_bytes()
executable_sha256 = hashlib.sha256(executable_bytes).hexdigest()

run_git(git_runner, workspace, "init")
run_git(git_runner, workspace, "config", "user.name", "Slice 10G Windows")
run_git(
    git_runner,
    workspace,
    "config",
    "user.email",
    "slice10g-windows@example.invalid",
)
baseline = workspace / "baseline.txt"
baseline.write_text("base\n", encoding="utf-8")
run_git(git_runner, workspace, "add", "baseline.txt")
run_git(git_runner, workspace, "commit", "-m", "base")
base_sha = run_git(git_runner, workspace, "rev-parse", "HEAD")
check(len(base_sha) == 40, "temporary workspace has one exact Git base SHA")

catalog_env = {"CI": "1", "PYTHONDONTWRITEBYTECODE": "1"}
catalog = ModelRigCommandCatalog(
    (
        ProjectCommandSpec(
            COMMAND_ID,
            TOOL_ID,
            ("burst",),
            ".",
            30,
            catalog_env,
        ),
    )
)
toolchain = Toolchain(
    (
        ToolBinding(
            TOOL_ID,
            str(source_executable),
            executable_sha256,
        ),
    )
)
task = DevelopmentTask.from_mapping(
    {
        "schema": "kaliv-development-task/v1",
        "task_id": "A10G_WINDOWS",
        "repository": "Ternedal/ModelRig",
        "base_sha": base_sha,
        "goal": "Prove one real Windows Tier-A command receipt.",
        "acceptance_criteria": [
            "The staged patch remains exact across the verified command."
        ],
        "risk": "low",
        "allowed_paths": ["baseline.txt"],
        "protected_paths": ["devcontrol/secrets/**"],
        "allowed_command_ids": [COMMAND_ID],
        "required_tests": [COMMAND_ID],
        "budget": {
            "max_changed_files": 10,
            "max_added_lines": 100,
            "max_deleted_lines": 100,
            "max_attempts": 2,
            "max_runtime_seconds": 120,
            "max_output_bytes": OUTPUT_BUDGET,
        },
        "merge_authority": "human",
    }
)
task_sha256 = hashlib.sha256(task.canonical_json().encode("utf-8")).hexdigest()
started = "2026-08-04T04:00:00Z"
completed = "2026-08-04T04:10:00Z"
probes = tuple(
    PhysicalProbeResult(
        name=name,
        passed=True,
        receipt_sha256=hashlib.sha256(
            ("slice10g:" + name.value).encode("utf-8")
        ).hexdigest(),
        detail=f"CI fixture for {name.value}",
        observed_at=completed,
    )
    for name in ProbeName
)
report = WindowsIsolationPhysicalReport(
    report_id="slice-10g-windows-command-receipt",
    task_id=task.task_id,
    task_sha256=task_sha256,
    repository=task.repository,
    base_sha=task.base_sha,
    catalog_sha256=catalog.sha256,
    toolchain_sha256=toolchain.sha256,
    rig_id="github-windows-server-2025",
    rig_fingerprint_sha256="1" * 64,
    candidate_version="slice-10g-ci",
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
signed_report = HmacIsolationReportSigner(
    REPORT_KEY_ID, REPORT_SECRET
).sign(report)
signed_report_path = (evidence_root / "signed-report.json").resolve()
signed_report_sha256 = write_signed_report(signed_report_path, signed_report)
attestation = IsolationAttestation(
    task_id=task.task_id,
    task_sha256=task_sha256,
    repository=task.repository,
    base_sha=task.base_sha,
    catalog_sha256=catalog.sha256,
    toolchain_sha256=toolchain.sha256,
    boundary=IsolationBoundary.OS_ISOLATED,
    network_mode=NetworkMode.DENY,
    evidence_sha256=(signed_report_sha256,),
)
physical_verifier = WindowsPhysicalIsolationVerifier(
    evidence_root.resolve(),
    {REPORT_KEY_ID: REPORT_SECRET},
    max_age=timedelta(days=366),
    now=lambda: datetime(2026, 8, 4, 4, 15, tzinfo=timezone.utc),
)
leased = LeasedCatalogMaterializer(
    catalog, physical_verifier
).materialize(task, toolchain, attestation)

closure_file = RuntimeClosureFile(
    relative_path="receipt-helper.exe",
    sha256=executable_sha256,
    size_bytes=len(executable_bytes),
)
manifest = RuntimeClosureManifest(
    task_id=task.task_id,
    task_sha256=task_sha256,
    repository=task.repository,
    base_sha=task.base_sha,
    command_id=COMMAND_ID,
    tool_id=TOOL_ID,
    catalog_sha256=catalog.sha256,
    toolchain_sha256=toolchain.sha256,
    lease_sha256=leased.lease.sha256,
    workspace_root_sha256=leased.lease.workspace_root_sha256,
    trusted_runtime_root_sha256=trusted_runtime_root_sha256(
        trusted_runtime_root
    ),
    entrypoint_relative_path="receipt-helper.exe",
    working_directory=".",
    files=(closure_file,),
    total_bytes=closure_file.size_bytes,
)
signed_closure = HmacRuntimeClosureSigner(
    CLOSURE_KEY_ID, CLOSURE_SECRET
).sign(manifest)
closure_verifier = RuntimeClosureVerifier(
    {CLOSURE_KEY_ID: CLOSURE_SECRET}
)

baseline.write_text("staged\n", encoding="utf-8")
run_git(git_runner, workspace, "add", "baseline.txt")
staged_status_before = run_git(git_runner, workspace, "status", "--short")
check(
    staged_status_before == "M  baseline.txt",
    "one exact staged patch exists before receipt execution",
)

receipt = run_single_verified_tier_a_command_with_receipt(
    task,
    catalog,
    toolchain,
    attestation,
    physical_verifier,
    git_runner=git_runner,
    signed_runtime_closure=signed_closure,
    runtime_closure_verifier=closure_verifier,
    trusted_runtime_root=trusted_runtime_root.resolve(),
    workspace_root=workspace.resolve(),
    control_plane_root=ROOT,
    source_env=dict(os.environ),
    process_memory_bytes=128 * 1024 * 1024,
    active_process_limit=1,
)
check(receipt.passed, "real Windows Tier-A execution produces a passing receipt")
check(
    receipt.git_runtime.runtime_manifest_sha256
    == git_runner.evidence().runtime_manifest_sha256,
    "receipt binds the complete staged Git runtime identity",
)
check(
    receipt.tier_a_result.returncode == 0
    and receipt.tier_a_result.output_truncated,
    "native output result remains bound and bounded inside the receipt",
)
check(
    receipt.workspace_before.staged_patch_bytes > 0
    and receipt.workspace_before.sha256 == receipt.workspace_after.sha256,
    "the exact staged Git patch is unchanged across the native command",
)
check(
    not receipt.workspace_reset_performed and receipt.workspace_reset is None,
    "an unchanged workspace is not reset",
)
check(
    run_git(git_runner, workspace, "status", "--short") == staged_status_before,
    "the staged patch remains present after receipt execution",
)
check(
    not (workspace / ".kaliv").exists(),
    "deterministic runtime staging is removed before the after snapshot",
)
reloaded = TierACommandReceipt.from_mapping(receipt.to_dict())
check(
    reloaded.canonical_json() == receipt.canonical_json()
    and reloaded.sha256 == receipt.sha256,
    "the complete native command receipt round-trips canonically",
)

print(f"\n===== WINDOWS TIER-A RECEIPT: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
