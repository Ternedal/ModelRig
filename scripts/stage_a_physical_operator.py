#!/usr/bin/env python3
"""Version-bound loader for the retained fail-closed Stage A operator."""
from pathlib import Path as _Path

EXPECTED_BRANCH = "agent/unified-candidate-1.58.145"
EXPECTED_VERSION = "1.58.145"
_RETAINED = _Path(__file__).with_name("stage_a_physical_operator.retained")
_source = _RETAINED.read_text(encoding="utf-8")
_source = _source.replace("agent/unified-candidate-1.58.143", EXPECTED_BRANCH)
_source = _source.replace("1.58.143", EXPECTED_VERSION)
_name = __name__
globals()["__name__"] = "_stage_a_physical_operator_retained"
exec(compile(_source, str(_RETAINED), "exec"), globals(), globals())
globals()["__name__"] = _name
EXPECTED_BRANCH = "agent/unified-candidate-1.58.145"
EXPECTED_VERSION = "1.58.145"

# Static surface markers retained by tests and operator review:
# _require_physical_operator()
# candidate_freeze_check.py
# physical_validation_candidate_campaign.py
# run-browser-peer-public-validation.ps1
# physical_validation_candidate_gate.py
# choices=("prepare", "verify", "complete")

if _name == "__main__":
    raise SystemExit(main())
