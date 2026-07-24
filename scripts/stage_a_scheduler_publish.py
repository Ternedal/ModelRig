#!/usr/bin/env python3
"""Publish a verified isolated scheduler pilot into the campaign evidence slots.

The physical scheduler flow deliberately runs in a fresh directory under
``validation/stage-a-runtime``.  The authoritative campaign, however, consumes
``validation/scheduler-pilot-latest.json``.  This helper bridges only that
storage boundary after the isolated report has already passed the finalizer's
exact-identity checks.  It cannot create, approve, or repair evidence.
"""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "validation" / "stage-a-runtime"
PHONE_STATE = RUNTIME / "phone-test-state.json"
FINALIZER = ROOT / "scripts" / "stage_a_scheduler_finalize.py"
CAMPAIGN_REPORT = ROOT / "validation" / "scheduler-pilot-latest.json"
CAMPAIGN_MANUAL = ROOT / "validation" / "scheduler-manual-observations.json"
MAX_BYTES = 32 * 1024 * 1024


class PublishError(RuntimeError):
    pass


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise PublishError(f"Kunne ikke indlæse {path}.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise PublishError(f"Evidensfilen mangler eller er ikke en almindelig fil: {path}")
    size = path.stat().st_size
    if size <= 0 or size > MAX_BYTES:
        raise PublishError(f"Evidensfilen har ugyldig størrelse: {path} ({size} bytes)")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublishError(f"Evidensfilen er ikke gyldig UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PublishError(f"Evidensfilen indeholder ikke et JSON-objekt: {path}")
    return value


def atomic_copy(source: Path, target: Path) -> None:
    raw = source.read_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=target.parent,
        prefix=target.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(raw)
        temp = Path(handle.name)
    temp.replace(target)


def main() -> int:
    try:
        phone = load_object(PHONE_STATE)
        if phone.get("schema") != "kaliv-stage-a-phone-test-state/v2":
            raise PublishError("Telefon-status er ikke fra den scheduler-kompatible Stage A-stack.")
        if phone.get("production_activation") is not False:
            raise PublishError("Telefon-status kan ikke bevise production_activation=false.")

        scheduler = phone.get("scheduler")
        if not isinstance(scheduler, dict) or scheduler.get("enabled") is not True:
            raise PublishError("Telefon-status indeholder ingen aktiv isoleret scheduler-runmappe.")
        raw_dir = scheduler.get("data_dir")
        if not isinstance(raw_dir, str) or not raw_dir.strip():
            raise PublishError("Scheduler-status mangler den isolerede runmappe.")
        data_dir = Path(raw_dir).resolve()
        try:
            data_dir.relative_to(RUNTIME.resolve())
        except ValueError as exc:
            raise PublishError("Scheduler-runmappen ligger uden for Stage A-runtimeområdet.") from exc

        report_source = data_dir / "scheduler-pilot-latest.json"
        manual_source = data_dir / "scheduler-manual-observations.json"
        load_object(report_source)
        manual = load_object(manual_source)
        if manual.get("revocation_confirmed") is not True:
            raise PublishError("Den afledte scheduler-observation mangler revocation_confirmed=true.")
        recovery_line = manual.get("recovery_line")
        if not isinstance(recovery_line, str) or "scheduler: recovered " not in recovery_line:
            raise PublishError("Den afledte scheduler-observation mangler recovery-linjen.")

        finalizer = load_module(FINALIZER, "stage_a_scheduler_publish_finalizer")
        common = finalizer.load_common()
        wizard, bound_dir = common.bind_wizard(phone)
        if bound_dir.resolve() != data_dir:
            raise PublishError("Telefon-status og scheduler-binding peger ikke på samme runmappe.")
        identity = wizard._current_candidate_identity()
        if not finalizer.report_passed(report_source, identity):
            raise PublishError("Den isolerede rapport består ikke finalizerens exact-identity-kontrol.")

        atomic_copy(report_source, CAMPAIGN_REPORT)
        atomic_copy(manual_source, CAMPAIGN_MANUAL)
        if not finalizer.report_passed(CAMPAIGN_REPORT, identity):
            raise PublishError("Den publicerede kampagnerapport består ikke efter atomisk kopiering.")

        print("\n===============================================================")
        print("  SCHEDULER-EVIDENS ER PUBLICERET TIL STAGE A-KAMPAGNEN")
        print("===============================================================")
        print(f"  Rapport:      {CAMPAIGN_REPORT}")
        print(f"  Observation:  {CAMPAIGN_MANUAL}")
        print(f"  Exact SHA:    {identity.get('git_sha')}")
        print("  production_activation=false")
        return 0
    except (PublishError, OSError) as exc:
        print(f"\n  STOP  {exc}")
        print("  Den isolerede rapport er bevaret, men Stage A-slotten er ikke markeret klar.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
