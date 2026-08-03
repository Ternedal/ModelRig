"""Contract and real-Windows proofs for restricted token + workspace SID.

The deterministic policy checks run on every platform. Native ACL, token,
private-desktop and CreateProcessAsUser proofs run in the Windows gate.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "worker"))

from app.windows_job import JobLimits, close_attached_job  # noqa: E402
from app.windows_restricted import (  # noqa: E402
    RESTRICTED_CODE_SID,
    RestrictedLaunchError,
    RestrictedLaunchPolicy,
    RestrictedToken,
    derive_workspace_sid,
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


with tempfile.TemporaryDirectory(prefix="kaliv-sid-contract-") as first:
    first_root = os.path.abspath(first)
    sid_a = derive_workspace_sid(first_root)
    sid_b = derive_workspace_sid(first_root)
    check(sid_a == sid_b, "workspace SID derivation is deterministic")
    check(sid_a.startswith("S-1-5-21-"), "workspace authority is a valid private SID shape")
    policy = RestrictedLaunchPolicy(first_root)
    check(policy.workspace_sid == sid_a, "policy binds the SID to the canonical root")
    check(
        policy.restricting_sids == (RESTRICTED_CODE_SID, sid_a),
        "policy combines Restricted Code with the dedicated workspace SID",
    )
    rejects(
        lambda: RestrictedLaunchPolicy(first_root, "S-1-5-21-1-2-3-4"),
        "does not match",
        "a caller cannot substitute a broader or unrelated SID",
    )

rejects(
    lambda: RestrictedLaunchPolicy("relative/workspace"),
    "absolute",
    "relative roots fail closed",
)

if os.name != "nt":
    check(True, "native restricted-token proofs are reserved for Windows CI")
else:
    helper_source = os.environ.get("KALIV_RESTRICTED_HELPER", "")
    check(bool(helper_source) and os.path.isfile(helper_source), "native helper was built")

    sandbox_parent = tempfile.mkdtemp(prefix="kaliv-restricted-parent-")
    workspace = os.path.join(sandbox_parent, "workspace")
    outside = os.path.join(sandbox_parent, "outside")
    os.mkdir(workspace)
    os.mkdir(outside)

    helper = os.path.join(workspace, "restricted-helper.exe")
    shutil.copy2(helper_source, helper)
    inside_read = os.path.join(workspace, "inside-read.txt")
    outside_read = os.path.join(outside, "outside-read.txt")
    inside_write = os.path.join(workspace, "inside-write.txt")
    outside_write = os.path.join(outside, "outside-write.txt")
    result_path = os.path.join(workspace, "result.json")
    Path(inside_read).write_text("inside", encoding="utf-8")
    Path(outside_read).write_text("outside", encoding="utf-8")
    Path(result_path).write_text('{"sentinel":true}', encoding="utf-8")

    receipt = provision_workspace_acl(workspace)
    policy = RestrictedLaunchPolicy(workspace, receipt.workspace_sid)
    check(receipt.paths_updated >= 4, "ACL provisioning covered root, executable, input and receipt")
    check(receipt.root == policy.workspace_root, "ACL receipt and launch policy share one canonical root")

    with RestrictedToken(policy) as token:
        check(not token.closed, "restricted primary token was created")
        with token.impersonate():
            check(
                Path(inside_read).read_text(encoding="utf-8") == "inside",
                "restricted thread can read inside the provisioned workspace",
            )
            try:
                Path(outside_read).read_text(encoding="utf-8")
            except OSError:
                outside_read_denied = True
            else:
                outside_read_denied = False
            check(outside_read_denied, "restricted thread is OS-denied outside the workspace")
            Path(inside_write).write_text("inside-write", encoding="utf-8")
            check(os.path.isfile(inside_write), "restricted thread can write inside workspace")
            try:
                Path(outside_write).write_text("outside-write", encoding="utf-8")
            except OSError:
                outside_write_denied = True
            else:
                outside_write_denied = False
            check(outside_write_denied, "restricted thread cannot write outside workspace")

    env = {
        key: value
        for key, value in os.environ.items()
        if key in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH"}
    }
    proc = spawn_restricted_in_job(
        [helper, inside_read, outside_read, inside_write, outside_write, result_path],
        env=env,
        # Diagnostic matrix: the private desktop is present, but Job Object UI
        # restrictions are temporarily absent. This isolates whether the
        # desktop UI bit blocks loader attachment after assignment.
        limits=JobLimits(
            process_memory_bytes=128 * 1024 * 1024,
            active_process_limit=1,
            ui_restrictions=0,
        ),
        policy=policy,
    )
    private_desktop = getattr(proc, "_desktop_lease", None)
    check(
        private_desktop is not None and "\\KalivRestricted-" in private_desktop.full_name,
        "restricted child is bound to a private non-default desktop",
    )
    exit_code = proc.wait(timeout=30)
    close_attached_job(proc)
    proc.close()
    check(
        private_desktop is not None and private_desktop.closed,
        "private desktop and temporary DACL grants are restored after exit",
    )
    result_exists = Path(result_path).is_file()
    result_text = Path(result_path).read_text(encoding="utf-8") if result_exists else ""
    try:
        payload = json.loads(result_text)
    except (TypeError, ValueError):
        payload = {}
    check(exit_code == 0, f"restricted child exits normally (exit={exit_code})")
    check(result_exists, "restricted child receipt path still exists")
    check(
        payload.get("sentinel") is not True,
        f"restricted child replaced the provisioned receipt ({result_text[:120]!r})",
    )
    check(payload.get("restricted") is True, "child sees a real restricted primary token")
    check(payload.get("inside_read") is True, "restricted child reads inside")
    check(payload.get("outside_read") is False, "restricted child cannot read outside")
    check(payload.get("inside_write") is True, "restricted child writes inside")
    check(payload.get("outside_write") is False, "restricted child cannot write outside")
    check(not payload.get("error"), "native launch completed without hidden errors")

print(f"\n===== WINDOWS RESTRICTED TOKEN: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
