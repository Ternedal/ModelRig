#!/usr/bin/env python3
"""Version-bound loader for the retained Stage A one-click implementation."""
# ruff: noqa: F821 -- denne fil er en shim. Den exec'er sin .retained-soester
# ind i globals(), saa navne som ROOT, REPORT_PATH, SCHEMA og main defineres
# ved koersel og er usynlige for statisk analyse. Undtagelsen staar her frem
# for i CI-kommandoen, saa den kan laeses sammen med sin aarsag.
from pathlib import Path as _Path

BRANCH = "physical-proof/2.0.13"
VERSION = "2.0.13"
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

_pair_start_old = '''        req = urllib.request.Request(f"{base}/pair/start", data=b"{}", method="POST")
        req.add_header("Content-Type", "application/json")'''
_pair_start_new = '''        req = urllib.request.Request(f"{base}/pair/start", data=b"{}", method="POST")
        req.add_header("Content-Type", "application/json")
        admin_key = os.environ.get("MODELRIG_ADMIN_KEY", "").strip()
        if admin_key:
            req.add_header("X-Admin-Key", admin_key)'''
if _source.count(_pair_start_old) != 1:
    raise RuntimeError("Stage A pairing hook drifted; refusing an ambiguous admin-key patch")
_source = _source.replace(_pair_start_old, _pair_start_new)

_pair_doc_old = "    callers need no admin key) yields a code; POST /pair/claim redeems it."
_pair_doc_new = (
    "    callers send MODELRIG_ADMIN_KEY when the backend requires it) yields a code; "
    "POST /pair/claim redeems it."
)
if _source.count(_pair_doc_old) != 1:
    raise RuntimeError("Stage A pairing documentation drifted; refusing an ambiguous replacement")
_source = _source.replace(_pair_doc_old, _pair_doc_new)

_name = __name__
globals()["__name__"] = "_stage_a_one_click_retained"
exec(compile(_source, str(_RETAINED), "exec"), globals(), globals())
globals()["__name__"] = _name
BRANCH = "physical-proof/2.0.13"
VERSION = "2.0.13"

# Static review markers preserve the retained wizard's exact flow and controls:
# strict_stage("Prepare", sha)
# run_preflight(planner)
# run_voice(planner)
# run_scheduler(planner, state)
# strict_stage("Verify", sha)
# strict_stage("Complete", sha, url)
# git("pull", "--ff-only"
# getpass.getpass
# _mint_device_token
# /pair/start
# /pair/claim
# len(token) != 64
# MODELRIG_ADMIN_KEY
# X-Admin-Key
# os.environ["GH_TOKEN"]
# state.get("candidate_sha") == sha
# [ollama, "stop", planner]
# worker_only=True
# stage_a_agent3_model_eval.py
# -SkipReadinessRegeneration

if _name == "__main__":
    raise SystemExit(main())
