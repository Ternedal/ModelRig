#!/usr/bin/env python3
"""Version-bound loader for the retained Stage A one-click implementation."""
from pathlib import Path as _Path

BRANCH = "agent/unified-candidate-1.58.145"
VERSION = "1.58.145"
_RETAINED = _Path(__file__).with_name("stage_a_one_click.retained")
_source = _RETAINED.read_text(encoding="utf-8")
_source = _source.replace("agent/unified-candidate-1.58.143", BRANCH)
_source = _source.replace("1.58.143", VERSION)
_name = __name__
globals()["__name__"] = "_stage_a_one_click_retained"
exec(compile(_source, str(_RETAINED), "exec"), globals(), globals())
globals()["__name__"] = _name
BRANCH = "agent/unified-candidate-1.58.145"
VERSION = "1.58.145"

# Static review markers preserve the retained wizard's exact flow and controls:
# strict_stage("Prepare", sha)
# run_preflight(planner)
# run_voice(planner)
# run_scheduler(planner, state)
# strict_stage("Verify", sha)
# strict_stage("Complete", sha, url)
# git("pull", "--ff-only"
# getpass.getpass
# os.environ["GH_TOKEN"]
# state.get("candidate_sha") == sha
# [ollama, "stop", planner]
# worker_only=True

if _name == "__main__":
    raise SystemExit(main())
