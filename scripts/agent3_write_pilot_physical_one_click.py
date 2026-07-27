#!/usr/bin/env python3
"""Resumable Windows operator for the physical T-022 append-only write pilot.

The wizard automates reproducible setup, candidate binding, ledger counts,
manifest binding, journal lifecycle and final collection. It cannot approve a
write or decide what was visible on Android/desktop. Every positive run and every
negative case requires exact operator attestations and is independently checked
against durable run, approval, audit and notes evidence.

Sequence is deliberately fixed:
    exact candidate -> rig report -> manifest -> GET-only preflight
    -> 20 positive bindings -> journal init -> 7 negative cases -> collection

It never merges, pushes, tags, releases or activates production.
"""
from __future__ import annotations

import getpass
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
VALIDATION = ROOT / "validation"
MANIFEST = VALIDATION / "agent3-write-pilot-manifest.json"
PREFLIGHT_REPORT = VALIDATION / "agent3-write-pilot-preflight.json"
JOURNAL = VALIDATION / "agent3-write-pilot-negative-journal.db"
NEGATIVE = VALIDATION / "agent3-write-pilot-negative.json"
REPORT = VALIDATION / "agent3-write-pilot-latest.json"
RIG_REPORT = VALIDATION / "agent3-rig-validation-latest.json"
TOOLS_STATE = VALIDATION / "agent3-write-pilot-tools-state.json"
RESPONSES = VALIDATION / "agent3-write-pilot-responses"
BRANCH = "agent/t022-current-main-physical-operator"
VERSION = "1.58.146"
BASE_URL = "http://127.0.0.1:8080"
ANDROID_PACKAGE = "dk.ternedal.modelrig"
ANDROID_ACTIVITY = f"{ANDROID_PACKAGE}/.MainActivity"
ANDROID_AGENT3_EXTRA = "dk.ternedal.modelrig.extra.AGENT3"

PREVIEW_PHRASE = "PREVIEW MATCHER"
APPROVAL_PHRASE = "APPROVAL GIVET"
COMPLETED_PHRASE = "RUN COMPLETED"
RECOVERY_PHRASE = "RECOVERED EVIDENCE REVIEWED"
NEGATIVE_START_PHRASE = "NEGATIV CASE UDFØRT"
NEGATIVE_FINISH_PHRASE = "NEGATIV DELTA BEKRÆFTET"

NEGATIVE_MIN_OBSERVATIONS = {
    "deny": 1,
    "timeout": 1,
    "changed_args": 1,
    "stale_revision": 1,
    "replay": 1,
    "concurrent_approval": 2,
    "stop_retry_replan": 3,
}
NEGATIVE_EXPECTED_DELTAS = {
    "deny": (0, 0),
    "timeout": (0, 0),
    "changed_args": (0, 0),
    "stale_revision": (0, 0),
    "replay": (0, 0),
    "concurrent_approval": (1, 1),
    "stop_retry_replan": (0, 0),
}
NEGATIVE_GUIDANCE = {
    "deny": "Opret en frisk note_append-confirmation og vælg Afvis på den parrede enhed.",
    "timeout": "Opret en frisk confirmation og lad både confirmation og approval-token udløbe.",
    "changed_args": "Få approval til den viste marker, men send derefter ændrede args; requesten skal afvises.",
    "stale_revision": "Godkend den viste revision, ændr/replan revisionen og forsøg derefter den gamle approval.",
    "replay": "Genbrug en allerede forbrugt approval fra det valgte positive run; ingen ny append må ske.",
    "concurrent_approval": "Send samme exact approval samtidigt to gange; præcis én må lykkes og appende én gang.",
    "stop_retry_replan": "Stop, retry og replan omkring den valgte positive marker; ingen ekstra append må ske.",
}

sys.path.insert(0, str(SCRIPTS))
import stage_a_one_click as stage  # noqa: E402


class OperatorError(RuntimeError):
    pass


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise OperatorError(f"Kan ikke indlæse {path.name}.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


common = _load_module("t022_operator_common", SCRIPTS / "agent3_write_pilot_common.py")
reporter = _load_module("t022_operator_report", SCRIPTS / "agent3_write_pilot_report.py")
preflight = _load_module("t022_operator_preflight", SCRIPTS / "agent3_write_pilot_preflight.py")
journal_cases = _load_module(
    "t022_operator_journal_cases", SCRIPTS / "agent3_write_pilot_journal_cases.py"
)
journal_store = _load_module(
    "t022_operator_journal_store", SCRIPTS / "agent3_write_pilot_journal_store.py"
)
forensics = _load_module(
    "t022_operator_forensics", SCRIPTS / "agent3_write_pilot_forensics.py"
)


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OperatorError(f"Kan ikke læse {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise OperatorError(f"{path} indeholder ikke et JSON-objekt.")
    return value


def run(
    args: list[str],
    *,
    cwd: Path = ROOT,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            env=os.environ.copy(),
            text=True,
            capture_output=capture,
            check=False,
            timeout=900,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OperatorError(f"Kunne ikke køre {args[0]}: {exc}") from exc
    if check and result.returncode != 0:
        output = (result.stderr or result.stdout) if capture else ""
        raise OperatorError(
            f"Kommandoen fejlede ({result.returncode}): {' '.join(args)}"
            + (f"\n{output[-1000:]}" if output else "")
        )
    return result


def prompt(message: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"  {message}{suffix}: ").strip()
    return value or (default or "")


def require_phrase(expected: str) -> None:
    entered = input(f"  Skriv præcis '{expected}' for at fortsætte: ").strip()
    if entered != expected:
        raise OperatorError("Attesteringen matchede ikke; evidensen blev ikke lukket.")


def data_root() -> Path:
    explicit = os.environ.get("KALIV_DATA_DIR", "").strip()
    if explicit:
        return Path(explicit)
    base = os.environ.get("LOCALAPPDATA", "").strip()
    if not base:
        base = str(Path.home() / "AppData" / "Local")
    return Path(base) / "Kaliv"


def evidence_paths() -> dict[str, Path]:
    root = data_root()
    tools_dir = Path(
        os.environ.get("KALIV_TOOLS_DIR", "").strip()
        or str(Path.home() / "Documents" / "Kaliv")
    )
    defaults = {
        "agent_db": Path(os.environ.get("KALIV_AGENT3_DB", "") or root / "kaliv-agent3.db"),
        "approval_db": Path(
            os.environ.get("KALIV_AGENT3_APPROVAL_DB", "")
            or root / "kaliv-agent3-approvals.db"
        ),
        "audit_db": Path(os.environ.get("KALIV_AUDIT_DB", "") or root / "kaliv-audit.db"),
        "notes": tools_dir / "notes.md",
    }
    labels = {
        "agent_db": "Agent 3 run-database",
        "approval_db": "Approval-use-database",
        "audit_db": "ToolGate audit-database",
        "notes": "notes.md",
    }
    resolved = {
        key: Path(prompt(labels[key], str(defaults[key]))).expanduser()
        for key in labels
    }
    resolved["tools_dir"] = resolved["notes"].parent
    return resolved


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


def ensure_secrets() -> None:
    token = os.environ.get("MODELRIG_TOKEN", "").strip()
    if not token:
        token = getpass.getpass("  MODELRIG_TOKEN (skjult, gemmes ikke): ").strip()
    if not token:
        raise OperatorError("MODELRIG_TOKEN er tomt.")
    secret = os.environ.get("KALIV_AGENT3_APPROVAL_SECRET", "").strip()
    if not secret:
        secret = getpass.getpass(
            "  KALIV_AGENT3_APPROVAL_SECRET (skjult, mindst 32 tegn): "
        ).strip()
    if len(secret.encode("utf-8")) < 32:
        raise OperatorError("Approval-secret skal være mindst 32 bytes.")
    os.environ["MODELRIG_TOKEN"] = token
    os.environ["KALIV_AGENT3_APPROVAL_SECRET"] = secret


def candidate_write_tools() -> list[str]:
    with tempfile.TemporaryDirectory(prefix="kaliv-t022-registry-") as tmp:
        env = os.environ.copy()
        env.update(
            {
                "PYTHONPATH": str(ROOT / "worker"),
                "PYTHONDONTWRITEBYTECODE": "1",
                "KALIV_DATA_DIR": tmp,
                "KALIV_AUDIT_DB": str(Path(tmp) / "audit.db"),
                "KALIV_TOOLS_STATE": str(Path(tmp) / "tools-state.json"),
                "KALIV_JOBS_DB": str(Path(tmp) / "jobs.db"),
                "KALIV_TOOLS_DIR": str(Path(tmp) / "tools"),
            }
        )
        code = (
            "import json\n"
            "from app.tools import REGISTRY\n"
            "print(json.dumps(sorted(name for name, tool in REGISTRY.items() "
            "if tool.risk != 'read')))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT / "worker",
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
    if result.returncode != 0:
        raise OperatorError(
            "Kunne ikke læse kandidatens write-tool inventory: " + result.stderr[-500:]
        )
    try:
        tools = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise OperatorError("Write-tool inventory var ikke gyldig JSON.") from exc
    if not isinstance(tools, list) or "note_append" not in tools:
        raise OperatorError("Kandidaten eksponerer ikke den forventede note_append capability.")
    return sorted(str(item) for item in tools)


def configure_environment(paths: Mapping[str, Path]) -> None:
    writes = candidate_write_tools()
    disabled = [name for name in writes if name != "note_append"]
    atomic_json(TOOLS_STATE, {"enabled": True, "disabled_tools": disabled})
    os.environ.update(
        {
            "KALIV_AGENT3_ENABLED": "1",
            "KALIV_AGENT3_APPROVAL_REQUIRED": "1",
            "KALIV_TOOLS_ENABLED": "1",
            "KALIV_TOOLS_STATE": str(TOOLS_STATE.resolve()),
            "KALIV_TOOLS_DIR": str(paths["tools_dir"].resolve()),
            "KALIV_AGENT3_DB": str(paths["agent_db"].resolve()),
            "KALIV_AGENT3_APPROVAL_DB": str(paths["approval_db"].resolve()),
            "KALIV_AUDIT_DB": str(paths["audit_db"].resolve()),
            "KALIV_AGENT3_VALIDATION_REPORT": str(RIG_REPORT.resolve()),
        }
    )
    stage.ok(
        "Isoleret tool-state: note_append er eneste aktive write-capability; "
        f"deaktiveret={disabled}"
    )


def ensure_stack() -> str:
    planner = stage.ensure_models()
    stage.ensure_device_token()
    stage.heading("Start exact-head backend og worker til T-022")
    stage.start_stack(planner)
    return planner


def regenerate_rig_validation(planner: str) -> None:
    stage.heading("Regenerér kandidatbundet rig-validation")
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
    if not RIG_REPORT.is_file():
        raise OperatorError("Rig-validation-rapporten blev ikke oprettet.")


def find_adb() -> str:
    adb = shutil.which("adb")
    if not adb:
        raise OperatorError("adb blev ikke fundet på PATH. Installer Android Platform Tools.")
    return adb


def one_android_device(adb: str) -> None:
    result = run([adb, "devices"], capture=True)
    devices = [
        line.split("\t", 1)[0]
        for line in result.stdout.splitlines()[1:]
        if "\tdevice" in line
    ]
    if len(devices) != 1:
        raise OperatorError(f"Der skal være præcis én ADB-enhed; fandt {len(devices)}.")


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


def launch_surfaces(adb: str) -> None:
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
    gradlew = ROOT / "desktop" / "gradlew.bat"
    if not gradlew.is_file():
        raise OperatorError("desktop\\gradlew.bat mangler.")
    subprocess.Popen(
        [str(gradlew), ":composeApp:run", "--args=--agent3"],
        cwd=ROOT / "desktop",
        env=os.environ.copy(),
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )


def run_preflight(paths: Mapping[str, Path]) -> None:
    result = preflight.run_preflight(
        manifest_path=MANIFEST,
        rig_validation_path=RIG_REPORT,
        agent_db=paths["agent_db"],
        approval_db=paths["approval_db"],
        audit_db=paths["audit_db"],
        notes_path=paths["notes"],
        negative_journal_path=JOURNAL,
        base_url=BASE_URL,
        token=os.environ["MODELRIG_TOKEN"],
    )
    common._atomic_json(PREFLIGHT_REPORT, result)
    if result.get("success") is not True:
        blockers = "\n".join(f"    - {item}" for item in result.get("blockers", []))
        raise OperatorError("T-022 preflight er rød:\n" + blockers)
    stage.ok("T-022 preflight er grøn og GET-only.")


def validate_resume_manifest(manifest: dict[str, Any], raw: bytes) -> None:
    errors = common.validate_manifest(manifest, require_bound=False)
    identity = common.candidate_identity(ROOT)
    target = manifest.get("target") if isinstance(manifest.get("target"), dict) else {}
    for field in ("version", "git_sha", "code_sha256", "identity_source"):
        if target.get(field) != identity.get(field):
            errors.append(f"manifestets {field} matcher ikke den aktuelle kandidat")
    if not RIG_REPORT.is_file():
        errors.append("manifestets rig-validation-rapport mangler")
    elif target.get("rig_validation_report_sha256") != common._sha_bytes(RIG_REPORT.read_bytes()):
        errors.append("rig-validation-rapporten har ændret sig efter manifest preparation")
    if errors:
        raise OperatorError("Eksisterende manifest kan ikke genoptages: " + "; ".join(errors))
    preflight_value = load_json(PREFLIGHT_REPORT) if PREFLIGHT_REPORT.is_file() else {}
    if preflight_value.get("success") is not True:
        raise OperatorError("Eksisterende manifest mangler en grøn preflight.")
    if preflight_value.get("evidence", {}).get("manifest_sha256") != common._sha_bytes(raw):
        # The preflight binds the unbound manifest. Once positive run ids are added,
        # that digest legitimately changes; only require equality before first bind.
        if not any(item.get("run_id") for item in manifest.get("runs", []) if isinstance(item, dict)):
            raise OperatorError("Preflightens manifest-hash matcher ikke det ubrugte manifest.")


def prepare_or_resume(paths: Mapping[str, Path], planner: str) -> dict[str, Any]:
    if MANIFEST.exists():
        manifest, raw = common._load_json(MANIFEST)
        validate_resume_manifest(manifest, raw)
        bound = sum(
            1 for item in manifest.get("runs", [])
            if isinstance(item, dict) and item.get("run_id")
        )
        if JOURNAL.exists() and bound != common.RUN_COUNT:
            raise OperatorError("Negativ journal findes, før alle 20 positive runs er bundet.")
        stage.ok(f"Eksisterende manifest genoptages: {bound}/20 positive runs bundet.")
        return manifest

    if any(path.exists() for path in (JOURNAL, NEGATIVE, REPORT, PREFLIGHT_REPORT)):
        raise OperatorError("T-022-evidens findes uden manifest; arkivér validation-filerne før start.")
    regenerate_rig_validation(planner)
    operator = prompt("Operatørnavn", os.environ.get("USERNAME", "Anders"))
    manifest = common.prepare_manifest(operator=operator, rig_validation_path=RIG_REPORT)
    common._atomic_json(MANIFEST, manifest)
    run_preflight(paths)
    stage.ok("20-run manifest er forberedt; journalen oprettes først efter alle binds.")
    return manifest


def snapshot_rows(paths: Mapping[str, Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    snapshots = [
        forensics.snapshot_sqlite(paths["agent_db"]),
        forensics.snapshot_sqlite(paths["approval_db"]),
        forensics.snapshot_sqlite(paths["audit_db"]),
    ]
    try:
        return (
            forensics.load_run_records(snapshots[0]),
            forensics.load_approval_rows(snapshots[1]),
            forensics.load_audit_rows(snapshots[2]),
        )
    finally:
        for item in snapshots:
            item.unlink(missing_ok=True)


def read_notes(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise OperatorError(f"Notesfilen er ikke en regulær fil: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise OperatorError(f"Kan ikke læse notesfilen: {exc}") from exc


def validate_positive_record(
    *,
    ordinal: int,
    marker: str,
    record: dict[str, Any],
    approvals: list[dict[str, Any]],
    audits: list[dict[str, Any]],
    notes: str,
) -> None:
    errors: list[str] = []
    forensics._validate_success_run(
        record=record,
        marker=marker,
        approval_rows=approvals,
        audit_rows=audits,
        errors=errors,
        label=f"positive run {ordinal}",
    )
    count = notes.splitlines().count(marker)
    if count != 1:
        errors.append(f"marker forekommer {count} gange i notes.md")
    if errors:
        raise OperatorError("Positivt run er ikke forensisk grønt: " + "; ".join(errors))


def recover_unbound_positive(
    *,
    ordinal: int,
    marker: str,
    paths: Mapping[str, Path],
) -> str | None:
    notes = read_notes(paths["notes"])
    count = notes.splitlines().count(marker)
    if count == 0:
        return None
    if count != 1:
        raise OperatorError(f"Ubundet ordinal {ordinal} forekommer {count} gange i notes.md.")
    runs, approvals, audits = snapshot_rows(paths)
    matching = [
        record for record in runs
        if forensics._marker_from_run(record) == marker
    ]
    if len(matching) != 1:
        raise OperatorError(
            f"Ubundet ordinal {ordinal} har {len(matching)} matchende run-records; kan ikke recover sikkert."
        )
    validate_positive_record(
        ordinal=ordinal,
        marker=marker,
        record=matching[0],
        approvals=approvals,
        audits=audits,
        notes=notes,
    )
    require_phrase(f"{RECOVERY_PHRASE} ORDINAL {ordinal}")
    return str(matching[0]["id"])


def positive_runs(manifest: dict[str, Any], paths: Mapping[str, Path]) -> dict[str, Any]:
    for item in manifest.get("runs", []):
        if not isinstance(item, dict) or item.get("run_id"):
            continue
        ordinal = int(item["ordinal"])
        marker = str(item["marker"])
        recovered = recover_unbound_positive(
            ordinal=ordinal,
            marker=marker,
            paths=paths,
        )
        if recovered:
            reporter.bind_run(manifest, ordinal, recovered)
            common._atomic_json(MANIFEST, manifest)
            stage.ok(f"Ordinal {ordinal} blev sikkert recovered og bundet.")
            continue

        stage.heading(f"POSITIV T-022 RUN {ordinal}/20")
        print(f"  Exact marker (hele note_append.text):\n\n    {marker}\n")
        print("  1. Opret server-authoriseret preview med præcis ét note_append-step.")
        print("  2. Kontrollér target, append-only konsekvens og den komplette marker.")
        require_phrase(f"{PREVIEW_PHRASE} ORDINAL {ordinal}")
        print("  3. Godkend fra den parrede Android-enhed; wizard'en kan ikke gøre det.")
        require_phrase(f"{APPROVAL_PHRASE} ORDINAL {ordinal}")
        print("  4. Vent til den synlige run-state er completed.")
        require_phrase(f"{COMPLETED_PHRASE} ORDINAL {ordinal}")
        run_id = getpass.getpass("  Indsæt run-id (skjult; bindes i manifestet): ").strip()
        if not common._OPAQUE_ID.fullmatch(run_id):
            raise OperatorError("Run-id er tomt eller ugyldigt.")
        runs, approvals, audits = snapshot_rows(paths)
        record = next((entry for entry in runs if entry.get("id") == run_id), None)
        if record is None:
            raise OperatorError(f"Run {run_id} findes ikke i Agent 3-ledgeren.")
        validate_positive_record(
            ordinal=ordinal,
            marker=marker,
            record=record,
            approvals=approvals,
            audits=audits,
            notes=read_notes(paths["notes"]),
        )
        reporter.bind_run(manifest, ordinal, run_id)
        common._atomic_json(MANIFEST, manifest)
        stage.ok(f"Ordinal {ordinal} er bundet og forensisk grøn.")
    return manifest


def ensure_journal(manifest: dict[str, Any]) -> None:
    if sum(
        1 for item in manifest.get("runs", [])
        if isinstance(item, dict) and item.get("run_id")
    ) != common.RUN_COUNT:
        raise OperatorError("Journalen må først initialiseres efter 20/20 positive binds.")
    if not JOURNAL.exists():
        journal_store._init(JOURNAL, MANIFEST)
        stage.ok("Negativ hashkædet journal er bundet til det færdige 20-run manifest.")
        return
    current, raw = common._load_json(MANIFEST)
    journal_store.verify_journal_binding(JOURNAL, current, raw)


def journal_state(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    current, raw = common._load_json(MANIFEST)
    rows, _final = journal_store.verify_journal_binding(JOURNAL, current, raw)
    _meta, cases = journal_store._state(rows)
    result: dict[str, dict[str, Any]] = {}
    for case_id, value in cases.items():
        begin = value.get("begin")
        if not isinstance(begin, dict):
            continue
        name = begin.get("payload", {}).get("name")
        if isinstance(name, str):
            result[name] = {"case_id": case_id, **value}
    return result


def approval_count(paths: Mapping[str, Path]) -> int:
    snapshot = forensics.snapshot_sqlite(paths["approval_db"])
    try:
        return len(forensics.load_approval_rows(snapshot))
    finally:
        snapshot.unlink(missing_ok=True)


def marker_count(path: Path, marker: str) -> int:
    if not path.exists():
        return 0
    return path.read_text(encoding="utf-8").splitlines().count(marker)


def response_file(case_name: str, index: int) -> Path:
    RESPONSES.mkdir(parents=True, exist_ok=True)
    mode = prompt("Response-kilde (paste/file)", "paste").lower()
    destination = RESPONSES / f"{case_name}-{index:02d}.body"
    if mode == "file":
        source = Path(prompt("Sti til fil med exact response body")).expanduser()
        if source.is_symlink() or not source.is_file():
            raise OperatorError("Response-filen findes ikke eller er ikke regulær.")
        destination.write_bytes(source.read_bytes())
    elif mode == "paste":
        body = input("  Indsæt exact response body på én linje: ")
        destination.write_bytes(body.encode("utf-8"))
    else:
        raise OperatorError("Response-kilde skal være paste eller file.")
    return destination


def observed_statuses(case: Mapping[str, Any]) -> list[int]:
    statuses: list[int] = []
    for row in case.get("observations", []):
        value = row.get("payload", {}).get("status") if isinstance(row, dict) else None
        if isinstance(value, int) and not isinstance(value, bool):
            statuses.append(value)
    return statuses


def validate_status_contract(name: str, statuses: list[int]) -> None:
    valid = False
    if name == "deny":
        valid = statuses == [200]
    elif name in {"timeout", "changed_args", "stale_revision", "replay"}:
        valid = statuses == [409]
    elif name == "concurrent_approval":
        valid = len(statuses) == 2 and sorted(statuses) == [200, 409]
    elif name == "stop_retry_replan":
        valid = len(statuses) >= 3 and all(value in {200, 202, 409} for value in statuses)
    if not valid:
        raise OperatorError(f"Negativ case {name} har ugyldig statussekvens: {statuses}")


def begin_or_resume_negative(
    *,
    name: str,
    manifest: dict[str, Any],
    paths: Mapping[str, Path],
) -> tuple[str, str, int, int, int]:
    existing = journal_state(manifest).get(name)
    if existing:
        if existing.get("finish") is not None:
            raise OperatorError(f"Case {name} er allerede lukket.")
        begin = existing["begin"]["payload"]
        stage.ok(
            f"Genoptager åben case {name} efter {len(existing['observations'])} observationer."
        )
        return (
            str(existing["case_id"]),
            str(begin["marker"]),
            int(begin["note_count_before"]),
            int(begin["approval_use_count_before"]),
            len(existing["observations"]),
        )

    positive_ordinal: int | None = None
    marker_hint: str | None = None
    if name in {"replay", "stop_retry_replan"}:
        default = "1" if name == "replay" else "2"
        raw = prompt("Positiv ordinal som casen skal målrette", default)
        try:
            positive_ordinal = int(raw)
            target = manifest["runs"][positive_ordinal - 1]
            marker_hint = str(target["marker"])
        except (ValueError, IndexError, KeyError, TypeError) as exc:
            raise OperatorError("Positiv ordinal er ugyldig.") from exc
        if not target.get("run_id"):
            raise OperatorError("Den valgte positive ordinal er endnu ikke fysisk bundet.")

    note_before = marker_count(paths["notes"], marker_hint) if marker_hint else 0
    approval_before = approval_count(paths)
    case_id, marker = journal_cases.begin_case(
        journal=JOURNAL,
        manifest_path=MANIFEST,
        name=name,
        note_count=note_before,
        approval_count=approval_before,
        positive_ordinal=positive_ordinal,
    )
    return case_id, marker, note_before, approval_before, 0


def record_negative_case(
    *,
    name: str,
    manifest: dict[str, Any],
    paths: Mapping[str, Path],
) -> None:
    case_id, marker, note_before, approval_before, existing_count = begin_or_resume_negative(
        name=name,
        manifest=manifest,
        paths=paths,
    )
    stage.heading(f"NEGATIV T-022 CASE — {name}")
    print(f"  {NEGATIVE_GUIDANCE[name]}")
    print(f"  Exact marker/target:\n\n    {marker}\n")
    if existing_count == 0:
        require_phrase(f"{NEGATIVE_START_PHRASE} {name}")

    minimum = NEGATIVE_MIN_OBSERVATIONS[name]
    observation = existing_count
    add_more = observation < minimum
    if observation >= minimum:
        answer = prompt("Tilføj flere request-observationer? (ja/nej)", "nej").lower()
        if answer not in {"ja", "nej"}:
            raise OperatorError("Svar skal være ja eller nej.")
        add_more = answer == "ja"
    while add_more:
        observation += 1
        try:
            status = int(prompt(f"HTTP-status for observation {observation}"))
        except ValueError as exc:
            raise OperatorError("HTTP-status skal være et heltal.") from exc
        body_path = response_file(name, observation)
        run_id = getpass.getpass("  Run-id for observationen (skjult): ").strip()
        journal_cases.observe_request(
            journal=JOURNAL,
            case_id=case_id,
            status=status,
            response_path=body_path,
            run_id=run_id,
        )
        if observation < minimum:
            continue
        answer = prompt("Flere request-observationer? (ja/nej)", "nej").lower()
        if answer not in {"ja", "nej"}:
            raise OperatorError("Svar skal være ja eller nej.")
        add_more = answer == "ja"

    current_case = journal_state(manifest)[name]
    validate_status_contract(name, observed_statuses(current_case))
    note_after = marker_count(paths["notes"], marker)
    approval_after = approval_count(paths)
    expected = NEGATIVE_EXPECTED_DELTAS[name]
    actual = (note_after - note_before, approval_after - approval_before)
    print(
        f"  Målte deltas: note={actual[0]}, approval-use={actual[1]} "
        f"(forventet {expected})"
    )
    if actual != expected:
        raise OperatorError(
            f"Negativ case {name} har forkerte deltas {actual}; journalcasen forbliver åben."
        )
    require_phrase(f"{NEGATIVE_FINISH_PHRASE} {name}")
    journal_cases.finish_case(
        journal=JOURNAL,
        case_id=case_id,
        note_count=note_after,
        approval_count=approval_after,
    )
    stage.ok(f"Negativ case {name} er append-only journalført og lukket.")


def negative_cases(manifest: dict[str, Any], paths: Mapping[str, Path]) -> None:
    for name in common._NEGATIVE_CASES:
        state = journal_state(manifest).get(name)
        if state and state.get("finish") is not None:
            continue
        record_negative_case(name=name, manifest=manifest, paths=paths)
    negative = journal_cases.finalize(JOURNAL, MANIFEST)
    common._atomic_json(NEGATIVE, negative)
    stage.ok("Alle syv negative cases er finaliseret fra den verificerede hashkæde.")


def collect(paths: Mapping[str, Path]) -> int:
    report = reporter.collect_report(
        manifest_path=MANIFEST,
        negative_path=NEGATIVE,
        negative_journal_path=JOURNAL,
        rig_validation_path=RIG_REPORT,
        agent_db=paths["agent_db"],
        approval_db=paths["approval_db"],
        audit_db=paths["audit_db"],
        notes_path=paths["notes"],
    )
    common._atomic_json(REPORT, report)
    if report.get("success") is not True:
        print("\n  T-022-RAPPORT: BLOKERET")
        for blocker in report.get("blockers", []):
            print(f"    - {blocker}")
        return 2
    stage.heading("T-022 FYSISK WRITE-PILOT BESTÅET")
    stage.ok("20/20 positive runs og 7/7 negative cases er forensisk grønne.")
    stage.ok(f"Rapport: {REPORT}")
    stage.ok("production_activation=false")
    return 0


def main() -> int:
    if os.name != "nt":
        raise OperatorError("T-022 one-click-operatoren skal køres på Windows-riggen.")
    os.chdir(ROOT)
    stage.heading("Kaliv T-022 — fysisk append-only write-pilot")
    print("  Wizard'en kan ikke selv godkende en write eller se confirmation-kortet.")
    print("  Alle 20 approvals kræver præcise operatørfraser og durable ledger-beviser.")
    print("  Negative cases lukkes kun ved de kontraktmæssige statusser og deltas.")
    print("  Den kan ikke merge, pushe, tagge, release eller aktivere produktion.")

    ensure_candidate()
    ensure_secrets()
    paths = evidence_paths()
    configure_environment(paths)
    planner = ensure_stack()
    adb = find_adb()
    one_android_device(adb)
    build_install_android(adb)
    launch_surfaces(adb)
    manifest = prepare_or_resume(paths, planner)
    manifest = positive_runs(manifest, paths)
    ensure_journal(manifest)
    negative_cases(manifest, paths)
    return collect(paths)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print(
            "\n  SIKKERT STOP: afbrudt; manifest, journal og responses er bevaret.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    except Exception as exc:
        print(
            f"\n  SIKKERT STOP: {type(exc).__name__}: {str(exc)[:1500]}",
            file=sys.stderr,
        )
        print("  Ingen case er auto-godkendt; eksisterende evidens er bevaret.", file=sys.stderr)
        raise SystemExit(1)
