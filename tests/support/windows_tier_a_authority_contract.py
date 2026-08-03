"""Authority and positive-runtime contract for the dormant Tier-A launcher.

This suite closes two false-positive paths:

* the negative loopback probe is meaningful only if the same copied curl.exe
  can actually start inside the AppContainer;
* runtime code must not bypass the credential-filtering Tier-A wrapper and call
  the low-level AppContainer launch primitive directly.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "worker"))

from app.windows_job import JobLimits, close_attached_job  # noqa: E402
from app.windows_restricted import (  # noqa: E402
    AppContainerProfile,
    RestrictedLaunchPolicy,
    provision_workspace_acl,
)
from app.windows_tier_a import spawn_tier_a_in_job  # noqa: E402

passed = failed = 0


def check(condition, message):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


# The low-level function accepts an already-filtered environment because it is
# also the Win32 ABI seam. Only the authoritative wrapper may import/call it.
root = Path(__file__).resolve().parents[2]
offenders = []
for source in sorted((root / "worker" / "app").glob("*.py")):
    if source.name in {"windows_restricted.py", "windows_tier_a.py"}:
        continue
    text = source.read_text(encoding="utf-8", errors="replace")
    if "spawn_restricted_in_job" in text:
        offenders.append(source.relative_to(root).as_posix())
check(
    not offenders,
    "no runtime module bypasses the authoritative Tier-A environment wrapper"
    if not offenders
    else "low-level AppContainer launcher bypassed by: " + ", ".join(offenders),
)

if os.name != "nt":
    check(True, "positive AppContainer runtime proof is reserved for Windows CI")
else:
    workspace = tempfile.mkdtemp(prefix="kaliv-tier-a-runtime-")
    system_curl = shutil.which("curl.exe")
    if not system_curl or not os.path.isfile(system_curl):
        check(False, "Windows curl.exe is available")
        raise SystemExit(1)
    curl = os.path.join(workspace, "curl.exe")
    shutil.copy2(system_curl, curl)

    policy = RestrictedLaunchPolicy(workspace)
    profile = AppContainerProfile(policy)
    try:
        receipt = provision_workspace_acl(policy, profile)
        proc = spawn_tier_a_in_job(
            [curl, "--version"],
            source_env=dict(os.environ),
            limits=JobLimits(
                process_memory_bytes=128 * 1024 * 1024,
                active_process_limit=1,
            ),
            policy=policy,
            profile=profile,
            acl_receipt=receipt,
        )
        exit_code = proc.wait(timeout=20)
        close_attached_job(proc)
        proc.close()
        check(
            exit_code == 0,
            f"the exact copied curl executable starts inside AppContainer (exit={exit_code})",
        )
    finally:
        profile.delete()
    check(profile.deleted and profile.closed, "positive-control profile is deleted")

print(f"\n===== WINDOWS TIER-A AUTHORITY: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
