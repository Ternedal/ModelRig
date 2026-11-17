#!/usr/bin/env python3
"""Stage B's reboot trial must prove that the machine booted after the pause.

Rig night 16/11 on 2.0.20: Enter was pressed at the reboot pause without a
restart, and the trial still recorded ``performed: true`` and printed "Reboot
bevist". ``seconds_since_boot`` was logged but never compared with anything.

These cases run the real ``trial_reboot`` with the machine stubbed out:
- a boot older than the pause is refused, nothing is recorded, the pause stays;
- an unreadable boot age is refused;
- the run after a real restart keeps the first pause time and passes;
- a first run never moves an existing pause time.

Run: python3 tests/workflow_stage_b_reboot_proof.py
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "support"))
from source_code import code_of  # noqa: E402
SPEC = importlib.util.spec_from_file_location("stage_b_reboot_under_test", ROOT / "scripts" / "stage_b_one_click.py")
assert SPEC and SPEC.loader
sb = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sb
SPEC.loader.exec_module(sb)

CHECKS = 0
FAILED: list[str] = []


def check(condition: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILED.append(label)
        print(f"  FAIL: {label}")


class Rig:
    def __init__(self, tmp: Path, *, boot_age: float | None) -> None:
        self.boot_age = boot_age
        self.saved_states: list[dict[str, Any]] = []
        self.saved_observations = 0
        sb.EVIDENCE = tmp / "evidence"
        sb.input = lambda _prompt="": ""  # type: ignore[attr-defined]
        sb.wait_ready = lambda timeout=0: 12.0
        sb.live_versions = lambda: {
            "backend_version": "2.0.21", "worker_version": "2.0.21",
            "worker_code_sha256": "", "worker_exe_sha256": "e" * 64,
        }
        sb.seconds_since_boot = lambda: self.boot_age
        sb.save_state = lambda state: self.saved_states.append(dict(state))
        sb.save_observations = lambda _obs: setattr(self, "saved_observations", self.saved_observations + 1)
        sb.heading = sb.note = sb.ok = lambda *_a, **_k: None

    @staticmethod
    def observations() -> dict[str, Any]:
        return {"trials": {"reboot": {}}}


def ago(seconds: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def run(rig: Rig, state: dict[str, Any]) -> tuple[str | None, dict[str, Any], dict[str, Any]]:
    observations = rig.observations()
    try:
        sb.trial_reboot(observations, state)
    except sb.StageBError as exc:
        return str(exc), state, observations
    return None, state, observations


def no_restart_is_refused(tmp: Path) -> None:
    rig = Rig(tmp, boot_age=4 * 3600.0)  # up for four hours
    error, state, obs = run(rig, {"reboot_pending_since": ago(60)})
    check(error is not None and "ikke genstartet siden pausepunktet" in error, f"refused: {error}")
    check(not state.get("reboot_done"), "reboot_done is not set")
    check(obs["trials"]["reboot"] == {}, "no reboot trial is recorded")
    check(rig.saved_observations == 0, "observations are not saved")
    check(state.get("reboot_pending_since"), "the pause stays set for the real restart")


def the_first_run_without_a_restart_is_refused(tmp: Path) -> None:
    # 16/11 exactly: the pause starts now, and Enter follows a few seconds later.
    rig = Rig(tmp, boot_age=3600.0)
    error, state, _obs = run(rig, {})
    check(error is not None and "ikke genstartet" in error, f"refused: {error}")
    check(bool(state.get("reboot_pending_since")), "the pause time is recorded")
    check(len(rig.saved_states) == 1, "and saved once, before the prompt")


def an_unreadable_boot_age_is_refused(tmp: Path) -> None:
    rig = Rig(tmp, boot_age=None)
    error, state, _obs = run(rig, {"reboot_pending_since": ago(600)})
    check(error is not None and "opstartstidspunkt kunne ikke læses" in error, f"refused: {error}")
    check(not state.get("reboot_done"), "reboot_done is not set")


def a_real_restart_passes_and_keeps_the_pause(tmp: Path) -> None:
    rig = Rig(tmp, boot_age=105.6)
    pause = ago(600)  # paused ten minutes ago, booted 105.6 s ago
    error, state, obs = run(rig, {"reboot_pending_since": pause})
    check(error is None, f"a real restart passes: {error}")
    check(state.get("reboot_done") is True, "reboot_done is set")
    check(state.get("reboot_pending_since") == pause, "the first pause time is kept, not moved to this run")
    check(not rig.saved_states or rig.saved_states[0].get("reboot_pending_since") == pause,
          "no save moved the pause time")
    check(obs["trials"]["reboot"].get("performed") is True, "the trial is recorded")
    log_lines = (sb.EVIDENCE / "reboot.log").read_text(encoding="utf-8").splitlines()
    check("seconds_since_boot=105.6" in log_lines, "the boot age is in the log")


def a_bad_pause_time_is_refused(tmp: Path) -> None:
    rig = Rig(tmp, boot_age=10.0)
    error, _state, _obs = run(rig, {"reboot_pending_since": "not-a-time"})
    check(error is not None and "tidsstempel" in error, f"refused: {error}")


def the_interruption_window_covers_the_download(_tmp: Path) -> None:
    # Same night: STRICT 2/2 gave launch-to-first-swap 300 s, and the 1335 MiB
    # worker download counts against it. The loader now widens it in the
    # substituted retained source; the retained file itself stays byte-for-byte.
    loader = ROOT / "scripts" / "stage_b_one_click_v2.py"
    text = loader.read_text(encoding="utf-8")
    scope: dict[str, Any] = {"__file__": str(loader)}
    exec(compile(text.split("_name = __name__")[0], str(loader), "exec"), scope)
    source = scope["_source"]
    window = float(scope["STRICT_INTERRUPTION_DEADLINE_S"])
    check("deadline = time.monotonic() + 300.0" not in source, "the 300 s window is gone from the run source")
    check("deadline = time.monotonic() + STRICT_INTERRUPTION_DEADLINE_S" in source, "the window is the named constant")
    check(window * 1.0 >= 1335, f"{window:.0f} s covers 1335 MiB at 1 MB/s")
    check("updater.lock" in source and "kaliv-update-" in source, "the refusal names what a kill leaves behind")
    retained = code_of(ROOT / "scripts" / "stage_b_one_click_v2.retained")
    check("deadline = time.monotonic() + 300.0" in retained, "the retained file is unchanged")
    compile(source, "retained-substituted", "exec")


def main() -> None:
    for case in (no_restart_is_refused, the_first_run_without_a_restart_is_refused,
                 an_unreadable_boot_age_is_refused, a_real_restart_passes_and_keeps_the_pause,
                 a_bad_pause_time_is_refused, the_interruption_window_covers_the_download):
        with tempfile.TemporaryDirectory() as tmp:
            case(Path(tmp))
    if FAILED:
        print(f"===== STAGE B REBOOT PROOF: {CHECKS - len(FAILED)} passed, {len(FAILED)} failed =====")
        raise SystemExit(1)
    print(f"===== STAGE B REBOOT PROOF: {CHECKS} passed, 0 failed =====")


if __name__ == "__main__":
    main()
