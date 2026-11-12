#!/usr/bin/env python3
"""A launcher whose pinned branch is gone stops with an instruction, before any fetch.

#2371 K1 / #2275 item 22: nine root launchers pin `agent/...` branches that no longer
exist. They stopped fail-closed at `git fetch`, but the operator saw only a raw git
error. `require_remote_branch` asks origin first: exit 2 from `ls-remote --exit-code`
(origin answered: no such branch) raises a WizardError that says what to use instead;
any other failure is left to the fetch, which already stops the wizard.

Behavioural: the real `ensure_candidate` from the shim, with git, the OS check and PATH
faked, so it runs on Linux and reaches nothing.

Run: python3 tests/workflow_stage_a_dead_pin.py
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import re
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "support"))
from source_code import code_of  # noqa: E402

spec = importlib.util.spec_from_file_location("stage_a_dead_pin_probe", ROOT / "scripts" / "stage_a_one_click.py")
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)

passed = failed = 0


def check(ok: bool, label: str) -> None:
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"FAIL: {label}")


class _StopAtFetch(Exception):
    pass


def run_ensure(branch: str, ls_remote, status: str = "") -> tuple[str | None, list[tuple[str, ...]]]:
    """Run the real ensure_candidate up to the fetch; return (error text, git calls)."""
    calls: list[tuple[str, ...]] = []

    def fake_git(*args: str) -> str:
        calls.append(args)
        if args[0] == "fetch":
            raise _StopAtFetch()
        return status if args[0] == "status" else ""

    def fake_run(args, **kwargs):
        if args[:2] == ["git", "ls-remote"]:
            calls.append(tuple(args[1:]))
            return ls_remote(args)
        raise AssertionError(f"unexpected subprocess: {args}")

    saved = {name: getattr(stage, name) for name in ("git", "os", "shutil", "subprocess", "BRANCH")}
    stage.git = fake_git
    stage.os = types.SimpleNamespace(name="nt", environ=os.environ)
    stage.shutil = types.SimpleNamespace(which=lambda command: f"C:/bin/{command}")
    stage.subprocess = types.SimpleNamespace(run=fake_run, TimeoutExpired=subprocess.TimeoutExpired)
    stage.BRANCH = branch
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            stage.ensure_candidate()
        return "no stop", calls
    except _StopAtFetch:
        return None, calls
    except stage.WizardError as exc:
        return str(exc), calls
    finally:
        for name, value in saved.items():
            setattr(stage, name, value)


def answer(code: int):
    return lambda args: subprocess.CompletedProcess(args, code, "", "")


def raising(args):
    raise OSError("git missing")


fetched = lambda calls: any(c[0] == "fetch" for c in calls)  # noqa: E731

# A branch that is gone: an instruction, and no fetch, switch or pull.
for branch, needle in (
    ("agent/t022-write-pilot-collector", "T-022 har ingen aktuel wrapper"),
    ("agent/t023-termination-physical-operator", "START_PROOF_CAMPAIGN.cmd"),
    ("agent/t033-memory-protected-backup-physical-operator", "START_PROOF_CAMPAIGN.cmd"),
    ("agent/milestone3-current-main-v2", "PR #250"),
    ("agent/something-else", "Launcheren er forældet"),
):
    error, calls = run_ensure(branch, answer(2))
    check(error is not None and needle in error and branch in error, f"{branch}: instruction ({error!r})")
    check(not fetched(calls), f"{branch}: stops before any fetch")

# Every other outcome changes nothing: the fetch runs, exactly as before.
for label, ls_remote in (("branch exists", answer(0)), ("network/auth failure", answer(128)),
                         ("git cannot start", raising)):
    error, calls = run_ensure("physical-proof/2.0.19", ls_remote)
    check(error is None and fetched(calls), f"{label}: falls through to the existing fetch ({error!r})")

# A dirty tree still stops first, before origin is even asked.
error, calls = run_ensure("agent/t022-write-pilot-collector", answer(2), status=" M x")
check(error is not None and "Working tree er ikke ren" in error, f"dirty tree stops first ({error!r})")
check(not any(c[0] == "ls-remote" for c in calls), "a dirty tree never reaches origin")

# Every pinned agent/ branch in the scripts gets a specific message, not the generic one.
pins = set()
for path in sorted((ROOT / "scripts").glob("*.py")):
    pins |= set(re.findall(r'^BRANCH\s*=\s*"(agent/[^"]+)"', code_of(path), re.MULTILINE))
check(len(pins) >= 8, f"the pinned agent/ branches are found ({len(pins)})")
for pin in sorted(pins):
    error, _ = run_ensure(pin, answer(2))
    check(error is not None and "Launcheren er forældet" not in error, f"{pin}: has a specific instruction")

print(f"\n===== STAGE A DEAD PIN: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
