from __future__ import annotations

import os
import tempfile

from app.agent3.core import AgentRunStore
from app.agent3.runtime_restore_guard import (
    acquire_agent3_restore_lease,
    agent3_restore_guard,
)

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


with tempfile.TemporaryDirectory(prefix="agent3-restore-guard-") as root:
    run_path = os.path.join(root, "agent3-runs.db")

    # A live runtime owns shared authority. Restore must fail before it can make
    # its durable marker or touch a live destination.
    runtime = AgentRunStore(run_path)
    try:
        acquire_agent3_restore_lease(run_path)
        check(False, "live runtime blocks exclusive restore authority")
    except RuntimeError as exc:
        check(
            "runtime is active" in str(exc),
            "live runtime blocks exclusive restore authority",
        )
    finally:
        runtime.close()

    # Once the runtime releases its lease, restore can enter. While EXCLUSIVE is
    # held, fresh runtime startup must fail closed on both POSIX and Windows.
    with agent3_restore_guard(run_path):
        try:
            AgentRunStore(run_path)
            check(False, "active restore blocks fresh runtime startup")
        except RuntimeError as exc:
            check(
                "restore is in progress" in str(exc),
                "active restore blocks fresh runtime startup",
            )

    after_success = AgentRunStore(run_path)
    after_success.close()
    check(True, "successful restore clears startup guard")

    # A failed restore leaves restore_in_progress durably set after the EXCLUSIVE
    # transaction rolls back. Starting Agent3 is forbidden until a complete retry
    # reaches the context manager's successful exit.
    try:
        with agent3_restore_guard(run_path):
            raise OSError("injected restore failure")
    except OSError:
        check(True, "injected restore failure propagates")

    try:
        AgentRunStore(run_path)
        check(False, "failed restore leaves durable startup blocker")
    except RuntimeError as exc:
        check(
            "restore is incomplete" in str(exc),
            "failed restore leaves durable startup blocker",
        )

    with agent3_restore_guard(run_path):
        pass
    repaired = AgentRunStore(run_path)
    repaired.close()
    check(True, "complete retry clears durable failed-restore blocker")

    # Multiple runtimes can coexist under shared read leases; restore remains
    # excluded until the final runtime releases authority.
    first = AgentRunStore(run_path)
    second = AgentRunStore(run_path)
    try:
        try:
            acquire_agent3_restore_lease(run_path)
            check(False, "two shared runtime leases exclude restore")
        except RuntimeError:
            check(True, "two shared runtime leases exclude restore")
        first.close()
        try:
            acquire_agent3_restore_lease(run_path)
            check(False, "one remaining runtime lease still excludes restore")
        except RuntimeError:
            check(True, "one remaining runtime lease still excludes restore")
    finally:
        first.close()
        second.close()

    with agent3_restore_guard(run_path):
        pass
    check(True, "restore authority succeeds after final runtime lease closes")

print(f"\n===== AGENT3 RESTORE GUARD: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
