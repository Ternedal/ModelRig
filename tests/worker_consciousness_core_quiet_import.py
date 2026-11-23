#!/usr/bin/env python3
"""Importing the Consciousness Core does not print a warning per wire model.

Every model carries a ``schema`` field (the contract's version tag), and pydantic
warns once per class that it shadows the deprecated ``BaseModel.schema()``: about
150 lines at each worker start. On the rig 20/11 that wall hid the two lines that
said the appliance was up. The package silences exactly that message.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_quiet_import.py
"""
from __future__ import annotations

import pkgutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "worker"

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def run(code: str) -> subprocess.CompletedProcess:
    # A fresh interpreter with warnings shown: the filter has to work before any class exists.
    return subprocess.run([sys.executable, "-W", "default", "-c", code], cwd=str(WORKER),
                          capture_output=True, text=True, timeout=180)


modules = sorted(m.name for m in pkgutil.iter_modules([str(WORKER / "app" / "consciousness_core")]))
check(len(modules) > 50, f"the package's modules are found ({len(modules)})")

everything = run(
    "import importlib\n"
    f"for name in {modules!r}:\n"
    "    importlib.import_module('app.consciousness_core.' + name)\n"
    "print('imported')\n")
check(everything.returncode == 0 and "imported" in everything.stdout,
      f"every module imports (exit {everything.returncode}): {everything.stderr[-300:]!r}")
check("shadows an attribute" not in everything.stderr,
      f"no 'shadows an attribute' line at import ({everything.stderr.count('shadows an attribute')} found)")

narrow = run(
    "from app.consciousness_core.contracts import StrictModel\n"
    "class Probe(StrictModel):\n"
    "    copy: int = 0\n"
    "class Tagged(StrictModel):\n"
    "    schema: str = 'x'\n")
check('Field name "copy" in "Probe" shadows an attribute' in narrow.stderr,
      "another shadowed attribute still warns: the filter is for the schema field only")
check('Field name "schema"' not in narrow.stderr, "and a new model with a schema field is quiet too")

print(f"\n===== CONSCIOUSNESS CORE QUIET IMPORT: {passed} passed, {failed} failed =====")
sys.exit(1 if failed else 0)
