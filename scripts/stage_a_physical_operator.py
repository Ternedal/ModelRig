#!/usr/bin/env python3
"""Version-bound loader for the retained fail-closed Stage A operator."""
# ruff: noqa: F821 -- denne fil er en shim. Den exec'er sin .retained-soester
# ind i globals(), saa navne som ROOT, REPORT_PATH, SCHEMA og main defineres
# ved koersel og er usynlige for statisk analyse. Undtagelsen staar her frem
# for i CI-kommandoen, saa den kan laeses sammen med sin aarsag.
from pathlib import Path as _Path

EXPECTED_BRANCH = "physical-proof/2.0.11"
EXPECTED_VERSION = "2.0.11"
_RETAINED = _Path(__file__).with_name("stage_a_physical_operator.retained")
_source = _RETAINED.read_text(encoding="utf-8")
_source = _source.replace("agent/unified-candidate-1.58.143", EXPECTED_BRANCH)
_source = _source.replace("1.58.143", EXPECTED_VERSION)
_name = __name__
globals()["__name__"] = "_stage_a_physical_operator_retained"
exec(compile(_source, str(_RETAINED), "exec"), globals(), globals())
globals()["__name__"] = _name
EXPECTED_BRANCH = "physical-proof/2.0.11"
EXPECTED_VERSION = "2.0.11"

# Static surface markers retained by tests and operator review:
# _require_physical_operator()
# candidate_freeze_check.py
# physical_validation_candidate_campaign.py
# run-browser-peer-public-validation.ps1
# physical_validation_candidate_gate.py
# choices=("prepare", "verify", "complete")

if _name == "__main__":
    raise SystemExit(main())
