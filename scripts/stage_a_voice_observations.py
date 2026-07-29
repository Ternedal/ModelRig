#!/usr/bin/env python3
"""Collect the five real Pixel voice observations without manual JSON editing.

The operator still performs every physical trial. This helper only guides the
questions, saves after each answer, validates the exact manual schema and keeps a
candidate-bound resume file. It never guesses a success or a latency.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANUAL_SCHEMA = "kaliv-voice-manual-observations/v1"
STATE_SCHEMA = "kaliv-stage-a-voice-observations-state/v1"
PHONE_STATE_SCHEMA = "kaliv-stage-a-phone-test-state/v1"
DEFAULT_PHONE_STATE = Path("validation/stage-a-runtime/phone-test-state.json")
DEFAULT_RESUME = Path("validation/stage-a-voice-observations-state.json")
DEFAULT_OUTPUT = Path("validation/voice-manual-observations.json")

TRIALS: tuple[dict[str, str], ...] = (
    {
        "id": "manual-01",
        "trigger": "tap stop during first audio chunk",
        "title": "Tryk Stop lige efter oplæsningen begynder",
        "instruction": "Bed Kaliv om et langt svar. Tryk Stop, så snart den første lyd høres.",
    },
    {
        "id": "manual-02",
        "trigger": "tap stop between audio chunks",
        "title": "Tryk Stop i en kort pause mellem sætninger",
        "instruction": "Start et nyt langt svar. Tryk Stop i den første tydelige pause.",
    },
    {
        "id": "manual-03",
        "trigger": "begin speaking during first audio chunk",
        "title": "Begynd at tale lige efter oplæsningen begynder",
        "instruction": "Start et nyt langt svar. Sig tydeligt 'stop' eller stil et nyt spørgsmål under den første lyd.",
    },
    {
        "id": "manual-04",
        "trigger": "begin speaking between audio chunks",
        "title": "Begynd at tale i en kort pause mellem sætninger",
        "instruction": "Start et nyt langt svar. Tal i den første tydelige pause.",
    },
    {
        "id": "manual-05",
        "trigger": "network interruption during playback",
        "title": "Afbryd netværket under oplæsningen",
        "instruction": "Start et nyt langt svar. Slå Wi-Fi og mobildata fra under oplæsningen, og slå dem til igen bagefter.",
    },
)


class ObservationError(RuntimeError):
    pass


def _repo_path(raw: Path) -> Path:
    candidate = raw if raw.is_absolute() else ROOT / raw
    resolved = candidate.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ObservationError("alle observationsfiler skal ligge under repositoryet") from exc
    return resolved


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ObservationError(f"kunne ikke læse {path}") from exc
    if not isinstance(value, dict):
        raise ObservationError(f"{path} indeholder ikke et JSON-objekt")
    return value


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
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
        temporary = Path(handle.name)
    temporary.replace(path)


def _git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ObservationError("git kunne ikke læse kandidatens SHA") from exc
    value = result.stdout.strip()
    if result.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ObservationError("repositoryet står ikke på en gyldig Git-kandidat")
    return value


def _candidate() -> dict[str, str]:
    try:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ObservationError("VERSION kunne ikke læses") from exc
    if not version:
        raise ObservationError("VERSION er tom")
    return {"version": version, "git_sha": _git_sha()}


def _health(url: str) -> dict[str, Any]:
    try:
        request = urllib.request.Request(url.rstrip("/") + "/healthz", method="GET")
        with urllib.request.urlopen(request, timeout=10) as response:
            value = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ObservationError(f"telefon-testbackenden svarer ikke på {url}") from exc
    if not isinstance(value, dict) or value.get("status") != "ok":
        raise ObservationError("telefon-testbackenden returnerede ikke status=ok")
    return value


def _phone_state(path: Path, candidate: dict[str, str]) -> dict[str, Any]:
    value = _read_json(path)
    if value.get("schema") != PHONE_STATE_SCHEMA:
        raise ObservationError("telefon-teststatus har forkert schema")
    if value.get("production_activation") is not False:
        raise ObservationError("telefon-teststatus bevarer ikke production_activation=false")
    if value.get("version") != candidate["version"]:
        raise ObservationError("telefon-teststackens version matcher ikke kandidaten")
    url = value.get("lan_url")
    if not isinstance(url, str) or not url.startswith("http://"):
        raise ObservationError("telefon-teststatus mangler en LAN-URL")
    store_raw = value.get("pairing_data")
    if not isinstance(store_raw, str) or not store_raw.strip():
        raise ObservationError("telefon-teststatus mangler pairing-store")
    store = _repo_path(Path(store_raw))
    health = _health(url)
    if health.get("version") != candidate["version"]:
        raise ObservationError("den kørende backend matcher ikke kandidatens version")
    return {**value, "pairing_store": store}


def _devices(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    value = _read_json(path)
    devices = value.get("devices")
    if not isinstance(devices, list):
        return []
    return [item for item in devices if isinstance(item, dict)]


def _prompt(message: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    while True:
        try:
            value = input(f"{message}{suffix}: ").strip()
        except EOFError as exc:
            raise ObservationError("input blev afbrudt") from exc
        if value:
            return value
        if default is not None:
            return default
        print("  Skriv en værdi.")


def _yes_no(message: str) -> bool:
    while True:
        value = _prompt(message).casefold()
        if value in {"j", "ja", "y", "yes"}:
            return True
        if value in {"n", "nej", "no"}:
            return False
        print("  Skriv J eller N.")


def _terminal_state() -> str:
    while True:
        value = _prompt("Efter stoppet: [A] afbrudt/cancelled eller [N] normal/idle").casefold()
        if value in {"a", "afbrudt", "cancelled", "c"}:
            return "cancelled"
        if value in {"n", "normal", "idle", "i"}:
            return "idle"
        print("  Skriv A eller N.")


def _latency(raw: str, *, allow_unknown: bool) -> int | None:
    value = raw.strip().casefold()
    if allow_unknown and value in {"", "?", "ukendt", "u"}:
        return None
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ObservationError("stoppetiden skal være et helt tal i millisekunder") from exc
    if not 0 <= parsed <= 30_000:
        raise ObservationError("stoppetiden skal være mellem 0 og 30000 ms")
    return parsed


def _adb(*args: str) -> str | None:
    executable = shutil.which("adb")
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _device_metadata(candidate: dict[str, str]) -> dict[str, str]:
    model = _adb("shell", "getprop", "ro.product.model") or "Pixel 6a"
    os_version = _adb("shell", "getprop", "ro.build.version.release")
    package = _adb("shell", "dumpsys", "package", "dk.ternedal.modelrig") or ""
    match = re.search(r"\bversionName=([^\s]+)", package)
    app_version = match.group(1) if match else None

    print("\nEnhedsoplysninger")
    print("-----------------")
    print(f"  Model: {model}")
    if os_version:
        print(f"  Android: {os_version} (læst automatisk)")
    else:
        os_version = _prompt("Android-version, fx 17")
    if app_version:
        print(f"  Kaliv-app: {app_version} (læst automatisk)")
    else:
        app_version = _prompt("Kaliv-appens version", candidate["version"])
    if app_version != candidate["version"]:
        raise ObservationError(
            f"Kaliv-appen er {app_version}, men kandidaten er {candidate['version']}; "
            "installér den eksakte kandidatapp før voice-beviset"
        )
    return {
        "model": model,
        "os_version": os_version,
        "app_version": app_version,
    }


def _archive_stale(path: Path) -> None:
    if not path.is_file():
        return
    archive = ROOT / "validation" / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path.replace(archive / f"stage-a-voice-observations-{stamp}.json")


def _load_or_create_state(
    path: Path,
    *,
    candidate: dict[str, str],
    pairing_store: Path,
) -> dict[str, Any]:
    if path.is_file():
        value = _read_json(path)
        if (
            value.get("schema") == STATE_SCHEMA
            and value.get("candidate") == candidate
            and value.get("pairing_store") == str(pairing_store.relative_to(ROOT))
            and isinstance(value.get("trials"), list)
        ):
            print(f"  Genoptager {len(value['trials'])}/5 gemte forsøg.")
            return value
        _archive_stale(path)
    value = {
        "schema": STATE_SCHEMA,
        "candidate": candidate,
        "pairing_store": str(pairing_store.relative_to(ROOT)),
        "paired_device_id": None,
        "device": None,
        "trials": [],
        "production_activation": False,
    }
    _write_json_atomic(path, value)
    return value


def _ensure_new_pairing(state: dict[str, Any], store: Path, state_path: Path) -> None:
    devices = _devices(store)
    existing_ids = {str(item.get("id")) for item in devices if item.get("id")}
    paired_id = state.get("paired_device_id")
    if isinstance(paired_id, str) and paired_id in existing_ids:
        print("  Den tidligere telefonparring til denne teststore findes stadig.")
        return

    print("\nPar telefonen nu")
    print("----------------")
    print("  Brug Server-URL og parringskode fra det grønne telefon-testvindue.")
    print("  Indtast koden, også hvis Kaliv allerede siger 'parret'.")
    while True:
        input("  Tryk Enter her, når Kaliv viser at forbindelsen virker ... ")
        current = _devices(store)
        new_devices = [item for item in current if str(item.get("id")) not in existing_ids]
        if new_devices:
            newest = new_devices[-1]
            state["paired_device_id"] = str(newest.get("id"))
            _write_json_atomic(state_path, state)
            print(f"  OK: Ny parring er registreret som {newest.get('name') or 'ukendt enhed'}.")
            return
        print("  Der er endnu ikke registreret en ny parring. Kontrollér koden og tryk Forbind igen.")


def _failure_trial(spec: dict[str, str]) -> dict[str, Any]:
    print("\n  Forsøget fejlede. Jeg gemmer det ærligt; intet markeres automatisk grønt.")
    recognized = _yes_no("  Blev Stop/tale/netværksafbrydelsen registreret? [J/N]")
    playback_stopped = _yes_no("  Stoppede lyden faktisk? [J/N]")
    stale_audio_resumed = _yes_no("  Kom gammel lyd tilbage bagefter? [J/N]")
    terminal = _terminal_state()
    while True:
        raw = _prompt("  Omtrentlig stoppetid i ms, eller U hvis ukendt", "U")
        try:
            latency = _latency(raw, allow_unknown=True)
            break
        except ObservationError as exc:
            print(f"  {exc}")
    return {
        "id": spec["id"],
        "trigger": spec["trigger"],
        "recognized": recognized,
        "playback_stopped": playback_stopped,
        "stale_audio_resumed": stale_audio_resumed,
        "ui_terminal_state": terminal,
        "stop_latency_ms": latency,
        "notes": "Fejl registreret gennem den guidede Stage A-launcher.",
    }


def _collect_trial(spec: dict[str, str], number: int) -> dict[str, Any]:
    print("\n" + "=" * 68)
    print(f"  FORSØG {number}/5 — {spec['title']}")
    print("=" * 68)
    print(f"  {spec['instruction']}")
    print("  Brug fx: 'Forklar grundigt forskellen på backup og synkronisering.'")
    input("\n  Tryk Enter, når du er klar. Udfør derefter forsøget på telefonen ... ")
    while True:
        raw = _prompt(
            "Hvis triggeren blev registreret, lyden stoppede, og gammel lyd IKKE kom igen: "
            "skriv stoppetiden i ms. Skriv F ved enhver fejl"
        )
        if raw.casefold() in {"f", "fejl", "n", "nej"}:
            return _failure_trial(spec)
        try:
            latency = _latency(raw, allow_unknown=False)
        except ObservationError as exc:
            print(f"  {exc}")
            continue
        terminal = _terminal_state()
        return {
            "id": spec["id"],
            "trigger": spec["trigger"],
            "recognized": True,
            "playback_stopped": True,
            "stale_audio_resumed": False,
            "ui_terminal_state": terminal,
            "stop_latency_ms": latency,
            "notes": "Bestået og registreret gennem den guidede Stage A-launcher.",
        }


def _voice_module():
    path = ROOT / "scripts" / "voice_baseline.py"
    spec = importlib.util.spec_from_file_location("stage_a_voice_baseline_contract", path)
    if spec is None or spec.loader is None:
        raise ObservationError("voice-baseline-kontrakten kunne ikke indlæses")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def collect(args: argparse.Namespace) -> int:
    phone_state_path = _repo_path(args.phone_state)
    resume_path = _repo_path(args.resume)
    output_path = _repo_path(args.output)
    candidate = _candidate()
    phone = _phone_state(phone_state_path, candidate)
    store = phone["pairing_store"]
    state = _load_or_create_state(
        resume_path,
        candidate=candidate,
        pairing_store=store,
    )
    _ensure_new_pairing(state, store, resume_path)
    if not isinstance(state.get("device"), dict):
        state["device"] = _device_metadata(candidate)
        _write_json_atomic(resume_path, state)

    completed = state["trials"]
    expected_ids = [item["id"] for item in TRIALS]
    if [item.get("id") for item in completed] != expected_ids[: len(completed)]:
        raise ObservationError("resume-filen indeholder trials i forkert rækkefølge")

    for index in range(len(completed), len(TRIALS)):
        trial = _collect_trial(TRIALS[index], index + 1)
        state["trials"].append(trial)
        state["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        _write_json_atomic(resume_path, state)
        print(f"  Gemt: {index + 1}/5. Du kan lukke vinduet og genoptage uden at gentage dette forsøg.")

    manual = {
        "schema": MANUAL_SCHEMA,
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "candidate": candidate,
        "device": state["device"],
        "trials": state["trials"],
        "operator": {
            "method": "guided-stage-a-launcher",
            "production_activation": False,
        },
    }
    _write_json_atomic(output_path, manual)
    module = _voice_module()
    loaded = module.load_manual_observations(output_path)
    summary = module._manual_summary(loaded)
    print("\n" + "=" * 68)
    print("  MANUEL VOICE-MATRIX GEMT")
    print("=" * 68)
    print(f"  Rapport: {output_path.relative_to(ROOT)}")
    print(f"  Forsøg: {summary['trials']}")
    print("  Resultat: " + ("BESTÅET" if summary["passed"] else "IKKE BESTÅET"))
    print("  production_activation=false")
    return 0 if summary["passed"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phone-state", type=Path, default=DEFAULT_PHONE_STATE)
    parser.add_argument("--resume", type=Path, default=DEFAULT_RESUME)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        return collect(args)
    except KeyboardInterrupt:
        print("\nSIKKERT STOP: De allerede besvarede forsøg er bevaret.", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"\nSIKKERT STOP: {type(exc).__name__}: {str(exc)[:800]}", file=sys.stderr)
        print("Ingen voice-success, merge, release eller produktionsaktivering blev opfundet.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
