#!/usr/bin/env python3
"""One-click, resumable Windows wizard for the physical Stage A campaign.

The wizard removes avoidable operator work around checkout, exact-head freeze,
GitHub authentication, model discovery, candidate stack startup and evidence
sequencing. It still stops for the physical observations that software cannot
truthfully fabricate: voice recordings/Pixel trials, scheduler app approval,
revocation/crash recovery and the final one-use public browser confirmation.

It cannot merge, push, tag, publish a release or activate production.
"""
from __future__ import annotations

import getpass
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "agent/unified-candidate-1.58.143"
VERSION = "1.58.143"
VALIDATION = ROOT / "validation"
STATE_PATH = VALIDATION / "stage-a-easy-state.json"
CAMPAIGN_PATH = VALIDATION / "physical-validation-candidate-campaign-latest.json"
AGENT3_REPORT = VALIDATION / "agent3-rig-validation-latest.json"
PROOFS = ("preflight", "agent3", "model_eval", "voice", "rag", "scheduler_pilot")
DEFAULT_URL = "https://example.com/"


class WizardError(RuntimeError):
    pass


def heading(text: str) -> None:
    print("\n" + "=" * 72)
    print(f"  {text}")
    print("=" * 72)


def ok(text: str) -> None:
    print(f"  OK    {text}")


def note(text: str) -> None:
    print(f"  ->    {text}")


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
        raise WizardError(f"Kunne ikke starte {args[0]}: {exc}") from exc
    if check and result.returncode != 0:
        raise WizardError(f"Kommandoen stoppede med exitkode {result.returncode}: {args[0]}")
    return result


def capture(args: list[str], *, cwd: Path = ROOT) -> str:
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            env=os.environ.copy(),
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WizardError(f"Kommandoen kunne ikke gennemføres: {' '.join(args)}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise WizardError(f"{' '.join(args)} fejlede: {detail[-500:]}")
    return result.stdout.strip()


def git(*args: str) -> str:
    return capture(["git", *args])


def prompt(message: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    value = input(f"{message}{suffix}: ").strip()
    return value or (default or "")


def load_state() -> dict[str, Any]:
    if not STATE_PATH.is_file():
        return {}
    try:
        value = json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        note("Den lokale wizard-status var ugyldig og nulstilles.")
        return {}
    return value if isinstance(value, dict) else {}


def save_state(state: dict[str, Any]) -> None:
    VALIDATION.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def archive_previous_evidence(sha: str, state: dict[str, Any]) -> None:
    if state.get("candidate_sha") == sha:
        return
    names = (
        "pre-release-candidate-freeze-latest.json",
        "rig-preflight-latest.json",
        "agent3-rig-validation-latest.json",
        "agent3-model-eval-latest.json",
        "voice-baseline-latest.json",
        "rag-benchmark-latest.json",
        "scheduler-pilot-latest.json",
        "physical-validation-candidate-campaign-latest.json",
        "browser-peer-public-validation-physical-latest.json",
        "browser-peer-public-validation-latest.json",
        "physical-validation-candidate-final-latest.json",
    )
    existing = [VALIDATION / name for name in names if (VALIDATION / name).is_file()]
    if existing:
        archive = VALIDATION / "archive" / time.strftime("stage-a-%Y%m%d-%H%M%S")
        archive.mkdir(parents=True, exist_ok=True)
        for source in existing:
            source.replace(archive / source.name)
        note(f"Tidligere rolling reports er bevaret i {archive}")
    state.clear()
    state["candidate_sha"] = sha
    save_state(state)


def ensure_candidate() -> str:
    heading("1/8  Hent og lås den rigtige kandidat")
    if os.name != "nt":
        raise WizardError("Wizard'en må kun køres på Windows-riggen.")
    for command in ("git", "python", "powershell.exe"):
        if not shutil.which(command):
            raise WizardError(f"{command} blev ikke fundet på PATH.")
    dirty = git("status", "--porcelain")
    if dirty:
        raise WizardError(f"Working tree er ikke ren. Flyt eller stash lokale filer først:\n{dirty}")
    git("fetch", "--quiet", "origin", "main", BRANCH)
    current = git("branch", "--show-current")
    if current != BRANCH:
        note(f"Skifter fra {current or 'detached HEAD'} til {BRANCH}")
        git("switch", BRANCH)
    git("pull", "--ff-only", "origin", BRANCH)
    sha = git("rev-parse", "HEAD")
    if sha != git("rev-parse", f"origin/{BRANCH}"):
        raise WizardError(f"Lokal HEAD matcher ikke origin/{BRANCH}.")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if version != VERSION:
        raise WizardError(f"VERSION er {version}, forventede {VERSION}.")
    ok(f"Kandidat {version} på {sha}")
    return sha


def install_with_winget(package_id: str, label: str) -> None:
    winget = shutil.which("winget")
    if not winget:
        raise WizardError(f"{label} mangler, og winget blev ikke fundet.")
    answer = prompt(f"{label} mangler. Tryk Enter for automatisk installation, eller skriv STOP")
    if answer.upper() == "STOP":
        raise WizardError(f"Stoppet før installation af {label}.")
    run(
        [
            winget,
            "install",
            "--id",
            package_id,
            "-e",
            "--source",
            "winget",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ]
    )


def find_gh() -> str:
    found = shutil.which("gh")
    if found:
        return found
    candidate = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "GitHub CLI" / "gh.exe"
    if candidate.is_file():
        return str(candidate)
    install_with_winget("GitHub.cli", "GitHub CLI")
    found = shutil.which("gh")
    if found:
        return found
    if candidate.is_file():
        return str(candidate)
    raise WizardError("GitHub CLI blev installeret. Luk vinduet og dobbeltklik igen.")


def ensure_github_token() -> None:
    heading("2/8  GitHub-login til exact-head-kontrollen")
    if os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"):
        ok("GitHub-token findes allerede i sessionen.")
        return
    gh = find_gh()
    status = run([gh, "auth", "status", "-h", "github.com"], check=False)
    if status.returncode != 0:
        note("Et browservindue åbnes til GitHub-login. Det er normalt kun nødvendigt én gang.")
        run([gh, "auth", "login", "--web", "--git-protocol", "https"])
    token = capture([gh, "auth", "token"]).strip()
    if not token:
        raise WizardError("GitHub CLI returnerede intet token.")
    os.environ["GH_TOKEN"] = token
    ok("GitHub-login er klar; tokenet vises eller gemmes ikke af wizard'en.")


def request_json(url: str, *, method: str = "GET", body: dict[str, Any] | None = None) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError) as exc:
        raise WizardError(f"Kunne ikke læse {url}: {exc}") from exc


def ollama_models() -> list[str]:
    try:
        payload = request_json("http://127.0.0.1:11434/api/tags")
    except WizardError:
        return []
    models = payload.get("models", []) if isinstance(payload, dict) else []
    return [str(item.get("name")) for item in models if isinstance(item, dict) and item.get("name")]


def ensure_models() -> str:
    heading("3/8  Ollama og modeller")
    ollama = shutil.which("ollama")
    if not ollama:
        raise WizardError("Ollama blev ikke fundet på PATH.")
    models = ollama_models()
    if not models:
        note("Starter Ollama...")
        subprocess.Popen([ollama, "serve"], creationflags=subprocess.CREATE_NEW_CONSOLE)
        for _ in range(30):
            time.sleep(1)
            models = ollama_models()
            if models:
                break
    if not models:
        raise WizardError("Ollama svarer ikke på http://127.0.0.1:11434.")

    configured = os.environ.get("KALIV_AGENT3_PLANNER_MODEL", "").strip()
    planner = configured if configured in models else ""
    if not planner:
        for pattern in ("qwen3:", "gemma3:"):
            planner = next((name for name in models if name.startswith(pattern)), "")
            if planner:
                break
    if not planner:
        planner = next((name for name in models if "embed" not in name.lower()), "")
    if not planner:
        answer = prompt("Ingen planner-model fundet. Tryk Enter for at hente qwen3:8b, eller skriv STOP")
        if answer.upper() == "STOP":
            raise WizardError("Ingen planner-model valgt.")
        run([ollama, "pull", "qwen3:8b"])
        planner = "qwen3:8b"

    if not any(name == "nomic-embed-text" or name.startswith("nomic-embed-text:") for name in models):
        answer = prompt("Embeddingmodellen mangler. Tryk Enter for at hente nomic-embed-text, eller skriv STOP")
        if answer.upper() == "STOP":
            raise WizardError("Embeddingmodellen mangler.")
        run([ollama, "pull", "nomic-embed-text"])

    os.environ["KALIV_AGENT3_PLANNER_MODEL"] = planner
    os.environ["KALIV_AGENT3_VALIDATION_REPORT"] = str(AGENT3_REPORT)
    ok(f"Planner/voice-model: {planner}")
    ok("Embeddingmodel: nomic-embed-text")
    return planner


def ensure_device_token() -> None:
    if os.environ.get("MODELRIG_TOKEN"):
        return
    heading("4/8  Parret device-token")
    token = getpass.getpass("  Indsæt MODELRIG_TOKEN (skjult, gemmes ikke): ").strip()
    if not token:
        raise WizardError("Device-tokenet var tomt.")
    os.environ["MODELRIG_TOKEN"] = token
    ok("Device-token er sat i denne proces.")


def strict_stage(action: str, sha: str, url: str | None = None) -> None:
    args = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ROOT / "scripts" / "run-stage-a-physical-validation.ps1"),
        "-Action",
        action,
        "-ExpectedSha",
        sha,
    ]
    if url:
        args += ["-Url", url]
    run(args)


def read_campaign() -> dict[str, Any]:
    try:
        value = json.loads(CAMPAIGN_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WizardError("Kampagnerapporten kunne ikke læses.") from exc
    if not isinstance(value, dict):
        raise WizardError("Kampagnerapporten har forkert format.")
    return value


def refresh_campaign() -> dict[str, Any]:
    run(
        [
            sys.executable,
            str(ROOT / "scripts" / "physical_validation_candidate_campaign.py"),
            "--mode",
            "prepare",
            "--report",
            str(CAMPAIGN_PATH),
        ]
    )
    return read_campaign()


def passed(campaign: dict[str, Any], name: str) -> bool:
    summary = campaign.get("summary", {})
    return name in summary.get("passed", []) if isinstance(summary, dict) else False


def show_progress(campaign: dict[str, Any]) -> None:
    summary = campaign.get("summary", {}) if isinstance(campaign.get("summary"), dict) else {}
    complete = set(summary.get("passed", []))
    failed = set(summary.get("failed", []))
    print("\n  Stage A-status")
    for name in PROOFS:
        marker = "OK" if name in complete else "FEJL" if name in failed else "MANGLER"
        print(f"    [{marker:<7}] {name}")


def start_stack(planner: str, *, worker_only: bool = False) -> None:
    args = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(ROOT / "scripts" / "start-stage-a-validation-stack.ps1"),
        "-PlannerModel",
        planner,
        "-ValidationReport",
        str(AGENT3_REPORT),
    ]
    if worker_only:
        args.append("-WorkerOnly")
    if not worker_only and not shutil.which("go"):
        install_with_winget("GoLang.Go", "Go")
        if not shutil.which("go"):
            raise WizardError("Go blev installeret. Luk vinduet og dobbeltklik igen, så PATH opdateres.")
    run(args)


def run_preflight(planner: str) -> None:
    heading("5/8  Start riggen og kør de automatiske beviser")
    args = [
        sys.executable,
        str(ROOT / "scripts" / "rig_preflight.py"),
        "--base-url",
        "http://127.0.0.1:8080",
        "--report",
        str(VALIDATION / "rig-preflight-latest.json"),
    ]
    result = run(args, check=False)
    if result.returncode == 0:
        ok("Rig preflight bestod.")
        return
    note("Wizard'en starter backend og worker direkte fra den eksakte kandidat.")
    input("  Tryk Enter. Luk de gamle backend/worker-vinduer, når du bliver bedt om det. ")
    start_stack(planner)
    run(args)
    ok("Rig preflight bestod på kandidat-stacken.")


def run_voice(planner: str) -> None:
    fixtures = VALIDATION / "voice-fixtures"
    manual = VALIDATION / "voice-manual-observations.json"
    fixtures.mkdir(parents=True, exist_ok=True)
    if not manual.is_file():
        shutil.copy2(ROOT / "eval" / "voice_manual_observations.example.json", manual)

    while len(list(fixtures.glob("turn-*.wav"))) != 20:
        heading("MANUELT PAUSEPUNKT  Voice-fixtures")
        print("  Optag de 20 fraser som turn-01.wav ... turn-20.wav.")
        print("  Manifest og mappe åbnes nu. Wizard'en fortsætter, når alle 20 filer findes.")
        os.startfile(ROOT / "eval" / "voice_baseline_manifest.v1.json")
        os.startfile(fixtures)
        input("  Tryk Enter efter optagelserne: ")

    run([sys.executable, str(ROOT / "scripts" / "voice_baseline.py"), "--validate-only", "--report", str(VALIDATION / "voice-baseline-fixture-check.json")])

    heading("MANUELT PAUSEPUNKT  Pixel stop/barge-in")
    os.startfile(manual)
    print("  Kør de fem Pixel 6a-trials og udfyld filen, der blev åbnet.")
    input("  Tryk Enter, når alle fem trials har rigtige booleans og tider: ")

    ollama = shutil.which("ollama")
    if ollama:
        run([ollama, "stop", planner], check=False)
    note("Voice-cold-start kræver en ny worker. Luk worker-vinduet; wizard'en fortsætter selv.")
    start_stack(planner, worker_only=True)

    run(
        [
            sys.executable,
            str(ROOT / "scripts" / "voice_baseline.py"),
            "--worker-url",
            "http://127.0.0.1:8099",
            "--model",
            planner,
            "--repetitions",
            "2",
            "--cold-start-confirmed",
            "--cancellation-probes",
            "4",
            "--manual-observations",
            str(manual),
            "--require-manual",
            "--report",
            str(VALIDATION / "voice-baseline-latest.json"),
        ]
    )


def run_scheduler(planner: str, state: dict[str, Any]) -> None:
    heading("MANUELT PAUSEPUNKT  Scheduler-pilot")
    read_id = str(state.get("read_schedule_id") or "")
    if not read_id:
        body = {"tool": "rig_status", "args": {}, "cadence": "every:60", "ttl_days": 1, "max_runs": 3}
        request_json("http://127.0.0.1:8099/schedules/preview", method="POST", body=body)
        created = request_json("http://127.0.0.1:8099/schedules", method="POST", body=body)
        read_id = str(created.get("schedule_id") or "")
        if not read_id:
            raise WizardError("Read-planen returnerede intet schedule_id.")
        state["read_schedule_id"] = read_id
        save_state(state)
    ok(f"Read schedule-id: {read_id}")

    write_id = str(state.get("write_schedule_id") or "")
    print("\n  Opret PRÆCIS denne plan i appens schedule-flow og godkend den:")
    print('    tool=note_append, args={"text":"pilot"}, cadence=every:60, max_runs=2, ttl_days=1')
    write_id = prompt("  Indsæt write schedule-id", write_id or None)
    if not write_id:
        raise WizardError("Write schedule-id mangler.")
    state["write_schedule_id"] = write_id
    save_state(state)

    print("\n  Revocation: vent til en read-occurrence er i gang, og tryk Enter.")
    input("  Wizard'en sender pausekaldet, når du trykker Enter: ")
    request_json(
        f"http://127.0.0.1:8099/schedules/{read_id}/enabled",
        method="POST",
        body={"enabled": False},
    )
    answer = prompt("  Blev jobbet cancelled med den danske pausegrund? Skriv JA")
    if answer.upper() != "JA":
        raise WizardError("Revocation/cancel blev ikke bekræftet.")

    print("\n  Crash recovery: start eller genaktivér en scheduled kørsel, og luk worker-vinduet mens jobbet kører.")
    input("  Tryk Enter efter worker-vinduet er lukket; wizard'en starter exact-head worker igen: ")
    start_stack(planner, worker_only=True)
    recovery = prompt("  Indsæt hele linjen der starter med 'scheduler: recovered'")
    if not recovery.startswith("scheduler: recovered "):
        raise WizardError("Recovery-linjen har forkert format.")

    manual = VALIDATION / "scheduler-manual-observations.json"
    manual.write_text(
        json.dumps(
            {"revocation_confirmed": True, "recovery_line": recovery, "operator": "Anders"},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    run(
        [
            sys.executable,
            str(ROOT / "scripts" / "scheduler_pilot_report.py"),
            "--worker-url",
            "http://127.0.0.1:8099",
            "--read-schedule-id",
            read_id,
            "--write-schedule-id",
            write_id,
            "--manual-observations",
            str(manual),
            "--report",
            str(VALIDATION / "scheduler-pilot-latest.json"),
        ]
    )


def main() -> int:
    os.chdir(ROOT)
    heading("Kaliv Stage A — lettest mulige fysiske test")
    print("  Dobbeltklik START_STAGE_A_TEST.cmd. Wizard'en kan genoptages efter et sikkert stop.")
    print("  Den kan ikke merge, pushe, tagge, release eller aktivere produktion.")

    sha = ensure_candidate()
    state = load_state()
    archive_previous_evidence(sha, state)
    ensure_github_token()
    planner = ensure_models()

    heading("Exact-head freeze og checklist")
    strict_stage("Prepare", sha)
    ensure_device_token()
    campaign = read_campaign()
    show_progress(campaign)

    if not passed(campaign, "preflight"):
        run_preflight(planner)
        campaign = refresh_campaign()
    if not passed(campaign, "agent3"):
        run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(ROOT / "scripts" / "run-agent3-rig-validation.ps1"),
                "-BaseUrl",
                "http://127.0.0.1:8080",
                "-PlannerModel",
                planner,
            ]
        )
        campaign = refresh_campaign()
    if not passed(campaign, "model_eval"):
        run(
            [
                sys.executable,
                str(ROOT / "scripts" / "agent3_model_eval.py"),
                "--planner-model",
                planner,
                "--repetitions",
                "1",
                "--fail-under",
                "1.0",
                "--report",
                str(VALIDATION / "agent3-model-eval-latest.json"),
            ]
        )
        campaign = refresh_campaign()
    if not passed(campaign, "rag"):
        run(
            [
                sys.executable,
                str(ROOT / "scripts" / "rag_benchmark.py"),
                "--scales",
                "1000,10000",
                "--queries",
                "40",
                "--repetitions",
                "2",
                "--embedding-model",
                "nomic-embed-text",
                "--report",
                str(VALIDATION / "rag-benchmark-latest.json"),
            ]
        )
        campaign = refresh_campaign()
    if not passed(campaign, "voice"):
        run_voice(planner)
        campaign = refresh_campaign()
    if not passed(campaign, "scheduler_pilot"):
        run_scheduler(planner, state)
        campaign = refresh_campaign()

    show_progress(campaign)
    strict_stage("Verify", sha)

    heading("8/8  Sidste browserbevis")
    url = prompt("Eksakt forhåndsgodkendt HTTPS/443-URL", DEFAULT_URL)
    note("Den eksisterende one-use gate viser URL'en og kræver din sidste eksplicitte bekræftelse.")
    strict_stage("Complete", sha, url)

    heading("STAGE A BESTÅET")
    ok(f"Syv fysiske beviser er bundet til {sha}")
    print("  Rapport: validation\\physical-validation-candidate-final-latest.json")
    print("  Releasevalidering mangler fortsat; production_activation er fortsat false.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n  SIKKERT STOP: afbrudt af operatøren.", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(f"\n  SIKKERT STOP: {type(exc).__name__}: {str(exc)[:800]}", file=sys.stderr)
        print("  Intet blev merget, releaset eller aktiveret. Ret problemet og dobbeltklik igen.", file=sys.stderr)
        raise SystemExit(1)
