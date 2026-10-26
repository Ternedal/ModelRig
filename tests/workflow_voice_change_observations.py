#!/usr/bin/env python3
"""Contract for the guided voice change-impact trials (v2.0.16-2.0.18 + D5).

The physical trials run on the rig with a Pixel. This test pins what can be
pinned without hardware: the trial set, that a result is derived from the
operator's literal answer and never assumed, that a trial not run makes the
whole result INCOMPLETE rather than PASS, that a tampered report is rejected,
and that the Stage A launcher runs the trials before the baseline and never
turns an incomplete result green.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts" / "voice_change_observations.py"
ORCHESTRATOR = ROOT / "scripts" / "stage-a-voice-test.ps1"
LAUNCHER = ROOT / "START_STAGE_A_VOICE_TEST.cmd"

spec = importlib.util.spec_from_file_location("voice_change_observations_contract", MODULE)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def raises(fn) -> bool:
    try:
        fn()
    except m.ChangeObservationError:
        return True
    return False


specs = {s["id"]: s for s in m.TRIALS}
check(list(specs) == ["change-01", "change-02", "change-03", "change-04"],
      "the four change trials keep their exact IDs and order")
check(specs["change-02"]["expected"] is False and specs["change-02"].get("cloud") is True,
      "the cloud trial passes only when Kaliv does NOT know the earlier turn")
check(all(specs[i]["expected"] is True for i in ("change-01", "change-03", "change-04")),
      "context, persistence and terminal trials pass only on an observed yes")

# Results come from the literal answer, compared with what the change promises.
check(m.trial_record(specs["change-01"], ran=True, observed=True, word="x")["result"] == "pass",
      "local context: recalled word passes")
check(m.trial_record(specs["change-01"], ran=True, observed=False, word="x")["result"] == "fail",
      "local context: forgotten word fails")
check(m.trial_record(specs["change-02"], ran=True, observed=True, word="y")["result"] == "fail",
      "cloud: a recalled earlier turn is a privacy failure")
check(m.trial_record(specs["change-02"], ran=True, observed=False, word="y")["result"] == "pass",
      "cloud: not knowing the earlier turn passes")
check(raises(lambda: m.trial_record(specs["change-03"], ran=True, observed=None)),
      "a run trial without an answer is refused, not assumed")
check(raises(lambda: m.trial_record(specs["change-02"], ran=False, observed=None)),
      "a trial not run requires a stated reason")
check(raises(lambda: m.trial_record(specs["change-02"], ran=False, observed=True, reason="r")),
      "a trial not run cannot carry an answer")

draws = [m.pick_words(2) for _ in range(50)]
check(all(len(set(w)) == 2 and set(w) <= set(m.WORDS) for w in draws),
      "test words are two distinct words from the fixed list")


def full(results: dict[str, bool | None]) -> list[dict]:
    out = []
    word_iter = iter(["agurk", "zebra"])
    for s in m.TRIALS:
        word = next(word_iter) if s.get("needs_word") else None
        observed = results[s["id"]]
        if observed is None:
            out.append(m.trial_record(s, ran=False, observed=None, word=word, reason="ingen nøgle"))
        else:
            out.append(m.trial_record(s, ran=True, observed=observed, word=word))
    return out


all_pass = {"change-01": True, "change-02": False, "change-03": True, "change-04": True}
check(m.summarize(full(all_pass))["status"] == "PASS", "every trial as promised -> PASS")
check(m.summarize(full({**all_pass, "change-02": None}))["status"] == "INCOMPLETE",
      "cloud not run -> INCOMPLETE, never PASS")
check(m.summarize(full({**all_pass, "change-02": None, "change-03": False}))["status"] == "FAIL",
      "a failure outranks an incomplete trial")
check(m.summarize(full(all_pass)[:3])["status"] == "INVALID", "missing trials are INVALID")
check(m.exit_code({"status": "PASS"}) == 0 and m.exit_code({"status": "INCOMPLETE"}) == 3
      and m.exit_code({"status": "FAIL"}) == 1 and m.exit_code({"status": "INVALID"}) == 1,
      "exit codes: 0 PASS, 3 INCOMPLETE, 1 otherwise")

candidate = {"version": "2.0.18", "git_sha": "a" * 40}
report = {"schema": m.SCHEMA, "candidate": candidate, "trials": full(all_pass),
          "production_activation": False}
check(m.validate(report, candidate)["status"] == "PASS", "a consistent report validates")
tampered = json.loads(json.dumps(report))
tampered["trials"][1]["result"] = "pass"
tampered["trials"][1]["observed"] = True
check(raises(lambda: m.validate(tampered, candidate)),
      "a report whose result contradicts its answer is rejected")
other = json.loads(json.dumps(report))
check(raises(lambda: m.validate(other, {"version": "2.0.18", "git_sha": "b" * 40})),
      "a report bound to another candidate is rejected")
active = json.loads(json.dumps(report))
active["production_activation"] = True
check(raises(lambda: m.validate(active, candidate)), "production_activation must stay false")
reused = json.loads(json.dumps(report))
reused["trials"][1]["word"] = reused["trials"][0]["word"]
check(raises(lambda: m.validate(reused, candidate)),
      "the cloud trial cannot reuse the local trial's word")

# Resume: answered trials are kept for the same candidate, archived for another.
base = m._base()
validation = ROOT / "validation"
validation.mkdir(exist_ok=True)
temp = Path(tempfile.mkdtemp(prefix="voice-change-test-", dir=validation))
try:
    state_path = temp / "resume.json"
    state = m._load_state(base, state_path, candidate)
    check(state["trials"] == [] and len(state["words"]) == 2 and state["production_activation"] is False,
          "a fresh resume state starts empty with two words and no activation")
    state["trials"].append(full(all_pass)[0])
    base._write_json_atomic(state_path, state)
    again = m._load_state(base, state_path, candidate)
    check(len(again["trials"]) == 1 and again["words"] == state["words"],
          "answered trials and their words survive a resume")
    fresh = m._load_state(base, state_path, {"version": "2.0.19", "git_sha": "c" * 40})
    check(fresh["trials"] == [], "a different candidate starts over instead of reusing answers")
finally:
    shutil.rmtree(temp, ignore_errors=True)
    archive = validation / "archive"
    if archive.is_dir():
        for leftover in archive.glob("stage-a-voice-observations-*.json"):
            if "voice-change" in leftover.read_text(encoding="utf-8", errors="ignore"):
                leftover.unlink()

orchestrator = code_of(ORCHESTRATOR)
order = [
    orchestrator.index("stage_a_voice_observations.py"),
    orchestrator.index("voice_change_observations.py"),
    orchestrator.index("--validate-only"),
    orchestrator.index("--cold-start-confirmed"),
]
check(order == sorted(order),
      "change trials run after the five interruption trials and before the baseline")
check("$LASTEXITCODE -eq 3" in orchestrator and "changeIncomplete" in orchestrator,
      "an incomplete change result is carried to the end, not dropped")
check("exit 3" in orchestrator, "the launcher exits non-zero when change trials are incomplete")
launcher = code_of(LAUNCHER)
check('"%EXIT_CODE%"=="3"' in launcher and "UFULDSTAENDIGE" in launcher,
      "the Windows launcher names an incomplete result instead of calling it green")

source = code_of(MODULE).lower()
for forbidden in ("git push", "git tag", "gh release", "production_activation=true", "token_hash"):
    check(forbidden not in source, f"no forbidden action in the collector: {forbidden}")

print(f"Voice change observation contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
