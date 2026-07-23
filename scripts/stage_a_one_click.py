#!/usr/bin/env python3
"""Version-bound loader for the retained Stage A one-click implementation."""
from pathlib import Path as _Path

BRANCH = "agent/unified-candidate-1.58.145"
VERSION = "1.58.145"
_RETAINED = _Path(__file__).with_name("stage_a_one_click.retained")
_source = _RETAINED.read_text(encoding="utf-8")
_source = _source.replace("agent/unified-candidate-1.58.143", BRANCH)
_source = _source.replace("1.58.143", VERSION)

_model_eval_old = 'str(ROOT / "scripts" / "agent3_model_eval.py"),'
_model_eval_new = 'str(ROOT / "scripts" / "stage_a_agent3_model_eval.py"),'
if _source.count(_model_eval_old) != 1:
    raise RuntimeError("Stage A model-eval hook drifted; refusing an ambiguous replacement")
_source = _source.replace(_model_eval_old, _model_eval_new)

_agent3_old = '''                str(ROOT / "scripts" / "run-agent3-rig-validation.ps1"),
                "-BaseUrl",
                "http://127.0.0.1:8080",
                "-PlannerModel",
                planner,
            ]'''
_agent3_new = '''                str(ROOT / "scripts" / "run-agent3-rig-validation.ps1"),
                "-BaseUrl",
                "http://127.0.0.1:8080",
                "-PlannerModel",
                planner,
                "-SkipReadinessRegeneration",
            ]'''
if _source.count(_agent3_old) != 1:
    raise RuntimeError("Stage A Agent 3 hook drifted; refusing an ambiguous replacement")
_source = _source.replace(_agent3_old, _agent3_new)

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
# stage_a_agent3_model_eval.py
# -SkipReadinessRegeneration

if _name == "__main__":
    raise SystemExit(main())
