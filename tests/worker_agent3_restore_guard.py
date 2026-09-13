from __future__ import annotations

import os
import tempfile

from app.agent3.core import AgentRunStore
from app.agent3.runtime_restore_guard import (
    acquire_agent3_restore_lease,
    agent3_maintenance_guard,
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

    # A live runtime owns shared authority. Restore and maintenance must both
    # fail before either transition can touch persistent Agent3 authority.
    runtime = AgentRunStore(run_path)
    try:
        try:
            acquire_agent3_restore_lease(run_path)
            check(False, "live runtime blocks exclusive restore authority")
        except RuntimeError as exc:
            check(
                "runtime" in str(exc) and "active" in str(exc),
                "live runtime blocks exclusive restore authority",
            )
        try:
            with agent3_maintenance_guard(run_path):
                pass
            check(False, "live runtime blocks exclusive maintenance authority")
        except RuntimeError as exc:
            check(
                "runtime is active" in str(exc),
                "live runtime blocks exclusive maintenance authority",
            )
    finally:
        runtime.close()

    # Maintenance is atomic and needs exclusion, not a durable restore marker.
    # While it owns EXCLUSIVE authority, fresh runtime startup is rejected.
    with agent3_maintenance_guard(run_path):
        try:
            AgentRunStore(run_path)
            check(False, "active maintenance blocks fresh runtime startup")
        except RuntimeError as exc:
            check(
                "maintenance is in progress" in str(exc),
                "active maintenance blocks fresh runtime startup",
            )

    # A failed maintenance transaction simply rolls back and releases exclusion;
    # unlike a partial restore it must not leave the durable restore blocker set.
    try:
        with agent3_maintenance_guard(run_path):
            raise OSError("injected maintenance failure")
    except OSError:
        check(True, "injected maintenance failure propagates")
    after_maintenance_failure = AgentRunStore(run_path)
    after_maintenance_failure.close()
    check(True, "failed maintenance does not manufacture restore-incomplete state")

    # Once the runtime releases its lease, restore can enter. While EXCLUSIVE is
    # held, fresh runtime startup cannot inspect enough guard state to distinguish
    # restore from maintenance on every SQLite/platform combination; the public
    # contract is therefore the deliberately generic exclusive-boundary blocker.
    with agent3_restore_guard(run_path):
        try:
            AgentRunStore(run_path)
            check(False, "active restore blocks fresh runtime startup")
        except RuntimeError as exc:
            check(
                "restore or maintenance is in progress" in str(exc),
                "active restore blocks fresh runtime startup",
            )

    after_success = AgentRunStore(run_path)
    after_success.close()
    check(True, "successful restore clears startup guard")

    # A failed restore leaves restore_in_progress durably set after the EXCLUSIVE
    # transaction rolls back. Starting Agent3 and entering unrelated maintenance
    # are forbidden until a complete retry reaches successful exit.
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

    try:
        with agent3_maintenance_guard(run_path):
            pass
        check(False, "incomplete restore blocks maintenance adoption boundary")
    except RuntimeError as exc:
        check(
            "restore is incomplete" in str(exc),
            "incomplete restore blocks maintenance adoption boundary",
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
