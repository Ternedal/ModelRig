#!/usr/bin/env python3
"""One-click Windows operator for the physical T-022 append-only write pilot.

The wizard automates reproducible setup and forensic bookkeeping only:
candidate checkout, local stack configuration, rig validation, manifest
preparation, read-only preflight, Android/desktop launching, GET verification,
single-use run binding, append-only negative journaling and final collection.

It never sends an approval, confirmation, write, retry, cancel or replan request.
Every physical action remains human-operated on the paired device/client. It
never merges, pushes, tags, releases or activates production.
"""
from __future__ import annotations

import argparse
import copy
import getpass
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
VALIDATION = ROOT / "validation"
MANIFEST = VALIDATION / "agent3-write-pilot-manifest.json"
PREFLIGHT = VALIDATION / "agent3-write-pilot-preflight.json"
JOURNAL = VALIDATION / "agent3-write-pilot-negative-journal.db"
NEGATIVE = VALIDATION / "agent3-write-pilot-negative.json"
REPORT = VALIDATION / "agent3-write-pilot-latest.json"
STATE = VALIDATION / "agent3-write-pilot-operator-state.json"
RIG_REPORT = VALIDATION / "agent3-rig-validation-latest.json"
RESPONSE_DIR = VALIDATION / "agent3-write-pilot-responses"
BRANCH = "agent/t022-write-pilot-operator"
VERSION = "1.58.146"
BASE_URL = "http://127.0.0.1:8080"
ANDROID_PACKAGE = "dk.ternedal.modelrig"
ANDROID_ACTIVITY = f"{ANDROID_PACKAGE}/.MainActivity"
ANDROID_AGENT3_EXTRA = "dk.ternedal.modelrig.extra.AGENT3"
STATE_SCHEMA = "kaliv-agent3-write-pilot-operator/v1"
POSITIVE_ATTEST_PREFIX = "APPEND T022"
PREVIEW_ATTEST_PREFIX = "PREVIEW T022"
NEGATIVE_START_PREFIX = "START NEGATIVE"
NEGATIVE_DONE_PREFIX = "DONE NEGATIVE"

sys.path.insert(0, str(SCRIPTS))
import stage_a_one_click as stage  # noqa: E402
import agent3_write_pilot_common as common  # noqa: E402
import agent3_write_pilot_journal_cases as journal_cases  # noqa: E402
import agent3_write_pilot_journal_store as journal_store  # noqa: E402
import agent3_write_pilot_preflight as preflight  # noqa: E402
import agent3_write_pilot_report as pilot_report  # noqa: E402


class OperatorError(RuntimeError):
    pass


@dataclass(frozen=True)
class PilotPaths:
    data_root: Path
    agent_db: Path
    approval_db: Path
    audit_db: Path
    tools_dir: Path
    notes: Path


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def iso_now() -> str:
    return common._iso(common._utc_now())


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    common._atomic_json(path, dict(value))


def run(
    args: list[str],
    *,
    cwd: Path = ROOT,
    check: bool = True,
    capture: bool = False,
    binary: bool = False,
) -> subprocess.CompletedProcess[Any]:
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            env=os.environ.copy(),
            text=not binary,
            capture_output=capture,
            check=False,
            timeout=900,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OperatorError(f"Kunne ikke køre {args[0]}: {exc}") from exc
    if check and result.returncode != 0:
        detail = ""
        if capture:
            output = result.stderr or result.stdout
            if isinstance(output, bytes):
                detail = output.decode("utf-8", errors="replace")
            else:
                detail = output or ""
        raise OperatorError(
            f"Kommandoen fejlede ({result.returncode}): {' '.join(args)}"
            + (f"\n{detail[-1200:]}" if detail else "")
        )
    return result


def prompt(message: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"  {message}{suffix}: ").strip()
    return value or (default or "")


def require_phrase(expected: str) -> None:
    entered = input(f"  Skriv præcis '{expected}' for at attestere: ").strip()
    if entered != expected:
        raise OperatorError("Attesteringen matchede ikke; evidensen forbliver ufuldstændig.")


def prompt_secret(name: str, minimum: int = 1) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        value = getpass.getpass(f"  Indsæt {name} (skjult, gemmes ikke): ").strip()
    if len(value) < minimum:
        raise OperatorError(f"{name} er tom eller for kort.")
    os.environ[name] = value
    return value


def data_root() -> Path:
    explicit = os.environ.get("KALIV_DATA_DIR", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        return (Path(local) / "Kaliv").resolve()
    return (Path.home() / "AppData" / "Local" / "Kaliv").resolve()


def path_from_env(label: str, env_name: str, default: Path, *, directory: bool = False) -> Path:
    raw = os.environ.get(env_name, "").strip()
    chosen = prompt(label, raw or str(default))
    path = Path(chosen).expanduser().resolve()
    if directory:
        path.mkdir(parents=True, exist_ok=True)
    elif not path.parent.is_dir():
        raise OperatorError(f"Parent-mappen findes ikke for {label}: {path.parent}")
    os.environ[env_name] = str(path)
    return path


def resolve_paths() -> PilotPaths:
    root = data_root()
    root.mkdir(parents=True, exist_ok=True)
    agent_db = path_from_env(
        "Agent 3 run-database", "KALIV_AGENT3_DB", root / "kaliv-agent3.db"
    )
    approval_db = path_from_env(
        "Approval-use-database",
        "KALIV_AGENT3_APPROVAL_DB",
        root / "kaliv-agent3-approvals.db",
    )
    audit_db = path_from_env(
        "ToolGate audit-database", "KALIV_AUDIT_DB", root / "kaliv-audit.db"
    )
    tools_default = Path.home() / "Documents" / "Kaliv"
    tools_dir = path_from_env(
        "KALIV_TOOLS_DIR", "KALIV_TOOLS_DIR", tools_default, directory=True
    )
    notes = tools_dir / "notes.md"
    if not notes.exists():
        notes.touch()
    return PilotPaths(root, agent_db, approval_db, audit_db, tools_dir, notes)


def ensure_candidate() -> str:
    stage.BRANCH = BRANCH
    stage.VERSION = VERSION
    sha = stage.ensure_candidate()
    identity = common.candidate_identity(ROOT)
    if (
        identity.get("git_sha") != sha
        or identity.get("version") != VERSION
        or identity.get("working_tree_clean") is not True
        or identity.get("version_stamps_consistent") is not True
    ):
        raise OperatorError("Kandidatidentiteten er ikke ren og exact-head-bundet.")
    return sha


def configure_environment(paths: PilotPaths) -> None:
    prompt_secret("MODELRIG_TOKEN")
    prompt_secret("KALIV_AGENT3_APPROVAL_SECRET", minimum=32)
    os.environ.update(
        {
            "KALIV_AGENT3_ENABLED": "1",
            "KALIV_AGENT3_APPROVAL_REQUIRED": "1",
            "KALIV_TOOLS_ENABLED": "1",
            "KALIV_AGENT3_VALIDATION_REPORT": str(RIG_REPORT),
            "KALIV_AGENT3_DB": str(paths.agent_db),
            "KALIV_AGENT3_APPROVAL_DB": str(paths.approval_db),
            "KALIV_AUDIT_DB": str(paths.audit_db),
            "KALIV_TOOLS_DIR": str(paths.tools_dir),
            "MODELRIG_BASE_URL": BASE_URL,
        }
    )


def request_json(path: str) -> dict[str, Any]:
    token = os.environ.get("MODELRIG_TOKEN", "").strip()
    if not token:
        raise OperatorError("MODELRIG_TOKEN mangler.")
    request = urllib.request.Request(BASE_URL + path, method="GET")
    request.add_header("Accept", "application/json")
    request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(2_000_001)
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read(2_000_001)
        status = exc.code
    except (urllib.error.URLError, OSError) as exc:
        raise OperatorError(f"Kunne ikke læse {path}: {exc}") from exc
    if len(raw) > 2_000_000:
        raise OperatorError(f"GET {path} returnerede for mange bytes.")
    if status != 200:
        raise OperatorError(
            f"GET {path} returnerede HTTP {status}: "
            + raw.decode("utf-8", errors="replace")[:500]
        )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OperatorError(f"GET {path} returnerede ikke UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise OperatorError(f"GET {path} returnerede ikke et JSON-objekt.")
    return value


def ensure_stack_and_rig_validation(paths: PilotPaths) -> None:
    planner = stage.ensure_models()
    stage.ensure_device_token()
    stage.heading("Start exact-head T-022 stack")
    stage.note(
        "Stacken startes lokalt med Agent 3, approval-required og Tools. "
        "Preflighten kræver stadig, at kun note_append er aktiv write-capability."
    )
    stage.start_stack(planner)

    identity = common.candidate_identity(ROOT)
    if MANIFEST.is_file():
        stage.heading("Genbrug manifestbundet rig-validation")
        if not RIG_REPORT.is_file():
            raise OperatorError(
                "Manifestet findes, men den bundne rig-validation-rapport mangler."
            )
        assessment, digest = common.assess_rig_validation(
            RIG_REPORT, identity, now=common._utc_now().timestamp()
        )
        manifest, _raw = common._load_json(MANIFEST)
        target = manifest.get("target") if isinstance(manifest.get("target"), dict) else {}
        if target.get("rig_validation_report_sha256") != digest:
            raise OperatorError(
                "Rig-validation-rapporten ændrede sig efter manifest preparation."
            )
        stage.ok("Den oprindelige rig-validation SHA genbruges uændret.")
    else:
        stage.heading("Kør kandidatbundet rig-validation")
        run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(SCRIPTS / "run-agent3-rig-validation.ps1"),
                "-BaseUrl",
                BASE_URL,
                "-PlannerModel",
                planner,
            ]
        )
        assessment, _digest = common.assess_rig_validation(
            RIG_REPORT, identity, now=common._utc_now().timestamp()
        )

    if assessment.get("eligible_for_write_pilot") is not True:
        raise OperatorError(
            "Rig-validation er ikke eligible_for_write_pilot. "
            "Ret de viste blockers før T-022 fortsættes."
        )
    ensure_approval_store(paths.approval_db)
    for path in (paths.agent_db, paths.audit_db, paths.notes):
        if not path.exists():
            raise OperatorError(f"Forventet evidensfil findes ikke efter stackstart: {path}")


def find_adb() -> str:
    adb = shutil.which("adb")
    if not adb:
        raise OperatorError("adb blev ikke fundet på PATH. Installer Android Platform Tools.")
    return adb


def android_device(adb: str) -> tuple[str, str]:
    result = run([adb, "devices"], capture=True)
    devices = [
        line.split("\t", 1)[0]
        for line in result.stdout.splitlines()[1:]
        if "\tdevice" in line
    ]
    if len(devices) != 1:
        raise OperatorError(f"Der skal være præcis én ADB-enhed; fandt {len(devices)}.")
    model = run([adb, "shell", "getprop", "ro.product.model"], capture=True).stdout.strip()
    release = run(
        [adb, "shell", "getprop", "ro.build.version.release"], capture=True
    ).stdout.strip()
    return model or devices[0], release or "unknown"


def build_install_android(adb: str) -> None:
    gradlew = ROOT / "android" / "gradlew.bat"
    if not gradlew.is_file():
        raise OperatorError("android\\gradlew.bat mangler.")
    stage.heading("Byg og installer exact-head Android-klienten")
    run([str(gradlew), ":app:assembleDebug"], cwd=ROOT / "android")
    apk = (
        ROOT
        / "android"
        / "app"
        / "build"
        / "outputs"
        / "apk"
        / "debug"
        / "app-debug.apk"
    )
    if not apk.is_file():
        raise OperatorError(f"APK mangler efter build: {apk}")
    run([adb, "install", "-r", str(apk)])
    stage.ok(f"Installeret {apk.name}.")


def launch_android_agent3(adb: str) -> None:
    run(
        [
            adb,
            "shell",
            "am",
            "start",
            "-S",
            "-n",
            ANDROID_ACTIVITY,
            "--ez",
            ANDROID_AGENT3_EXTRA,
            "true",
        ]
    )


def launch_desktop_agent3() -> None:
    gradlew = ROOT / "desktop" / "gradlew.bat"
    if not gradlew.is_file():
        raise OperatorError("desktop\\gradlew.bat mangler.")
    subprocess.Popen(
        [str(gradlew), ":composeApp:run", "--args=--agent3"],
        cwd=ROOT / "desktop",
        env=os.environ.copy(),
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )


def load_manifest() -> dict[str, Any]:
    value, _raw = common._load_json(MANIFEST)
    errors = common.validate_manifest(value, require_bound=False)
    if errors:
        raise OperatorError("Manifestet er ugyldigt: " + "; ".join(errors))
    identity = common.candidate_identity(ROOT)
    target = value.get("target") if isinstance(value.get("target"), dict) else {}
    for field in ("version", "git_sha", "code_sha256", "identity_source"):
        if target.get(field) != identity.get(field):
            raise OperatorError(f"Manifestets kandidat-{field} matcher ikke checkoutet.")
    return value


def prepared_manifest_sha(manifest: Mapping[str, Any]) -> str:
    """Hash the exact pre-bind manifest representation used by _atomic_json."""
    normalized = copy.deepcopy(dict(manifest))
    runs = normalized.get("runs")
    if isinstance(runs, list):
        for item in runs:
            if isinstance(item, dict):
                item["run_id"] = None
                item["bound_at"] = None
    raw = (
        json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    return sha256_bytes(raw)


def ensure_approval_store(path: Path) -> None:
    """Create only the canonical empty approval-use table when the rig is pristine."""
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise OperatorError(f"Approval-databasen er uregelmæssig: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """CREATE TABLE agent3_approval_uses (
                   nonce_sha256 TEXT PRIMARY KEY,
                   action_sha256 TEXT NOT NULL UNIQUE,
                   used_at REAL NOT NULL,
                   run_id TEXT NOT NULL,
                   step_id TEXT NOT NULL,
                   device_id TEXT NOT NULL,
                   plan_revision INTEGER NOT NULL,
                   token_sha256 TEXT NOT NULL
               )"""
        )
        conn.commit()
    stage.note("Oprettede en tom kanonisk approval-use-database til preflight-baseline.")


def initial_state(identity: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": STATE_SCHEMA,
        "updated_at": iso_now(),
        "candidate": {
            key: identity.get(key)
            for key in ("version", "git_sha", "code_sha256", "identity_source")
        },
        "manifest_sha256": None,
        "preflight_sha256": None,
        "positive_completed": [],
        "negative_completed": [],
        "report_success": False,
        "advisory_only": True,
        "production_activation": False,
    }


def load_state() -> dict[str, Any]:
    if not STATE.is_file():
        return initial_state(common.candidate_identity(ROOT))
    value, _raw = common._load_json(STATE)
    if value.get("schema") != STATE_SCHEMA:
        raise OperatorError("Operator-state har ukendt schema.")
    if value.get("production_activation") is not False:
        raise OperatorError("Operator-state må aldrig aktivere produktion.")
    identity = common.candidate_identity(ROOT)
    for field in ("version", "git_sha", "code_sha256", "identity_source"):
        if (value.get("candidate") or {}).get(field) != identity.get(field):
            raise OperatorError(f"Operator-state tilhører en anden kandidat ({field}).")
    return value


def save_state(value: dict[str, Any]) -> None:
    value["updated_at"] = iso_now()
    value["advisory_only"] = True
    value["production_activation"] = False
    atomic_json(STATE, value)


def prepare_and_preflight(paths: PilotPaths) -> dict[str, Any]:
    state = load_state()
    if not MANIFEST.exists():
        stage.heading("Forbered 20 kandidatbundne append-markører")
        run(
            [
                sys.executable,
                str(SCRIPTS / "agent3_write_pilot_report.py"),
                "prepare",
                "--operator",
                prompt("Operatørnavn", os.environ.get("USERNAME", "Anders")),
                "--rig-validation",
                str(RIG_REPORT),
                "--manifest",
                str(MANIFEST),
            ]
        )
    manifest = load_manifest()
    manifest_raw = MANIFEST.read_bytes()
    bound = [
        item.get("ordinal")
        for item in manifest.get("runs", [])
        if isinstance(item, dict) and item.get("run_id")
    ]

    if not bound:
        if JOURNAL.exists():
            raise OperatorError(
                "Negativjournalen findes før preflight. Arkivér hele T-022-kampagnen "
                "og start med et nyt manifest; wizard'en sletter aldrig evidens."
            )
        stage.heading("Kør read-only T-022 preflight")
        report = preflight.run_preflight(
            manifest_path=MANIFEST,
            rig_validation_path=RIG_REPORT,
            agent_db=paths.agent_db,
            approval_db=paths.approval_db,
            audit_db=paths.audit_db,
            notes_path=paths.notes,
            negative_journal_path=JOURNAL,
            base_url=BASE_URL,
            token=os.environ["MODELRIG_TOKEN"],
        )
        atomic_json(PREFLIGHT, report)
        if not report.get("success"):
            print("  PREFLIGHT BLOKERET:")
            for blocker in report.get("blockers", []):
                print(f"    - {blocker}")
            raise OperatorError("T-022 preflight er rød.")
        stage.ok("Preflight er grøn; negativjournalen oprettes først efter 20/20 bindinger.")
    else:
        if not PREFLIGHT.is_file():
            raise OperatorError("Manifestet er i brug, men preflight-rapporten mangler.")
        report, _raw = common._load_json(PREFLIGHT)
        if report.get("schema") != preflight.PREFLIGHT_SCHEMA or report.get("success") is not True:
            raise OperatorError("Den bevarede preflight er ikke grøn.")
        if report.get("evidence", {}).get("manifest_sha256") != prepared_manifest_sha(manifest):
            raise OperatorError("Manifestets forberedte indhold ændrede sig efter den grønne preflight.")
        if JOURNAL.exists() and len(bound) != 20:
            raise OperatorError(
                "Negativjournalen findes før alle 20 positive runs er bundet; "
                "kampagnerækkefølgen er ugyldig."
            )
        if JOURNAL.is_file():
            journal_cases.verify_journal_binding(JOURNAL, manifest, manifest_raw)
        stage.note(f"Genoptager eksisterende pilot; {len(bound)}/20 positive runs er bundet.")

    state["manifest_sha256"] = prepared_manifest_sha(manifest)
    state["preflight_sha256"] = sha256_bytes(PREFLIGHT.read_bytes())
    state["positive_completed"] = sorted(int(value) for value in bound)
    save_state(state)
    return manifest


def note_count(notes: Path, marker: str) -> int:
    if not notes.is_file():
        return 0
    text = notes.read_text(encoding="utf-8")
    return text.splitlines().count(marker)


def approval_total(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        row = conn.execute("SELECT COUNT(*) FROM agent3_approval_uses").fetchone()
    return int(row[0]) if row else 0


def approval_count_for_run(path: Path, run_id: str) -> int:
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM agent3_approval_uses WHERE run_id=?", (run_id,)
        ).fetchone()
    return int(row[0]) if row else 0


def audit_count_for_marker(path: Path, marker: str) -> int:
    count = 0
    with sqlite3.connect(path) as conn:
        rows = conn.execute(
            "SELECT args_json, outcome FROM audit WHERE tool='note_append'"
        ).fetchall()
    for args_json, outcome in rows:
        try:
            args = json.loads(args_json)
        except (TypeError, json.JSONDecodeError):
            continue
        if outcome == "executed" and args == {"text": marker}:
            count += 1
    return count


def verify_positive_live(paths: PilotPaths, ordinal: int, marker: str, run_id: str) -> None:
    encoded = urllib.parse.quote(run_id, safe="")
    payload = request_json(f"/api/v1/experimental/agent3/runs/{encoded}")
    run_value = payload.get("run") if isinstance(payload.get("run"), dict) else payload
    if run_value.get("id") != run_id or run_value.get("state") != "completed":
        raise OperatorError(f"Run {ordinal} er ikke completed på serveren.")
    route = run_value.get("route")
    if not isinstance(route, dict) or route.get("kind") != "rig_tools_local":
        raise OperatorError(f"Run {ordinal} har ikke route=rig_tools_local.")
    steps = run_value.get("steps")
    if not isinstance(steps, list) or len(steps) != 1:
        raise OperatorError(f"Run {ordinal} har ikke præcis ét step.")
    step = steps[0] if isinstance(steps[0], dict) else {}
    if (
        step.get("tool") != "note_append"
        or step.get("args") != {"text": marker}
        or step.get("state") != "succeeded"
    ):
        raise OperatorError(f"Run {ordinal} matcher ikke det eksakte note_append-step.")
    events_payload = request_json(
        f"/api/v1/experimental/agent3/runs/{encoded}/events?limit=200"
    )
    events = events_payload.get("events")
    if not isinstance(events, list):
        raise OperatorError(f"Run {ordinal} har ingen eventliste.")
    kinds = [item.get("kind") for item in events if isinstance(item, dict)]
    required = {
        "approval_consumed",
        "confirmation_approved",
        "step_started",
        "step_succeeded",
        "run_completed",
    }
    missing = sorted(required - set(kinds))
    if missing:
        raise OperatorError(f"Run {ordinal} mangler events: {', '.join(missing)}")
    if note_count(paths.notes, marker) != 1:
        raise OperatorError(f"Run {ordinal} har ikke præcis én markør i notes.md.")
    if approval_count_for_run(paths.approval_db, run_id) != 1:
        raise OperatorError(f"Run {ordinal} har ikke præcis én approval-use-række.")
    if audit_count_for_marker(paths.audit_db, marker) != 1:
        raise OperatorError(f"Run {ordinal} har ikke præcis én executed audit-række.")


def run_positive_phase(paths: PilotPaths, adb: str) -> None:
    launch_android_agent3(adb)
    launch_desktop_agent3()
    while True:
        manifest = load_manifest()
        pending = [
            item
            for item in manifest.get("runs", [])
            if isinstance(item, dict) and not item.get("run_id")
        ]
        if not pending:
            stage.ok("Alle 20 positive runs er bundet.")
            break
        item = pending[0]
        ordinal = int(item["ordinal"])
        marker = str(item["marker"])
        stage.heading(f"POSITIVT APPEND {ordinal:02d}/20")
        print(f"  Brug denne tekst som hele note_append.text:\n\n    {marker}\n")
        print("  Kontrollér i preview-kortet:")
        print("    - præcis ét step")
        print("    - tool=note_append")
        print("    - præcis ovenstående tekst, uden ekstra prose")
        print("    - append-only write-konsekvens og paired-device approval")
        require_phrase(f"{PREVIEW_ATTEST_PREFIX} {ordinal:02d}")
        print("  Udfør nu den fysiske approval på den parrede Android-enhed.")
        print("  Vent til run er completed og markerlinjen er synlig i notes.md.")
        raw_run_id = getpass.getpass("  Indsæt completed run-id (skjult): ").strip()
        if not common._OPAQUE_ID.fullmatch(raw_run_id):
            raise OperatorError("Run-id er tomt eller ugyldigt.")
        verify_positive_live(paths, ordinal, marker, raw_run_id)
        require_phrase(f"{POSITIVE_ATTEST_PREFIX} {ordinal:02d}")
        run(
            [
                sys.executable,
                str(SCRIPTS / "agent3_write_pilot_report.py"),
                "bind",
                "--manifest",
                str(MANIFEST),
                "--ordinal",
                str(ordinal),
                "--run-id",
                raw_run_id,
            ]
        )
        del raw_run_id
        state = load_state()
        completed = set(int(value) for value in state.get("positive_completed", []))
        completed.add(ordinal)
        state["positive_completed"] = sorted(completed)
        save_state(state)
        stage.ok(f"Run {ordinal:02d} er live-verificeret og single-use-bundet.")


CASE_GUIDANCE = {
    "deny": (
        "Opret et nyt note_append-preview med den viste negative marker. "
        "Afvis fysisk på den parrede enhed. Gem afslutningsresponsen og run-id."
    ),
    "timeout": (
        "Opret previewet, men godkend ikke. Vent til confirmation udløber, "
        "forsøg derefter den forventede handling og gem 409-responsen."
    ),
    "changed_args": (
        "Få en approval til den eksakte viste marker, men send derefter en request "
        "med ændret text/args. Den skal fejle 409 uden note- eller approval-delta."
    ),
    "stale_revision": (
        "Få approval til den aktuelle revision, ændr/replan revisionen og forsøg "
        "at bruge den gamle approval. Den skal fejle 409."
    ),
    "replay": (
        "Genbrug approval/action fra den valgte positive run. Replay skal fejle "
        "409, og den eksisterende marker må stadig kun stå én gang."
    ),
    "concurrent_approval": (
        "Send to samtidige forsøg mod samme approval/action. Præcis ét må lykkes "
        "(200), og ét skal afvises (409); note og approval-use må stige præcis én."
    ),
    "stop_retry_replan": (
        "Brug den valgte positive marker og observer mindst tre stop/retry/replan-"
        "relaterede responses. Ingen ny append eller approval-use må opstå."
    ),
}

EXPECTED_STATUSES = {
    "deny": [200],
    "timeout": [409],
    "changed_args": [409],
    "stale_revision": [409],
    "replay": [409],
    "concurrent_approval": [200, 409],
    "stop_retry_replan": [200, 202, 409],
}


def journal_state(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows, _final = journal_cases.verify_journal_binding(
        JOURNAL, manifest, MANIFEST.read_bytes()
    )
    _meta, cases = journal_store._state(rows)
    return cases


def response_body_file(case_name: str, index: int) -> Path:
    RESPONSE_DIR.mkdir(parents=True, exist_ok=True)
    destination = RESPONSE_DIR / f"{case_name}-{index:02d}.body"
    body = input(
        "  Indsæt eksakt response body som én linje, eller @sti til en eksisterende fil: "
    )
    if body.startswith("@"):
        source = Path(body[1:]).expanduser().resolve()
        if source.is_symlink() or not source.is_file():
            raise OperatorError(f"Response-filen er ugyldig: {source}")
        raw = source.read_bytes()
    else:
        raw = body.encode("utf-8")
    destination.write_bytes(raw)
    return destination


def begin_or_resume_case(
    paths: PilotPaths,
    manifest: dict[str, Any],
    name: str,
) -> tuple[str, str, bool]:
    cases = journal_state(manifest)
    for case_id, case in cases.items():
        begin = case.get("begin")
        if begin and begin.get("payload", {}).get("name") == name:
            if case.get("finish") is not None:
                return case_id, str(begin["payload"]["marker"]), True
            return case_id, str(begin["payload"]["marker"]), False

    positive_ordinal = None
    if name in {"replay", "stop_retry_replan"}:
        default = "1" if name == "replay" else "2"
        raw = prompt(f"Positiv ordinal som {name} skal binde til", default)
        try:
            positive_ordinal = int(raw)
        except ValueError as exc:
            raise OperatorError("Positiv ordinal skal være et heltal.") from exc
        if not 1 <= positive_ordinal <= 20:
            raise OperatorError("Positiv ordinal skal være 1..20.")
        marker = str(manifest["runs"][positive_ordinal - 1]["marker"])
        before_notes = note_count(paths.notes, marker)
    else:
        before_notes = 0
    case_id, marker = journal_cases.begin_case(
        journal=JOURNAL,
        manifest_path=MANIFEST,
        name=name,
        note_count=before_notes,
        approval_count=approval_total(paths.approval_db),
        positive_ordinal=positive_ordinal,
    )
    return case_id, marker, False


def record_negative_case(
    paths: PilotPaths,
    manifest: dict[str, Any],
    name: str,
    adb: str,
) -> None:
    case_id, marker, finished = begin_or_resume_case(paths, manifest, name)
    if finished:
        stage.note(f"Negativ case {name} er allerede færdig; springer over.")
        return
    stage.heading(f"NEGATIV CASE — {name}")
    print(f"  Marker:\n\n    {marker}\n")
    print("  " + CASE_GUIDANCE[name])
    launch_android_agent3(adb)
    require_phrase(f"{NEGATIVE_START_PREFIX} {name}")

    existing = journal_state(manifest)[case_id]["observations"]
    start_index = len(existing) + 1
    if name == "stop_retry_replan":
        required_count = int(prompt("Antal observerede responses (mindst 3)", "3"))
        if required_count < 3:
            raise OperatorError("stop_retry_replan kræver mindst tre responses.")
    else:
        required_count = len(EXPECTED_STATUSES[name])

    for index in range(start_index, required_count + 1):
        default_status = str(EXPECTED_STATUSES[name][min(index - 1, len(EXPECTED_STATUSES[name]) - 1)])
        status_raw = prompt(f"HTTP-status for response {index}/{required_count}", default_status)
        try:
            status = int(status_raw)
        except ValueError as exc:
            raise OperatorError("HTTP-status skal være et heltal.") from exc
        response_file = response_body_file(name, index)
        run_id = getpass.getpass(f"  Run-id for response {index} (skjult): ").strip()
        if not common._OPAQUE_ID.fullmatch(run_id):
            raise OperatorError("Negativt run-id er ugyldigt.")
        journal_cases.observe_request(
            journal=JOURNAL,
            case_id=case_id,
            status=status,
            response_path=response_file,
            run_id=run_id,
        )
        del run_id

    after_notes = note_count(paths.notes, marker)
    after_approvals = approval_total(paths.approval_db)
    require_phrase(f"{NEGATIVE_DONE_PREFIX} {name}")
    journal_cases.finish_case(
        journal=JOURNAL,
        case_id=case_id,
        note_count=after_notes,
        approval_count=after_approvals,
    )
    state = load_state()
    completed = set(str(value) for value in state.get("negative_completed", []))
    completed.add(name)
    state["negative_completed"] = sorted(completed)
    save_state(state)
    stage.ok(f"Negativ case {name} er append-only journalført.")


def run_negative_phase(paths: PilotPaths, adb: str) -> None:
    manifest = load_manifest()
    if any(not item.get("run_id") for item in manifest.get("runs", []) if isinstance(item, dict)):
        raise OperatorError("Alle 20 positive runs skal bindes før negative cases.")
    if not JOURNAL.exists():
        journal_store._init(JOURNAL, MANIFEST)
        stage.ok("Append-only negativjournal er nu bundet til det fuldt bundne manifest.")
    else:
        journal_cases.verify_journal_binding(JOURNAL, manifest, MANIFEST.read_bytes())
    for name in common._NEGATIVE_CASES:
        record_negative_case(paths, manifest, name, adb)
    negative = journal_cases.finalize(JOURNAL, MANIFEST)
    atomic_json(NEGATIVE, negative)
    stage.ok("Syv negative cases er kompileret bytebundet fra journalen.")


def collect(paths: PilotPaths) -> int:
    manifest = load_manifest()
    if any(not item.get("run_id") for item in manifest.get("runs", []) if isinstance(item, dict)):
        raise OperatorError("Manifestet er ikke fuldt bundet.")
    if not NEGATIVE.is_file():
        negative = journal_cases.finalize(JOURNAL, MANIFEST)
        atomic_json(NEGATIVE, negative)
    report = pilot_report.collect_report(
        manifest_path=MANIFEST,
        negative_path=NEGATIVE,
        negative_journal_path=JOURNAL,
        rig_validation_path=RIG_REPORT,
        agent_db=paths.agent_db,
        approval_db=paths.approval_db,
        audit_db=paths.audit_db,
        notes_path=paths.notes,
    )
    atomic_json(REPORT, report)
    state = load_state()
    state["report_success"] = bool(report.get("success"))
    save_state(state)
    if report.get("success"):
        stage.heading("T-022 FYSISK EVIDENS BESTÅET")
        stage.ok("20/20 append-runs og 7/7 negative cases er forensisk grønne.")
        stage.ok(f"Rapport: {REPORT}")
        stage.ok("production_activation=false")
        return 0
    print("\n  T-022-RAPPORT: BLOKERET")
    for blocker in report.get("blockers", []):
        print(f"    - {blocker}")
    return 2


def archive_for_reset() -> None:
    existing = [
        path
        for path in (MANIFEST, PREFLIGHT, JOURNAL, NEGATIVE, REPORT, STATE)
        if path.exists() or path.is_symlink()
    ]
    if not existing and not RESPONSE_DIR.exists():
        return
    require_phrase("ARCHIVE T022")
    archive = VALIDATION / "archive" / time.strftime("t022-write-pilot-%Y%m%d-%H%M%S")
    archive.mkdir(parents=True, exist_ok=False)
    for source in existing:
        source.replace(archive / source.name)
    if RESPONSE_DIR.exists():
        RESPONSE_DIR.replace(archive / RESPONSE_DIR.name)
    stage.note(f"Tidligere T-022-evidens er bevaret i {archive}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase",
        choices=("all", "prepare", "positive", "negative", "collect"),
        default="all",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="arkivér eksisterende kampagne efter eksakt ARCHIVE T022-attestering",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    os.chdir(ROOT)
    stage.heading("Kaliv T-022 — fysisk append-only write-pilot")
    print("  Wizard'en sender ingen POST/approve/write/retry/cancel/replan-request.")
    print("  Fysiske handlinger udføres og attesteres på den parrede klient.")
    print("  Delvis manifest, journal og state bevares ved sikkert stop.")
    print("  Den kan ikke merge, pushe, tagge, release eller aktivere produktion.")

    ensure_candidate()
    if args.reset:
        archive_for_reset()
    paths = resolve_paths()
    configure_environment(paths)
    ensure_stack_and_rig_validation(paths)
    prepare_and_preflight(paths)

    adb: str | None = None
    if args.phase in {"all", "positive", "negative"}:
        adb = find_adb()
        model, release = android_device(adb)
        stage.ok(f"Fysisk Android-enhed: {model} / Android {release}")
        build_install_android(adb)

    if args.phase in {"all", "positive"}:
        if adb is None:
            raise OperatorError("Android-enheden er ikke initialiseret.")
        run_positive_phase(paths, adb)
    if args.phase in {"all", "negative"}:
        if adb is None:
            raise OperatorError("Android-enheden er ikke initialiseret.")
        run_negative_phase(paths, adb)
    if args.phase in {"all", "collect"}:
        return collect(paths)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print(
            "\n  SIKKERT STOP: afbrudt af operatøren; delvis T-022-evidens er bevaret.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    except Exception as exc:
        print(
            f"\n  SIKKERT STOP: {type(exc).__name__}: {str(exc)[:1200]}",
            file=sys.stderr,
        )
        print(
            "  Manifest, preflight, journal og operator-state slettes aldrig automatisk.",
            file=sys.stderr,
        )
        raise SystemExit(1)
