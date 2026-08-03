"""Contract and real-Windows proofs for the Tier-A AppContainer boundary.

The deterministic authority checks run on every platform. Native profile,
package-SID ACL, process creation and filesystem proofs run in Windows CI.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "worker"))

from app.windows_job import JobLimits, close_attached_job  # noqa: E402
from app.windows_restricted import (  # noqa: E402
    AppContainerProfile,
    RestrictedLaunchError,
    RestrictedLaunchPolicy,
    derive_profile_name,
    provision_workspace_acl,
    spawn_restricted_in_job,
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


def rejects(fn, text, message):
    try:
        fn()
    except RestrictedLaunchError as exc:
        check(text in str(exc), message)
    else:
        check(False, message)


def build_static_helper(workspace: str) -> str:
    """Build a statically linked fixture with the hosted MSVC toolchain."""

    root = Path(__file__).resolve().parents[2]
    source = root / "tests" / "support" / "windows_restricted_helper.c"
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
        cwd=root,
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

    output = Path(workspace) / "appcontainer-helper.exe"
    build_dir = Path(tempfile.mkdtemp(prefix="kaliv-appcontainer-build-"))
    script = build_dir / "build-helper.cmd"
    script.write_text(
        "@echo off\r\n"
        f'call "{devcmd}" -no_logo -arch=x64 -host_arch=x64\r\n'
        "if errorlevel 1 exit /b %errorlevel%\r\n"
        f'cl /nologo /O2 /MT /W4 /WX "{source}" '
        f'/Fe:"{output}" /link Advapi32.lib\r\n'
        "exit /b %errorlevel%\r\n",
        encoding="ascii",
    )
    built = subprocess.run(
        ["cmd.exe", "/d", "/c", str(script)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if built.returncode != 0 or not output.is_file():
        raise RuntimeError(
            "static Win32 helper build failed:\n"
            + (built.stdout + "\n" + built.stderr)[-1200:]
        )
    return str(output)


with tempfile.TemporaryDirectory(prefix="kaliv-appcontainer-policy-") as first:
    first_root = os.path.abspath(first)
    name_a = derive_profile_name(first_root)
    name_b = derive_profile_name(first_root)
    check(name_a == name_b, "AppContainer profile derivation is deterministic")
    check(
        name_a.startswith("Kaliv.ModelRig.") and len(name_a) <= 64,
        "profile moniker is valid and bounded",
    )
    policy = RestrictedLaunchPolicy(first_root)
    check(
        policy.profile_name == name_a,
        "policy binds the profile to the canonical root",
    )
    rejects(
        lambda: RestrictedLaunchPolicy(first_root, "Kaliv.ModelRig.unrelated"),
        "does not match",
        "a caller cannot substitute an unrelated AppContainer profile",
    )

rejects(
    lambda: RestrictedLaunchPolicy("relative/workspace"),
    "absolute",
    "relative roots fail closed",
)

if os.name != "nt":
    check(True, "native AppContainer proofs are reserved for Windows CI")
else:
    sandbox_parent = tempfile.mkdtemp(prefix="kaliv-appcontainer-parent-")
    workspace = os.path.join(sandbox_parent, "workspace")
    outside = os.path.join(sandbox_parent, "outside")
    os.mkdir(workspace)
    os.mkdir(outside)

    try:
        helper = build_static_helper(workspace)
    except RuntimeError as exc:
        check(False, f"static Win32 helper compiled ({exc})")
        raise SystemExit(1) from exc
    check(os.path.isfile(helper), "static Win32 helper compiled")

    inside_read = os.path.join(workspace, "inside-read.txt")
    outside_read = os.path.join(outside, "outside-read.txt")
    inside_write = os.path.join(workspace, "inside-write.txt")
    outside_write = os.path.join(outside, "outside-write.txt")
    result_path = os.path.join(workspace, "result.json")
    Path(inside_read).write_text("inside", encoding="utf-8")
    Path(outside_read).write_text("outside", encoding="utf-8")
    Path(result_path).write_text('{"sentinel":true}', encoding="utf-8")

    policy = RestrictedLaunchPolicy(workspace)
    profile = AppContainerProfile(policy)
    check(not profile.closed, "AppContainer profile and Package SID resolved")
    check(
        profile.sid_string.startswith("S-1-15-2-"),
        "profile exposes an AppContainer Package SID",
    )
    receipt = provision_workspace_acl(policy, profile)
    check(
        receipt.paths_updated >= 4,
        "Package SID ACL covers root, executable, input and receipt",
    )
    check(
        receipt.root == policy.workspace_root
        and receipt.profile_name == policy.profile_name
        and receipt.appcontainer_sid == profile.sid_string,
        "ACL receipt is bound to the exact root and profile",
    )
    check(
        receipt.capability_count == 0,
        "profile declares zero capabilities, including zero network capabilities",
    )

    # Controlled A/B: preserve the complete parent environment while changing
    # no token, SID, ACL, capability or Job Object property. The native helper
    # never reads or emits environment values. A green launch proves WinError
    # 203 came from a missing profile-initialization variable; the final code
    # will then replace this diagnostic inheritance with a strict allowlist.
    env = dict(os.environ)
    proc = spawn_restricted_in_job(
        [helper, inside_read, outside_read, inside_write, outside_write, result_path],
        env=env,
        limits=JobLimits(
            process_memory_bytes=128 * 1024 * 1024,
            active_process_limit=1,
        ),
        policy=policy,
        profile=profile,
        acl_receipt=receipt,
    )
    check(
        proc.profile_name == policy.profile_name,
        "child process remains bound to the expected profile",
    )
    exit_code = proc.wait(timeout=30)
    close_attached_job(proc)
    proc.close()

    result_exists = Path(result_path).is_file()
    result_text = (
        Path(result_path).read_text(encoding="utf-8") if result_exists else ""
    )
    try:
        payload = json.loads(result_text)
    except (TypeError, ValueError):
        payload = {}
    check(exit_code == 0, f"AppContainer child exits normally (exit={exit_code})")
    check(result_exists, "AppContainer receipt path still exists")
    check(
        payload.get("sentinel") is not True,
        f"AppContainer child replaced the provisioned receipt ({result_text[:120]!r})",
    )
    check(
        payload.get("appcontainer") is True,
        "child token is a real AppContainer token",
    )
    check(
        payload.get("lpac") is False,
        "boundary uses regular AppContainer system compatibility, not LPAC",
    )
    check(payload.get("inside_read") is True, "AppContainer child reads inside")
    check(
        payload.get("outside_read") is False,
        "AppContainer child is OS-denied reading outside",
    )
    check(payload.get("inside_write") is True, "AppContainer child writes inside")
    check(
        payload.get("outside_write") is False,
        "AppContainer child is OS-denied writing outside",
    )

    profile.delete()
    check(profile.deleted and profile.closed, "test AppContainer profile is deleted")

print(f"\n===== WINDOWS APPCONTAINER: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
