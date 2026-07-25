#!/usr/bin/env python3
"""T-006 forced recovery — kør hele forsøget med ét dobbeltklik.

Beviser den ene rest fra rig-dagen 22/7: at recovery virker efter en ÆGTE
proces-død, ikke kun mod konstrueret DB-tilstand. Enhedstestene skriver
nedbrudstilstanden; det her producerer den ved at dræbe en proces.

Forsøget er todelt, og begge dele betyder noget:

  Del 1  genstart HURTIGT (som supervisoren gør)  -> recovery springes over,
         fordi den døde workers lease er 90 sekunder gyldig endnu
  Del 2  genstart efter lease-udløb                -> recovery kører og
         afklarer occurrencen

Del 1 er ikke en fejl. Den er den operationelle sandhed man ellers først
opdager kl. 02 en tirsdag: en worker der dør og genstartes med det samme
efterlader sin occurrence uafklaret indtil NÆSTE opstart.

Alt kører i en midlertidig mappe. Riggens egne schedules, jobs og audit røres
ikke. Mappen slettes til sidst.

Kør:  START_FORCED_RECOVERY.cmd   (eller: python scripts/forced_recovery_test.py)
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "worker"
IS_WIN = os.name == "nt"

# The claim is durable the moment it commits, so the child only has to get that
# far before we kill it. Ten seconds is generous even on a cold Windows start.
ARM_TIMEOUT_S = 60.0
LEASE_TTL_S = 90.0
LEASE_MARGIN_S = 8.0


def hdr(text: str) -> None:
    print()
    print("=" * 68)
    print(f"  {text}")
    print("=" * 68)


def say(text: str = "") -> None:
    print(text, flush=True)


CHILD = r'''
import json, os, sys, time
sys.path.insert(0, os.environ["KALIV_WORKER_PATH"])
D = os.environ["RECOV_DIR"]
os.environ.setdefault("KALIV_TOOLS_ENABLED", "1")
os.environ.setdefault("KALIV_SCHEDULER", "1")
os.environ["KALIV_TOOLS_DIR"] = os.path.join(D, "notes")
os.environ["KALIV_AUDIT_DB"] = os.path.join(D, "audit.db")
from app import tools as T
from app.jobs import JobStore
from app.schedule_runner import SchedulerRunner
from app.scheduler import ScheduleStore

schedules = ScheduleStore(path=os.path.join(D, "schedules.db"))
jobs = JobStore(os.path.join(D, "jobs.db"))
runner = SchedulerRunner(schedules=schedules, jobs=jobs, gate=T.GATE)
mode = sys.argv[1]

if mode == "arm":
    schedules.create("rig_status", {}, "every:60", now=time.time() - 120)
    ok = schedules.acquire_lease(runner.owner_id,
                                 ttl_seconds=runner.lease_ttl_seconds)
    claims = schedules.claim_due(now=time.time())
    print("READY " + json.dumps({
        "owner_id": runner.owner_id,
        "lease_acquired": bool(ok),
        "claims": [c.claim_id for c in claims],
        "lease_ttl": runner.lease_ttl_seconds,
    }), flush=True)
    while True:          # stay alive so the kill lands mid-flight
        time.sleep(0.2)

if mode == "recover":
    out = runner.recover_interrupted()
    print("RESULT " + json.dumps({
        "owner_id": runner.owner_id,
        "executed": list(out.get("executed", [])),
        "abandoned": list(out.get("abandoned", [])),
        "unknown": list(out.get("unknown", [])),
    }), flush=True)
'''


def _env(d: Path) -> dict:
    e = dict(os.environ)
    e["RECOV_DIR"] = str(d)
    e["KALIV_WORKER_PATH"] = str(WORKER)
    e["PYTHONDONTWRITEBYTECODE"] = "1"
    e["PYTHONIOENCODING"] = "utf-8"
    return e


def _occurrences(d: Path) -> list[tuple[str, str]]:
    import sqlite3
    db = d / "schedules.db"
    if not db.exists():
        return []
    c = sqlite3.connect(str(db))
    try:
        return [(r[0], r[1]) for r in
                c.execute("SELECT claim_id, status FROM occurrences")]
    finally:
        c.close()


def _runs_used(d: Path) -> int | None:
    import sqlite3
    db = d / "schedules.db"
    if not db.exists():
        return None
    c = sqlite3.connect(str(db))
    try:
        row = c.execute("SELECT runs_used FROM schedules LIMIT 1").fetchone()
        return row[0] if row else None
    finally:
        c.close()


def run_recover(d: Path, script: Path) -> dict:
    p = subprocess.run([sys.executable, str(script), "recover"],
                       cwd=str(ROOT), env=_env(d),
                       capture_output=True, text=True, timeout=180)
    blob: dict = {}
    for line in (p.stdout or "").splitlines():
        if line.startswith("RESULT "):
            blob = json.loads(line[len("RESULT "):])
    blob["_skipped_msg"] = any(
        "sprunget over" in ln for ln in (p.stderr or "").splitlines())
    blob["_stderr"] = (p.stderr or "").strip()
    return blob


def main() -> int:
    hdr("T-006 — FORCED RECOVERY")
    say("Beviser at recovery virker efter en aegte proces-doed.")
    say("Tager ca. 2 minutter. Du skal ikke goere noget undervejs.")
    say()
    say("Riggens egne data roeres IKKE — alt koerer i en midlertidig mappe.")

    if not (WORKER / "app" / "schedule_runner.py").exists():
        say()
        say("FEJL: kan ikke finde worker/app/schedule_runner.py.")
        say("Koer scriptet fra roden af repoet/udpakningen.")
        return 2

    d = Path(tempfile.mkdtemp(prefix="kaliv-t006-"))
    script = d / "child.py"
    script.write_text(CHILD, encoding="utf-8")
    verdict: list[tuple[bool, str]] = []

    try:
        # ---------------------------------------------------- arm and kill
        hdr("1/3  Starter en proces og lader den claime en occurrence")
        proc = subprocess.Popen(
            [sys.executable, str(script), "arm"], cwd=str(ROOT), env=_env(d),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            bufsize=1)
        armed: dict = {}
        t0 = time.time()
        while time.time() - t0 < ARM_TIMEOUT_S:
            line = proc.stdout.readline() if proc.stdout else ""
            if line.startswith("READY "):
                armed = json.loads(line[len("READY "):])
                break
            if proc.poll() is not None:
                break
        if not armed.get("claims"):
            say("FEJL: processen naaede ikke at claime. Afbryder.")
            proc.kill()
            return 2

        claim = armed["claims"][0]
        say(f"  claimede occurrence : {claim[:12]}")
        say(f"  ejer-id             : {armed['owner_id'][:12]}")
        say(f"  lease-TTL           : {armed['lease_ttl']:.0f} sekunder")
        say()
        say("  Draeber processen HAARDT (ingen oprydning, ingen finally) ...")
        if IS_WIN:
            # taskkill /F is the Windows SIGKILL: no cleanup runs.
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True)
        else:
            proc.send_signal(signal.SIGKILL)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            pass
        killed_at = time.time()
        say("  Processen er doed.")

        before = dict(_occurrences(d))
        ok = before.get(claim) == "reserved"
        verdict.append((ok, "occurrencen stod 'reserved' efter proces-doeden "
                            f"(fik: {before.get(claim)!r})"))
        say(f"  Occurrence-tilstand : {before.get(claim)}")

        # ------------------------------------------------- part 1: fast
        hdr("2/3  HURTIG genstart — som supervisoren goer det")
        say("  En ny proces starter med et NYT tilfaeldigt ejer-id.")
        say("  Den doede workers lease er stadig gyldig i ~"
            f"{LEASE_TTL_S - (time.time() - killed_at):.0f} sekunder.")
        say()
        fast = run_recover(d, script)
        touched = fast.get("executed") or fast.get("abandoned") or fast.get("unknown")
        ok = not touched
        verdict.append((ok, "hurtig genstart: recovery blev sprunget over "
                            "(leasen holdt) — forventet"))
        say(f"  recovery roerte     : {'ingenting' if not touched else touched}")
        if fast.get("_skipped_msg"):
            say("  loggen sagde        : \"recovery sprunget over — en anden "
                "ejer holder lease'en\"")
        still = dict(_occurrences(d)).get(claim)
        say(f"  Occurrence-tilstand : {still}")
        verdict.append((still == "reserved",
                        "occurrencen er stadig uafklaret efter hurtig genstart"))

        # ------------------------------------------------- part 2: slow
        wait = LEASE_TTL_S - (time.time() - killed_at) + LEASE_MARGIN_S
        hdr("3/3  Venter leasen ud, saa genstart igen")
        say(f"  Venter {wait:.0f} sekunder ...")
        step = max(1.0, wait / 10.0)
        waited = 0.0
        while waited < wait:
            time.sleep(min(step, wait - waited))
            waited += step
            say(f"    {min(waited, wait):.0f}/{wait:.0f}s")
        say()
        slow = run_recover(d, script)
        abandoned = slow.get("abandoned") or []
        executed = slow.get("executed") or []
        say(f"  recovery afskrev    : {abandoned or '(ingen)'}")
        say(f"  recovery bekraeftede: {executed or '(ingen)'}")
        verdict.append((claim in abandoned,
                        "recovery afklarede occurrencen som 'abandoned'"))

        after = dict(_occurrences(d)).get(claim)
        runs = _runs_used(d)
        say(f"  Occurrence-tilstand : {after}")
        say(f"  runs_used           : {runs}   (0 = budget-slot refunderet)")
        verdict.append((after == "abandoned",
                        "occurrencen endte 'abandoned' i databasen"))
        verdict.append((runs == 0,
                        "budget-slottet blev refunderet — ingen koersel talt "
                        "der ikke skete"))

        # ------------------------------------------------------- verdict
        hdr("RESULTAT")
        for ok_, text in verdict:
            say(f"  {'OK  ' if ok_ else 'FEJL'}  {text}")
        failed = [t for ok_, t in verdict if not ok_]
        say()
        if failed:
            say("T-006 forced recovery: NOGET AFVIGER.")
            say("Send outputtet videre — det er praecis det der skal kigges paa.")
            return 1
        say("T-006 forced recovery: BESTAAET paa denne maskine.")
        say()
        say("Hvad det beviser:")
        say("  * recovery virker efter en aegte, haard proces-doed")
        say("  * SQLite overlevede drabet uden nogen oprydning")
        say("  * budget-slottet blev refunderet korrekt (W2-vinduet)")
        say("  * lease-vinduet er reelt: en genstart inden for "
            f"{LEASE_TTL_S:.0f}s springer recovery over")
        say()
        say("Det sidste er ikke en fejl — det er beskyttelsen mod at afskrive")
        say("en LEVENDE workers koersler. Men det betyder at en worker der doer")
        say("og genstartes med det samme, foerst faar afklaret sin occurrence")
        say("ved NAESTE opstart. Godt at vide foer det sker kl. 02.")
        return 0
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nAfbrudt.")
        raise SystemExit(130)
