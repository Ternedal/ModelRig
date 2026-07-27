#!/usr/bin/env python3
"""Every preflight check in the baseline wrapper must be able to block.

A preflight that cannot fail is decoration, and worse than none: it converts
"I do not know" into "verified". Each check is driven into its failure state
here, on the machine, without a rig -- which is the whole point, since the rig
day is exactly when there is no time to debug the thing that was supposed to
save time.

Run: python3 tests/workflow_baseline_one_click.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "_wf_one_click", ROOT / "scripts" / "workflow_baseline_one_click.py")
assert spec and spec.loader
oc = importlib.util.module_from_spec(spec)
sys.modules["_wf_one_click"] = oc
spec.loader.exec_module(oc)

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def blocks(label: str, needle: str, fn, *args, **kwargs) -> None:
    """Assert fn blocks, and that the message names the fix rather than the symptom."""
    try:
        fn(*args, **kwargs)
    except oc.Blocked as exc:
        text = str(exc)
        check(needle.lower() in text.lower(),
              f"{label} blokerer og naevner {needle!r}")
        return
    except Exception as exc:  # noqa: BLE001
        check(False, f"{label} rejste {type(exc).__name__}, ikke Blocked: {exc}")
        return
    check(False, f"{label} blokerede IKKE -- checket er dekoration")


def allows(label: str, fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
        check(True, label)
    except oc.Blocked as exc:
        check(False, f"{label} blokerede uventet: {exc}")


DEAD = "http://127.0.0.1:9"  # discard-porten; garanteret uden lytter

# --- bytecode -------------------------------------------------------------
saved = os.environ.get("PYTHONDONTWRITEBYTECODE")
try:
    os.environ.pop("PYTHONDONTWRITEBYTECODE", None)
    blocks("manglende PYTHONDONTWRITEBYTECODE", "PYTHONDONTWRITEBYTECODE", oc.check_bytecode)
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    # Sabotage-cyklus frem for en assertion om omgivelserne: plant en .pyc,
    # kraev roedt, fjern den igen, kraev groent. Uafhaengig af hvad der laa i
    # traeet i forvejen.
    planted = ROOT / "worker" / "__pycache__" / "_preflight_probe.cpython-312.pyc"
    pre_existing = list((ROOT / "worker").rglob("*.pyc"))
    if pre_existing:
        check(True, f"traeet havde {len(pre_existing)} .pyc -- checket fanger dem")
    else:
        allows("rent trae accepteres", oc.check_bytecode)
        planted.parent.mkdir(parents=True, exist_ok=True)
        planted.write_bytes(b"\x00")
        try:
            blocks("plantet .pyc", ".pyc", oc.check_bytecode)
        finally:
            planted.unlink(missing_ok=True)
            try:
                planted.parent.rmdir()
            except OSError:
                pass
        allows("efter oprydning accepteres traeet igen", oc.check_bytecode)
finally:
    if saved is None:
        os.environ.pop("PYTHONDONTWRITEBYTECODE", None)
    else:
        os.environ["PYTHONDONTWRITEBYTECODE"] = saved

# --- token ----------------------------------------------------------------
saved_tok = os.environ.get("MODELRIG_TOKEN")
try:
    os.environ.pop("MODELRIG_TOKEN", None)
    blocks("manglende token", "MODELRIG_TOKEN", oc.check_token)

    os.environ["MODELRIG_TOKEN"] = "abc123"
    blocks("for kort token", "64 hex", oc.check_token)

    os.environ["MODELRIG_TOKEN"] = "Z" * 64
    blocks("64 tegn men ikke hex", "64 hex", oc.check_token)

    good = "a1b2c3d4" * 8
    os.environ["MODELRIG_TOKEN"] = good
    allows("64 hex accepteres", oc.check_token)
    check(oc.check_token() == good, "check_token returnerer tokenet")
finally:
    if saved_tok is None:
        os.environ.pop("MODELRIG_TOKEN", None)
    else:
        os.environ["MODELRIG_TOKEN"] = saved_tok

# --- worker ---------------------------------------------------------------
blocks("worker uden lytter", "svarer ikke", oc.check_worker, DEAD, "a" * 64)
blocks("worker uden lytter naevner run-windows-faelden", "run-windows.ps1",
       oc.check_worker, DEAD, "a" * 64)

# --- ollama / model -------------------------------------------------------
blocks("Ollama uden lytter", "Ollama svarer ikke", oc.check_model, "x", DEAD)

# --- spec -----------------------------------------------------------------
allows("den rigtige spec accepteres", oc.check_spec)
check(oc.check_spec() >= 1, "check_spec returnerer antal workflows")

print(f"\nworkflow baseline one-click preflight: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
