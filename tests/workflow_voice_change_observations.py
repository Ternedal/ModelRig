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

# ChatGPT review on #2279 (5652695748): integrity of a stored report.
wordless = json.loads(json.dumps(report))
for t in wordless["trials"]:
    t.pop("word", None)
check(raises(lambda: m.validate(wordless, candidate)),
      "recall trials without their test word are rejected, not PASS")
for trial_index in (0, 1):
    missing = json.loads(json.dumps(report))
    del missing["trials"][trial_index]["word"]
    check(raises(lambda: m.validate(missing, candidate)),
          f"{missing['trials'][trial_index]['id']} without a word is rejected")
foreign = json.loads(json.dumps(report))
foreign["trials"][0]["word"] = "kodeord"
check(raises(lambda: m.validate(foreign, candidate)), "a word outside the fixed list is rejected")
spurious = json.loads(json.dumps(report))
spurious["trials"][2]["word"] = "giraf"
check(raises(lambda: m.validate(spurious, candidate)),
      "a trial that asks about no word cannot carry one")
incomplete = {**json.loads(json.dumps(report)), "trials": full({**all_pass, "change-02": None})}
forged = {**incomplete, "summary": {**m.summarize(incomplete["trials"]), "status": "PASS"}}
check(raises(lambda: m.validate(forged, candidate)),
      "a stored PASS summary over an INCOMPLETE report is rejected")
honest = {**incomplete, "summary": m.summarize(incomplete["trials"])}
check(m.validate(honest, candidate)["status"] == "INCOMPLETE",
      "a stored summary that matches the trials is accepted")
check(m.validate(incomplete, candidate)["status"] == "INCOMPLETE",
      "a report without a stored summary is still read")

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

# Codex review on #2279: a failed cloud exchange must not count as non-recall,
# and a skipped trial must be offered again on resume.
check([q[1] for q in specs["change-02"]["preconditions"]] ==
      ["ingen Ollama Cloud-nøgle på telefonen",
       "cloud svarede ikke på begge ture; privatlivsegenskaben blev ikke observeret"],
      "the cloud trial requires a key and a real cloud answer to both turns")
check(m.retry_indices(full({**all_pass, "change-02": None})) == [1],
      "a not_run trial is identified for retry on resume")


class _Script:
    """Replays the operator's J/N answers and records every question asked."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.asked = []

    def __call__(self, message):
        self.asked.append(message.strip())
        return self.answers.pop(0)


import builtins  # noqa: E402

saved = {k: getattr(base, k) for k in ("_candidate", "_phone_state", "_device_metadata", "_yes_no")}
saved_input, saved_base = builtins.input, m._base
temp = Path(tempfile.mkdtemp(prefix="voice-change-collect-", dir=validation))
try:
    base._candidate = lambda: candidate
    base._phone_state = lambda path, cand: {}
    base._device_metadata = lambda cand: {"model": "Pixel 6a", "os_version": "17", "app_version": "2.0.18"}
    builtins.input = lambda message="": ""
    m._base = lambda: base

    def run(answers):
        script = _Script(answers)
        base._yes_no = script
        args = type("Args", (), {})()
        rel = temp.relative_to(ROOT)
        args.phone_state = rel / "phone.json"
        args.manual = rel / "manual.json"
        args.resume = rel / "resume.json"
        args.output = rel / "out.json"
        code = m.collect(args)
        return code, json.loads((temp / "out.json").read_text(encoding="utf-8")), script.asked

    # change-01 J, key J, cloud answered N (bad key / failed request), 03 J, 04 J.
    code, report, _ = run([True, True, False, True, True])
    check(code == 3 and report["trials"][1]["result"] == "not_run",
          "a configured key without a real cloud answer is not_run, not a privacy PASS")
    # Resume after fixing the key: retry J, key J, answered J, recalled N -> PASS.
    code, report, asked = run([True, True, True, False])
    check(code == 0 and report["summary"]["status"] == "PASS",
          "the skipped cloud trial is offered again on resume and can complete the evidence")
    check(len(asked) == 4 and "change-02" in asked[0],
          "answered trials are not repeated when the skipped one is retried")
finally:
    for k, v in saved.items():
        setattr(base, k, v)
    builtins.input, m._base = saved_input, saved_base
    shutil.rmtree(temp, ignore_errors=True)

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
