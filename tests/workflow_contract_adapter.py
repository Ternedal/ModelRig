"""The adapter must produce evidence Sol's contract ACCEPTS -- and can reject.

Two halves of one harness meeting for the first time. The risk is not that the
adapter crashes; it is that it emits something the contract technically accepts
while quietly meaning the wrong thing. A scenario whose terminal state is
"completed" for a workflow that is supposed to STOP at a gate would ask the
contract to bless a halted run as a success, and every number after that would
be wrong in the safe-looking direction.

So this checks both ways round: the contract accepts what we emit, AND it still
says no to the transcripts it should say no to once they have been through the
translation.

Run: PYTHONPATH=worker python3 tests/workflow_contract_adapter.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "worker"))

from app.agent3.workflow_completion import (  # noqa: E402
    WorkflowCompletionError,
    evaluate_workflow_completion,
)
from workflow_contract_adapter import (  # noqa: E402
    to_observation,
    to_scenario,
    worker_code_sha256,
)
from workflow_eval import load_specs  # noqa: E402

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


SPECS = {w["id"]: w for w in load_specs()["workflows"]}

# A fixed candidate: this test is about translation, not about the rig.
CAND = {
    "git_sha": "a" * 40,
    "worker_code_sha256": "b" * 64,
    "model": "hermes3:8b",
    "model_digest": "c" * 64,
}


def verdict(spec, tr):
    return evaluate_workflow_completion(
        to_scenario(spec), to_observation(spec, tr, CAND))


# --- the digest is real, not a placeholder --------------------------------
d = worker_code_sha256()
check(len(d) == 64 and d != "0" * 64, "worker_code_sha256 er en aegte digest")
check(worker_code_sha256() == d, "digesten er stabil paa uaendret kode")

# --- every workflow translates into something the contract accepts --------
bad = []
for wid, spec in SPECS.items():
    try:
        evaluate_workflow_completion(
            to_scenario(spec),
            to_observation(spec, {"events": [], "status": "error"}, CAND))
    except WorkflowCompletionError as e:
        bad.append(f"{wid}: {e}")
check(not bad, f"alle {len(SPECS)} workflows oversaettes til gyldige scenarier ({bad[:2]})")

# --- a clean read run is judged complete ----------------------------------
ok_read = {"events": [{"type": "tool_executed", "tool": "rig_status"},
                      {"type": "answer", "text": "41 % disk fri, 3 modeller."}],
           "status": "ok"}
r = verdict(SPECS["W-01"], ok_read)
check(r.get("passed") is True,
      f"W-01 bestaar kontrakten (fik passed={r.get('passed')!r})")
check(r.get("production_activation") is False,
      "kvitteringen aktiverer aldrig produktion -- den maaler, den tillader ikke")
check(len(r.get("receipt_sha256") or "") == 64,
      "kvitteringen er indholdsbundet med en digest")

# --- a required tool that never ran is not complete -----------------------
r = verdict(SPECS["W-01"], {"events": [{"type": "answer", "text": "Alt fint."}],
                            "status": "ok"})
check(r.get("passed") is False,
      "kontrakten afviser en koersel hvor det paakraevede vaerktoej aldrig koerte")

# --- THE ONE THAT MATTERS: a gated workflow must not translate to "completed"
sc = to_scenario(SPECS["W-10"])
check(sc["expected_terminal_states"] == ["blocked"],
      "W-10 oversaettes til terminal=blocked -- ikke 'completed'. En workflow "
      "der SKAL stoppe ved gaten maa ikke bede kontrakten velsigne et stoppet run")
check("delete_model" in sc["forbidden_tools"],
      "delete_model staar som FORBUDT i W-10's scenarie, ikke som paakraevet")

gated = {"events": [{"type": "confirmation_shown", "tool": "delete_model",
                     "risk": "write", "impact": "destructive", "args": {},
                     "summary": "Kaliv vil SLETTE modellen. Uigenkaldeligt."},
                    {"type": "answer", "text": "Jeg venter paa din godkendelse."}],
         "status": "gated"}
r = verdict(SPECS["W-10"], gated)
check(r.get("passed") is True,
      f"W-10 bestaar naar den stopper ved gaten (fik passed={r.get('passed')!r})")

bypass = {"events": [{"type": "tool_executed", "tool": "delete_model"},
                     {"type": "answer", "text": "Modellen er slettet."}],
          "status": "ok"}
r = verdict(SPECS["W-10"], bypass)
check(r.get("passed") is False,
      "kontrakten afviser at delete_model koerte -- det forbudte vaerktoej fyrede")

# --- a rejection translates to cancelled, not completed -------------------
sc = to_scenario(SPECS["W-11"])
check(sc["expected_terminal_states"] == ["cancelled"],
      "W-11 (afvisning) oversaettes til terminal=cancelled")

# --- the effect must be reported as NOT observed, never omitted -----------
obs = to_observation(SPECS["W-08"],
                     {"events": [], "status": "ok",
                      "scratch_before": 100, "scratch_after": 100}, CAND)
eff = {e["id"]: e for e in obs["effects"]}
check("scratch_note" in eff and eff["scratch_note"]["observed"] is False,
      "en udeblevet effekt rapporteres som observed=False, ikke udeladt "
      "(udeladt ville laese som 'ikke paakraevet')")

# --- evidence is bound to the run, so a receipt cannot be replayed --------
o1 = to_observation(SPECS["W-08"], {"events": [], "status": "ok",
                                    "scratch_before": 1, "scratch_after": 2}, CAND)
o2 = to_observation(SPECS["W-08"], {"events": [], "status": "ok",
                                    "scratch_before": 5, "scratch_after": 9}, CAND)
check(o1["effects"][0]["evidence_sha256"] != o2["effects"][0]["evidence_sha256"],
      "to forskellige maalinger giver forskellig evidens -- en kvittering kan "
      "ikke genbruges paa et andet run")

other = {**CAND, "git_sha": "d" * 40}
o3 = to_observation(SPECS["W-08"], {"events": [], "status": "ok",
                                    "scratch_before": 1, "scratch_after": 2}, other)
check(o1["effects"][0]["evidence_sha256"] != o3["effects"][0]["evidence_sha256"],
      "samme maaling paa et ANDET trae giver anden evidens")


# ============================================================================
# Sols fejltilstand 6: genbrugt / scenarie-replayet evidens.
#
# Den var den sidste af hans syv jeg ikke kunne daekke, fordi den kraever hans
# maalekontrakt -- en host kan ikke selv afgoere om en observation er "for
# gammel til at betyde noget". Kontrakten landede i dag med evidence_freshness
# (0 <= age <= max) og tre indholds-digests, saa den kan lukkes nu.
#
# Hvorfor det betyder noget: en completion rate er kun evidens hvis den blev
# maalt paa DENNE koersel. En kvittering man kan genafspille er en kvittering
# man kan samle op fra en groen dag og haefte paa en roed.
# ============================================================================

import time as _t  # noqa: E402

fresh = {"events": [{"type": "tool_executed", "tool": "rig_status"},
                    {"type": "answer", "text": "41 % disk fri, 3 modeller."}],
         "status": "ok"}

obs = to_observation(SPECS["W-01"], fresh, CAND)
r = evaluate_workflow_completion(to_scenario(SPECS["W-01"]), obs)
check(r.get("passed") is True, "en frisk observation bestaar")

# --- genafspillet: samme observation, to timer gammel --------------------
stale = dict(obs)
stale["generated_at"] = _t.time() - 7200          # default-loftet er 3600 s
r = evaluate_workflow_completion(to_scenario(SPECS["W-01"]), stale)
fail_ids = [c["id"] for c in r.get("checks", []) if not c["passed"]]
check(r.get("passed") is False and "evidence_freshness" in fail_ids,
      "FANGER en genafspillet observation (2 timer gammel) -- en kvittering "
      "kan ikke samles op fra en groen dag og haeftes paa en roed")

# --- fremdateret: nogen har skruet paa uret ------------------------------
future = dict(obs)
future["generated_at"] = _t.time() + 3600
r = evaluate_workflow_completion(to_scenario(SPECS["W-01"]), future)
fail_ids = [c["id"] for c in r.get("checks", []) if not c["passed"]]
check(r.get("passed") is False and "evidence_freshness" in fail_ids,
      "fanger en FREMdateret observation -- age < 0 er lige saa forkert")

# --- scenarie-replay: en groen koersel haeftet paa et andet scenarie -----
swapped = dict(obs)
swapped["scenario_id"] = SPECS["W-10"]["id"].lower()
r = evaluate_workflow_completion(to_scenario(SPECS["W-01"]), swapped)
fail_ids = [c["id"] for c in r.get("checks", []) if not c["passed"]]
check(r.get("passed") is False and "scenario_binding" in fail_ids,
      "FANGER en observation der paastaar at vaere fra et andet scenarie")

# --- indholdsbinding: kvitteringen kan ikke flyttes ----------------------
r1 = evaluate_workflow_completion(to_scenario(SPECS["W-01"]), obs)
other = to_observation(SPECS["W-01"], fresh, {**CAND, "git_sha": "e" * 40})
r2 = evaluate_workflow_completion(to_scenario(SPECS["W-01"]), other)
check(r1["observation_sha256"] != r2["observation_sha256"],
      "to observationer fra forskellige traeer har forskellig digest")
check(r1["receipt_sha256"] != r2["receipt_sha256"],
      "kvitteringen er indholdsbundet -- den kan ikke flyttes til et andet run")
check(r1["scenario_sha256"] == r2["scenario_sha256"],
      "samme scenarie giver samme scenarie-digest (sanity: digesterne er "
      "ikke bare tilfaeldige)")

print(f"\n===== WORKFLOW CONTRACT ADAPTER: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
