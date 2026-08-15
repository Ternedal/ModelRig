#!/usr/bin/env python3
"""Bind the existing T-023 physical UI evidence operator to the current checkout."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PAIR_STATE = ROOT / "validation" / "stage-a-runtime" / "t023-phone-pairing.json"
sys.path.insert(0, str(ROOT / "scripts"))
import agent3_termination_ui_physical_one_click as op  # noqa: E402


def cap(*args: str) -> str:
    result = subprocess.run(
        args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return result.stdout.strip()


def exact() -> str:
    dirty = cap("git", "status", "--porcelain")
    if dirty:
        raise RuntimeError("Working tree er ikke ren:\n" + dirty)
    branch = cap("git", "branch", "--show-current")
    if not branch:
        raise RuntimeError("Detached HEAD afvises")
    cap("git", "fetch", "--quiet", "origin", branch)
    cap("git", "pull", "--ff-only", "origin", branch)
    sha = cap("git", "rev-parse", "HEAD")
    if sha != cap("git", "rev-parse", f"origin/{branch}"):
        raise RuntimeError("HEAD/remote mismatch")
    return sha


def find_adb_current() -> str:
    candidates: list[Path] = []
    direct = shutil.which("adb")
    if direct:
        candidates.append(Path(direct))
    for env_name in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        value = os.environ.get(env_name, "").strip()
        if value:
            candidates.append(Path(value) / "platform-tools" / "adb.exe")
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        candidates.append(Path(local_app_data) / "Android" / "Sdk" / "platform-tools" / "adb.exe")

    for candidate in candidates:
        if candidate.is_file():
            print(f"  ADB: {candidate}")
            return str(candidate)
    raise op.OperatorError(
        "adb blev ikke fundet. Android Studio/SDK kan bruges direkte; "
        "scriptet leder automatisk i PATH, ANDROID_SDK_ROOT, ANDROID_HOME "
        "og %LOCALAPPDATA%\\Android\\Sdk\\platform-tools."
    )


def pair_start() -> dict[str, Any]:
    request = urllib.request.Request(
        "http://127.0.0.1:8080/api/v1/pair/start",
        method="POST",
    )
    admin_key = os.environ.get("MODELRIG_ADMIN_KEY", "").strip()
    if admin_key:
        request.add_header("X-Admin-Key", admin_key)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            value = json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise op.OperatorError(f"T-023 kunne ikke oprette en frisk parringskode: {exc}") from exc
    if not isinstance(value, dict) or not str(value.get("code") or "").strip():
        raise op.OperatorError("T-023 pairing-endpoint returnerede ingen parringskode.")
    return value


def setup_android_pairing(adb: str) -> None:
    # T-023 already requires a physically attached ADB device. Reverse only the
    # proof backend port so the phone can use the exact loopback candidate
    # without opening an extra LAN listener or firewall rule.
    reverse = subprocess.run(
        [adb, "reverse", "tcp:8080", "tcp:8080"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if reverse.returncode != 0:
        raise op.OperatorError(
            "ADB reverse til exact-head backenden fejlede: "
            + (reverse.stderr or reverse.stdout).strip()
        )

    pairing = pair_start()
    PAIR_STATE.parent.mkdir(parents=True, exist_ok=True)
    PAIR_STATE.write_text(
        json.dumps(
            {
                "lan_url": "http://127.0.0.1:8080",
                "pairing_code": str(pairing["code"]),
                "pairing_expires_at": pairing.get("expires_at"),
                "transport": "adb-reverse",
                "production_activation": False,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    qr = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "show_pairing_qr.py"),
            "--state",
            str(PAIR_STATE),
            "--open",
        ],
        cwd=ROOT,
        text=True,
        check=False,
    )
    print("\n  T-023 TELEFONPARRING")
    if qr.returncode == 0:
        print("  På telefonen: Kaliv -> Rig -> Skan QR -> kontrollér 127.0.0.1:8080 -> Forbind.")
        print("  127.0.0.1 virker her med vilje via den fysiske ADB-kabeltunnel.")
    else:
        print("  QR kunne ikke vises. Brug disse fallback-felter i Kaliv:")
        print("  Server-URL:   http://127.0.0.1:8080")
        print(f"  Parringskode: {pairing['code']}")
    input("  Når Kaliv viser at riggen er forbundet, tryk Enter her: ")


def run_ids(token: str) -> set[str]:
    payload = op.request_json("/api/v1/experimental/agent3/runs?limit=100", token)
    runs = payload.get("runs")
    if not isinstance(runs, list):
        return set()
    return {
        str(item.get("id"))
        for item in runs
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }


def main() -> int:
    os.chdir(ROOT)
    exact()
    branch = cap("git", "branch", "--show-current")
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    op.BRANCH, op.VERSION = branch, version
    op.stage.BRANCH, op.stage.VERSION = branch, version
    op.stage.ensure_candidate = exact
    op.find_adb = find_adb_current

    original_build_install = op.build_install_android
    adb_holder: dict[str, str] = {}

    def build_install_android_current(adb: str) -> None:
        original_build_install(adb)
        adb_holder["path"] = adb
        setup_android_pairing(adb)

    op.build_install_android = build_install_android_current

    original_record_case = op.record_case

    def record_case_current(
        observations: dict[str, Any],
        inventory: dict[str, list[str]],
        *,
        platform_name: str,
        case_name: str,
        adb: str,
    ) -> None:
        token = os.environ.get("MODELRIG_TOKEN", "").strip()
        before = run_ids(token) if token else set()
        original_getpass = op.getpass.getpass

        def getpass_current(prompt: str, *args: Any, **kwargs: Any) -> str:
            if "Indsæt run-id" in prompt and token:
                after = run_ids(token)
                fresh = sorted(after - before)
                if len(fresh) == 1:
                    print("  Run-id: identificeret automatisk som den ene nye run; kun SHA-256 gemmes.")
                    return fresh[0]
                if not fresh:
                    print("  Run-id kunne ikke identificeres automatisk; brug den skjulte fallback.")
                else:
                    print(
                        f"  {len(fresh)} nye runs blev set; deterministisk valg er umuligt, "
                        "så brug den skjulte fallback."
                    )
            return original_getpass(prompt, *args, **kwargs)

        op.getpass.getpass = getpass_current
        try:
            original_record_case(
                observations,
                inventory,
                platform_name=platform_name,
                case_name=case_name,
                adb=adb,
            )
        finally:
            op.getpass.getpass = original_getpass

    op.record_case = record_case_current

    try:
        return int(op.main())
    finally:
        adb = adb_holder.get("path")
        if adb:
            subprocess.run(
                [adb, "reverse", "--remove", "tcp:8080"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"T-023 BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
