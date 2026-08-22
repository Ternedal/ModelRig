#!/usr/bin/env python3
"""Run the decomposed physical scheduler pilot as one resumable operator flow.

All durable proof remains owned by the bounded helpers.  This orchestrator only
orders them, reuses a still-live isolated stack, refreshes the phone pairing code
immediately before the one Android approval, publishes the verified report to
the campaign slot, and cleans up the recorded test processes after success.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "validation" / "stage-a-runtime"
PHONE_STATE = RUNTIME / "phone-test-state.json"
PHONE_INSTRUCTIONS = RUNTIME / "PHONE_TEST.txt"
PHONE_SCRIPT = ROOT / "scripts" / "stage-a-phone-test.ps1"
CANDIDATE_BRANCH_PREFIX = "physical-proof/2.0.11"
EXPECTED_VERSION = "2.0.11"

STEPS = (
    ("read-plan", ROOT / "scripts" / "stage_a_scheduler_read.py"),
    ("revocation", ROOT / "scripts" / "stage_a_scheduler_revocation.py"),
    ("crash-recovery", ROOT / "scripts" / "stage_a_scheduler_crash_recovery.py"),
)
FINALIZER = ROOT / "scripts" / "stage_a_scheduler_finalize.py"
PUBLISHER = ROOT / "scripts" / "stage_a_scheduler_publish.py"
CAMPAIGN_REPORT = ROOT / "validation" / "scheduler-pilot-latest.json"


class EasyPilotError(RuntimeError):
    pass


def heading(text: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70)


def run(args: list[str], *, label: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    print(f"\n  -> {label}")
    try:
        result = subprocess.run(args, cwd=ROOT, text=True, check=False)
    except OSError as exc:
        raise EasyPilotError(f"Kunne ikke starte {args[0]}: {exc}") from exc
    if check and result.returncode != 0:
        raise EasyPilotError(f"{label} stoppede med exitkode {result.returncode}.")
    return result


def capture(args: list[str], *, label: str) -> str:
    try:
        result = subprocess.run(
            args,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EasyPilotError(f"{label} kunne ikke gennemføres: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise EasyPilotError(f"{label} fejlede: {detail[-600:]}")
    return result.stdout.strip()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(payload)
        temp = Path(handle.name)
    temp.replace(path)


def load_state() -> dict[str, Any]:
    try:
        value = json.loads(PHONE_STATE.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def request_json(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            value = json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise EasyPilotError(f"Kunne ikke læse {url}: {exc}") from exc
    if not isinstance(value, dict):
        raise EasyPilotError(f"{url} returnerede ikke et JSON-objekt.")
    return value


def ensure_checkout() -> str:
    if os.name != "nt":
        raise EasyPilotError("Den fysiske scheduler-pilot må kun køres på Windows-riggen.")
    for command in ("git", "python", "powershell.exe"):
        if shutil.which(command) is None:
            raise EasyPilotError(f"{command} blev ikke fundet på PATH.")

    dirty = capture(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        label="Git-status",
    )
    if dirty:
        raise EasyPilotError(f"Tracked working tree er ikke ren:\n{dirty}")

    # Bind to the rig candidate that is already checked out and frozen. The
    # scheduler proof must share the exact candidate SHA with the other five
    # Stage A proofs, so this NEVER fetches, switches or pulls a branch -- that
    # would move the checkout off the frozen candidate and bind the evidence to
    # the wrong SHA (which the candidate campaign would then reject).
    current = capture(["git", "branch", "--show-current"], label="Aktuel branch")
    if current != CANDIDATE_BRANCH_PREFIX:
        raise EasyPilotError(
            "Scheduler-piloten skal køre på den udcheckede rig-kandidat "
            f"'{CANDIDATE_BRANCH_PREFIX}', ikke '{current or 'detached HEAD'}'. "
            "Checkout kandidaten først; piloten skifter ikke branch."
        )

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if version != EXPECTED_VERSION:
        raise EasyPilotError(f"VERSION er {version}; forventede {EXPECTED_VERSION}.")
    sha = capture(["git", "rev-parse", "HEAD"], label="Exact HEAD")
    if len(sha) != 40:
        raise EasyPilotError("Git returnerede ikke en gyldig exact HEAD.")
    return sha


def stack_ready() -> bool:
    state = load_state()
    scheduler = state.get("scheduler")
    if not (
        state.get("schema") == "kaliv-stage-a-phone-test-state/v2"
        and state.get("production_activation") is False
        and isinstance(scheduler, dict)
        and scheduler.get("enabled") is True
        and scheduler.get("configured") is True
        and scheduler.get("running") is True
        and scheduler.get("resources_open") is True
    ):
        return False
    try:
        health = request_json("http://127.0.0.1:8080/healthz", timeout=2.0)
        status = request_json("http://127.0.0.1:8099/schedules/status", timeout=2.0)
    except EasyPilotError:
        return False
    return (
        health.get("status") == "ok"
        and status.get("configured") is True
        and status.get("running") is True
        and status.get("resources_open") is True
        and not status.get("last_error")
    )


def ensure_stack() -> None:
    if stack_ready():
        print("  OK  Genbruger den levende, isolerede scheduler-teststack.")
        return
    run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PHONE_SCRIPT),
            "-EnableSchedulerPilot",
        ],
        label="Starter isoleret backend, worker og scheduler",
    )
    if not stack_ready():
        raise EasyPilotError("Scheduler-teststacken startede, men bestod ikke readiness-kontrollen.")


def run_bounded_steps() -> None:
    for label, script in STEPS:
        run([sys.executable, str(script)], label=f"Kører {label}")


def refresh_pairing() -> dict[str, Any]:
    state = load_state()
    if not stack_ready():
        raise EasyPilotError("Teststacken er ikke længere klar før Android-godkendelsen.")
    pairing = request_json(
        "http://127.0.0.1:8080/api/v1/pair/start",
        method="POST",
        timeout=10.0,
    )
    code = pairing.get("code")
    if not isinstance(code, str) or not code.strip():
        raise EasyPilotError("Backenden returnerede ingen frisk parringskode.")
    state["pairing_code"] = code
    state["pairing_expires_at"] = pairing.get("expires_at")
    atomic_json(PHONE_STATE, state)

    lan_url = str(state.get("lan_url") or "")
    instructions = f"""KALIV STAGE A - SIDSTE ANDROID-TRIN

Server-URL:   {lan_url}
Parringskode: {code}
Udløber:      {pairing.get('expires_at')}

1. Åbn Kaliv på Pixel 6a.
2. Vælg Rig og brug Server-URL + den friske parringskode ovenfor.
3. Tryk Forbind, også hvis appen tidligere sagde parret.
4. Følg derefter write-planen, som vises i dette vindue.

Ingen token, schedule-ID eller JSON skal kopieres tilbage.
production_activation=false
"""
    PHONE_INSTRUCTIONS.write_text(instructions, encoding="utf-8")
    return {"lan_url": lan_url, "code": code, "expires_at": pairing.get("expires_at")}


def finalize_and_publish() -> None:
    run([sys.executable, str(FINALIZER)], label="Venter på Android-godkendelse og finaliserer")
    run([sys.executable, str(PUBLISHER)], label="Publicerer verificeret rapport til Stage A-kampagnen")
    if not CAMPAIGN_REPORT.is_file():
        raise EasyPilotError("Finaliseringen returnerede grønt, men kampagnerapporten mangler.")


def stop_stack() -> None:
    result = run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PHONE_SCRIPT),
            "-Stop",
        ],
        label="Rydder den isolerede teststack og firewall-reglen",
        check=False,
    )
    if result.returncode != 0:
        print("  ADVARSEL  Automatisk cleanup fejlede. Brug STOP_STAGE_A_PHONE_TEST.cmd.")


def main() -> int:
    heading("KALIV STAGE A — ÉN GUIDET SCHEDULER-PILOT")
    print("  Automatik: stack, read, revocation, crash-recovery, ID'er, rapport og cleanup.")
    print("  Dig: forbind Pixel og godkend én præcis write-plan, når den vises.")
    print("  Ingen merge, release eller produktion aktiveres.")

    try:
        sha = ensure_checkout()
        print(f"  Exact HEAD: {sha}")
        ensure_stack()
        run_bounded_steps()

        pairing = refresh_pairing()
        heading("PIXEL 6A — FORBIND MED DEN FRISKE KODE")
        print(f"  Server-URL:   {pairing['lan_url']}")
        print(f"  Parringskode: {pairing['code']}")
        print(f"  Udløber:      {pairing['expires_at']}")
        print("  Koden er også gemt i validation\\stage-a-runtime\\PHONE_TEST.txt")
        print("  Finalizeren venter nu op til 15 minutter på den ene godkendelse.")

        finalize_and_publish()
        stop_stack()

        heading("SCHEDULER-PILOTEN ER BESTÅET OG GEMT")
        print(f"  Rapport:   {CAMPAIGN_REPORT}")
        print(f"  Exact SHA: {sha}")
        print("  Teststack og midlertidig firewall-regel er stoppet.")
        print("  production_activation=false")
        return 0
    except (EasyPilotError, KeyboardInterrupt) as exc:
        print(f"\n  STOP  {exc}")
        print("  Delresultater er bevaret. Lad teststacken stå og kør samme launcher igen.")
        print("  Brug STOP_STAGE_A_PHONE_TEST.cmd, hvis du vil afbryde og rydde op.")
        print("  Intet er merget, releaset eller aktiveret.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
