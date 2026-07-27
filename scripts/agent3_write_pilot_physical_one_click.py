#!/usr/bin/env python3
"""One-click Windows operator for the physical T-022 append-only write pilot.

The wizard automates reproducible setup and forensic bookkeeping only. It cannot
approve a write, observe a screen, invent an HTTP response, or make a physical
pilot green. Positive runs require exact operator attestations and are verified
against notes.md, the Agent 3 ledger, approval-use DB and ToolGate audit before
continuing. Negative requests are captured in the append-only hash-chained
journal and cannot be edited away later.

It never merges, pushes, tags, releases, changes normal routing or activates
production.
"""
from __future__ import annotations

import getpass
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
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
PREFLIGHT_REPORT = VALIDATION / "agent3-write-pilot-preflight.json"
NEGATIVE_JOURNAL = VALIDATION / "agent3-write-pilot-negative-journal.db"
NEGATIVE_JSON = VALIDATION / "agent3-write-pilot-negative.json"
FINAL_REPORT = VALIDATION / "agent3-write-pilot-latest.json"
OPERATOR_STATE = VALIDATION / "agent3-write-pilot-operator-state.json"
RESPONSE_DIR = VALIDATION / "agent3-write-pilot-responses"
RIG_REPORT = VALIDATION / "agent3-rig-validation-latest.json"
BRANCH = "agent/t022-write-pilot-physical-operator"
VERSION = "1.58.146"
BASE_URL = "http://127.0.0.1:8080"
ANDROID_PACKAGE = "dk.ternedal.modelrig"
ANDROID_ACTIVITY = f"{ANDROID_PACKAGE}/.MainActivity"
ANDROID_AGENT3_EXTRA = "dk.ternedal.modelrig.extra.AGENT3"
STATE_SCHEMA = "kaliv-agent3-write-pilot-operator-state/v1"
NEGATIVE_CASES = (
    "deny",
    "timeout",
    "changed_args",
    "stale_revision",
    "replay",
    "concurrent_approval",
    "stop_retry_replan",
)
POSITIVE_ATTEST_PREFIX = "PREVIEWET T-022"
APPROVAL_ATTEST_PREFIX = "GODKENDT T-022"
NEGATIVE_ATTEST_PREFIX = "OBSERVERET T-022"
NEGATIVE_RECEIPT_PREFIX = "KVITTERING T-022"

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


pilot = _load_module("t022_operator_report", SCRIPTS / "agent3_write_pilot_report.py")
preflight = _load_module(
    "t022_operator_preflight", SCRIPTS / "agent3_write_pilot_preflight.py"
)
recorder = _load_module("t022_operator_recorder", SCRIPTS / "agent3_write_pilot_recorder.py")
journal = _load_module(
    "t022_operator_journal", SCRIPTS / "agent3_write_pilot_journal_cases.py"
)
journal_store = _load_module(
    "t022_operator_journal_store", SCRIPTS / "agent3_write_pilot_journal_store.py"
)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def load_json(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise OperatorError(f"JSON-filen mangler eller er uregelmæssig: {path}")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OperatorError(f"Ugyldig UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise OperatorError(f"JSON-roden er ikke et objekt: {path}")
    return value, raw


def run(
    args: list[str],
    *,
    cwd: Path = ROOT,
    check: bool = True,
    capture: bool = False,
    binary: bool = False,
    timeout: int = 900,
) -> subprocess.CompletedProcess[Any]:
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            env=os.environ.copy(),
            text=not binary,
            capture_output=capture,
            check=False,
            timeout=timeout,
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


def require_exact(expected: str) -> None:
    entered = input(f"  Skriv præcis '{expected}' for at fortsætte: ").strip()
    if entered != expected:
        raise OperatorError("Attesteringen matchede ikke; evidensen forbliver rød.")


def path_prompt(label: str, default: Path) -> Path:
    return Path(prompt(label, str(default))).expanduser().resolve()


def ensure_candidate() -> dict[str, Any]:
    stage.BRANCH = BRANCH
    stage.VERSION = VERSION
    sha = stage.ensure_candidate()
    identity = pilot.candidate_identity(ROOT)
    if (
        identity.get("git_sha") != sha
        or identity.get("version") != VERSION
        or identity.get("working_tree_clean") is not True
        or identity.get("version_stamps_consistent") is not True
    ):
        raise OperatorError("Kandidatidentiteten er ikke ren og exact-head-bundet.")
    return identity


def ensure_token() -> str:
    token = os.environ.get("MODELRIG_TOKEN", "").strip()
    if not token:
        token = getpass.getpass("  Indsæt MODELRIG_TOKEN (skjult, gemmes ikke): ").strip()
    if not token:
        raise OperatorError("MODELRIG_TOKEN er tomt.")
    os.environ["MODELRIG_TOKEN"] = token
    return token


def ensure_approval_secret() -> str:
    secret = os.environ.get("KALIV_AGENT3_APPROVAL_SECRET", "")
    if not secret:
        secret = getpass.getpass(
            "  Indsæt fælles KALIV_AGENT3_APPROVAL_SECRET (skjult, gemmes ikke): "
        )
    if len(secret.encode("utf-8")) < 32:
        raise OperatorError("Approval-secret skal være mindst 32 UTF-8-bytes.")
    os.environ["KALIV_AGENT3_APPROVAL_SECRET"] = secret
    os.environ["KALIV_AGENT3_APPROVAL_REQUIRED"] = "1"
    return secret


def configure_paths(existing_state: Mapping[str, Any] | None = None) -> dict[str, Path]:
    saved = existing_state.get("paths") if isinstance(existing_state, Mapping) else {}
    if not isinstance(saved, Mapping):
        saved = {}
    data_default = Path(
        str(saved.get("data_dir") or os.environ.get("KALIV_DATA_DIR") or ROOT / "data")
    )
    data_dir = path_prompt("KALIV_DATA_DIR", data_default)
    tools_default = Path(
        str(saved.get("tools_dir") or os.environ.get("KALIV_TOOLS_DIR") or data_dir / "tools")
    )
    tools_dir = path_prompt("KALIV_TOOLS_DIR", tools_default)
    paths = {
        "data_dir": data_dir,
        "tools_dir": tools_dir,
        "agent_db": path_prompt(
            "Agent 3-run database",
            Path(
                str(
                    saved.get("agent_db")
                    or os.environ.get("KALIV_AGENT3_DB")
                    or data_dir / "kaliv-agent3.db"
                )
            ),
        ),
        "approval_db": path_prompt(
            "Approval-use database",
            Path(
                str(
                    saved.get("approval_db")
                    or os.environ.get("KALIV_AGENT3_APPROVAL_DB")
                    or data_dir / "kaliv-agent3-approvals.db"
                )
            ),
        ),
        "audit_db": path_prompt(
            "ToolGate audit database",
            Path(
                str(
                    saved.get("audit_db")
                    or os.environ.get("KALIV_AUDIT_DB")
                    or data_dir / "kaliv-audit.db"
                )
            ),
        ),
        "notes": path_prompt(
            "notes.md",
            Path(str(saved.get("notes") or tools_dir / "notes.md")),
        ),
    }
    data_dir.mkdir(parents=True, exist_ok=True)
    tools_dir.mkdir(parents=True, exist_ok=True)
    os.environ.update(
        {
            "KALIV_DATA_DIR": str(data_dir),
            "KALIV_TOOLS_DIR": str(tools_dir),
            "KALIV_AGENT3_DB": str(paths["agent_db"]),
            "KALIV_AGENT3_APPROVAL_DB": str(paths["approval_db"]),
            "KALIV_AUDIT_DB": str(paths["audit_db"]),
            "KALIV_AGENT3_ENABLED": "1",
            "KALIV_TOOLS_ENABLED": "1",
            "KALIV_AGENT3_TASK_UI": "0",
            "KALIV_AGENT3_VALIDATION_REPORT": str(RIG_REPORT),
        }
    )
    return paths


def ensure_stack_and_rig(identity: Mapping[str, Any]) -> None:
    planner = stage.ensure_models()
    stage.ensure_device_token()
    stage.heading("Start exact-head backend og worker til T-022")
    stage.note("Approval-required=1; normal task-routing forbliver slået fra.")
    stage.start_stack(planner)

    assessment: dict[str, Any] | None = None
    if RIG_REPORT.is_file():
        try:
            assessment, _digest = pilot.assess_rig_validation(
                RIG_REPORT, dict(identity), now=time.time()
            )
        except Exception:
            assessment = None
    if not assessment or assessment.get("eligible_for_write_pilot") is not True:
        stage.heading("Kør frisk kandidatbundet rig-validation")
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
        assessment, _digest = pilot.assess_rig_validation(
            RIG_REPORT, dict(identity), now=time.time()
        )
    if assessment.get("eligible_for_write_pilot") is not True:
        raise OperatorError("Rig-validation er ikke eligible_for_write_pilot.")
    stage.ok("Rig-validation er frisk og kandidatbundet til write-piloten.")


def archive_session() -> None:
    candidates = [
        MANIFEST,
        PREFLIGHT_REPORT,
        NEGATIVE_JOURNAL,
        NEGATIVE_JSON,
        FINAL_REPORT,
        OPERATOR_STATE,
    ]
    existing = [path for path in candidates if path.exists() or path.is_symlink()]
    if RESPONSE_DIR.exists():
        existing.append(RESPONSE_DIR)
    if not existing:
        return
    archive = VALIDATION / "archive" / time.strftime("t022-write-pilot-%Y%m%d-%H%M%S")
    archive.mkdir(parents=True, exist_ok=True)
    for source in existing:
        source.replace(archive / source.name)
    stage.note(f"Tidligere T-022-session er bevaret i {archive}")


def session_state(identity: Mapping[str, Any]) -> dict[str, Any] | None:
    if not OPERATOR_STATE.is_file():
        return None
    state, _raw = load_json(OPERATOR_STATE)
    if state.get("schema") != STATE_SCHEMA or state.get("production_activation") is not False:
        raise OperatorError("Operator-state har forkert schema eller activation-boundary.")
    target = state.get("candidate") if isinstance(state.get("candidate"), Mapping) else {}
    for field in ("version", "git_sha", "code_sha256", "identity_source"):
        if target.get(field) != identity.get(field):
            raise OperatorError(f"Operator-state tilhører en anden kandidat ({field}).")
    return state


def save_state(
    *,
    identity: Mapping[str, Any],
    pilot_id: str,
    prepared_manifest_sha256: str,
    paths: Mapping[str, Path],
    preflight_sha256: str | None = None,
    status: str = "prepared",
) -> dict[str, Any]:
    current = session_state(identity) or {}
    value = {
        "schema": STATE_SCHEMA,
        "updated_at": iso_now(),
        "candidate": {
            key: identity.get(key)
            for key in ("version", "git_sha", "code_sha256", "identity_source")
        },
        "pilot_id": pilot_id,
        "prepared_manifest_sha256": prepared_manifest_sha256,
        "preflight_sha256": preflight_sha256 or current.get("preflight_sha256"),
        "paths": {key: str(path) for key, path in paths.items()},
        "status": status,
        "production_activation": False,
    }
    atomic_json(OPERATOR_STATE, value)
    return value


def prepare_or_resume(
    identity: Mapping[str, Any], paths: Mapping[str, Path]
) -> tuple[dict[str, Any], dict[str, Any]]:
    state = session_state(identity)
    if MANIFEST.is_file():
        manifest, raw = load_json(MANIFEST)
        errors = pilot.validate_manifest(manifest, require_bound=False)
        if errors:
            raise OperatorError("Eksisterende manifest er ugyldigt: " + "; ".join(errors))
        target = manifest.get("target") if isinstance(manifest.get("target"), Mapping) else {}
        for field in ("version", "git_sha", "code_sha256", "identity_source"):
            if target.get(field) != identity.get(field):
                raise OperatorError(f"Manifestet tilhører en anden kandidat ({field}).")
        if state is None:
            raise OperatorError(
                "Manifest findes uden kandidatbundet operator-state; arkivér manuelt eller start nyt."
            )
        expected = f"FORTSÆT T-022 {manifest.get('pilot_id')}"
        alternative = "NY T-022 KAMPAGNE"
        entered = input(
            f"  Skriv præcis '{expected}' for resume eller '{alternative}' for ny session: "
        ).strip()
        if entered == alternative:
            archive_session()
            return prepare_or_resume(identity, paths)
        if entered != expected:
            raise OperatorError("Session-valget matchede ikke; intet blev ændret.")
        if state.get("pilot_id") != manifest.get("pilot_id"):
            raise OperatorError("Operator-state og manifest har forskelligt pilot-id.")
        if state.get("prepared_manifest_sha256") is None:
            raise OperatorError("Operator-state mangler det oprindelige manifest-digest.")
        stage.ok(
            f"Genoptager pilot {manifest.get('pilot_id')} med "
            f"{sum(1 for item in manifest['runs'] if item.get('run_id'))}/20 bundne runs."
        )
        return manifest, state

    manifest = pilot.prepare_manifest(
        operator=prompt("Operatørnavn", os.environ.get("USERNAME", "Anders")),
        rig_validation_path=RIG_REPORT,
    )
    pilot._atomic_json(MANIFEST, manifest)
    raw = MANIFEST.read_bytes()
    state = save_state(
        identity=identity,
        pilot_id=str(manifest["pilot_id"]),
        prepared_manifest_sha256=sha256_bytes(raw),
        paths=paths,
        status="manifest_prepared",
    )
    stage.ok(f"Forberedte 20 uforudsigelige markers i {MANIFEST}.")
    return manifest, state


def ensure_preflight(
    *,
    manifest: Mapping[str, Any],
    state: Mapping[str, Any],
    identity: Mapping[str, Any],
    paths: Mapping[str, Path],
    token: str,
) -> None:
    bound = [item for item in manifest["runs"] if item.get("run_id")]
    if bound:
        if not PREFLIGHT_REPORT.is_file() or not state.get("preflight_sha256"):
            raise OperatorError("En startet pilot mangler den oprindelige grønne preflight.")
        report, raw = load_json(PREFLIGHT_REPORT)
        if (
            report.get("success") is not True
            or report.get("pilot_id") != manifest.get("pilot_id")
            or report.get("production_activation") is not False
            or sha256_bytes(raw) != state.get("preflight_sha256")
            or report.get("evidence", {}).get("manifest_sha256")
            != state.get("prepared_manifest_sha256")
        ):
            raise OperatorError("Den gemte preflight matcher ikke den startede session.")
        stage.ok("Genbruger den immutable grønne preflight fra før første append.")
        return

    report = preflight.run_preflight(
        manifest_path=MANIFEST,
        rig_validation_path=RIG_REPORT,
        agent_db=paths["agent_db"],
        approval_db=paths["approval_db"],
        audit_db=paths["audit_db"],
        notes_path=paths["notes"],
        negative_journal_path=NEGATIVE_JOURNAL,
        base_url=BASE_URL,
        token=token,
    )
    preflight._atomic_json(PREFLIGHT_REPORT, report)
    if report.get("success") is not True:
        print("\n  T-022 PREFLIGHT: BLOKERET")
        for blocker in report.get("blockers", []):
            print(f"    - {blocker}")
        raise OperatorError("Preflight er rød; ingen fysisk append må startes.")
    raw = PREFLIGHT_REPORT.read_bytes()
    save_state(
        identity=identity,
        pilot_id=str(manifest["pilot_id"]),
        prepared_manifest_sha256=str(state["prepared_manifest_sha256"]),
        paths=paths,
        preflight_sha256=sha256_bytes(raw),
        status="preflight_green",
    )
    stage.ok("Read-only preflight er grøn; journalen findes endnu ikke.")


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
    stage.heading("Byg og installer exact-head approval-klienten")
    run([str(gradlew), ":app:assembleDebug"], cwd=ROOT / "android")
    apk = ROOT / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    if not apk.is_file():
        raise OperatorError(f"APK mangler efter build: {apk}")
    run([adb, "install", "-r", str(apk)])
    stage.ok(f"Installeret {apk.name} på den tilsluttede Android-enhed.")


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


def evidence_snapshot(paths: Mapping[str, Path]) -> dict[str, Any]:
    snapshots = [
        pilot.snapshot_sqlite(paths["agent_db"]),
        pilot.snapshot_sqlite(paths["approval_db"]),
        pilot.snapshot_sqlite(paths["audit_db"]),
    ]
    try:
        agent_snapshot, approval_snapshot, audit_snapshot = snapshots
        notes_raw = paths["notes"].read_bytes() if paths["notes"].is_file() else b""
        try:
            notes = notes_raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise OperatorError("notes.md er ikke UTF-8.") from exc
        return {
            "runs": pilot.load_run_records(agent_snapshot),
            "approvals": pilot.load_approval_rows(approval_snapshot),
            "audits": pilot.load_audit_rows(audit_snapshot),
            "notes": notes,
        }
    finally:
        for snapshot in snapshots:
            snapshot.unlink(missing_ok=True)


def marker_count(snapshot: Mapping[str, Any], marker: str) -> int:
    return str(snapshot.get("notes") or "").splitlines().count(marker)


def approval_count(snapshot: Mapping[str, Any]) -> int:
    approvals = snapshot.get("approvals")
    return len(approvals) if isinstance(approvals, list) else 0


def verify_positive_run(
    *,
    ordinal: int,
    run_id: str,
    marker: str,
    paths: Mapping[str, Path],
    timeout_seconds: int = 120,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_reason = "run er endnu ikke synlig"
    while time.monotonic() < deadline:
        snapshot = evidence_snapshot(paths)
        record = next(
            (item for item in snapshot["runs"] if item.get("id") == run_id), None
        )
        if record is None:
            last_reason = "run-id findes ikke i Agent 3-ledgeren"
        elif record.get("state") != "completed":
            last_reason = f"run-state er {record.get('state')!r}, ikke 'completed'"
        else:
            errors: list[str] = []
            result = pilot._validate_success_run(
                record=record,
                marker=marker,
                approval_rows=snapshot["approvals"],
                audit_rows=snapshot["audits"],
                errors=errors,
                label=f"positive run {ordinal}",
            )
            count = marker_count(snapshot, marker)
            if result and not errors and count == 1:
                stage.ok(
                    f"Run {ordinal:02d} er forensisk grøn: én note, én approval og én audit."
                )
                return
            last_reason = "; ".join(errors + [f"note-count={count}"])
        time.sleep(2)
    raise OperatorError(f"Run {ordinal:02d} blev ikke forensisk grøn: {last_reason}")


def run_positive_cases(
    manifest: dict[str, Any], paths: Mapping[str, Path], adb: str
) -> None:
    launch_desktop_agent3()
    launch_android_agent3(adb)
    stage.heading("20 FYSISKE NOTE_APPEND-RUNS")
    for item in manifest["runs"]:
        ordinal = int(item["ordinal"])
        marker = str(item["marker"])
        existing_run = item.get("run_id")
        if existing_run:
            verify_positive_run(
                ordinal=ordinal,
                run_id=str(existing_run),
                marker=marker,
                paths=paths,
            )
            continue

        print(f"\n  RUN {ordinal:02d}/20")
        print("  Brug desktop Agent 3-developerfladen til en server-authoritativ preview.")
        print("  Previewet skal indeholde præcis ét note_append-step og denne komplette tekst:")
        print(f"\n    {marker}\n")
        print("  Kontrollér target, append-only konsekvens, exact args og confirmation digest.")
        require_exact(f"{POSITIVE_ATTEST_PREFIX} {ordinal:02d}")
        print("  Godkend nu fysisk fra den parrede Android-enhed og vent på completed.")
        require_exact(f"{APPROVAL_ATTEST_PREFIX} {ordinal:02d}")
        run_id = getpass.getpass(
            "  Indsæt completed run-id (skjult; gemmes kandidatbundet i manifestet): "
        ).strip()
        if not run_id:
            raise OperatorError("Run-id var tomt.")
        pilot.bind_run(manifest, ordinal, run_id)
        pilot._atomic_json(MANIFEST, manifest)
        verify_positive_run(
            ordinal=ordinal,
            run_id=run_id,
            marker=marker,
            paths=paths,
        )


def negative_contract(name: str) -> dict[str, Any]:
    contracts = {
        "deny": {"observations": 1, "statuses": [200], "note_delta": 0, "approval_delta": 0},
        "timeout": {"observations": 1, "statuses": [409], "note_delta": 0, "approval_delta": 0},
        "changed_args": {"observations": 1, "statuses": [409], "note_delta": 0, "approval_delta": 0},
        "stale_revision": {"observations": 1, "statuses": [409], "note_delta": 0, "approval_delta": 0},
        "replay": {"observations": 1, "statuses": [409], "note_delta": 0, "approval_delta": 0},
        "concurrent_approval": {
            "observations": 2,
            "statuses": [200, 409],
            "note_delta": 1,
            "approval_delta": 1,
        },
        "stop_retry_replan": {
            "observations": 3,
            "allowed_statuses": {200, 202, 409},
            "note_delta": 0,
            "approval_delta": 0,
        },
    }
    if name not in contracts:
        raise OperatorError(f"Ukendt negativ case: {name}")
    return contracts[name]


def negative_instructions(name: str, marker: str) -> list[str]:
    instructions = {
        "deny": [
            "Opret preview med marker og vælg Deny på den parrede enhed.",
            "Run skal ende med confirmation_denied og ingen side-effekt.",
        ],
        "timeout": [
            "Opret preview med marker og lad confirmation udløbe uden approval.",
            "Forsøg derefter approval; HTTP-resultatet skal være 409.",
        ],
        "changed_args": [
            "Opret confirmation for marker, men send approval mod ændrede text-args.",
            "Backend/worker skal afvise med 409 før note eller approval-use.",
        ],
        "stale_revision": [
            "Opret confirmation, fremprovokér en ny planrevision og brug den gamle approval.",
            "Stale revision skal afvises med 409.",
        ],
        "replay": [
            "Genbrug approval/action fra det allerede succesfulde positive run.",
            "Replay skal afvises med 409 og marker-count må forblive én.",
        ],
        "concurrent_approval": [
            "Send to samtidige approve-requests for samme nye confirmation.",
            "Præcis én skal lykkes (200), én skal afvises (409), og der må komme én note.",
        ],
        "stop_retry_replan": [
            "Brug den eksisterende positive marker gennem Stop, retry og replan-forsøg.",
            "Registrér mindst tre HTTP-observationer; marker-count må forblive én.",
        ],
    }[name]
    return [*instructions, f"Exact marker: {marker}"]


def response_file(case_name: str, index: int) -> Path:
    RESPONSE_DIR.mkdir(parents=True, exist_ok=True)
    path = RESPONSE_DIR / f"{case_name}-{index:02d}.json"
    if path.exists() or path.is_symlink():
        raise OperatorError(f"Response-filen findes allerede: {path}")
    path.write_bytes(b"")
    stage.note(
        "Notepad åbnes nu. Indsæt den EKSAKTE HTTP-response body, gem og luk vinduet."
    )
    run(["notepad.exe", str(path)], timeout=3600)
    if path.is_symlink() or not path.is_file():
        raise OperatorError("Response-filen blev ikke gemt som en regulær fil.")
    if path.stat().st_size > journal_store.MAX_RESPONSE_BYTES:
        raise OperatorError("Response body overskrider recorderens størrelsesgrænse.")
    return path


def journal_state(manifest: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_value, manifest_raw = load_json(MANIFEST)
    if manifest_value.get("pilot_id") != manifest.get("pilot_id"):
        raise OperatorError("Manifest ændrede pilot-id under journalbehandlingen.")
    rows, _final = journal_store.verify_journal_binding(
        NEGATIVE_JOURNAL, manifest_value, manifest_raw
    )
    meta, cases = journal_store._state(rows)
    return meta, cases


def verify_negative_result(
    *,
    name: str,
    begin_payload: Mapping[str, Any],
    finish_payload: Mapping[str, Any],
    statuses: list[int],
) -> list[str]:
    contract = negative_contract(name)
    errors: list[str] = []
    if name == "stop_retry_replan":
        if len(statuses) < int(contract["observations"]):
            errors.append("stop_retry_replan har færre end tre observationer")
        if any(status not in contract["allowed_statuses"] for status in statuses):
            errors.append("stop_retry_replan indeholder en ikke-tilladt HTTP-status")
    elif sorted(statuses) != sorted(contract["statuses"]):
        errors.append(f"HTTP-statusser er {statuses}, forventet {contract['statuses']}")
    note_delta = int(finish_payload["note_count_after"]) - int(
        begin_payload["note_count_before"]
    )
    approval_delta = int(finish_payload["approval_use_count_after"]) - int(
        begin_payload["approval_use_count_before"]
    )
    if note_delta != contract["note_delta"]:
        errors.append(f"note-delta er {note_delta}, forventet {contract['note_delta']}")
    if approval_delta != contract["approval_delta"]:
        errors.append(
            f"approval-delta er {approval_delta}, forventet {contract['approval_delta']}"
        )
    return errors


def run_negative_cases(manifest: dict[str, Any], paths: Mapping[str, Path]) -> None:
    if not NEGATIVE_JOURNAL.exists():
        recorder._init(NEGATIVE_JOURNAL, MANIFEST)
        stage.ok("Initialiserede kandidatbundet append-only negativ journal.")

    for name in NEGATIVE_CASES:
        _meta, cases = journal_state(manifest)
        matching = [
            case
            for case in cases.values()
            if case.get("begin") is not None
            and case["begin"]["payload"].get("name") == name
        ]
        if len(matching) > 1:
            raise OperatorError(f"Journalen har flere {name}-cases.")
        case = matching[0] if matching else None
        if case and case.get("finish") is not None:
            stage.ok(f"Negativ case {name} er allerede afsluttet i hashkæden.")
            continue

        if case is None:
            before = evidence_snapshot(paths)
            positive_ordinal = 1 if name == "replay" else 2 if name == "stop_retry_replan" else None
            initial_note_count = (
                marker_count(before, manifest["runs"][positive_ordinal - 1]["marker"])
                if positive_ordinal is not None
                else 0
            )
            case_id, marker = journal.begin_case(
                journal=NEGATIVE_JOURNAL,
                manifest_path=MANIFEST,
                name=name,
                note_count=initial_note_count,
                approval_count=approval_count(before),
                positive_ordinal=positive_ordinal,
            )
            _meta, cases = journal_state(manifest)
            case = cases[case_id]
        else:
            case_id = str(case["begin"]["case_id"])
            marker = str(case["begin"]["payload"]["marker"])
            stage.note(f"Genoptager åben negativ case {name}.")

        stage.heading(f"NEGATIV FYSISK CASE — {name}")
        for line in negative_instructions(name, marker):
            print(f"  - {line}")
        require_exact(f"{NEGATIVE_ATTEST_PREFIX} {name}")

        contract = negative_contract(name)
        observations = list(case.get("observations") or [])
        target = int(contract["observations"])
        while len(observations) < target:
            index = len(observations) + 1
            status_raw = prompt(f"HTTP-status for observation {index}")
            try:
                status = int(status_raw)
            except ValueError as exc:
                raise OperatorError("HTTP-status skal være et heltal.") from exc
            raw_run_id = getpass.getpass(
                f"  Run-id for observation {index} (skjult; journalen kræver rå id): "
            ).strip()
            if not raw_run_id:
                raise OperatorError("Run-id var tomt.")
            response = response_file(name, index)
            journal.observe_request(
                journal=NEGATIVE_JOURNAL,
                case_id=case_id,
                status=status,
                response_path=response,
                run_id=raw_run_id,
            )
            _meta, cases = journal_state(manifest)
            case = cases[case_id]
            observations = list(case.get("observations") or [])

        require_exact(f"{NEGATIVE_RECEIPT_PREFIX} {name}")
        after = evidence_snapshot(paths)
        journal.finish_case(
            journal=NEGATIVE_JOURNAL,
            case_id=case_id,
            note_count=marker_count(after, marker),
            approval_count=approval_count(after),
        )
        _meta, cases = journal_state(manifest)
        completed = cases[case_id]
        statuses = [int(item["payload"]["status"]) for item in completed["observations"]]
        errors = verify_negative_result(
            name=name,
            begin_payload=completed["begin"]["payload"],
            finish_payload=completed["finish"]["payload"],
            statuses=statuses,
        )
        if errors:
            raise OperatorError(
                f"Negativ case {name} er sandfærdigt gemt, men RØD: " + "; ".join(errors)
            )
        stage.ok(f"Negativ case {name} har korrekt status- og delta-kontrakt.")

    negative = recorder.finalize(NEGATIVE_JOURNAL, MANIFEST)
    pilot._atomic_json(NEGATIVE_JSON, negative)
    stage.ok(f"Kompilerede immutable negative evidence til {NEGATIVE_JSON}.")


def collect_final(
    *,
    identity: Mapping[str, Any],
    state: Mapping[str, Any],
    paths: Mapping[str, Path],
) -> int:
    report = pilot.collect_report(
        manifest_path=MANIFEST,
        negative_path=NEGATIVE_JSON,
        negative_journal_path=NEGATIVE_JOURNAL,
        rig_validation_path=RIG_REPORT,
        agent_db=paths["agent_db"],
        approval_db=paths["approval_db"],
        audit_db=paths["audit_db"],
        notes_path=paths["notes"],
    )
    pilot._atomic_json(FINAL_REPORT, report)
    if report.get("success") is not True:
        print("\n  T-022 FORENSISK RAPPORT: BLOKERET")
        for blocker in report.get("blockers", []):
            print(f"    - {blocker}")
        return 2
    save_state(
        identity=identity,
        pilot_id=str(report["pilot_id"]),
        prepared_manifest_sha256=str(state["prepared_manifest_sha256"]),
        paths=paths,
        preflight_sha256=str(state["preflight_sha256"]),
        status="physical_report_green",
    )
    stage.heading("T-022 FYSISK WRITE-PILOT BESTÅET")
    stage.ok("20/20 positive appends og 7/7 negative cases er forensisk bundet.")
    stage.ok(f"Rapport: {FINAL_REPORT}")
    stage.ok("production_activation=false; normal routing er fortsat uændret.")
    return 0


def main() -> int:
    os.chdir(ROOT)
    stage.heading("Kaliv T-022 — fysisk append-only write-pilot")
    print("  Wizard'en kan ikke selv approve, se UI eller opfinde responses.")
    print("  Hvert positivt run verificeres i fire faktiske sandhedskilder.")
    print("  Negative observations gemmes append-only og kan ikke redigeres væk.")
    print("  Ingen merge, push, tag, release eller production activation udføres.")

    identity = ensure_candidate()
    existing_state = session_state(identity)
    paths = configure_paths(existing_state)
    ensure_approval_secret()
    token = ensure_token()
    ensure_stack_and_rig(identity)
    manifest, state = prepare_or_resume(identity, paths)
    ensure_preflight(
        manifest=manifest,
        state=state,
        identity=identity,
        paths=paths,
        token=token,
    )
    state = session_state(identity) or state

    adb = find_adb()
    device_name, android_version = android_device(adb)
    stage.ok(f"Parret Android-enhed: {device_name} · Android {android_version}")
    build_install_android(adb)
    run_positive_cases(manifest, paths, adb)
    run_negative_cases(manifest, paths)
    return collect_final(identity=identity, state=state, paths=paths)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print(
            "\n  SIKKERT STOP: afbrudt af operatøren; manifest/journal er bevaret.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    except Exception as exc:
        print(
            f"\n  SIKKERT STOP: {type(exc).__name__}: {str(exc)[:1200]}",
            file=sys.stderr,
        )
        print(
            "  Ingen evidens er auto-godkendt. Delvis kandidatbundet state er bevaret.",
            file=sys.stderr,
        )
        raise SystemExit(1)
