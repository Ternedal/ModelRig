#!/usr/bin/env python3
"""Last-mile UX adapter for the T-019 one-click scheduler pilot.

The proven pilot module owns all safety and evidence logic. This adapter only:
1. discovers the newly created exact Android write plan, so no schedule-id must
   be copied;
2. asks for the in-flight observation while the deterministic hold is active;
3. converts each hold into pause -> arm -> enable -> wait, removing the final
   claim-before-command race without changing scheduler production code.
"""
from __future__ import annotations

import time
from typing import Any

import scheduler_pilot_one_click as pilot


def _list_schedules() -> list[dict[str, Any]]:
    payload = pilot.stage.request_json(f"{pilot.WORKER_URL}/schedules")
    schedules = payload.get("schedules")
    if not isinstance(schedules, list):
        raise pilot.PilotError("Workerens schedule-liste har forkert format.")
    return [item for item in schedules if isinstance(item, dict)]


def _matches_write(schedule: dict[str, Any]) -> bool:
    manifest = pilot.WRITE_MANIFEST
    return (
        schedule.get("tool") == manifest["tool"]
        and schedule.get("args") == manifest["args"]
        and schedule.get("cadence") == manifest["cadence"]
        and schedule.get("max_runs") == manifest["max_runs"]
    )


def discover_write_id(state: dict[str, Any]) -> str:
    existing = str(state.get("write_schedule_id") or "")
    if existing:
        try:
            if _matches_write(pilot.get_schedule(existing)):
                return existing
        except Exception:
            pass

    before = {
        str(item.get("schedule_id"))
        for item in _list_schedules()
        if item.get("schedule_id")
    }
    print("\n  Opret PRÆCIS denne plan i Android-appens schedule-flow og godkend den:")
    print('    note_append · {"text":"pilot"} · every:60 · max_runs=2 · ttl_days=1')
    input("  Tryk Enter her, når appen siger, at planen er oprettet: ")

    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        matches = [
            item
            for item in _list_schedules()
            if _matches_write(item)
            and str(item.get("schedule_id") or "") not in before
        ]
        if len(matches) == 1:
            schedule_id = str(matches[0]["schedule_id"])
            state["write_schedule_id"] = schedule_id
            pilot.save_state(state)
            pilot.stage.ok(f"Wizard'en fandt automatisk write-planen: {schedule_id}")
            return schedule_id
        if len(matches) > 1:
            ids = ", ".join(str(item.get("schedule_id")) for item in matches)
            raise pilot.PilotError(
                "Der blev oprettet flere matchende pilotplaner. Pause dem i appen "
                f"og prøv igen. Nye id'er: {ids}"
            )
        time.sleep(0.5)
    raise pilot.PilotError(
        "Wizard'en fandt ingen ny exact note_append-pilotplan inden for ét minut."
    )


_original_require_yes = pilot.require_yes
_original_arm_hold = pilot.arm_hold
_original_wait_hold = pilot.wait_hold
_deferred_in_flight = False
_hold_count = 0


def defer_in_flight_question(message: str) -> None:
    global _deferred_in_flight
    if "in-flight/running" in message:
        _deferred_in_flight = True
        return
    _original_require_yes(message)


def arm_hold_safely(schedule_id: str, purpose: str) -> str:
    # The underlying flow historically enabled before arming. Force the plan
    # paused here, write the exact one-shot command, and let wait_hold_and_confirm
    # perform the only re-enable after the command is durable.
    pilot.set_schedule_enabled(schedule_id, False)
    return _original_arm_hold(schedule_id, purpose)


def wait_hold_and_confirm(schedule_id: str, nonce: str, *, timeout: float = 90.0):
    global _hold_count, _deferred_in_flight
    pilot.set_schedule_enabled(schedule_id, True)
    marker = _original_wait_hold(schedule_id, nonce, timeout=timeout)
    _hold_count += 1
    if _hold_count == 1 and _deferred_in_flight:
        _original_require_yes(
            "Occurrence er holdt åben nu. Viser Android planen/jobbet som in-flight/running? Skriv JA"
        )
        _deferred_in_flight = False
    return marker


pilot.get_write_id = discover_write_id
pilot.require_yes = defer_in_flight_question
pilot.arm_hold = arm_hold_safely
pilot.wait_hold = wait_hold_and_confirm

if __name__ == "__main__":
    raise SystemExit(pilot.main())
