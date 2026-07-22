#!/usr/bin/env python3
"""Resumable one-click operator for the physical T-019 scheduler pilot.

The wizard reuses the authoritative ``scheduler_pilot_report.py`` evaluator. It
creates the exact read schedule, discovers the exact write schedule after the
human approves it in Android, deterministically exercises revoke and crash
recovery through the real occurrence ledger, and writes the manual-observation
JSON from observed durable evidence.

It cannot mint a write approval, merge, push, tag, publish or activate anything.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "agent/scheduler-m2-pilot-candidate"
VERSION = "1.58.141"
WORKER_URL = "http://127.0.0.1:8099"
BACKEND_URL = "http://127.0.0.1:8080"
VALIDATION = ROOT / "validation"
STATE_PATH = VALIDATION / "scheduler-pilot-easy-state.json"
LOG_PATH = VALIDATION / "scheduler-pilot-worker.log"
REPORT_PATH = VALIDATION / "scheduler-pilot-latest.json"
MANUAL_PATH = VALIDATION / "scheduler-manual-observations.json"
SCHEDULES_DB = ROOT / "kaliv-schedules.db"
JOBS_DB = ROOT / "modelrig-jobs.db"
AUDIT_DB = ROOT / "kaliv-audit.db"
AGENT3_REPORT = VALIDATION / "agent3-rig-validation-latest.json"
POLL_SECONDS = 65.0

READ_SPEC = {
    "tool": "rig_status",
    "args": {},
    "cadence": "every:60",
    "ttl_days": 1,
    "max_runs": 3,
}
WRITE_SPEC = {
    "tool": "note_append",
    "args": {"text": "pilot"},
    "cadence": "every:60",
    "ttl_days": 1,
    "max_runs": 2,
}
RECOVERY_RE = re.compile(
    r"scheduler: recovered \d+ executed / \d+ abandoned / \d+ unknown occurrence\(s\) at startup"
)


class PilotError(RuntimeError):
    pass


def heading(text: str) -> None:
    print("\n" + "=" * 74)
    print(f"  {text}")
    print("=" * 74)


def note(text: str) -> None:
    print(f"  -> {text}")


def ok(text: str) -> None:
    print(f"  OK {text}")


def run(
    args: list[str],
    *,
    cwd: Path = ROOT,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    effective = os.environ.copy()
    if env:
        effective.update(env)
    try:
        result = subprocess.run(args, cwd=cwd, env=effective, text=True, check=False)
    except OSError as exc:
        raise PilotError(f"Kunne ikke starte {args[0]}: {exc}") from exc
    if check and result.returncode != 0:
        raise PilotError(f"Kommandoen fejlede ({result.returncode}): {' '.join(args)}")
    return result


def capture(args: list[str], *, cwd: Path = ROOT) -> str:
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            env=os.environ.copy(),
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PilotError(f"Kommandoen kunne ikke gennemføres: {' '.join(args)}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise PilotError(f"{' '.join(args)} fejlede: {detail[-500:]}")
    return result.stdout.strip()


def git(*args: str) -> str:
    return capture(["git", *args])


def request_json(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise PilotError(f"Kunne ikke læse {url}: {exc}") from exc


def endpoint_ok(url: str) -> bool:
    try:
        request_json(url, timeout=2.0)
        return True
    except PilotError:
        return False


def wait_endpoint(url: str, *, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if endpoint_ok(url):
            return
        time.sleep(1.0)
    raise PilotError(f"Tjenesten blev ikke klar: {url}")


def load_state() -> dict[str, Any]:
    if not STATE_PATH.is_file():
        return {}
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def save_state(state: dict[str, Any]) -> None:
    VALIDATION.mkdir(parents=True, exist_ok=True)
    temp = STATE_PATH.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp.replace(STATE_PATH)


def existing_report_passed(sha: str) -> bool:
    if not REPORT_PATH.is_file():
        return False
    try:
        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(report, dict)
        and (report.get("candidate") or {}).get("git_sha") == sha
        and (report.get("pilot") or {}).get("passed") is True
    )


def ensure_checkout() -> str:
    if os.name != "nt":
        raise PilotError("T-019-wizard'en må kun køres på Windows-riggen.")
    for command in ("git", "python", "powershell.exe"):
        if not shutil.which(command):
            raise PilotError(f"{command} blev ikke fundet på PATH.")
    dirty = git("status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise PilotError(f"Tracked working tree er ikke ren:\n{dirty}")
    git("fetch", "--quiet", "origin", BRANCH)
    current = git("branch", "--show-current")
    if current != BRANCH:
        git("switch", BRANCH)
    git("pull", "--ff-only", "origin", BRANCH)
    sha = git("rev-parse", "HEAD")
    if sha != git("rev-parse", f"origin/{BRANCH}"):
        raise PilotError(f"Lokal HEAD matcher ikke origin/{BRANCH}.")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if version != VERSION:
        raise PilotError(f"VERSION er {version}, forventede {VERSION}.")
    return sha


def reset_state_for_sha(state: dict[str, Any], sha: str) -> None:
    if state.get("candidate_sha") == sha:
        return
    if STATE_PATH.is_file() or REPORT_PATH.is_file() or MANUAL_PATH.is_file():
        archive = VALIDATION / "archive" / time.strftime("scheduler-pilot-%Y%m%d-%H%M%S")
        archive.mkdir(parents=True, exist_ok=True)
        for path in (STATE_PATH, REPORT_PATH, MANUAL_PATH):
            if path.is_file():
                path.replace(archive / path.name)
        note(f"Tidligere pilotfiler er bevaret i {archive}")
    state.clear()
    state.update({"candidate_sha": sha, "pilot_started_at": time.time()})
    save_state(state)


def ollama_models() -> list[str]:
    try:
        payload = request_json("http://127.0.0.1:11434/api/tags", timeout=3.0)
    except PilotError:
        return []
    models = payload.get("models", []) if isinstance(payload, dict) else []
    return [
        str(item.get("name"))
        for item in models
        if isinstance(item, dict) and item.get("name")
    ]


def planner_model() -> str:
    configured = os.environ.get("KALIV_AGENT3_PLANNER_MODEL", "").strip()
    models = ollama_models()
    if configured and (not models or configured in models):
        return configured
    for prefix in ("qwen3:", "gemma3:"):
        match = next((name for name in models if name.startswith(prefix)), "")
        if match:
            return match
    match = next((name for name in models if "embed" not in name.lower()), "")
    if match:
        return match
    raise PilotError("Ingen Ollama planner-model blev fundet. Start Ollama og pull fx qwen3:8b.")


def ensure_backend() -> None:
    if endpoint_ok(f"{BACKEND_URL}/healthz"):
        return
    model = planner_model()
    note("Backend mangler; starter den eksisterende exact-head validation-stack.")
    run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(ROOT / "scripts" / "start-stage-a-validation-stack.ps1"),
            "-PlannerModel",
            model,
            "-ValidationReport",
            str(AGENT3_REPORT),
        ]
    )
    wait_endpoint(f"{BACKEND_URL}/healthz")


def wait_port_free(port: int, *, timeout: float = 300.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        command = (
            f"$x=Get-NetTCPConnection -State Listen -LocalPort {port} "
            "-ErrorAction SilentlyContinue | Select-Object -First 1; "
            "if($null -eq $x){exit 0}else{exit 1}"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            cwd=ROOT,
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(1.0)
    raise PilotError(f"Port {port} blev ikke frigivet inden for fem minutter.")


def controlled_worker_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(ROOT / "worker"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "KALIV_SCHEDULER": "1",
            "KALIV_SCHEDULER_API": "1",
            "KALIV_TOOLS_ENABLED": "1",
            "KALIV_SCHEDULER_POLL_S": str(POLL_SECONDS),
            "KALIV_SCHEDULES_DB": str(SCHEDULES_DB),
            "MODELRIG_JOBS_DB": str(JOBS_DB),
            "KALIV_AUDIT_DB": str(AUDIT_DB),
        }
    )
    return env


def start_controlled_worker() -> tuple[subprocess.Popen[bytes], Any]:
    VALIDATION.mkdir(parents=True, exist_ok=True)
    log = LOG_PATH.open("ab", buffering=0)
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.entrypoint:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8099",
        ],
        cwd=ROOT,
        env=controlled_worker_env(),
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=flags,
    )
    try:
        wait_endpoint(f"{WORKER_URL}/healthz", timeout=90.0)
        wait_for_first_tick(timeout=20.0)
    except Exception:
        process.kill()
        process.wait(timeout=10)
        log.close()
        raise
    return process, log


def stop_worker(process: subprocess.Popen[bytes], log: Any, *, abrupt: bool) -> None:
    if process.poll() is None:
        if abrupt:
            process.kill()
        else:
            try:
                process.send_signal(signal.CTRL_BREAK_EVENT)
            except (AttributeError, OSError, ValueError):
                process.terminate()
        try:
            process.wait(timeout=15.0 if not abrupt else 5.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5.0)
    log.close()


def replace_existing_worker() -> tuple[subprocess.Popen[bytes], Any]:
    if endpoint_ok(f"{WORKER_URL}/healthz"):
        heading("Én manuel handling: luk det gamle worker-vindue")
        print("  Backend må gerne blive kørende. Wizard'en fortsætter selv, når port 8099 er fri.")
        wait_port_free(8099)
    wait_for_lease_expiry()
    return start_controlled_worker()


def schedule_status() -> dict[str, Any]:
    payload = request_json(f"{WORKER_URL}/schedules/status")
    if not isinstance(payload, dict):
        raise PilotError("Scheduler-status havde forkert format.")
    return payload


def wait_for_first_tick(*, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = schedule_status()
        if status.get("running") and int(status.get("accepted_ticks") or 0) >= 1:
            return
        time.sleep(0.25)
    raise PilotError("Scheduler-servicen startede, men intet tick blev observeret.")


def schedules() -> list[dict[str, Any]]:
    payload = request_json(f"{WORKER_URL}/schedules")
    rows = payload.get("schedules", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        raise PilotError("Schedule-listen havde forkert format.")
    return [row for row in rows if isinstance(row, dict)]


def schedule_id(row: dict[str, Any]) -> str:
    return str(row.get("schedule_id") or row.get("id") or "")


def matches_manifest(row: dict[str, Any], spec: dict[str, Any]) -> bool:
    return (
        row.get("tool") == spec["tool"]
        and row.get("args") == spec["args"]
        and row.get("cadence") == spec["cadence"]
        and int(row.get("max_runs") or -1) == int(spec["max_runs"])
    )


def detail(schedule_id_value: str) -> dict[str, Any]:
    payload = request_json(f"{WORKER_URL}/schedules/{schedule_id_value}")
    if not isinstance(payload, dict):
        raise PilotError(f"Schedule {schedule_id_value} havde forkert format.")
    return payload


def schedule_view(payload: dict[str, Any]) -> dict[str, Any]:
    nested = payload.get("schedule")
    return nested if isinstance(nested, dict) else payload


def set_enabled(schedule_id_value: str, enabled: bool) -> dict[str, Any]:
    payload = request_json(
        f"{WORKER_URL}/schedules/{schedule_id_value}/enabled",
        method="POST",
        body={"enabled": enabled},
    )
    return payload if isinstance(payload, dict) else {}


def pause_preexisting(state: dict[str, Any]) -> None:
    if "preexisting_ids" in state:
        return
    rows = schedules()
    state["preexisting_ids"] = [schedule_id(row) for row in rows if schedule_id(row)]
    paused: list[str] = []
    for row in rows:
        sid = schedule_id(row)
        if sid and row.get("enabled"):
            set_enabled(sid, False)
            paused.append(sid)
    state["preexisting_paused"] = paused
    save_state(state)
    if paused:
        ok(f"{len(paused)} eksisterende plan(er) er midlertidigt pauset.")


def restore_preexisting(state: dict[str, Any]) -> None:
    for sid in state.get("preexisting_paused", []):
        try:
            set_enabled(str(sid), True)
        except PilotError:
            note(f"Kunne ikke genaktivere tidligere plan {sid}; kontrollér den manuelt.")


def create_read(state: dict[str, Any]) -> str:
    existing = str(state.get("read_schedule_id") or "")
    if existing:
        try:
            if matches_manifest(schedule_view(detail(existing)), READ_SPEC):
                return existing
        except PilotError:
            pass
    request_json(f"{WORKER_URL}/schedules/preview", method="POST", body=READ_SPEC)
    created = request_json(f"{WORKER_URL}/schedules", method="POST", body=READ_SPEC)
    payload = created if isinstance(created, dict) else {}
    sid = schedule_id(payload) or schedule_id(schedule_view(payload))
    if not sid:
        raise PilotError("Read-planen returnerede intet schedule_id.")
    state["read_schedule_id"] = sid
    save_state(state)
    return sid


def wait_for_write(state: dict[str, Any], *, timeout: float = 900.0) -> str:
    existing = str(state.get("write_schedule_id") or "")
    if existing:
        try:
            if matches_manifest(schedule_view(detail(existing)), WRITE_SPEC):
                return existing
        except PilotError:
            pass

    baseline = set(state.get("preexisting_ids", []))
    baseline.add(str(state.get("read_schedule_id") or ""))
    heading("Android: godkend den ene kanoniske write-plan")
    print("  Wizard'en finder selv ID'et. Opret præcis:")
    print('    note_append · {"text":"pilot"} · every:60 · max_runs=2 · ttl_days=1')
    print("  Tryk Godkend i appen. Du skal ikke kopiere noget tilbage hertil.")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        matches: list[dict[str, Any]] = []
        for row in schedules():
            sid = schedule_id(row)
            if not sid or sid in baseline or not matches_manifest(row, WRITE_SPEC):
                continue
            receipts = detail(sid).get("approval_receipts")
            if isinstance(receipts, list) and receipts:
                matches.append(row)
        ids = sorted({schedule_id(row) for row in matches if schedule_id(row)})
        if len(ids) == 1:
            state["write_schedule_id"] = ids[0]
            save_state(state)
            return ids[0]
        if len(ids) > 1:
            raise PilotError(f"Flere nye kanoniske write-planer blev fundet: {ids}")
        time.sleep(2.0)
    raise PilotError("Write-planen blev ikke fundet inden for 15 minutter.")


def wait_runs(schedule_id_value: str, minimum: int, *, timeout: float = 150.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = detail(schedule_id_value)
        view = schedule_view(payload)
        if int(view.get("runs_used") or 0) >= minimum:
            return payload
        time.sleep(1.0)
    raise PilotError(f"Schedule {schedule_id_value} nåede ikke runs_used={minimum}.")


def db_rows(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    conn = sqlite3.connect(f"file:{SCHEDULES_DB}?mode=ro", uri=True, timeout=1.0)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(query, params)]
    finally:
        conn.close()


def occurrence_ids(schedule_id_value: str) -> set[str]:
    return {
        str(row["claim_id"])
        for row in db_rows(
            "SELECT claim_id FROM occurrences WHERE schedule_id=?",
            (schedule_id_value,),
        )
    }


def reserved_after(schedule_id_value: str, before: set[str]) -> dict[str, Any] | None:
    rows = db_rows(
        "SELECT claim_id, status, created, job_id FROM occurrences "
        "WHERE schedule_id=? ORDER BY created DESC",
        (schedule_id_value,),
    )
    for row in rows:
        if str(row.get("claim_id")) not in before and row.get("status") == "reserved":
            return row
    return None


def lease_until() -> float:
    try:
        rows = db_rows("SELECT lease_until FROM runner_lease WHERE id=1")
    except sqlite3.Error:
        return time.time()
    return float(rows[0]["lease_until"]) if rows else time.time()


def wait_for_lease_expiry() -> None:
    expiry = lease_until()
    if expiry > time.time():
        note(f"Venter {max(0, int(expiry - time.time()))} sekunder på schedulerens owner-lease.")
        wait_until(expiry + 1.0)


@contextmanager
def lock_job_store() -> Iterator[None]:
    conn = sqlite3.connect(str(JOBS_DB), timeout=0.2, isolation_level=None)
    try:
        conn.execute("BEGIN EXCLUSIVE")
        yield
    finally:
        try:
            conn.rollback()
        finally:
            conn.close()


def wait_until(epoch: float) -> None:
    while True:
        remaining = epoch - time.time()
        if remaining <= 0:
            return
        time.sleep(min(1.0, remaining))


def prepare_aligned_schedule(schedule_id_value: str) -> tuple[float, set[str], int]:
    wait_for_first_tick(timeout=20.0)
    before = occurrence_ids(schedule_id_value)
    prior_runs = int(schedule_view(detail(schedule_id_value)).get("runs_used") or 0)
    enabled_payload = set_enabled(schedule_id_value, True)
    due = float(schedule_view(enabled_payload).get("due_at") or 0)
    if due <= time.time():
        due = float(schedule_view(detail(schedule_id_value)).get("due_at") or 0)
    if due <= time.time():
        raise PilotError("Kunne ikke læse en fremtidig due_at efter aktivering.")
    return due, before, prior_runs


def wait_occurrence(claim_id: str, status: str, *, timeout: float = 20.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = db_rows(
            "SELECT claim_id, schedule_id, status, job_id, resolved "
            "FROM occurrences WHERE claim_id=?",
            (claim_id,),
        )
        if rows and rows[0].get("status") == status:
            return rows[0]
        time.sleep(0.2)
    raise PilotError(f"Occurrence {claim_id} nåede ikke status {status}.")


def job_row(job_id: str) -> dict[str, Any] | None:
    conn = sqlite3.connect(f"file:{JOBS_DB}?mode=ro", uri=True, timeout=1.0)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT id, status, detail FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def catch_claim_and_pause(schedule_id_value: str, due: float, before: set[str]) -> dict[str, Any]:
    wait_until(due + 2.5)
    claim = None
    with lock_job_store():
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            claim = reserved_after(schedule_id_value, before)
            if claim is not None:
                set_enabled(schedule_id_value, False)
                break
            time.sleep(0.02)
    if claim is None:
        raise PilotError("Revocation-claim blev ikke fanget; kør wizard'en igen.")
    return claim


def catch_claim_and_crash(
    process: subprocess.Popen[bytes],
    log: Any,
    schedule_id_value: str,
    due: float,
    before: set[str],
) -> dict[str, Any]:
    wait_until(due + 2.5)
    claim = None
    with lock_job_store():
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            claim = reserved_after(schedule_id_value, before)
            if claim is not None:
                stop_worker(process, log, abrupt=True)
                break
            time.sleep(0.02)
    if claim is None:
        raise PilotError("Crash-claim blev ikke fanget; kør wizard'en igen.")
    return claim


def run_revocation(
    process: subprocess.Popen[bytes],
    log: Any,
    read_id: str,
) -> tuple[subprocess.Popen[bytes], Any]:
    heading("Automatisk revocation-bevis")
    stop_worker(process, log, abrupt=False)
    wait_for_lease_expiry()
    process, log = start_controlled_worker()
    due, before, prior_runs = prepare_aligned_schedule(read_id)
    claim = catch_claim_and_pause(read_id, due, before)

    resolved = wait_occurrence(str(claim["claim_id"]), "released")
    if not resolved.get("job_id"):
        raise PilotError("Revocation-occurrence blev released uden job-binding.")
    job = job_row(str(resolved["job_id"]))
    if not job or job.get("status") != "cancelled":
        raise PilotError("Revocation-jobbet blev ikke cancelled.")
    detail_text = str(job.get("detail") or "").lower()
    if "pauset" not in detail_text and "ændret eller slettet" not in detail_text:
        raise PilotError("Revocation-jobbet mangler den forventede danske grund.")
    runs_after = int(schedule_view(detail(read_id)).get("runs_used") or 0)
    if runs_after != prior_runs:
        raise PilotError(
            f"Revocation refunderede ikke budgettet ({prior_runs} -> {runs_after})."
        )
    ok("Claim blev released, jobbet cancelled og budget-slotten refunderet.")
    return process, log


def wait_for_recovery_line(offset: int, *, timeout: float = 30.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            raw = LOG_PATH.read_bytes()[offset:]
        except OSError:
            raw = b""
        text = raw.decode("utf-8", errors="replace")
        matches = RECOVERY_RE.findall(text)
        if matches:
            return matches[-1]
        time.sleep(0.25)
    raise PilotError("Worker-loggen indeholdt ingen genkendelig recovery-linje.")


def run_crash_recovery(
    process: subprocess.Popen[bytes],
    log: Any,
    read_id: str,
) -> tuple[subprocess.Popen[bytes], Any, str]:
    heading("Automatisk crash/restart/recovery-bevis")
    stop_worker(process, log, abrupt=False)
    wait_for_lease_expiry()
    process, log = start_controlled_worker()
    due, before, _ = prepare_aligned_schedule(read_id)
    claim = catch_claim_and_crash(process, log, read_id, due, before)

    wait_for_lease_expiry()

    offset = LOG_PATH.stat().st_size if LOG_PATH.is_file() else 0
    process, log = start_controlled_worker()
    recovery_line = wait_for_recovery_line(offset)
    wait_occurrence(str(claim["claim_id"]), "abandoned", timeout=30.0)
    set_enabled(read_id, False)
    ok(recovery_line)
    return process, log, recovery_line


def write_manual(recovery_line: str) -> None:
    VALIDATION.mkdir(parents=True, exist_ok=True)
    MANUAL_PATH.write_text(
        json.dumps(
            {
                "revocation_confirmed": True,
                "recovery_line": recovery_line,
                "operator": os.environ.get("USERNAME") or "Anders",
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def generate_report(read_id: str, write_id: str) -> None:
    run(
        [
            sys.executable,
            str(ROOT / "scripts" / "scheduler_pilot_report.py"),
            "--worker-url",
            WORKER_URL,
            "--read-schedule-id",
            read_id,
            "--write-schedule-id",
            write_id,
            "--manual-observations",
            str(MANUAL_PATH),
            "--schedules-db",
            str(SCHEDULES_DB),
            "--jobs-db",
            str(JOBS_DB),
            "--audit-db",
            str(AUDIT_DB),
            "--report",
            str(REPORT_PATH),
        ]
    )


def main() -> int:
    os.chdir(ROOT)
    heading("Kaliv T-019 — lettest mulige fysiske scheduler-pilot")
    print("  Den eneste uundgåelige manuelle handling er Android-godkendelsen.")
    print("  Wizard'en kan ikke mint'e en write-token, merge, pushe, release eller aktivere.")

    process: subprocess.Popen[bytes] | None = None
    log: Any = None
    state = load_state()
    try:
        sha = ensure_checkout()
        reset_state_for_sha(state, sha)
        if existing_report_passed(sha):
            heading("T-019 ER ALLEREDE BESTÅET")
            ok(f"Rapport: {REPORT_PATH}")
            ok(f"Exact SHA: {sha}")
            return 0
        ensure_backend()
        process, log = replace_existing_worker()
        pause_preexisting(state)

        read_id = create_read(state)
        ok(f"Read-plan: {read_id}")
        wait_runs(read_id, 1)
        set_enabled(read_id, False)
        ok("Read-planen kørte uden approval og blev pauset efter første execution.")

        process, log = run_revocation(process, log, read_id)
        process, log, recovery_line = run_crash_recovery(process, log, read_id)

        # Create the write grant last. The exact max_runs=2 grant therefore has
        # time for one real execution and its report, but not a later cadence
        # that would mutate the pilot state before evidence is frozen.
        write_id = wait_for_write(state)
        ok(f"Write-plan fundet automatisk: {write_id}")
        wait_runs(write_id, 1)
        ok("Write-planen kørte under sin device-bundne approval.")

        write_manual(recovery_line)
        generate_report(read_id, write_id)
        set_enabled(write_id, False)
        restore_preexisting(state)

        heading("T-019 PILOT BESTÅET")
        ok(f"Rapport: {REPORT_PATH}")
        ok(f"Exact SHA: {sha}")
        print("  Worker-processen bliver stående, så rapport/API kan inspiceres.")
        return 0
    except (PilotError, KeyboardInterrupt) as exc:
        print(f"\n  STOP  {exc}")
        print("  Dobbeltklik igen. Kandidat, plan-ID'er og rapportfiler genbruges sikkert.")
        return 1
    finally:
        if process is not None and process.poll() is not None and log is not None:
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
