#!/usr/bin/env python3
"""One exact-candidate entrypoint for the remaining Milestone 3 physical work.

The coordinator reuses the existing T-020, T-022 and T-023 operators. Each child
runs in a separate Python process, but its version-bound BRANCH/VERSION globals
are overridden before main() so every report is produced from the same clean
candidate. The coordinator cannot approve a write, observe a device, merge,
push, tag, release or activate production.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
BRANCH = "agent/milestone3-physical-candidate-v1"
VERSION = "1.58.146"
STAGE_A_GATE = SCRIPTS / "physical_validation_candidate_gate.py"
STAGE_A_REPORT = ROOT / "validation" / "physical-validation-candidate-final-latest.json"
OPERATORS = (
    (
        "T-020 read-only developer-pilot",
        SCRIPTS / "agent3_readonly_pilot_one_click.py",
        ROOT / "validation" / "agent3-readonly-pilot-latest.json",
        "kaliv-agent3-readonly-pilot/v1",
    ),
    (
        "T-022 append-only write-pilot",
        SCRIPTS / "agent3_write_pilot_physical_one_click.py",
        ROOT / "validation" / "agent3-write-pilot-latest.json",
        "kaliv-agent3-write-pilot/v1",
    ),
    (
        "T-023 termination UI-pilot",
        SCRIPTS / "agent3_termination_ui_physical_one_click.py",
        ROOT / "validation" / "agent3-termination-ui-physical-latest.json",
        "kaliv-agent3-termination-ui-physical/v1",
    ),
)


class Milestone3Error(RuntimeError):
    pass


def heading(text: str) -> None:
    print(f"\n{'=' * 72}\n  {text}\n{'=' * 72}")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise Milestone3Error(f"Kan ikke indlæse {path.name}.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def ensure_exact_candidate() -> str:
    stage = load_module("milestone3_stage_a", SCRIPTS / "stage_a_one_click.py")
    stage.BRANCH = BRANCH
    stage.VERSION = VERSION
    sha = stage.ensure_candidate()
    if not isinstance(sha, str) or len(sha) != 40:
        raise Milestone3Error("Kandidat-checkout returnerede ikke en Git SHA.")
    print(f"  OK  Fælles Milestone 3-kandidat: {sha}")
    return sha


def run_stage_a_gate() -> int:
    if not STAGE_A_GATE.is_file():
        raise Milestone3Error(f"Mangler Stage A-gate: {STAGE_A_GATE}")
    heading("Forudsætning — verificér Stage A på den fælles kandidat")
    result = subprocess.run(
        [
            sys.executable,
            str(STAGE_A_GATE),
            "--report",
            str(STAGE_A_REPORT),
        ],
        cwd=ROOT,
        env=os.environ.copy(),
        check=False,
    )
    return int(result.returncode)


def child_bootstrap(path: Path) -> str:
    return (
        "import importlib.util, pathlib, sys; "
        f"p=pathlib.Path({str(path)!r}); "
        "spec=importlib.util.spec_from_file_location('milestone3_child', p); "
        "m=importlib.util.module_from_spec(spec); "
        "sys.modules['milestone3_child']=m; "
        "spec.loader.exec_module(m); "
        f"m.BRANCH={BRANCH!r}; m.VERSION={VERSION!r}; "
        "raise SystemExit(m.main())"
    )


def run_operator(label: str, path: Path) -> int:
    if not path.is_file():
        raise Milestone3Error(f"Mangler operator: {path}")
    heading(label)
    result = subprocess.run(
        [sys.executable, "-B", "-c", child_bootstrap(path)],
        cwd=ROOT,
        env=os.environ.copy(),
        check=False,
    )
    return int(result.returncode)


def report_status(path: Path, expected_sha: str, expected_schema: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        return {
            "path": str(path),
            "present": False,
            "success": False,
            "candidate_match": False,
            "schema_match": False,
            "production_activation": None,
        }
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {
            "path": str(path),
            "present": True,
            "success": False,
            "candidate_match": False,
            "schema_match": False,
            "production_activation": None,
        }
    if not isinstance(value, dict):
        return {
            "path": str(path),
            "present": True,
            "success": False,
            "candidate_match": False,
            "schema_match": False,
            "production_activation": None,
        }

    candidate = value.get("candidate")
    if not isinstance(candidate, dict):
        candidate = {}
    target = value.get("target")
    if not isinstance(target, dict):
        target = {}
    activation = value.get("production_activation")
    if activation is None:
        activation = target.get("production_activation")

    return {
        "path": str(path.relative_to(ROOT)),
        "present": True,
        "success": value.get("success") is True,
        "candidate_match": candidate.get("git_sha") == expected_sha,
        "schema_match": value.get("schema") == expected_schema,
        "production_activation": activation,
    }


def main() -> int:
    os.chdir(ROOT)
    heading("Kaliv Milestone 3 — samlet fysisk Agent 3-kandidat")
    print("  Én kandidat. Tre eksisterende, uafhængigt resumable operatorer.")
    print("  Rækkefølge: T-020 read-only → T-022 append-only → T-023 termination UI.")
    print("  Ingen fysisk observation, approval eller response kan auto-udfyldes.")
    print("  Ingen merge, push, tag, release eller production activation udføres.")

    sha = ensure_exact_candidate()
    stage_code = run_stage_a_gate()
    if stage_code != 0:
        print(
            f"\n  SIKKERT STOP: Stage A-gaten returnerede {stage_code}; "
            "Milestone 3 må ikke starte.",
            file=sys.stderr,
        )
        return stage_code

    for label, path, report, schema in OPERATORS:
        code = run_operator(label, path)
        if code != 0:
            print(f"\n  SIKKERT STOP: {label} returnerede {code}.", file=sys.stderr)
            print("  Ret den viste fysiske blocker og start samme launcher igen.", file=sys.stderr)
            return code
        status = report_status(report, sha, schema)
        if (
            status.get("present") is not True
            or status.get("success") is not True
            or status.get("candidate_match") is not True
            or status.get("schema_match") is not True
            or status.get("production_activation") is not False
        ):
            print(
                f"\n  SIKKERT STOP: {label} returnerede 0, men rapporten er ikke "
                "grøn, schema-korrekt, exact-SHA-bundet og non-activating.",
                file=sys.stderr,
            )
            return 2
        print(f"  OK  Verificeret rapport: {status['path']}")

    heading("MILESTONE 3 FYSISK EVIDENS ER KOMPLET PÅ ÉN KANDIDAT")
    print(f"  Kandidat: {sha}")
    for _label, _path, report, _schema in OPERATORS:
        print(f"  - {report.relative_to(ROOT)}")
    print("  production_activation=false; integration kræver fortsat separat review.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n  SIKKERT STOP: afbrudt af operatøren.", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        print(
            f"\n  SIKKERT STOP: {type(exc).__name__}: {str(exc)[:1000]}",
            file=sys.stderr,
        )
        raise SystemExit(1)
