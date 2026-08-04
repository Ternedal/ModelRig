"""End-to-end signed evidence -> immutable closure -> captured Tier-A proof.

A statically linked helper and one support file begin only in a separate operator
runtime root. The public runtime verifies a command-specific signed exact-file
manifest, stages the closure, lifetime-locks it, binds an exact cwd, and enters
the existing AppContainer + Job Object + bounded-output path. No network is used.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import threading
import time
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
from kaliv_dev_control.tier_a_execution import (  # noqa: E402
    HmacRuntimeClosureSigner,
    LeasedCatalogMaterializer,
    RuntimeClosureFile,
    RuntimeClosureManifest,
    RuntimeClosureVerifier,
    TIER_A_APPLICATION_ENVIRONMENT,
    TierAExecutionTimeout,
    TrustedRuntimeClosureStager,
    build_tier_a_launch_plan,
    run_verified_tier_a_command,
    tier_a_toolhost_sha256,
    trusted_runtime_root_sha256,
    working_directory_authority_sha256,
    workspace_root_authority_sha256,
)

passed = failed = 0
BURST_COMMAND = "modelrig.tier-a.capture-burst"
CWD_COMMAND = "modelrig.tier-a.cwd-probe"
MUTATE_COMMAND = "modelrig.tier-a.runtime-mutation-probe"
HOLD_COMMAND = "modelrig.tier-a.runtime-host-sabotage"
TIMEOUT_COMMAND = "modelrig.tier-a.capture-timeout"
OUTPUT_BUDGET = 4096
CHUNK_BYTES = 4096
CHUNK_COUNT = 64
EXPECTED_STDOUT = b"STDOUT-BEGIN\n" + (b"A" * CHUNK_BYTES * CHUNK_COUNT)
EXPECTED_STDERR = b"STDERR-BEGIN\n" + (b"B" * CHUNK_BYTES * CHUNK_COUNT)
TIMEOUT_MARKER = b"BEFORE-TIMEOUT\n"
IMMUTABLE_MARKER = b"RUNTIME-IMMUTABLE\n"
GUARD_READY_MARKER = b"GUARD-READY\n"
CLOSURE_KEY_ID = "slice-10f-runtime-key"
CLOSURE_SECRET = b"slice-10f-runtime-closure-secret-01"


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


def closure_file(root: Path, relative: str) -> RuntimeClosureFile:
    payload = root.joinpath(*Path(relative).parts).read_bytes()
    return RuntimeClosureFile(
        relative_path=relative,
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )


def staged_root_for(closure) -> Path:
    return (
        workspace
        / ".kaliv"
        / "runtime-closures"
        / "capture-helper"
        / closure.manifest.sha256
    )


base_sha = "a" * 40
started = "2026-08-04T00:00:00Z"
completed = "2026-08-04T00:10:00Z"
secret = b"slice-10f-windows-test-secret-01"
key_id = "slice-10f-windows-test-key"

parent = Path(tempfile.mkdtemp(prefix="kaliv-tier-a-closure-"))
trusted_runtime_root = parent / "trusted-runtime"
workspace = parent / "workspace"
evidence_root = parent / "evidence"
(trusted_runtime_root / "support").mkdir(parents=True)
(workspace / "backend").mkdir(parents=True)
evidence_root.mkdir()
source_executable = build_static_capture_helper(
    trusted_runtime_root / "capture-helper.exe"
)
support_file = trusted_runtime_root / "support" / "runtime.dat"
support_file.write_bytes(b"exact signed runtime support file\n")
executable_hash = hashlib.sha256(source_executable.read_bytes()).hexdigest()
check(
    source_executable.is_file(),
    "exact static helper is held in the separate operator runtime root",
)
check(
    support_file.is_file(),
    "runtime closure contains a second exact non-entrypoint file",
)
check(
    not any(path.is_file() for path in workspace.rglob("*")),
    "signed workspace starts without a caller-prestaged runtime file",
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
            CWD_COMMAND,
            "capture-helper",
            ("cwd",),
            "backend",
            30,
            catalog_env,
        ),
        ProjectCommandSpec(
            MUTATE_COMMAND,
            "capture-helper",
            ("mutate",),
            ".",
            30,
            catalog_env,
        ),
        ProjectCommandSpec(
            HOLD_COMMAND,
            "capture-helper",
            ("hold",),
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
all_commands = (
    BURST_COMMAND,
    CWD_COMMAND,
    MUTATE_COMMAND,
    HOLD_COMMAND,
    TIMEOUT_COMMAND,
)
task = DevelopmentTask.from_mapping(
    {
        "schema": "kaliv-development-task/v1",
        "task_id": "A10F_WINDOWS",
        "repository": "Ternedal/ModelRig",
        "base_sha": base_sha,
        "goal": "Prove exact runtime closure and lifetime immutability.",
        "acceptance_criteria": [
            "Only signed runtime files launch.",
            "The nested working directory reaches CreateProcessW exactly.",
            "AppContainer and host mutation fail while the Job Object lives.",
            "Both streams remain bounded and timeout cleanup reaches EOF.",
        ],
        "risk": "low",
        "allowed_paths": ["devcontrol/**"],
        "protected_paths": ["devcontrol/secrets/**"],
        "allowed_command_ids": list(all_commands),
        "required_tests": list(all_commands),
        "budget": {
            "max_changed_files": 30,
            "max_added_lines": 8000,
            "max_deleted_lines": 8000,
            "max_attempts": 3,
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
            ("slice10f:" + name.value).encode("utf-8")
        ).hexdigest(),
        detail=f"CI fixture for {name.value}",
        observed_at=completed,
    )
    for name in ProbeName
)
report = WindowsIsolationPhysicalReport(
    report_id="slice-10f-windows-kernel-proof",
    task_id=task.task_id,
    task_sha256=task_sha,
    repository=task.repository,
    base_sha=task.base_sha,
    catalog_sha256=catalog.sha256,
    toolchain_sha256=toolchain.sha256,
    rig_id="github-windows-server-2025",
    rig_fingerprint_sha256="1" * 64,
    candidate_version="slice-10f-ci",
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
    now=lambda: datetime(2026, 8, 4, 0, 15, tzinfo=timezone.utc),
)
leased = LeasedCatalogMaterializer(catalog, verifier).materialize(
    task, toolchain, attestation
)
closure_verifier = RuntimeClosureVerifier({CLOSURE_KEY_ID: CLOSURE_SECRET})
closure_entries = tuple(
    sorted(
        (
            closure_file(trusted_runtime_root, "capture-helper.exe"),
            closure_file(trusted_runtime_root, "support/runtime.dat"),
        ),
        key=lambda item: item.relative_path,
    )
)


def command_closure(command_id: str):
    template = leased.resolve(task, command_id)
    manifest = RuntimeClosureManifest(
        task_id=task.task_id,
        task_sha256=task_sha,
        repository=task.repository,
        base_sha=task.base_sha,
        command_id=command_id,
        tool_id="capture-helper",
        catalog_sha256=catalog.sha256,
        toolchain_sha256=toolchain.sha256,
        lease_sha256=leased.lease.sha256,
        workspace_root_sha256=leased.lease.workspace_root_sha256,
        trusted_runtime_root_sha256=trusted_runtime_root_sha256(
            trusted_runtime_root
        ),
        entrypoint_relative_path="capture-helper.exe",
        working_directory=template.cwd,
        files=closure_entries,
        total_bytes=sum(item.size_bytes for item in closure_entries),
    )
    return HmacRuntimeClosureSigner(CLOSURE_KEY_ID, CLOSURE_SECRET).sign(manifest)


burst_closure = command_closure(BURST_COMMAND)
cwd_closure = command_closure(CWD_COMMAND)
mutate_closure = command_closure(MUTATE_COMMAND)
hold_closure = command_closure(HOLD_COMMAND)
timeout_closure = command_closure(TIMEOUT_COMMAND)
check(
    burst_closure.manifest.files == cwd_closure.manifest.files,
    "distinct commands bind the same exact file closure independently",
)
check(
    burst_closure.sha256 != cwd_closure.sha256,
    "command and working-directory authority change the signed closure identity",
)

stager = TrustedRuntimeClosureStager(
    trusted_runtime_root.resolve(), workspace.resolve()
)
staging_receipt = stager.stage(
    burst_closure,
    closure_verifier,
    leased,
    task,
    BURST_COMMAND,
)
staged_leased = stager.bind_for_launch(
    staging_receipt,
    burst_closure,
    closure_verifier,
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
    runtime_closure_receipt=staging_receipt,
)
check(plan.runtime_closure_verified, "launch plan binds a verified closure")
check(
    plan.runtime_closure_sha256 == burst_closure.manifest.sha256
    and plan.signed_runtime_closure_sha256 == burst_closure.sha256
    and plan.runtime_closure_staging_receipt_sha256 == staging_receipt.sha256,
    "launch plan retains manifest, signature and staging identities",
)
check(
    plan.signed_report_sha256 == signed_hash
    and plan.lease_sha256 == leased.lease.sha256,
    "launch plan retains exact report and lease hashes",
)
check(
    plan.max_output_bytes == OUTPUT_BUDGET,
    "launch plan binds the signed output budget",
)
check(
    Path(plan.argv[0]).is_relative_to(workspace.resolve()),
    "launch executable is the verified workspace copy",
)
check(
    dict(WINDOWS_TIER_A_APPLICATION_ENVIRONMENT)
    == dict(TIER_A_APPLICATION_ENVIRONMENT),
    "catalog and worker agree on the reviewed environment",
)
filtered = appcontainer_environment(dict(os.environ), application_env=catalog_env)
check(filtered["CI"] == "1", "reviewed catalog environment reaches Tier-A")
check(
    "GITHUB_TOKEN" not in filtered and "ACTIONS_RUNTIME_TOKEN" not in filtered,
    "parent credentials remain excluded",
)

common_run = {
    "trusted_runtime_root": trusted_runtime_root.resolve(),
    "workspace_root": workspace.resolve(),
    "control_plane_root": ROOT,
    "source_env": dict(os.environ),
    "process_memory_bytes": 128 * 1024 * 1024,
    "active_process_limit": 1,
}

burst_result = run_verified_tier_a_command(
    task,
    catalog,
    toolchain,
    attestation,
    verifier,
    BURST_COMMAND,
    signed_runtime_closure=burst_closure,
    runtime_closure_verifier=closure_verifier,
    **common_run,
)
check(
    burst_result.returncode == 0 and burst_result.passed,
    "closure burst exits through Tier-A",
)
check(
    burst_result.stdout.total_bytes == len(EXPECTED_STDOUT)
    and burst_result.stderr.total_bytes == len(EXPECTED_STDERR),
    "both streams drain beyond pipe-buffer size",
)
check(
    burst_result.stdout.sha256 == hashlib.sha256(EXPECTED_STDOUT).hexdigest()
    and burst_result.stderr.sha256 == hashlib.sha256(EXPECTED_STDERR).hexdigest(),
    "full output streams receive deterministic hashes",
)
check(
    burst_result.stdout.captured == EXPECTED_STDOUT[: OUTPUT_BUDGET // 2]
    and burst_result.stderr.captured == EXPECTED_STDERR[: OUTPUT_BUDGET // 2],
    "only deterministic prefixes are retained",
)
check(
    burst_result.captured_output_bytes == OUTPUT_BUDGET
    and burst_result.output_truncated,
    "retained output never exceeds the task budget",
)

cwd_result = run_verified_tier_a_command(
    task,
    catalog,
    toolchain,
    attestation,
    verifier,
    CWD_COMMAND,
    signed_runtime_closure=cwd_closure,
    runtime_closure_verifier=closure_verifier,
    **common_run,
)
expected_cwd = (workspace / "backend").resolve()
observed_cwd = Path(cwd_result.stdout.captured.decode("utf-8"))
check(
    cwd_result.passed and cwd_result.stderr.total_bytes == 0,
    "nested cwd probe exits cleanly",
)
check(
    os.path.normcase(os.fspath(observed_cwd))
    == os.path.normcase(os.fspath(expected_cwd)),
    "CreateProcessW receives the reviewed nested cwd",
)
check(
    working_directory_authority_sha256(workspace, "backend")
    != working_directory_authority_sha256(workspace, "."),
    "nested and root cwd identities differ",
)

mutate_result = run_verified_tier_a_command(
    task,
    catalog,
    toolchain,
    attestation,
    verifier,
    MUTATE_COMMAND,
    signed_runtime_closure=mutate_closure,
    runtime_closure_verifier=closure_verifier,
    **common_run,
)
check(
    mutate_result.passed
    and mutate_result.stdout.captured == IMMUTABLE_MARKER
    and mutate_result.stderr.total_bytes == 0,
    "AppContainer cannot overwrite, delete, rename or extend its runtime closure",
)
mutate_root = staged_root_for(mutate_closure)
check(
    hashlib.sha256((mutate_root / "capture-helper.exe").read_bytes()).hexdigest()
    == executable_hash
    and (mutate_root / "support" / "runtime.dat").read_bytes()
    == support_file.read_bytes(),
    "child sabotage leaves every staged byte unchanged",
)

hold_root = staged_root_for(hold_closure)
hold_support = hold_root / "support" / "runtime.dat"
hold_executable = hold_root / "capture-helper.exe"
hold_renamed = hold_root / "support" / "runtime-renamed.dat"
hold_injected = hold_root / "support" / "host-injected.dll"
ready_marker = workspace / "guard-ready.txt"
attack_results: dict[str, bool] = {}


def expect_blocked(name: str, action, cleanup=None) -> None:
    try:
        action()
    except OSError:
        attack_results[name] = True
    else:
        attack_results[name] = False
        if cleanup is not None:
            cleanup()


def host_sabotage() -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not ready_marker.exists():
        time.sleep(0.02)
    attack_results["marker"] = ready_marker.exists()
    if not attack_results["marker"]:
        return
    expect_blocked(
        "overwrite_executable",
        lambda: hold_executable.write_bytes(b"host tamper"),
    )
    expect_blocked(
        "overwrite_support",
        lambda: hold_support.write_bytes(b"host tamper"),
    )
    expect_blocked(
        "delete_support",
        hold_support.unlink,
    )
    expect_blocked(
        "rename_support",
        lambda: os.replace(hold_support, hold_renamed),
        lambda: os.replace(hold_renamed, hold_support),
    )
    expect_blocked(
        "insert_file",
        lambda: hold_injected.write_bytes(b"host injection"),
        lambda: hold_injected.unlink(missing_ok=True),
    )


attack_thread = threading.Thread(target=host_sabotage, daemon=False)
attack_thread.start()
hold_result = run_verified_tier_a_command(
    task,
    catalog,
    toolchain,
    attestation,
    verifier,
    HOLD_COMMAND,
    signed_runtime_closure=hold_closure,
    runtime_closure_verifier=closure_verifier,
    **common_run,
)
attack_thread.join(timeout=20)
check(not attack_thread.is_alive(), "host sabotage thread reaches a result")
check(
    hold_result.passed
    and hold_result.stdout.captured == GUARD_READY_MARKER
    and hold_result.stderr.total_bytes == 0,
    "guard remains active while the Job Object command is alive",
)
check(
    attack_results
    == {
        "marker": True,
        "overwrite_executable": True,
        "overwrite_support": True,
        "delete_support": True,
        "rename_support": True,
        "insert_file": True,
    },
    "concurrent host overwrite, delete, rename and insertion are denied",
)
check(
    hashlib.sha256(hold_executable.read_bytes()).hexdigest() == executable_hash
    and hold_support.read_bytes() == support_file.read_bytes()
    and not hold_renamed.exists()
    and not hold_injected.exists(),
    "host sabotage leaves the lifetime-locked tree exact",
)
post_guard = hold_root / "support" / "post-guard.tmp"
try:
    post_guard.write_bytes(b"restored")
    restored = post_guard.read_bytes() == b"restored"
finally:
    post_guard.unlink(missing_ok=True)
check(restored, "original DACL is restored only after Job Object completion")

try:
    run_verified_tier_a_command(
        task,
        catalog,
        toolchain,
        attestation,
        verifier,
        TIMEOUT_COMMAND,
        signed_runtime_closure=timeout_closure,
        runtime_closure_verifier=closure_verifier,
        **common_run,
    )
except TierAExecutionTimeout as exc:
    timeout_result = exc.result
    check(True, "timeout is surfaced as typed execution evidence")
    check(
        timeout_result.timed_out and not timeout_result.passed,
        "timeout can never claim success",
    )
    check(
        timeout_result.stdout.captured == TIMEOUT_MARKER
        and timeout_result.stdout.sha256
        == hashlib.sha256(TIMEOUT_MARKER).hexdigest(),
        "pre-timeout output is preserved and hashed",
    )
    check(
        timeout_result.stderr.total_bytes == 0
        and not timeout_result.output_truncated,
        "timeout cleanup reaches EOF on both streams",
    )
    check(
        timeout_result.duration_ms >= 900,
        "timeout records the enforced wall-clock boundary",
    )
except Exception as exc:
    check(False, f"timeout produced the wrong failure type: {exc!r}")
else:
    check(False, "sleeping helper was not terminated")

print(f"\n===== WINDOWS CATALOG TIER-A: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
