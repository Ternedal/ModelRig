#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OBSERVATIONS = ROOT / "scripts" / "stage_a_voice_observations.py"
ORCHESTRATOR = ROOT / "scripts" / "stage-a-voice-test.ps1"
LAUNCHER = ROOT / "START_STAGE_A_VOICE_TEST.cmd"


def load_module():
    spec = importlib.util.spec_from_file_location("stage_a_voice_observations_contract", OBSERVATIONS)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


module = load_module()
passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


check(
    [item["id"] for item in module.TRIALS]
    == ["manual-01", "manual-02", "manual-03", "manual-04", "manual-05"],
    "the guided flow preserves the exact five manual trial IDs",
)
check(
    [item["trigger"] for item in module.TRIALS]
    == [
        "tap stop during first audio chunk",
        "tap stop between audio chunks",
        "begin speaking during first audio chunk",
        "begin speaking between audio chunks",
        "network interruption during playback",
    ],
    "the guided flow preserves the exact versioned trigger matrix",
)
check(module._latency("0", allow_unknown=False) == 0, "zero-millisecond latency is typed and accepted")
check(module._latency("30000", allow_unknown=False) == 30000, "the documented latency ceiling is accepted")
for bad in ("-1", "30001", "175.5", "true"):
    try:
        module._latency(bad, allow_unknown=False)
    except module.ObservationError:
        rejected = True
    else:
        rejected = False
    check(rejected, f"invalid latency fails closed: {bad}")
check(module._latency("U", allow_unknown=True) is None, "an honestly unknown failed-trial latency remains null")

validation = ROOT / "validation"
validation.mkdir(exist_ok=True)
temp = Path(tempfile.mkdtemp(prefix="stage-a-voice-guided-test-", dir=validation))
try:
    candidate = {"version": "1.58.145", "git_sha": "a" * 40}
    store = temp / "phone-store.json"
    store.write_text(json.dumps({"devices": [], "pairings": {}}), encoding="utf-8")
    state_path = temp / "resume.json"
    state = module._load_or_create_state(
        state_path,
        candidate=candidate,
        pairing_store=store,
    )
    check(state["trials"] == [] and state["production_activation"] is False,
          "a fresh resume state starts empty and cannot activate production")
    state["trials"].append({"id": "manual-01"})
    module._write_json_atomic(state_path, state)
    resumed = module._load_or_create_state(
        state_path,
        candidate=candidate,
        pairing_store=store,
    )
    check(len(resumed["trials"]) == 1,
          "answered trials resume instead of being repeated")

    good_trials = []
    for spec in module.TRIALS:
        good_trials.append(
            {
                "id": spec["id"],
                "trigger": spec["trigger"],
                "recognized": True,
                "playback_stopped": True,
                "stale_audio_resumed": False,
                "ui_terminal_state": "idle",
                "stop_latency_ms": 250,
                "notes": "physical operator observation",
            }
        )
    manual_path = temp / "manual.json"
    manual = {
        "schema": module.MANUAL_SCHEMA,
        "candidate": candidate,
        "device": {"model": "Pixel 6a", "os_version": "17", "app_version": "1.58.145"},
        "trials": good_trials,
        "operator": {"method": "guided-stage-a-launcher", "production_activation": False},
    }
    module._write_json_atomic(manual_path, manual)
    voice = module._voice_module()
    summary = voice._manual_summary(voice.load_manual_observations(manual_path))
    check(summary["trials"] == 5 and summary["passed"] is True,
          "guided output passes the authoritative manual voice contract")

    failed_manual = dict(manual)
    failed_manual["trials"] = [dict(item) for item in good_trials]
    failed_manual["trials"][2]["stale_audio_resumed"] = True
    module._write_json_atomic(manual_path, failed_manual)
    summary = voice._manual_summary(voice.load_manual_observations(manual_path))
    check(summary["passed"] is False,
          "a real stale-audio observation remains red")
finally:
    shutil.rmtree(temp, ignore_errors=True)

observation_source = OBSERVATIONS.read_text(encoding="utf-8")
observation_lower = observation_source.lower()
check("_write_json_atomic(resume_path, state)" in observation_source,
      "each completed trial is saved to the resume receipt")
check("input(\"  Tryk Enter her, når Kaliv viser at forbindelsen virker" in observation_source,
      "the helper waits for the operator before accepting phone pairing")
check("new_devices" in observation_source and "paired_device_id" in observation_source,
      "a new pairing is verified in the isolated backend store")
check("app_version != candidate[\"version\"]" in observation_source,
      "a different Android app version blocks exact-head evidence")
check("return 0 if summary[\"passed\"] else 1" in observation_source,
      "failed physical observations cannot produce a green exit")

orchestrator = ORCHESTRATOR.read_text(encoding="utf-8")
order = [
    orchestrator.index("& $phoneScript -PlannerModel $model"),
    orchestrator.index("stage_a_voice_observations.py"),
    orchestrator.index("--validate-only"),
    orchestrator.index("& ollama stop $model"),
    orchestrator.index("-WorkerOnly"),
    orchestrator.index("--cold-start-confirmed"),
]
check(order == sorted(order),
      "phone pairing, observations, fixtures, cold reset and baseline execute in order")
check("Assert-ExpectedWorker" in orchestrator and "recordedWorkerPid" in orchestrator,
      "the cold reset stops only the recorded Stage A worker")
check("finally" in orchestrator and "& $phoneScript -Stop" in orchestrator,
      "backend, worker and firewall cleanup runs after success or failure")
check("--repetitions 2" in orchestrator and "--cancellation-probes 4" in orchestrator,
      "the authoritative 40-run and four-cancellation baseline is retained")
check("--manual-observations $manualPath" in orchestrator and "--require-manual" in orchestrator,
      "the generated matrix remains mandatory for the final voice gate")

launcher = LAUNCHER.read_text(encoding="utf-8")
check("stage-a-voice-test.ps1" in launcher,
      "one Windows launcher owns the complete guided flow")
check("pause" in launcher.lower(),
      "the final verdict remains visible to the operator")

for source_name, source in (
    ("observation helper", observation_lower),
    ("voice orchestrator", orchestrator.lower()),
    ("voice launcher", launcher.lower()),
):
    for forbidden in (
        "git push",
        "git tag",
        "gh release",
        "merge_pull_request",
        "production_activation=true",
    ):
        check(forbidden not in source,
              f"{source_name} has no forbidden action: {forbidden}")

check("device token" not in observation_lower and "token_hash" not in observation_lower,
      "the observation helper never reads or prints a device token")

print(f"Stage A guided voice contracts: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
