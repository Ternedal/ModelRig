#!/usr/bin/env python3
"""Resumable Windows operator for the physical T-022 append-only write pilot.

The wizard automates reproducible setup, candidate binding, preflight, evidence
measurements, manifest binding and forensic collection. It cannot approve a
request or observe a screen for the operator. Every positive run requires two
exact operator phrases, and every negative request requires an exact response
body plus status and run id.

It never merges, pushes, tags, publishes, activates production or stores tokens.
"""
from __future__ import annotations

import getpass
import importlib.util
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
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
RESPONSES = VALIDATION / "agent3-write-pilot-responses"
RIG_REPORT = VALIDATION / "agent3-rig-validation-latest.json"
BRANCH = "agent/t022-write-pilot-one-click"
VERSION = "1.58.146"
BASE_URL = "http://127.0.0.1:8080"
ANDROID_PACKAGE = "dk.ternedal.modelrig"
ANDROID_ACTIVITY = f"{ANDROID_PACKAGE}/.MainActivity"
ANDROID_AGENT3_EXTRA = "dk.ternedal.modelrig.extra.AGENT3"
POSITIVE_PREVIEW_PREFIX = "PREVIEW GODKENDT"
POSITIVE_APPEND_PREFIX = "APPEND BEKRÆFTET"
NEGATIVE_PREFIX = "NEGATIV CASE OBSERVERET"

sys.path.insert(0, str(SCRIPTS))
import stage_a_one_click as stage  # noqa: E402


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise OperatorError(f"Kan ikke indlæse {path.name}.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pilot = _load_module("t022_operator_report", SCRIPTS / "agent3_write_pilot_report.py")
preflight = _load_module("t022_operator_preflight", SCRIPTS / "agent3_write_pilot_preflight.py")
forensics = _load_module("t022_operator_forensics", SCRIPTS / "agent3_write_pilot_forensics.py")
journal_cases = _load_module(
    "t022_operator_journal_cases", SCRIPTS / "agent3_write_pilot_journal_cases.py"
)
journal_store = _load_module(
    "t022_operator_journal_store", SCRIPTS / "agent3_write_pilot_journal_store.py"
)
common = _load_module("t022_operator_common", SCRIPTS / "agent3_write_pilot_common.py")


class OperatorError(RuntimeError):
    pass


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def prompt(message: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"  {message}{suffix}: ").strip()
    return value or (default or "")


def require_phrase(expected: str) -> None:
    entered = input(f"  Skriv præcis '{expected}' for at attestere: ").strip()
    if entered != expected:
        raise OperatorError("Attesteringen matchede ikke; evidensen blev ikke bundet.")


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


def ensure_secrets() -> str:
    token = os.environ.get("MODELRIG_TOKEN", "").strip()
    if not token:
        token = getpass.getpass("  MODELRIG_TOKEN (skjult, gemmes ikke): ").strip()
    if not token:
        raise OperatorError("MODELRIG_TOKEN er tomt.")
    os.environ["MODELRIG_TOKEN"] = token
    approval_secret = os.environ.get("KALIV_AGENT3_APPROVAL_SECRET", "").strip()
    if not approval_secret:
        approval_secret = getpass.getpass(
            "  KALIV_AGENT3_APPROVAL_SECRET (skjult, gemmes ikke): "
        ).strip()
    if not approval_secret:
        raise OperatorError("KALIV_AGENT3_APPROVAL_SECRET er tomt.")
    os.environ["KALIV_AGENT3_APPROVAL_SECRET"] = approval_secret
    return token


def ensure_stack() -> None:
    os.environ.update(
        {
            "KALIV_AGENT3_ENABLED": "1",
            "KALIV_TOOLS_ENABLED": "1",
            "KALIV_AGENT3_APPROVAL_REQUIRED": "1",
            "KALIV_AGENT3_VALIDATION_REPORT": str(RIG_REPORT),
        }
    )
    planner = stage.ensure_models()
    stage.ensure_device_token()
    stage.heading("Start exact-head write-pilot stack")
    stage.note(
        "Stacken startes med Agent 3, tools og backend-issued approval aktivt; "
        "preflighten kræver, at note_append er eneste aktive write-capability."
    )
    stage.start_stack(planner)


def find_adb() -> str:
    adb = shutil.which("adb")
    if not adb:
        raise OperatorError("adb blev ikke fundet på PATH. Installer Android Platform Tools.")
    return adb


def android_device(adb: str) -> str:
    result = run([adb, "devices"], capture=True)
    devices = [
        line.split("\t", 1)[0]
        for line in result.stdout.splitlines()[1:]
        if "\tdevice" in line
    ]
    if len(devices) != 1:
        raise OperatorError(f"Der skal være præcis én ADB-enhed; fandt {len(devices)}.")
    model = run([adb, "shell", "getprop", "ro.product.model"], capture=True).stdout.strip()
    return model or devices[0]


def build_install_android(adb: str) -> None:
    gradlew = ROOT / "android" / "gradlew.bat"
    if not gradlew.is_file():
        raise OperatorError("android\\gradlew.bat mangler.")
    stage.heading("Byg og installer exact-head Android-klienten")
    run([str(gradlew), ":app:assembleDebug"], cwd=ROOT / "android")
    apk = ROOT / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    if not apk.is_file():
        raise OperatorError(f"APK mangler efter build: {apk}")
    run([adb, "install", "-r", str(apk)])
    stage.ok(f"Installeret {apk.name}.")


def launch_android(adb: str) -> None:
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


def launch_desktop() -> None:
    gradlew = ROOT / "desktop" / "gradlew.bat"
    if not gradlew.is_file():
        raise OperatorError("desktop\\gradlew.bat mangler.")
    subprocess.Popen(
        [str(gradlew), ":composeApp:run", "--args=--agent3"],
        cwd=ROOT / "desktop",
        env=os.environ.copy(),
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )


def archive_existing() -> None:
    paths = [MANIFEST, PREFLIGHT, JOURNAL, NEGATIVE, REPORT, STATE]
    paths.extend(RESPONSES.glob("*") if RESPONSES.is_dir() else [])
    existing = [path for path in paths if path.exists() or path.is_symlink()]
    if not existing:
        return
    archive = VALIDATION / "archive" / time.strftime("t022-write-pilot-%Y%m%d-%H%M%S")
    archive.mkdir(parents=True, exist_ok=True)
    for source in existing:
        if source.is_file() or source.is_symlink():
            source.replace(archive / source.name)
    if RESPONSES.is_dir() and not any(RESPONSES.iterdir()):
        RESPONSES.rmdir()
    stage.note(f"Tidligere T-022-evidens er bevaret i {archive}")


def path_config() -> dict[str, str]:
    data_default = Path(os.environ.get("KALIV_DATA_DIR", ROOT / "data"))
    tools_default = Path(os.environ.get("KALIV_TOOLS_DIR", data_default / "tools"))
    defaults = {
        "agent_db": data_default / "kaliv-agent3.db",
        "approval_db": data_default / "kaliv-agent3-approvals.db",
        "audit_db": data_default / "kaliv-audit.db",
        "notes": tools_default / "notes.md",
    }
    result: dict[str, str] = {}
    stage.heading("Bekræft fysiske evidence-paths")
    for key, default in defaults.items():
        value = Path(prompt(key, str(default))).expanduser().resolve()
        if value.is_symlink() or not value.is_file():
            raise OperatorError(f"{key} er ikke en regulær fil: {value}")
        result[key] = str(value)
    return result


def load_state() -> dict[str, Any] | None:
    if not STATE.is_file():
        return None
    value = json.loads(STATE.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != "kaliv-agent3-write-pilot-operator/v1":
        raise OperatorError("Operator-state har forkert schema.")
    if value.get("production_activation") is not False:
        raise OperatorError("Operator-state bryder production_activation=false.")
    return value


def save_state(value: dict[str, Any]) -> None:
    value["updated_at"] = iso_now()
    value["production_activation"] = False
    atomic_json(STATE, value)


def prepare_new_session(candidate_sha: str, operator: str, paths: dict[str, str]) -> dict[str, Any]:
    if not RIG_REPORT.is_file():
        raise OperatorError(f"Den kandidatbundne rig-validation mangler: {RIG_REPORT}")
    archive_existing()
    manifest = common.prepare_manifest(operator=operator, rig_validation_path=RIG_REPORT)
    common._atomic_json(MANIFEST, manifest)
    report = preflight.run_preflight(
        manifest_path=MANIFEST,
        rig_validation_path=RIG_REPORT,
        agent_db=Path(paths["agent_db"]),
        approval_db=Path(paths["approval_db"]),
        audit_db=Path(paths["audit_db"]),
        notes_path=Path(paths["notes"]),
        negative_journal_path=JOURNAL,
        base_url=BASE_URL,
        token=os.environ["MODELRIG_TOKEN"],
    )
    common._atomic_json(PREFLIGHT, report)
    if not report.get("success"):
        blockers = "\n".join(f"  - {item}" for item in report.get("blockers", []))
        raise OperatorError(f"T-022 preflight er rød:\n{blockers}")
    journal_store._init(JOURNAL, MANIFEST)
    state = {
        "schema": "kaliv-agent3-write-pilot-operator/v1",
        "created_at": iso_now(),
        "candidate_sha": candidate_sha,
        "operator": operator,
        "android_device": None,
        "paths": paths,
        "preflight_sha256": common._sha_bytes(PREFLIGHT.read_bytes()),
        "positive_complete": [],
        "negative_complete": [],
        "phase": "positive",
        "production_activation": False,
    }
    save_state(state)
    stage.ok("Manifest, grøn preflight og append-only journal er kandidatbundet.")
    return state


def db_snapshot_rows(path: Path, loader) -> list[dict[str, Any]]:
    snapshot = forensics.snapshot_sqlite(path)
    try:
        return loader(snapshot)
    finally:
        snapshot.unlink(missing_ok=True)


def approval_count(path: Path) -> int:
    return len(db_snapshot_rows(path, forensics.load_approval_rows))


def note_count(path: Path, marker: str) -> int:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OperatorError("notes.md er ikke UTF-8.") from exc
    return text.splitlines().count(marker)


def verify_positive(
    *,
    run_id: str,
    marker: str,
    paths: Mapping[str, str],
    before_approval_count: int,
) -> list[str]:
    errors: list[str] = []
    runs = db_snapshot_rows(Path(paths["agent_db"]), forensics.load_run_records)
    approvals = db_snapshot_rows(Path(paths["approval_db"]), forensics.load_approval_rows)
    audits = db_snapshot_rows(Path(paths["audit_db"]), forensics.load_audit_rows)
    record = next((item for item in runs if item.get("id") == run_id), None)
    if record is None:
        errors.append("run-id findes ikke i Agent 3-ledgeren")
    else:
        forensics._validate_success_run(
            record=record,
            marker=marker,
            approval_rows=approvals,
            audit_rows=audits,
            errors=errors,
            label="physical positive run",
        )
    if note_count(Path(paths["notes"]), marker) != 1:
        errors.append("markøren forekommer ikke præcis én gang i notes.md")
    if len(approvals) != before_approval_count + 1:
        errors.append("approval-use-delta er ikke præcis én")
    return errors


def positive_runs(state: dict[str, Any], adb: str) -> None:
    manifest, _ = common._load_json(MANIFEST)
    paths = state["paths"]
    complete = set(int(value) for value in state.get("positive_complete", []))
    for item in manifest["runs"]:
        ordinal = int(item["ordinal"])
        if item.get("run_id") and ordinal in complete:
            continue
        marker = str(item["marker"])
        stage.heading(f"T-022 POSITIV {ordinal:02d}/20")
        print(f"  Brug hele denne tekst som note_append.text:\n\n  {marker}\n")
        print("  Krav på skærmen:")
        print("    - præcis ét note_append-step")
        print("    - risk=write, egress=local, idempotent=false")
        print("    - target og append-only konsekvens er synlig")
        print("    - godkendelsen sker på den parrede Android-enhed")
        launch_android(adb)
        if ordinal == 1:
            launch_desktop()
        before_approval = approval_count(Path(paths["approval_db"]))
        before_note = note_count(Path(paths["notes"]), marker)
        if before_note != 0:
            raise OperatorError(f"Positiv markør {ordinal} findes allerede i notes.md.")
        require_phrase(f"{POSITIVE_PREVIEW_PREFIX} {ordinal:02d}")
        input("  Godkend fysisk på Android, vent på completed, og tryk Enter: ")
        require_phrase(f"{POSITIVE_APPEND_PREFIX} {ordinal:02d}")
        run_id = getpass.getpass("  Run-id (skjult; bindes i manifestet): ").strip()
        if common._OPAQUE_ID.fullmatch(run_id) is None:
            raise OperatorError("Run-id har ugyldigt format.")
        errors = verify_positive(
            run_id=run_id,
            marker=marker,
            paths=paths,
            before_approval_count=before_approval,
        )
        if errors:
            raise OperatorError(
                "Run verificerede ikke fysisk/forensisk:\n"
                + "\n".join(f"  - {error}" for error in errors)
            )
        manifest, _ = common._load_json(MANIFEST)
        common.bind_run(manifest, ordinal, run_id)
        common._atomic_json(MANIFEST, manifest)
        del run_id
        complete.add(ordinal)
        state["positive_complete"] = sorted(complete)
        save_state(state)
        stage.ok(f"Positiv run {ordinal:02d} er verificeret og bundet én gang.")
    state["phase"] = "negative"
    save_state(state)


def completed_negative_names() -> set[str]:
    rows, _ = journal_store.verify_journal_binding(
        JOURNAL, *common._load_json(MANIFEST)
    )
    _meta, cases = journal_store._state(rows)
    return {
        str(case["begin"]["payload"]["name"])
        for case in cases.values()
        if case.get("begin") is not None and case.get("finish") is not None
    }


def expected_statuses(name: str) -> tuple[int, ...]:
    return {
        "deny": (200,),
        "timeout": (409,),
        "changed_args": (409,),
        "stale_revision": (409,),
        "replay": (409,),
        "concurrent_approval": (200, 409),
        "stop_retry_replan": (200, 202, 409),
    }[name]


def response_observation_count(name: str) -> int:
    if name == "concurrent_approval":
        return 2
    if name == "stop_retry_replan":
        return 3
    return 1


def capture_response(name: str, index: int) -> Path:
    RESPONSES.mkdir(parents=True, exist_ok=True)
    supplied = prompt("Path til exact response body-fil (tom = indsæt én linje)", "")
    destination = RESPONSES / f"{name}-{index:02d}.body"
    if supplied:
        source = Path(supplied).expanduser().resolve()
        if source.is_symlink() or not source.is_file():
            raise OperatorError(f"Response-filen er ikke regulær: {source}")
        destination.write_bytes(source.read_bytes())
    else:
        body = input("  Indsæt exact response body som én linje: ")
        destination.write_text(body, encoding="utf-8")
    if destination.stat().st_size > journal_store.MAX_RESPONSE_BYTES:
        raise OperatorError("Response body overskrider recorderens størrelsesgrænse.")
    return destination


def select_positive_ordinal(name: str) -> int | None:
    if name not in {"replay", "stop_retry_replan"}:
        return None
    raw = prompt(f"Positiv ordinal som {name} skal målrette", "1")
    try:
        ordinal = int(raw)
    except ValueError as exc:
        raise OperatorError("Ordinal skal være et heltal.") from exc
    if not 1 <= ordinal <= 20:
        raise OperatorError("Ordinal skal være 1..20.")
    return ordinal


def negative_cases(state: dict[str, Any], adb: str) -> None:
    paths = state["paths"]
    manifest, _ = common._load_json(MANIFEST)
    complete = completed_negative_names()
    for name in common._NEGATIVE_CASES:
        if name in complete:
            continue
        stage.heading(f"T-022 NEGATIV CASE — {name}")
        ordinal = select_positive_ordinal(name)
        if ordinal is None:
            marker_for_before = None
            before_note = 0
        else:
            marker_for_before = manifest["runs"][ordinal - 1]["marker"]
            before_note = note_count(Path(paths["notes"]), marker_for_before)
        before_approval = approval_count(Path(paths["approval_db"]))
        case_id, marker = journal_cases.begin_case(
            journal=JOURNAL,
            manifest_path=MANIFEST,
            name=name,
            note_count=before_note,
            approval_count=before_approval,
            positive_ordinal=ordinal,
        )
        print(f"  Marker: {marker}")
        print("  Udfør den navngivne adversarial case på den parrede enhed/klient.")
        print("  Gem den eksakte HTTP-response body; recorderens hashkæde binder den.")
        launch_android(adb)
        require_phrase(f"{NEGATIVE_PREFIX} {name}")
        statuses: list[int] = []
        for index in range(1, response_observation_count(name) + 1):
            allowed = expected_statuses(name)
            raw_status = prompt(f"HTTP-status observation {index} ({'/'.join(map(str, allowed))})")
            try:
                status = int(raw_status)
            except ValueError as exc:
                raise OperatorError("HTTP-status skal være et heltal.") from exc
            if status not in allowed:
                raise OperatorError(f"HTTP-status {status} er ikke tilladt for {name}.")
            response_path = capture_response(name, index)
            run_id = getpass.getpass(f"  Run-id for observation {index} (skjult): ").strip()
            if common._OPAQUE_ID.fullmatch(run_id) is None:
                raise OperatorError("Run-id har ugyldigt format.")
            journal_cases.observe_request(
                journal=JOURNAL,
                case_id=case_id,
                status=status,
                response_path=response_path,
                run_id=run_id,
            )
            del run_id
            statuses.append(status)
        if name == "concurrent_approval" and sorted(statuses) != [200, 409]:
            raise OperatorError("concurrent_approval kræver præcis én 200 og én 409.")
        after_note = note_count(Path(paths["notes"]), marker)
        after_approval = approval_count(Path(paths["approval_db"]))
        journal_cases.finish_case(
            journal=JOURNAL,
            case_id=case_id,
            note_count=after_note,
            approval_count=after_approval,
        )
        complete.add(name)
        state["negative_complete"] = sorted(complete)
        save_state(state)
        stage.ok(f"Negativ case {name} er append-only registreret.")
    negative = journal_cases.finalize(JOURNAL, MANIFEST)
    common._atomic_json(NEGATIVE, negative)
    state["phase"] = "collect"
    save_state(state)


def collect(state: dict[str, Any]) -> int:
    paths = state["paths"]
    report = pilot.collect_report(
        manifest_path=MANIFEST,
        negative_path=NEGATIVE,
        negative_journal_path=JOURNAL,
        rig_validation_path=RIG_REPORT,
        agent_db=Path(paths["agent_db"]),
        approval_db=Path(paths["approval_db"]),
        audit_db=Path(paths["audit_db"]),
        notes_path=Path(paths["notes"]),
    )
    common._atomic_json(REPORT, report)
    if not report.get("success"):
        print("\n  T-022-RAPPORT: BLOKERET")
        for blocker in report.get("blockers", []):
            print(f"    - {blocker}")
        return 2
    state["phase"] = "complete"
    state["report_sha256"] = common._sha_bytes(REPORT.read_bytes())
    save_state(state)
    stage.heading("T-022 FYSISK WRITE-PILOT BESTÅET")
    stage.ok("20/20 positive appends og 7/7 negative cases er forensisk bundet.")
    stage.ok(f"Rapport: {REPORT}")
    stage.ok("production_activation=false")
    return 0


def main() -> int:
    os.chdir(ROOT)
    stage.heading("Kaliv T-022 — fysisk append-only write-pilot")
    print("  Wizard'en kan ikke selv godkende en write eller se UI'en.")
    print("  20 positive runs kræver to præcise operatørfraser hver.")
    print("  Syv negative cases bindes i en append-only hashkædet journal.")
    print("  Den kan ikke merge, pushe, tagge, release eller aktivere produktion.")

    candidate_sha = ensure_candidate()
    ensure_secrets()
    ensure_stack()
    adb = find_adb()
    device = android_device(adb)
    build_install_android(adb)

    state = load_state()
    if state is None:
        operator = prompt("Operatørnavn", os.environ.get("USERNAME", "Anders"))
        paths = path_config()
        state = prepare_new_session(candidate_sha, operator, paths)
        state["android_device"] = device
        save_state(state)
    elif state.get("candidate_sha") != candidate_sha:
        raise OperatorError("Gemte operator-state tilhører en anden kandidat-SHA.")

    phase = state.get("phase")
    if phase == "positive":
        positive_runs(state, adb)
        phase = state.get("phase")
    if phase == "negative":
        negative_cases(state, adb)
        phase = state.get("phase")
    if phase == "collect":
        return collect(state)
    if phase == "complete":
        stage.ok(f"T-022 er allerede komplet for candidate {candidate_sha[:12]}.")
        stage.ok(f"Rapport: {REPORT}")
        return 0
    raise OperatorError(f"Ukendt operator-fase: {phase!r}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n  SIKKERT STOP: delvis kandidatbundet state er bevaret.", file=sys.stderr)
        raise SystemExit(1)
    except (OperatorError, common.PilotEvidenceError, journal_store.RecorderError, sqlite3.Error) as exc:
        print(f"\n  SIKKERT STOP: {type(exc).__name__}: {str(exc)[:1500]}", file=sys.stderr)
        print(f"  State/evidens er bevaret under {VALIDATION}.", file=sys.stderr)
        raise SystemExit(1)
