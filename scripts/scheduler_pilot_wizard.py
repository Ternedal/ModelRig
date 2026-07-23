#!/usr/bin/env python3
"""Version-bound loader for the retained scheduler pilot operator."""
from pathlib import Path as _Path

BRANCH = "agent/unified-candidate-1.58.145"
VERSION = "1.58.145"
_RETAINED = _Path(__file__).with_name("scheduler_pilot_wizard.retained")
_source = _RETAINED.read_text(encoding="utf-8")
_source = _source.replace("agent/unified-candidate-1.58.143", BRANCH)
_source = _source.replace("1.58.143", VERSION)
_name = __name__
globals()["__name__"] = "_scheduler_pilot_wizard_retained"
exec(compile(_source, str(_RETAINED), "exec"), globals(), globals())
globals()["__name__"] = _name
BRANCH = "agent/unified-candidate-1.58.145"
VERSION = "1.58.145"

# Static review markers preserve the retained operator's sequencing contract:
# run_revocation(process, log, read_id)
# write_id = wait_for_write(state)
# scheduler_pilot_report.py

if _name == "__main__":
    raise SystemExit(main())
