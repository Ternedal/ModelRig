#!/usr/bin/env python3
"""One-click Windows operator for physical T-023 termination UI evidence.

The wizard automates only reproducible setup: exact branch checkout, candidate
identity, local stack/readiness preparation, Android build/install, surface
launching, screenshots, hashing and report verification. It cannot observe a UI
for the operator. Every physical case stays red until the operator types the
case-specific attestation phrase and supplies the visible receipt values.

It never merges, pushes, tags, publishes, activates production or stores raw run
IDs.
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
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
VALIDATION = ROOT / "validation"
OBSERVATIONS = VALIDATION / "agent3-termination-ui-observations.json"
REPORT = VALIDATION / "agent3-termination-ui-physical-latest.json"
CANDIDATE_COMPOSITION = VALIDATION / "physical-validation-termination-candidate-latest.json"
RIG_REPORT = VALIDATION / "agent3-rig-validation-latest.json"
PILOT_REPORT = VALIDATION / "agent3-readonly-pilot-latest.json"
BRANCH = "agent/t023-termination-physical-operator"
VERSION = "1.58.146"
BASE_URL = "http://127.0.0.1:8080"
READINESS_PATH = "/api/v1/experimental/agent3/task-readiness"
ANDROID_PACKAGE = "dk.ternedal.modelrig"
ANDROID_ACTIVITY = f"{ANDROID_PACKAGE}/.MainActivity"
ANDROID_TASK_EXTRA = "dk.ternedal.modelrig.extra.AGENT3_TASK"
ANDROID_AGENT3_EXTRA = "dk.ternedal.modelrig.extra.AGENT3"
ATTEST_PREFIX = "OBSERVERET"
RECEIPT_PREFIX = "KVITTERING"

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


physical = _load_module(
    "t023_physical_operator_report",
    SCRIPTS / "agent3_termination_ui_physical_report.py",
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
            if isinstance(output, bytes):
                detail = output.decode("utf-8", errors="replace")
            else:
                detail = output or ""
        raise OperatorError(
            f"Kommandoen fejlede ({result.returncode}): {' '.join(args)}"
            + (f"\n{detail[-800:]}" if detail else "")
        )
    return result


def prompt(message: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"  {message}{suffix}: ").strip()
    return value or (default or "")


def require_phrase(prefix: str, platform_name: str, case_name: str) -> None:
    expected = f"{prefix} {platform_name} {case_name}"
    entered = input(f"  Skriv præcis '{expected}' for at attestere: ").strip()
    if entered != expected:
        raise OperatorError("Attesteringen matchede ikke; casen forbliver rød.")


def choose(message: str, allowed: tuple[str, ...], default: str) -> str:
    value = prompt(f"{message} ({'/'.join(allowed)})", default)
    if value not in allowed:
        raise OperatorError(f"Ugyldig værdi: {value!r}.")
    return value


def yes_no(message: str, default: bool = False) -> bool:
    raw = prompt(message + " (ja/nej)", "ja" if default else "nej").lower()
    if raw not in {"ja", "nej"}:
        raise OperatorError("Svar skal være ja eller nej.")
    return raw == "ja"


def archive_existing() -> None:
    existing = [path for path in (OBSERVATIONS, REPORT, CANDIDATE_COMPOSITION) if path.is_file()]
    if not existing:
        return
    archive = VALIDATION / "archive" / time.strftime("t023-termination-ui-%Y%m%d-%H%M%S")
    archive.mkdir(parents=True, exist_ok=True)
    for source in existing:
        source.replace(archive / source.name)
    stage.note(f"Tidligere T-023-evidens er bevaret i {archive}")


def ensure_candidate() -> str:
    stage.BRANCH = BRANCH
    stage.VERSION = VERSION
    sha = stage.ensure_candidate()
    identity = physical.candidate_identity(ROOT)
    if (
        identity.get("git_sha") != sha
        or identity.get("version") != VERSION
        or identity.get("working_tree_clean") is not True
        or identity.get("version_stamps_consistent") is not True
    ):
        raise OperatorError("Kandidatidentiteten er ikke ren og exact-head-bundet.")
    return sha


def ensure_token() -> str:
    token = os.environ.get("MODELRIG_TOKEN", "").strip()
    if not token:
        token = getpass.getpass("  Indsæt MODELRIG_TOKEN (skjult, gemmes ikke): ").strip()
    if not token:
        raise OperatorError("MODELRIG_TOKEN er tomt.")
    os.environ["MODELRIG_TOKEN"] = token
    return token


def request_json(path: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(BASE_URL + path, method="GET")
    request.add_header("Accept", "application/json")
    request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            value = json.load(response)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError) as exc:
        raise OperatorError(f"Kunne ikke læse {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise OperatorError(f"{path} returnerede ikke et JSON-objekt.")
    return value


def ensure_stack_and_readiness(token: str) -> None:
    planner = stage.ensure_models()
    os.environ["KALIV_AGENT3_VALIDATION_REPORT"] = str(RIG_REPORT)
    os.environ["KALIV_AGENT3_PILOT_REPORT"] = str(PILOT_REPORT)
    stage.ensure_device_token()

    try:
        readiness = request_json(READINESS_PATH, token)
    except OperatorError:
        stage.heading("Start exact-head backend og worker")
        stage.note("Luk gamle backend/worker-vinduer, når stackstarteren beder om det.")
        stage.start_stack(planner)
        readiness = {}

    if readiness.get("selected_surface") != "agent3_readonly":
        stage.heading("Forbered exact kandidat-readiness")
        stage.note("Genstarter kandidat-stacken med de kandidatbundne rapportstier.")
        stage.start_stack(planner)
        stage.run(
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
                # UDEN DENNE BLOKERER T-023 SIG SELV. Valideringen regenererer
                # ACTIVATION_READINESS.md i trin 3/3, og pilot-evidensen kraever
                # umiddelbart efter et RENT arbejdstrae -- saa wizarden
                # snavsede sit eget trae til og faldt over det, hver eneste
                # gang. 20/8 kostede det flere fulde koersler, og en manuel
                # "git checkout ACTIVATION_READINESS.md" foer start hjalp ikke,
                # fordi regenereringen sker INDE i koerslen.
                #
                # stage_a_one_click.py sender allerede flaget; denne wizard
                # havde bare aldrig faaet det.
                "-SkipReadinessRegeneration",
            ]
        )
        stage.run(
            [
                sys.executable,
                str(SCRIPTS / "agent3_readonly_pilot.py"),
                "--base-url",
                BASE_URL,
                "--planner-model",
                planner,
                "--answer-model",
                planner,
                "--fallback-model",
                planner,
                "--report",
                str(PILOT_REPORT),
            ]
        )
        readiness = request_json(READINESS_PATH, token)

    if (
        readiness.get("schema") != "kaliv-agent3-task-readiness/v1"
        or readiness.get("selected_surface") != "agent3_readonly"
        or readiness.get("reason") != "agent3_readonly_selected"
        or readiness.get("production_activation") is not False
        or readiness.get("normal_chat_route_unchanged") is not True
    ):
        raise OperatorError(
            "Task-readiness er ikke exact agent3_readonly: "
            f"{readiness.get('reasons')}"
        )
    stage.ok("Serveren vælger agent3_readonly; normal chat er uændret.")


def find_adb() -> str:
    adb = shutil.which("adb")
    if not adb:
        raise OperatorError("adb blev ikke fundet på PATH. Installer Android Platform Tools.")
    return adb


def android_device(adb: str) -> tuple[str, str]:
    result = run([adb, "devices"], capture=True)
    lines = [
        line.split("\t", 1)[0]
        for line in result.stdout.splitlines()[1:]
        if "\tdevice" in line
    ]
    if len(lines) != 1:
        raise OperatorError(f"Der skal være præcis én ADB-enhed; fandt {len(lines)}.")
    model = run([adb, "shell", "getprop", "ro.product.model"], capture=True).stdout.strip()
    release = run([adb, "shell", "getprop", "ro.build.version.release"], capture=True).stdout.strip()
    return model or lines[0], release or "unknown"


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
    stage.ok(f"Installeret {apk.name} på den tilsluttede Android-enhed.")


def launch_android(adb: str, surface: str) -> None:
    extra = ANDROID_TASK_EXTRA if surface == "normal_task" else ANDROID_AGENT3_EXTRA
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
            extra,
            "true",
        ]
    )


def launch_desktop(surface: str) -> None:
    gradlew = ROOT / "desktop" / "gradlew.bat"
    if not gradlew.is_file():
        raise OperatorError("desktop\\gradlew.bat mangler.")
    arg = "--tasks" if surface == "normal_task" else "--agent3"
    subprocess.Popen(
        [str(gradlew), ":composeApp:run", f"--args={arg}"],
        cwd=ROOT / "desktop",
        env=os.environ.copy(),
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )


def capture_android(adb: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = run([adb, "exec-out", "screencap", "-p"], capture=True, binary=True)
    if not result.stdout:
        raise OperatorError("Android-screenshot var tomt.")
    destination.write_bytes(result.stdout)


def capture_windows(destination: Path) -> None:
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


def select_tool(inventory: Mapping[str, list[str]], semantics: str) -> str:
    tools = inventory.get(semantics, [])
    if not tools:
        raise OperatorError(f"Kandidaten har ingen capability med termination={semantics}.")
    print("  Tilladte capabilities:")
    for index, tool in enumerate(tools, 1):
        print(f"    {index}. {tool}")
    raw = prompt("Vælg capability-nummer", "1")
    try:
        selected = tools[int(raw) - 1]
    except (ValueError, IndexError) as exc:
        raise OperatorError("Ugyldigt capability-valg.") from exc
    return selected


def case_by_name(
    observations: dict[str, Any], platform_name: str, case_name: str
) -> dict[str, Any]:
    cases = observations["platforms"][platform_name]["cases"]
    for case in cases:
        if case.get("name") == case_name:
            return case
    raise OperatorError(f"Observationsskabelonen mangler {platform_name}.{case_name}.")


def record_case(
    observations: dict[str, Any],
    inventory: Mapping[str, list[str]],
    *,
    platform_name: str,
    case_name: str,
    adb: str,
) -> None:
    case = case_by_name(observations, platform_name, case_name)
    surface = case["surface"]
    semantics = case["receipt"]["active_tool"]["semantics"]
    stage.heading(f"FYSISK CASE — {platform_name} / {case_name}")

    if platform_name == "android":
        launch_android(adb, surface)
    else:
        launch_desktop(surface)

    print(f"  Surface: {surface}")
    print("  Opret en frisk run og bring den til et aktivt tool-step.")
    print("  Kontrollér på skærmen:")
    print("    - separate Plan / Model stream / Aktivt tool-sektioner")
    print("    - 'Stop plan' er synlig; en løs/bare 'Stop' er ikke synlig")
    print("    - aktivt tool fortsætter-advarslen er sand for denne case")
    print("    - klienten poller efter plan-stop og viser tool-sluttilstanden")
    print("    - normal chat er fortsat den almindelige Agent 2-route")
    print("  Tryk først Stop plan, og vent til den krævede sluttilstand vises.")
    input("  Placér UI'en på den endelige kvittering og tryk Enter for screenshot: ")

    artifact = ROOT / case["artifact_path"]
    if platform_name == "android":
        capture_android(adb, artifact)
    else:
        capture_windows(artifact)
    case["artifact_sha256"] = sha256_bytes(artifact.read_bytes())

    require_phrase(ATTEST_PREFIX, platform_name, case_name)
    raw_run_id = getpass.getpass("  Indsæt run-id (skjult; kun SHA-256 gemmes): ").strip()
    if not raw_run_id:
        raise OperatorError("Run-id var tomt.")
    case["run_id_sha256"] = sha256_bytes(raw_run_id.encode("utf-8"))
    del raw_run_id

    active = case["receipt"]["active_tool"]
    active["tool"] = select_tool(inventory, semantics)
    active["state_before"] = "executing"
    active["reason"] = prompt("Synlig reason/årsag fra kvitteringen")
    if not active["reason"]:
        raise OperatorError("Kvitteringens reason må ikke være tom.")

    handle = False
    if case_name == "runtime_bound":
        handle = True
    elif case_name == "cooperative_declaration":
        handle = yes_no("Viste kvitteringen en konkret bound handle med direkte tool-kontrol?")
    active["handle_present"] = handle
    active["can_request"] = handle
    active["request_state_before"] = (
        choose("Tool request-state før stop", ("available", "pending"), "available")
        if handle
        else "unavailable"
    )

    if case_name == "late_completion":
        active["state_after"] = "completed_after_cancel"
    else:
        active["state_after"] = choose(
            "Synlig tool-sluttilstand",
            ("cancelled", "succeeded", "failed", "completed_after_cancel"),
            "cancelled",
        )
    active["request_state_after"] = "terminal"
    active["cleanup_ms"] = (
        float(prompt("Målt cleanup i ms (0..5000)", "0")) if handle else None
    )
    if handle and not 0 <= active["cleanup_ms"] <= 5000:
        raise OperatorError("Cleanup skal være mellem 0 og 5000 ms.")

    plan = case["receipt"]["plan"]
    plan.update(
        {
            "state_before": "available",
            "can_request_before": True,
            "effect_before": (
                "prevent_future_steps"
                if case_name == "runtime_bound"
                else "prevent_future_steps_active_tool_continues"
            ),
            "state_after": "terminal",
            "can_request_after": False,
        }
    )
    stream = case["receipt"]["model_stream"]
    stream.update(
        {
            "state": "not_active",
            "active": False,
            "handle_present": False,
            "can_request": False,
        }
    )
    ui = case["ui"]
    ui.update(
        {
            "shows_plan_scope": True,
            "shows_model_stream_scope": True,
            "shows_active_tool_scope": True,
            "shows_stop_plan": True,
            "shows_bare_stop": False,
            "shows_direct_tool_stop": handle,
            "warns_active_tool_continues": True,
            "polls_after_plan_cancel": True,
            "shows_final_tool_state": True,
            "normal_chat_unchanged": True,
        }
    )
    case["observed_at"] = iso_now()
    require_phrase(RECEIPT_PREFIX, platform_name, case_name)
    atomic_json(OBSERVATIONS, observations)
    stage.ok(
        f"{platform_name}.{case_name} er gemt kandidatbundet; rå run-id er ikke gemt."
    )


def prepare_observations(
    operator: str, adb: str
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    identity = physical.candidate_identity(ROOT)
    inventory = physical.capability_inventory(ROOT)
    observations = physical.prepare_observations(
        operator=operator,
        identity=identity,
        inventory=inventory,
    )
    android_name, android_version = android_device(adb)
    observations["platforms"]["android"]["device_name"] = android_name
    observations["platforms"]["android"]["os_version"] = android_version
    observations["platforms"]["windows"]["device_name"] = platform.node() or "Windows rig"
    observations["platforms"]["windows"]["os_version"] = platform.platform()
    atomic_json(OBSERVATIONS, observations)
    return observations, inventory


def verify_and_compose() -> int:
    report = physical.verify_report(
        observations_path=OBSERVATIONS,
        report_path=REPORT,
    )
    if not report.get("success"):
        print("\n  T-023-RAPPORT: BLOKERET")
        for error in report.get("errors", []):
            print(f"    - {error}")
        return 2

    stage.heading("T-023 FYSISK EVIDENS BESTÅET")
    stage.ok(f"Rapport: {REPORT}")
    stage.ok("Android og Windows er bundet til samme kandidat og artifact-hashes.")
    stage.ok("production_activation=false")

    result = run(
        [
            sys.executable,
            str(SCRIPTS / "physical_validation_termination_campaign.py"),
            "--stage",
            "candidate",
            "--termination-report",
            str(REPORT),
            "--report",
            str(CANDIDATE_COMPOSITION),
        ],
        check=False,
    )
    if result.returncode == 0:
        stage.ok("Den additive 7-bevis kandidatkampagne er komplet.")
    else:
        stage.note(
            "T-023 er grøn, men den samlede kandidatkampagne er fortsat blokeret "
            "af et andet manglende/stale base-bevis."
        )
    return 0


def main() -> int:
    os.chdir(ROOT)
    stage.heading("Kaliv T-023 — fysisk termination UI-wizard")
    print("  Wizard'en kan ikke selv se UI'en og kan derfor ikke auto-godkende noget.")
    print("  Hver case kræver to præcise operatørfraser og et kandidatbundet screenshot.")
    print("  Den kan ikke merge, pushe, tagge, release eller aktivere produktion.")

    ensure_candidate()
    archive_existing()
    token = ensure_token()
    ensure_stack_and_readiness(token)
    adb = find_adb()
    build_install_android(adb)
    operator = prompt("Operatørnavn", os.environ.get("USERNAME", "Anders"))
    observations, inventory = prepare_observations(operator, adb)

    required_cases = list(physical._required_cases(inventory))
    for platform_name in physical.PLATFORMS:
        for case_name in required_cases:
            record_case(
                observations,
                inventory,
                platform_name=platform_name,
                case_name=case_name,
                adb=adb,
            )

    return verify_and_compose()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print(
            "\n  SIKKERT STOP: afbrudt af operatøren; delvis skabelon er bevaret.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    except Exception as exc:
        print(
            f"\n  SIKKERT STOP: {type(exc).__name__}: {str(exc)[:1000]}",
            file=sys.stderr,
        )
        print(f"  Delvis evidens er bevaret i {OBSERVATIONS}.", file=sys.stderr)
        raise SystemExit(1)
