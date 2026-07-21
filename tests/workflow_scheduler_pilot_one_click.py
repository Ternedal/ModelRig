#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "worker"))
passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


wizard_path = ROOT / "scripts" / "scheduler_pilot_one_click.py"
easy_path = ROOT / "scripts" / "scheduler_pilot_easy_entry.py"
gate_path = ROOT / "scripts" / "scheduler_pilot_android_gate.py"
stack_path = ROOT / "scripts" / "start-stage-a-validation-stack.ps1"
control_path = ROOT / "worker" / "app" / "scheduler_pilot_control.py"
pilot_entrypoint_path = ROOT / "worker" / "app" / "scheduler_pilot_entrypoint.py"
cmd_path = ROOT / "START_SCHEDULER_PILOT.cmd"
ignore_path = ROOT / ".gitignore"

for path, label in (
    (wizard_path, "scheduler pilot engine"),
    (easy_path, "zero-copy UX adapter"),
    (gate_path, "Android observation gate"),
    (stack_path, "exact-head stack launcher"),
    (control_path, "deterministic hold"),
    (pilot_entrypoint_path, "pilot-only worker entrypoint"),
    (cmd_path, "double-click entrypoint"),
):
    check(path.is_file(), f"{label} exists")

wizard_text = wizard_path.read_text(encoding="utf-8")
easy_text = easy_path.read_text(encoding="utf-8")
stack_text = stack_path.read_text(encoding="utf-8")
entrypoint_text = pilot_entrypoint_path.read_text(encoding="utf-8")
cmd_text = cmd_path.read_text(encoding="utf-8")
ignore_text = ignore_path.read_text(encoding="utf-8")

check("scheduler_pilot_easy_entry.py" in cmd_text, "entrypoint launches the zero-copy adapter")
check("scheduler_pilot_android_gate.py" in cmd_text, "entrypoint enforces Android observations")
check("PYTHONDONTWRITEBYTECODE" in cmd_text, "entrypoint suppresses Python bytecode")
check("run_deterministic_pilot(planner, state)" in wizard_text, "engine uses deterministic pilot flow")
check("arm_hold(read_id, \"revocation\")" in wizard_text, "revocation is armed before timing")
check("arm_hold(read_id, \"crash_recovery\")" in wizard_text, "crash recovery is armed before timing")
check("schedule_payload(" in wizard_text, "engine reads the actual nested schedule API shape")
check("def discover_write_id" in easy_text, "adapter discovers the Android-created write plan")
check("pilot.get_write_id = discover_write_id" in easy_text, "adapter replaces schedule-id copying")
check("pilot.arm_hold = arm_hold_safely" in easy_text, "adapter enforces safe hold arming")
check("pilot.wait_hold = wait_hold_and_confirm" in easy_text, "in-flight confirmation uses the held occurrence")
check('"-SchedulerPilot"' in wizard_text, "every pilot stack launch requests scheduler mode")
check("[switch]$SchedulerPilot" in stack_text, "stack exposes an explicit pilot switch")
check('KALIV_SCHEDULER=1' in stack_text, "pilot worker enables the scheduler")
check('KALIV_SCHEDULER_API=1' in stack_text, "pilot stack enables the scheduler API")
check('KALIV_SCHEDULER_POLL_S=5' in stack_text, "pilot uses the bounded five-second poll")
check("app.scheduler_pilot_entrypoint:app" in stack_text, "pilot uses a separate worker entrypoint")
check("KALIV_SCHEDULER_PILOT_CONTROL_DIR" in stack_text, "pilot control path is process-local")
check("KALIV_SCHEDULER_PILOT_LOG" in stack_text, "pilot recovery log is explicit")
check("install_pilot_hold" in entrypoint_text, "pilot entrypoint installs the hold before normal app import")
for ignored in (
    "/validation/scheduler-pilot-easy-state.json",
    "/validation/scheduler-pilot-control/",
    "/validation/scheduler-pilot-worker.log",
):
    check(ignored in ignore_text, f"local pilot artifact is ignored: {ignored}")

wizard = load("scheduler_pilot_one_click_contract", wizard_path)
gate_module = load("scheduler_pilot_android_gate_contract", gate_path)
control = load("scheduler_pilot_control_contract", control_path)
easy = load("scheduler_pilot_easy_entry_contract", easy_path)
check(
    wizard.BRANCH == "agent/t019-physical-pilot-candidate",
    "wizard is pinned to the isolated pilot branch",
)
check(wizard.VERSION == "1.58.141", "wizard is pinned to version 1.58.141")
check(
    wizard.report_passes(
        {"candidate": {"git_sha": "a" * 40}, "pilot": {"passed": True}},
        "a" * 40,
    ),
    "a passing report is accepted only for its exact SHA",
)
check(
    not wizard.report_passes(
        {"candidate": {"git_sha": "b" * 40}, "pilot": {"passed": True}},
        "a" * 40,
    ),
    "a passing report from another SHA is rejected",
)

calls: list[list[str]] = []
original_run = wizard.stage.run
original_which = wizard.shutil.which
wizard.stage.run = lambda args, **kwargs: calls.append(list(args))
wizard.shutil.which = lambda command: f"C:/fake/{command}.exe"
try:
    wizard.start_pilot_stack("qwen3:8b")
    wizard.start_pilot_stack("qwen3:8b", worker_only=True)
finally:
    wizard.stage.run = original_run
    wizard.shutil.which = original_which
check(all("-SchedulerPilot" in call for call in calls), "normal and recovery starts keep pilot mode")
check("-WorkerOnly" not in calls[0], "first start builds backend and worker")
check("-WorkerOnly" in calls[1], "recovery restart is worker-only")

base_report = {
    "schema": "kaliv-scheduler-pilot/v4",
    "manual": {},
    "pilot": {"passed": True, "problems": []},
}
all_confirmed = {
    "android_schedule_list_confirmed": True,
    "android_in_flight_confirmed": True,
    "android_terminal_confirmed": True,
}
gated = gate_module.apply_gate(json.loads(json.dumps(base_report)), all_confirmed)
check(gated["pilot"]["passed"] is True, "Android gate preserves a complete pilot")
missing = dict(all_confirmed)
missing["android_terminal_confirmed"] = False
gated_missing = gate_module.apply_gate(json.loads(json.dumps(base_report)), missing)
check(gated_missing["pilot"]["passed"] is False, "Android gate fails a missing terminal observation")
check(
    any("Android-observation mangler" in item for item in gated_missing["pilot"]["problems"]),
    "Android gate records a human-readable refusal",
)

old_write = {
    "schedule_id": "old-write",
    "tool": "note_append",
    "args": {"text": "pilot"},
    "cadence": "every:60",
    "max_runs": 2,
}
new_write = dict(old_write, schedule_id="new-write")
snapshots = [[old_write], [old_write, new_write]]
snapshot_index = [0]
saved_states: list[dict] = []
original_list = easy._list_schedules
original_input = getattr(easy, "input", None)
original_save = easy.pilot.save_state
original_ok = easy.pilot.stage.ok


def fake_list():
    index = min(snapshot_index[0], len(snapshots) - 1)
    snapshot_index[0] += 1
    return snapshots[index]


easy._list_schedules = fake_list
easy.input = lambda _message="": ""
easy.pilot.save_state = lambda state: saved_states.append(dict(state))
easy.pilot.stage.ok = lambda _message: None
try:
    discovery_state: dict[str, str] = {}
    discovered = easy.discover_write_id(discovery_state)
finally:
    easy._list_schedules = original_list
    if original_input is None:
        delattr(easy, "input")
    else:
        easy.input = original_input
    easy.pilot.save_state = original_save
    easy.pilot.stage.ok = original_ok
check(discovered == "new-write", "adapter selects the one newly created exact plan")
check(discovery_state.get("write_schedule_id") == "new-write", "new schedule id is saved for resume")
check(saved_states and saved_states[-1].get("write_schedule_id") == "new-write", "persisted resume state uses the new plan")
check(discovered != "old-write", "an older matching plan is never selected")

messages: list[str] = []
activation_order: list[tuple[str, object]] = []
original_yes = easy._original_require_yes
original_arm = easy._original_arm_hold
original_hold = easy._original_wait_hold
original_set_enabled = easy.pilot.set_schedule_enabled
easy._deferred_in_flight = False
easy._hold_count = 0
easy._original_require_yes = lambda message: messages.append(message)
easy._original_arm_hold = lambda schedule_id, purpose: (
    activation_order.append(("arm", purpose)) or "safe-nonce"
)
easy._original_wait_hold = lambda schedule_id, nonce, timeout=90.0: {
    "schedule_id": schedule_id,
    "nonce": nonce,
    "phase": "before_live_guard",
}
easy.pilot.set_schedule_enabled = lambda schedule_id, enabled: (
    activation_order.append(("enabled", enabled)) or {"schedule_id": schedule_id}
)
try:
    easy.defer_in_flight_question("Så du mindst én plan som in-flight/running? Skriv JA")
    check(not messages, "in-flight question is deferred until the occurrence is held")
    nonce = easy.arm_hold_safely("read-1", "revocation")
    easy.wait_hold_and_confirm("read-1", nonce)
    check(
        activation_order[:3]
        == [("enabled", False), ("arm", "revocation"), ("enabled", True)],
        "effective order is pause, arm, then activate",
    )
    check(len(messages) == 1 and "holdt åben" in messages[0], "in-flight question is asked during the first hold")
    easy.wait_hold_and_confirm("read-1", "nonce-2")
    check(len(messages) == 1, "crash hold does not ask the in-flight question twice")
finally:
    easy._original_require_yes = original_yes
    easy._original_arm_hold = original_arm
    easy._original_wait_hold = original_hold
    easy.pilot.set_schedule_enabled = original_set_enabled
    easy._deferred_in_flight = False
    easy._hold_count = 0

with tempfile.TemporaryDirectory(prefix="kaliv-t019-control-") as tmp:
    root = Path(tmp)
    old_control = os.environ.get("KALIV_SCHEDULER_PILOT_CONTROL_DIR")
    os.environ["KALIV_SCHEDULER_PILOT_CONTROL_DIR"] = str(root)

    class FakeSchedules:
        def __init__(self):
            self.enabled = True

        def set_enabled(self, schedule_id, enabled, now=None):
            self.enabled = bool(enabled)
            return True

    class FakeRunner:
        def __init__(self):
            self.schedules = FakeSchedules()
            self.calls = 0

        def _run_claim(self, claim, job_id, now):
            self.calls += 1
            return "blocked" if not self.schedules.enabled else "completed"

    control.install_pilot_hold(FakeRunner)
    runner = FakeRunner()
    schedule = SimpleNamespace(schedule_id="read-1", tool="rig_status")
    claim = SimpleNamespace(schedule=schedule, claim_id="claim-1")
    nonce = "n" * 32
    (root / "command.json").write_text(
        json.dumps(
            {
                "schema": control.SCHEMA,
                "action": "hold_before_guard",
                "schedule_id": "read-1",
                "nonce": nonce,
                "expires_at": time.time() + 60,
                "timeout_seconds": 30,
            }
        ),
        encoding="utf-8",
    )
    result: list[str] = []
    thread = threading.Thread(target=lambda: result.append(runner._run_claim(claim, "job-1", time.time())))
    thread.start()
    deadline = time.monotonic() + 5.0
    marker = {}
    while time.monotonic() < deadline:
        marker_path = root / "holding.json"
        if marker_path.is_file():
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            break
        time.sleep(0.02)
    check(marker.get("nonce") == nonce, "exact occurrence reaches the deterministic hold")
    check(not (root / "command.json").exists(), "hold command is consumed exactly once")
    check((root / f"command.consumed-{nonce}.json").is_file(), "consumed command remains auditable")
    runner.schedules.set_enabled("read-1", False)
    (root / f"release-{nonce}.flag").write_text("release\n", encoding="ascii")
    thread.join(5.0)
    check(not thread.is_alive(), "held occurrence resumes after explicit release")
    check(result == ["blocked"], "live guard sees the pause after deterministic release")
    check(runner.calls == 1, "underlying claim runs exactly once")

    other = SimpleNamespace(
        schedule=SimpleNamespace(schedule_id="read-2", tool="rig_status"),
        claim_id="claim-2",
    )
    (root / "command.json").write_text(
        json.dumps(
            {
                "schema": control.SCHEMA,
                "action": "hold_before_guard",
                "schedule_id": "different-id",
                "nonce": "m" * 32,
                "expires_at": time.time() + 60,
            }
        ),
        encoding="utf-8",
    )
    runner.schedules.enabled = True
    direct = runner._run_claim(other, "job-2", time.time())
    check(not (root / "holding.json").exists(), "a mismatched schedule never enters the hold")
    check(direct == "completed", "mismatched schedule keeps normal execution")
    check((root / "command.json").is_file(), "mismatched command is not consumed")

    if old_control is None:
        os.environ.pop("KALIV_SCHEDULER_PILOT_CONTROL_DIR", None)
    else:
        os.environ["KALIV_SCHEDULER_PILOT_CONTROL_DIR"] = old_control

print(f"one-click scheduler pilot contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
