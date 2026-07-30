#!/usr/bin/env python3
"""Physical operator wizard for the 20 positive T-022 note_append runs.

This first operator slice deliberately does not start a write-enabled stack and
never sends preview, start, approve, retry, replan or cancel requests. It requires
an already-running exact candidate, runs the existing authenticated GET-only
preflight, opens the existing developer clients, captures candidate-bound screen
artifacts, requires exact human attestations and binds each returned run id to the
prepared manifest.

The raw run id is stored only where the existing forensic manifest requires it.
The separate physical-observation journal stores only its SHA-256 digest.
"""
from __future__ import annotations

import getpass
import hashlib
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
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
OBSERVATIONS = VALIDATION / "agent3-write-pilot-positive-observations.json"
RIG_REPORT = VALIDATION / "agent3-rig-validation-latest.json"
NEGATIVE_JOURNAL = VALIDATION / "agent3-write-pilot-negative-journal.db"
EVIDENCE_DIR = VALIDATION / "agent3-write-pilot-evidence" / "positive"
BRANCH = "agent/t022-write-pilot-positive-operator"
VERSION = "1.58.146"
BASE_URL = os.environ.get("MODELRIG_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
OBSERVATIONS_SCHEMA = "kaliv-agent3-write-pilot-positive-observations/v1"
ANDROID_PACKAGE = "dk.ternedal.modelrig"
ANDROID_ACTIVITY = f"{ANDROID_PACKAGE}/.MainActivity"
ANDROID_AGENT3_EXTRA = "dk.ternedal.modelrig.extra.AGENT3"
PREVIEW_PHRASE = "PREVIEW {ordinal:02d} NOTE_APPEND MATCHER"
APPROVAL_PHRASE = "APPROVAL {ordinal:02d} ENHED GODKENDT"
OUTCOME_PHRASE = "OUTCOME {ordinal:02d} COMPLETED SYNLIG"

sys.path.insert(0, str(SCRIPTS))
import stage_a_one_click as stage  # noqa: E402
from agent3_write_pilot_common import (  # noqa: E402
    RUN_COUNT,
    PilotEvidenceError,
    _atomic_json,
    _load_json,
    _sha_bytes,
    _sha_text,
    bind_run,
    candidate_identity,
    prepare_manifest,
    validate_manifest,
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise OperatorError(f"Kan ikke indlæse {path.name}.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


preflight = _load_module(
    "t022_positive_operator_preflight",
    SCRIPTS / "agent3_write_pilot_preflight.py",
)


class OperatorError(RuntimeError):
    pass


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OperatorError(f"Kunne ikke køre {args[0]}: {exc}") from exc
    if check and result.returncode != 0:
        detail = ""
        if capture:
            output = result.stderr or result.stdout
            detail = (
                output.decode("utf-8", errors="replace")
                if isinstance(output, bytes)
                else (output or "")
            )
        raise OperatorError(
            f"Kommandoen fejlede ({result.returncode}): {' '.join(args)}"
            + (f"\n{detail[-1000:]}" if detail else "")
        )
    return result


def prompt(message: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"  {message}{suffix}: ").strip()
    return value or (default or "")


def require_phrase(expected: str) -> None:
    entered = input(f"  Skriv præcis '{expected}' for at fortsætte: ").strip()
    if entered != expected:
        raise OperatorError("Attesteringen matchede ikke; runnet forbliver ubundet.")


def existing_path(label: str, env_name: str, default: Path) -> Path:
    suggested = os.environ.get(env_name, "").strip() or str(default)
    value = Path(prompt(label, suggested)).expanduser()
    if value.is_symlink() or not value.is_file():
        raise OperatorError(f"{label} er ikke en regulær fil: {value}")
    return value.resolve()


def notes_path() -> Path:
    tools_dir = os.environ.get("KALIV_TOOLS_DIR", "").strip()
    suggested = Path(tools_dir) / "notes.md" if tools_dir else ROOT / "data" / "tools" / "notes.md"
    value = Path(prompt("Sti til kandidatens notes.md", str(suggested))).expanduser()
    target = value if value.exists() else value.parent
    if value.is_symlink() or target.is_symlink() or not target.exists():
        raise OperatorError(f"notes.md-stien er ugyldig: {value}")
    return value.resolve()


def database_paths() -> dict[str, Path]:
    data_dir = Path(os.environ.get("KALIV_DATA_DIR", "").strip() or (ROOT / "data"))
    return {
        "agent_db": existing_path(
            "Agent 3 run-database",
            "KALIV_AGENT3_DB",
            data_dir / "kaliv-agent3.db",
        ),
        "approval_db": existing_path(
            "Approval-use-database",
            "KALIV_AGENT3_APPROVAL_DB",
            data_dir / "kaliv-agent3-approvals.db",
        ),
        "audit_db": existing_path(
            "ToolGate audit-database",
            "KALIV_AUDIT_DB",
            data_dir / "kaliv-audit.db",
        ),
        "notes": notes_path(),
    }


def ensure_candidate() -> dict[str, Any]:
    stage.BRANCH = BRANCH
    stage.VERSION = VERSION
    sha = stage.ensure_candidate()
    identity = candidate_identity(ROOT)
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


def find_adb() -> str:
    adb = shutil.which("adb")
    if not adb:
        raise OperatorError("adb blev ikke fundet på PATH. Installer Android Platform Tools.")
    result = run([adb, "devices"], capture=True)
    devices = [
        line.split("\t", 1)[0]
        for line in result.stdout.splitlines()[1:]
        if "\tdevice" in line
    ]
    if len(devices) != 1:
        raise OperatorError(f"Der skal være præcis én ADB-enhed; fandt {len(devices)}.")
    return adb


def android_identity(adb: str) -> dict[str, str]:
    serial = run([adb, "get-serialno"], capture=True).stdout.strip()
    model = run([adb, "shell", "getprop", "ro.product.model"], capture=True).stdout.strip()
    release = run(
        [adb, "shell", "getprop", "ro.build.version.release"], capture=True
    ).stdout.strip()
    return {
        "serial_sha256": _sha_text(serial),
        "model": model or "unknown",
        "os_version": release or "unknown",
    }


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
    stage.ok(f"Installeret exact-head {apk.name}.")


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


def copy_marker(marker: str) -> None:
    run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "$input | Set-Clipboard",
        ],
        check=True,
        capture=False,
    ) if False else subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", "Set-Clipboard -Value $env:KALIV_T022_MARKER"],
        env={**os.environ, "KALIV_T022_MARKER": marker},
        check=False,
        timeout=20,
    )


def capture_android(adb: str, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = run([adb, "exec-out", "screencap", "-p"], capture=True, binary=True)
    if not result.stdout:
        raise OperatorError("Android-screenshot var tomt.")
    destination.write_bytes(result.stdout)
    return {
        "path": str(destination.relative_to(ROOT)),
        "sha256": _sha_bytes(destination.read_bytes()),
        "bytes": destination.stat().st_size,
    }


def capture_windows(destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    escaped = str(destination.resolve()).replace("'", "''")
    command = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "Add-Type -AssemblyName System.Drawing;"
        "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
        "$i=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
        "$g=[System.Drawing.Graphics]::FromImage($i);"
        "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size);"
        f"$i.Save('{escaped}',[System.Drawing.Imaging.ImageFormat]::Png);"
        "$g.Dispose();$i.Dispose()"
    )
    run(["powershell.exe", "-NoProfile", "-Command", command])
    if not destination.is_file() or destination.stat().st_size <= 0:
        raise OperatorError("Windows-screenshot blev ikke oprettet.")
    return {
        "path": str(destination.relative_to(ROOT)),
        "sha256": _sha_bytes(destination.read_bytes()),
        "bytes": destination.stat().st_size,
    }


def manifest_progress(manifest: Mapping[str, Any]) -> tuple[list[int], list[int]]:
    bound: list[int] = []
    pending: list[int] = []
    for item in manifest.get("runs", []):
        if not isinstance(item, Mapping) or not isinstance(item.get("ordinal"), int):
            continue
        target = bound if item.get("run_id") else pending
        target.append(int(item["ordinal"]))
    return sorted(bound), sorted(pending)


def new_observations(
    manifest: Mapping[str, Any],
    identity: Mapping[str, Any],
    preflight_report: Mapping[str, Any],
    android: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "schema": OBSERVATIONS_SCHEMA,
        "created_at": iso_now(),
        "updated_at": iso_now(),
        "pilot_id": manifest.get("pilot_id"),
        "operator": manifest.get("operator"),
        "candidate": {
            key: identity.get(key)
            for key in ("version", "git_sha", "code_sha256", "identity_source")
        },
        "preflight": {
            "report_path": str(PREFLIGHT_REPORT.relative_to(ROOT)),
            "manifest_sha256": preflight_report.get("evidence", {}).get("manifest_sha256"),
            "rig_validation_report_sha256": preflight_report.get("evidence", {}).get(
                "rig_validation_report_sha256"
            ),
            "generated_at": preflight_report.get("generated_at"),
        },
        "devices": {
            "android": dict(android),
            "windows": {
                "device_name": platform.node() or "Windows rig",
                "os_version": platform.platform(),
            },
        },
        "runs": [],
        "production_activation": False,
    }


def validate_resume(
    observations: Mapping[str, Any],
    manifest: Mapping[str, Any],
    identity: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    if observations.get("schema") != OBSERVATIONS_SCHEMA:
        errors.append("positive observations schema mismatch")
    if observations.get("pilot_id") != manifest.get("pilot_id"):
        errors.append("positive observations pilot_id mismatch")
    if observations.get("production_activation") is not False:
        errors.append("positive observations activated production")
    candidate = observations.get("candidate") if isinstance(observations.get("candidate"), Mapping) else {}
    for key in ("version", "git_sha", "code_sha256", "identity_source"):
        if candidate.get(key) != identity.get(key):
            errors.append(f"positive observations candidate.{key} mismatch")
    observed_ordinals = {
        item.get("ordinal")
        for item in observations.get("runs", [])
        if isinstance(item, Mapping)
    }
    bound, _pending = manifest_progress(manifest)
    if observed_ordinals != set(bound):
        errors.append(
            "positive observations do not exactly match the manifest's bound ordinals"
        )
    return errors


def run_preflight(
    *,
    manifest_path: Path,
    token: str,
    paths: Mapping[str, Path],
) -> dict[str, Any]:
    report = preflight.run_preflight(
        manifest_path=manifest_path,
        rig_validation_path=RIG_REPORT,
        agent_db=paths["agent_db"],
        approval_db=paths["approval_db"],
        audit_db=paths["audit_db"],
        notes_path=paths["notes"],
        negative_journal_path=NEGATIVE_JOURNAL,
        base_url=BASE_URL,
        token=token,
    )
    _atomic_json(PREFLIGHT_REPORT, report)
    if not report.get("success"):
        print("\n  T-022 PREFLIGHT: BLOKERET")
        for blocker in report.get("blockers", []):
            print(f"    - {blocker}")
        raise OperatorError("Preflight er rød; ingen fysisk write-run må startes.")
    stage.ok("GET-only T-022-preflight er grøn; ingen write-request er sendt.")
    return report


def prepare_or_resume(
    *,
    operator: str,
    identity: Mapping[str, Any],
    token: str,
    paths: Mapping[str, Path],
    android: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not MANIFEST.exists():
        manifest = prepare_manifest(operator=operator, rig_validation_path=RIG_REPORT)
        _atomic_json(MANIFEST, manifest)
        stage.ok(f"Forberedt {RUN_COUNT} uforudsigelige markers i {MANIFEST}.")
    manifest, _raw = _load_json(MANIFEST)
    errors = validate_manifest(manifest, require_bound=False)
    target = manifest.get("target") if isinstance(manifest.get("target"), Mapping) else {}
    for key in ("version", "git_sha", "code_sha256", "identity_source"):
        if target.get(key) != identity.get(key):
            errors.append(f"manifest target {key} matcher ikke kandidaten")
    if errors:
        raise OperatorError("Manifestet er ikke sikkert at bruge: " + "; ".join(errors))

    bound, _pending = manifest_progress(manifest)
    if not bound:
        report = run_preflight(manifest_path=MANIFEST, token=token, paths=paths)
        if OBSERVATIONS.exists():
            raise OperatorError(
                "Positive observations findes allerede til et ubundet manifest; arkivér dem først."
            )
        observations = new_observations(manifest, identity, report, android)
        _atomic_json(OBSERVATIONS, observations)
        return manifest, observations

    if not PREFLIGHT_REPORT.is_file() or not OBSERVATIONS.is_file():
        raise OperatorError(
            "Manifestet er delvist bundet, men preflight/observationsjournal mangler; "
            "resume må ikke rekonstrueres bagefter."
        )
    preflight_report, _ = _load_json(PREFLIGHT_REPORT)
    if (
        preflight_report.get("success") is not True
        or preflight_report.get("pilot_id") != manifest.get("pilot_id")
        or preflight_report.get("production_activation") is not False
    ):
        raise OperatorError("Den bevarede preflight kan ikke autorisere resume.")
    observations, _ = _load_json(OBSERVATIONS)
    resume_errors = validate_resume(observations, manifest, identity)
    if resume_errors:
        raise OperatorError("Resume fejler lukket: " + "; ".join(resume_errors))
    stage.ok(f"Sikkert resume: {len(bound)}/{RUN_COUNT} positive runs er allerede bundet.")
    return manifest, observations


def record_run(
    *,
    manifest: dict[str, Any],
    observations: dict[str, Any],
    ordinal: int,
    run_id: str,
    preview_artifact: Mapping[str, Any],
    approval_artifact: Mapping[str, Any],
    outcome_artifact: Mapping[str, Any],
) -> None:
    item = next(
        (
            entry
            for entry in manifest.get("runs", [])
            if isinstance(entry, Mapping) and entry.get("ordinal") == ordinal
        ),
        None,
    )
    if not isinstance(item, Mapping):
        raise OperatorError(f"Manifestet mangler ordinal {ordinal}.")
    if item.get("run_id"):
        raise OperatorError(f"Ordinal {ordinal} er allerede bundet.")
    marker = item.get("marker")
    if not isinstance(marker, str) or not marker:
        raise OperatorError(f"Ordinal {ordinal} mangler marker.")

    bind_run(manifest, ordinal, run_id)
    observations["runs"].append(
        {
            "ordinal": ordinal,
            "observed_at": iso_now(),
            "marker_sha256": _sha_text(marker),
            "run_id_sha256": _sha_text(run_id),
            "preview_attested": True,
            "approval_attested": True,
            "outcome_attested": True,
            "preview_artifact": dict(preview_artifact),
            "approval_artifact": dict(approval_artifact),
            "outcome_artifact": dict(outcome_artifact),
            "production_activation": False,
        }
    )
    observations["updated_at"] = iso_now()
    _atomic_json(MANIFEST, manifest)
    _atomic_json(OBSERVATIONS, observations)


def run_positive_case(
    *,
    manifest: dict[str, Any],
    observations: dict[str, Any],
    ordinal: int,
    adb: str,
) -> None:
    item = next(
        entry
        for entry in manifest["runs"]
        if isinstance(entry, Mapping) and entry.get("ordinal") == ordinal
    )
    marker = str(item["marker"])
    stage.heading(f"T-022 POSITIV RUN {ordinal:02d}/{RUN_COUNT}")
    copy_marker(marker)
    launch_desktop()
    launch_android(adb)
    print("  Marker er kopieret til Windows-clipboard.")
    print("  Opret præcis ét server-authoritativt step:")
    print("    - tool = note_append")
    print("    - args.text = hele markeren, uden ekstra tekst")
    print("    - append-only konsekvens skal være synlig")
    print("    - preview må endnu ikke have kørt tool'et")
    input("  Placér desktop på det komplette preview og tryk Enter for screenshot: ")
    preview = capture_windows(EVIDENCE_DIR / f"{ordinal:02d}-preview-windows.png")
    require_phrase(PREVIEW_PHRASE.format(ordinal=ordinal))

    print("  Godkend nu den eksakte confirmation på den parrede Android-enhed.")
    print("  Kontrollér marker, note_append, revision og append-only konsekvens.")
    input("  Placér Android på approval-kvitteringen og tryk Enter for screenshot: ")
    approval = capture_android(adb, EVIDENCE_DIR / f"{ordinal:02d}-approval-android.png")
    require_phrase(APPROVAL_PHRASE.format(ordinal=ordinal))

    print("  Vent til runnet er completed og outcome er synligt på desktop.")
    input("  Placér desktop på completed/outcome og tryk Enter for screenshot: ")
    outcome = capture_windows(EVIDENCE_DIR / f"{ordinal:02d}-outcome-windows.png")
    require_phrase(OUTCOME_PHRASE.format(ordinal=ordinal))

    raw_run_id = getpass.getpass(
        "  Indsæt det returnerede run-id (skjult; manifest kræver det): "
    ).strip()
    if not raw_run_id:
        raise OperatorError("Run-id er tomt; runnet forbliver ubundet.")
    record_run(
        manifest=manifest,
        observations=observations,
        ordinal=ordinal,
        run_id=raw_run_id,
        preview_artifact=preview,
        approval_artifact=approval,
        outcome_artifact=outcome,
    )
    del raw_run_id
    stage.ok(f"Run {ordinal:02d} er atomisk bundet og fysisk attesteret.")


def main() -> int:
    os.chdir(ROOT)
    stage.heading("Kaliv T-022 — positiv 20-run physical operator")
    print("  Del 1/4: prepare + GET-only preflight + 20 positive note_append-runs.")
    print("  Wizard'en sender ingen write-request og kan ikke selv godkende noget.")
    print("  Den starter ikke en write-aktiveret stack; preflight skal bevise den live stack.")
    print("  Hvert run kræver tre præcise operatørfraser og tre screenshots.")

    identity = ensure_candidate()
    if not RIG_REPORT.is_file():
        raise OperatorError(
            f"Kandidatbundet rig-validation mangler: {RIG_REPORT}. Kør den fysiske prerequisite først."
        )
    token = ensure_token()
    paths = database_paths()
    adb = find_adb()
    build_install_android(adb)
    android = android_identity(adb)
    operator = prompt("Operatørnavn", os.environ.get("USERNAME", "Anders"))
    manifest, observations = prepare_or_resume(
        operator=operator,
        identity=identity,
        token=token,
        paths=paths,
        android=android,
    )

    _bound, pending = manifest_progress(manifest)
    for ordinal in pending:
        run_positive_case(
            manifest=manifest,
            observations=observations,
            ordinal=ordinal,
            adb=adb,
        )

    bound, pending = manifest_progress(manifest)
    if pending or len(bound) != RUN_COUNT:
        raise OperatorError(
            f"Positiv ceremoni er ufuldstændig: {len(bound)}/{RUN_COUNT} bundet."
        )
    stage.heading("DEL 1 FÆRDIG — 20 POSITIVE RUNS BUNDET")
    stage.ok(f"Manifest: {MANIFEST}")
    stage.ok(f"Fysiske observationer: {OBSERVATIONS}")
    stage.ok("Næste del er den append-only negative-case-wizard; ingen rapport er endnu grøn.")
    stage.ok("production_activation=false")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print(
            "\n  SIKKERT STOP: delvis manifest og observationsjournal er bevaret til resume.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    except (OperatorError, PilotEvidenceError, OSError) as exc:
        print(
            f"\n  SIKKERT STOP: {type(exc).__name__}: {str(exc)[:1200]}",
            file=sys.stderr,
        )
        print("  Ingen fysisk case auto-godkendes; delvis evidens bevares.", file=sys.stderr)
        raise SystemExit(1)
