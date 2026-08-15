#!/usr/bin/env python3
"""Static contract for the low-friction physical proof entrypoint.

The convenience layer is allowed to remove typing and command-copying. It is
not allowed to remove physical evidence, bypass device pairing, persist the
proof token, kill arbitrary listeners, or turn diagnostic skips into PASS.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
FILES = {
    "launcher": ROOT / "START_PROOF_CAMPAIGN.cmd",
    "easy": ROOT / "scripts/run-proof-campaign-easy.ps1",
    "core": ROOT / "scripts/run-proof-campaign.ps1",
    "qr": ROOT / "scripts/show_pairing_qr.py",
    "cleanup": ROOT / "scripts/stop-stage-a-known-processes.ps1",
    "voice": ROOT / "scripts/stage-a-voice-test.ps1",
    "scheduler": ROOT / "scripts/proof_scheduler_current.py",
    "t023": ROOT / "scripts/proof_t023_current.py",
}

passed = 0
failed = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} {detail}")


def main() -> int:
    missing = [name for name, path in FILES.items() if not path.is_file()]
    check("alle one-click-filer findes", not missing, f"-- mangler: {missing}")
    if missing:
        return 1

    text = {name: path.read_text(encoding="utf-8") for name, path in FILES.items()}

    check(
        "dobbeltklik selv-elevater via Windows UAC",
        "-Verb RunAs" in text["launcher"] and "run-proof-campaign-easy.ps1" in text["launcher"],
    )
    check(
        "proof-token kommer gennem normal pairing start+claim",
        "/api/v1/pair/start" in text["easy"] and "/api/v1/pair/claim" in text["easy"],
    )
    check(
        "easy-wrapperen beder ikke om manuel MODELRIG_TOKEN",
        "Read-Host 'MODELRIG_TOKEN" not in text["easy"]
        and "getpass" not in text["easy"].lower(),
    )
    check(
        "proof-token fjernes fra wrapperens miljø efter core-run",
        "Remove-Item Env:MODELRIG_TOKEN" in text["easy"],
    )
    check(
        "QR-linket bærer kun pair-url og code-parametre",
        'link = f"kaliv://pair?url=' in text["qr"]
        and "&code=" in text["qr"]
        and "MODELRIG_TOKEN" not in text["qr"],
    )
    check(
        "ukendte 8080/8099-processer stoppes ikke automatisk",
        "ukendt proces" in text["cleanup"].lower()
        and "Den stoppes ikke automatisk" in text["cleanup"],
    )
    check(
        "voice bruger QR men beholder manuel fallback",
        "show_pairing_qr.py" in text["voice"] and "fallback" in text["voice"].lower(),
    )
    check(
        "scheduler bruger den friske pairing-kode til QR",
        "original_refresh_pairing" in text["scheduler"]
        and "show_pairing_qr.py" in text["scheduler"],
    )
    check(
        "T-023 finder ADB i normale SDK-placeringer",
        "ANDROID_SDK_ROOT" in text["t023"]
        and "ANDROID_HOME" in text["t023"]
        and "LOCALAPPDATA" in text["t023"],
    )
    check(
        "T-023 bruger fysisk ADB-tunnel og frisk pairing",
        '"reverse", "tcp:8080", "tcp:8080"' in text["t023"]
        and "/api/v1/pair/start" in text["t023"],
    )
    check(
        "T-023 auto-identificerer kun en entydig ny run-id",
        "fresh = sorted(after - before)" in text["t023"]
        and "if len(fresh) == 1" in text["t023"]
        and "original_getpass" in text["t023"],
    )
    check(
        "T-033 anden bruger behøver ikke ejerens Python-sti eller GitHub-login",
        "where py" in text["easy"]
        and "where python" in text["easy"]
        and "git clone --quiet --local --no-hardlinks" in text["easy"],
    )
    check(
        "T-023 skip er fail-closed",
        "$t23pass=$false" in text["core"]
        and "T-023 blev sprunget over" in text["core"],
    )
    check(
        "T-033 skip er fail-closed",
        "$t33pass=$false" in text["core"]
        and "T-033 blev sprunget over" in text["core"],
    )
    check(
        "ingen convenience-lag aktiverer produktion",
        "production_activation = True" not in text["t023"]
        and "production_activation=true" not in text["easy"].lower()
        and "production_activation=true" not in text["qr"].lower(),
    )

    print(f"proof campaign easy contract: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
