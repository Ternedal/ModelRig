#!/usr/bin/env python3
"""The validation stack can start a worker for V1 gates 8 and 3.

The generated worker cmd builds an explicit environment (#753): flags set in
the operator's shell are not the authority. Before this, gate 8
(end_to_end_latency) and gate 3 (visionrig_physical_perception) could only be
enabled by hand-set ``$env:`` lines, and nothing recorded which candidate SHA
the latency receipts were bound to.

These cases read the real script and hold it to the names the worker itself
reads, taken from the worker source, so a renamed flag fails here:

- -EnableE2eLatency writes the latency flag, the HEAD SHA and the evidence root;
- -EnableVisionRigAdmission writes VisionRig's admission flag;
- without -EnableConsciousnessLifecycle both get the live-cycle session flags
  and the profile (docs/consciousness-core/LIVE_CYCLE_QUALIFICATION.md);
- the worker cmd carries all three blocks;
- the latency evidence root is ignored, so the checkout stays clean.

Run: python3 tests/workflow_validation_stack_v1_gates.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "support"))
from source_code import code_of  # noqa: E402

CHECKS = 0
FAILED: list[str] = []


def check(condition: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILED.append(label)
        print(f"FAIL {label}")


def constant(path: str, name: str) -> str:
    for line in (ROOT / path).read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(rf'{name}\s*=\s*"([A-Z0-9_]+)"', line.strip())
        if match:
            return match.group(1)
    raise AssertionError(f"{name} not found in {path}")


STACK = code_of(ROOT / "scripts" / "start-stage-a-validation-stack.ps1")


def block(variable: str) -> str:
    """The guard line and the here-string of ``$<variable> = @" ... "@``."""
    lines = STACK.splitlines()
    head = next((i for i, l in enumerate(lines) if l.strip() == f'${variable} = @"'), None)
    check(head is not None, f"${variable} is assigned from a here-string")
    if head is None:
        return ""
    guard = next((lines[i] for i in range(head, -1, -1) if lines[i].startswith("if (")), "")
    tail = next((i for i in range(head + 1, len(lines)) if lines[i] == '"@'), head)
    return "\n".join([guard, *lines[head + 1:tail]])


def latency_switch_writes_the_worker_names() -> None:
    flag = constant("worker/app/e2e_latency_voice.py", "FLAG")
    sha = constant("worker/app/e2e_latency_voice.py", "SHA_ENV")
    root = constant("worker/app/e2e_latency_voice.py", "ROOT_ENV")
    check("[switch]$EnableE2eLatency" in STACK, "the stack has -EnableE2eLatency")
    body = block("e2eLatencyEnv")
    check(body.startswith("if ($EnableE2eLatency)"), "the latency block is guarded by its switch")
    check(f'set "{flag}=1"' in body, f"{flag}=1 is written")
    check(f'set "{sha}=$candidateSha"' in body, f"{sha} is the candidate SHA")
    check(f'set "{root}=$escapedE2eRoot"' in body, f"{root} is written")
    check("rev-parse HEAD" in STACK and "'^[0-9a-f]{40}$'" in STACK,
          "the SHA is the checkout's HEAD and must be 40 hex")
    check('validation\\e2e-latency' in STACK, "the root is validation\\e2e-latency in the checkout")


def visionrig_switch_writes_the_worker_name() -> None:
    flag = constant("worker/app/consciousness_core/visionrig_admission.py", "CONSCIOUSNESS_VISIONRIG_FLAG")
    check("[switch]$EnableVisionRigAdmission" in STACK, "the stack has -EnableVisionRigAdmission")
    line = re.search(r"^\$visionRigEnv = if \(\$EnableVisionRigAdmission\) \{ '(.*?)' \}", STACK, re.M)
    check(line is not None and line.group(1) == f'set "{flag}=1"', f"{flag}=1 is written")


def live_session_is_the_documented_one() -> None:
    doc = (ROOT / "docs" / "consciousness-core" / "LIVE_CYCLE_QUALIFICATION.md").read_text(encoding="utf-8")
    documented = sorted(set(re.findall(r"^(KALIV_CONSCIOUSNESS_[A-Z_]+_ENABLED)=1$", doc, re.M)))
    check(len(documented) >= 4, "the live-cycle doc lists its flags")
    body = block("liveSessionEnv")
    check("-not $EnableConsciousnessLifecycle" in body.splitlines()[0] if body else False,
          "the live session is only added when gate 2's block is absent")
    for flag in documented:
        check(f'set "{flag}=1"' in body, f"live session sets {flag}")
    profile = "KALIV_CONSCIOUSNESS_PROFILE_FILE"
    check(f'"{profile}"' in (ROOT / "worker/app/consciousness_core/profile_source.py").read_text(encoding="utf-8"),
          f"the worker reads {profile}")
    check(f'set "{profile}=$escapedLiveProfile"' in body, "and the profile file")
    check(STACK.count("Resolve-ConsciousnessProfile") >= 3,
          "gate 2 and the live session resolve the profile the same way")


def worker_cmd_carries_the_blocks() -> None:
    worker_cmd = re.search(
        r'set "KALIV_AGENT3_VALIDATION_REPORT=.*?"@ \| Set-Content -LiteralPath \$workerCmd', STACK, re.S
    )
    text = worker_cmd.group(0) if worker_cmd else ""
    for variable in ("$consciousnessEnv", "$liveSessionEnv", "$e2eLatencyEnv", "$visionRigEnv"):
        check(variable in text, f"the worker cmd carries {variable}")
    backend_cmd = re.search(r'set "MODELRIG_HOST=.*?"@ \| Set-Content -LiteralPath \$backendCmd', STACK, re.S)
    check(backend_cmd is not None and "$e2eLatencyEnv" not in backend_cmd.group(0),
          "the backend cmd does not get the worker's qualification flags")


def write_worker_cmd_only_stops_before_anything_starts() -> None:
    check("[switch]$WriteWorkerCmdOnly" in STACK, "the stack has -WriteWorkerCmdOnly")
    written = STACK.find("Set-Content -LiteralPath $workerCmd")
    dry = STACK.find("if ($WriteWorkerCmdOnly) {")
    first_start = min(i for i in (STACK.find("Wait-PortFree -Port"), STACK.find("Start-WorkerCommand\n"),
                                  STACK.find("& go build")) if i >= 0)
    check(0 <= written < dry < first_start,
          "the dry run returns after the worker cmd is written and before any port wait, build or start")
    stray = STACK.find("$inheritedKaliv = @(Get-ChildItem Env:")
    check(written < stray < dry and "Write-Warning" in STACK[stray:dry],
          "inherited KALIV_* names are computed after the cmd is written and warned about on a real start")
    check('"INHERITED-KALIV: "' in STACK[dry:first_start], "and printed by the dry run")
    manifest = json.loads((ROOT / "scripts" / "rig_simulator" / "operators.json").read_text(encoding="utf-8"))
    simulated = {op["id"] for op in manifest["operators"]}
    check({"stack-worker-cmd-v1-gates-3-8", "stack-worker-cmd-v1-gate2-with-3-8",
           "stack-worker-cmd-gate2-refuses-without-scheduler"} <= simulated,
          "the rig simulator runs the three V1 stack command lines")


def evidence_root_is_ignored() -> None:
    probe = "validation/e2e-latency/run-1/perception_received.json"
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", probe], cwd=ROOT, capture_output=True
    )
    check(result.returncode == 0, f"{probe} is ignored")


def main() -> int:
    for case in (
        latency_switch_writes_the_worker_names,
        visionrig_switch_writes_the_worker_name,
        live_session_is_the_documented_one,
        worker_cmd_carries_the_blocks,
        write_worker_cmd_only_stops_before_anything_starts,
        evidence_root_is_ignored,
    ):
        case()
    if FAILED:
        print(f"{len(FAILED)} of {CHECKS} checks failed")
        return 1
    print(f"OK: {CHECKS} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
