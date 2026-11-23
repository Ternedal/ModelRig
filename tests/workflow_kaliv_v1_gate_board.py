#!/usr/bin/env python3
"""scripts/kaliv_v1_gate_board.py: gate-by-gate status against a set of pins.

The board must never be a second copy of the gate's rules, never call anything a pass, and
never be mistaken for a qualification (#2264 track D, #2390).

Run: python3 tests/workflow_kaliv_v1_gate_board.py
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "support"))

from scripts import kaliv_system_release_gate as gate  # noqa: E402
from scripts import kaliv_v1_gate_board as tool  # noqa: E402
from source_code import code_of  # noqa: E402

passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {name}")


M, B, V, O = "a" * 40, "b" * 40, "c" * 40, "d" * 40
PINS = {"Ternedal/ModelRig": M, "Ternedal/BodyRig": B, "Ternedal/VisionRig": V, "Ternedal/VoiceRig": O}
GREEN = f"kaliv-software-exact-green:{M}:{B}:{V}:{O}:{'e' * 64}"


def status(result, name):
    return next(row for row in result["gates"] if row["gate"] == name)


# 1. No evidence at all: every v1 gate is MISSING, the three body gates are DEFERRED.
empty = tool.board("v1", PINS, {})
check([row["gate"] for row in empty["gates"]] == list(gate.REQUIRED_GATES), "one row per gate, in the gate's own order")
check(all(status(empty, name)["status"] == "MISSING" for name in gate.V1_GATES), "v1 gates without a ref are MISSING")
check(all(status(empty, name)["status"] == "DEFERRED" for name in gate.BODY_GATES), "body gates are DEFERRED under v1")
check(empty["summary"] == {"REF_BINDS": 0, "STALE": 0, "MISSING": len(gate.V1_GATES)}, "the summary counts v1 gates only")
check(empty["qualifies"] is False, "the board says in its data that it qualifies nothing")
everything = tool.board("embodied", PINS, {})
check(all(row["status"] == "MISSING" for row in everything["gates"]), "under embodied all ten are counted")

# 2. A ref on the pins binds; the same ref after ModelRig moved is STALE, with the gate's reason.
bound = tool.board("v1", PINS, {"software_exact_green": GREEN})
check(status(bound, "software_exact_green")["status"] == "REF_BINDS", "a ref on exactly these pins binds")
check("not checked here" in status(bound, "software_exact_green")["reason"], "REF_BINDS says the artifact is not checked")
for moved in PINS:
    pins = dict(PINS, **{moved: "f" * 40})
    row = status(tool.board("v1", pins, {"software_exact_green": GREEN}), "software_exact_green")
    check(row["status"] == "STALE" and "do not match the pinned" in row["reason"], f"{moved} moved: gate 1's ref is STALE")

# 3. The board has no rules of its own: for every gate, what it says is what the gate does.
for name in gate.V1_GATES:
    for ref in (GREEN, "not-a-ref", f"kaliv-{name.replace('_', '-')}:{M}:{'e' * 64}"):
        manifest = tool._manifest("v1", PINS, name, ref)
        try:
            gate.evaluate_manifest(manifest)
            expected = "REF_BINDS"
        except gate.SystemReleaseManifestError:
            expected = "STALE"
        check(status(tool.board("v1", PINS, {name: ref}), name)["status"] == expected,
              f"{name} / {ref[:24]}: the board repeats the gate's own answer ({expected})")
source = code_of(ROOT / "scripts" / "kaliv_v1_gate_board.py")  # code only: a commented-out line must not satisfy a check
check("re.compile" not in source.split("_SHA = ")[1].split("\n", 1)[1], "no evidence-ref pattern of its own (only the SHA form of a pin)")
check('"PASS"' not in source.replace('{"status": "PASS", "evidence_refs": [ref]}', ""),
      "the board never prints or stores PASS; PASS appears only in the manifest it hands the gate")

# 4. One ref never colours another gate.
mixed = tool.board("v1", PINS, {"software_exact_green": GREEN, "recovery_soak": "junk"})
check(status(mixed, "software_exact_green")["status"] == "REF_BINDS" and status(mixed, "recovery_soak")["status"] == "STALE"
      and status(mixed, "end_to_end_latency")["status"] == "MISSING", "each gate is judged alone")

# 5. Refusals: bad pins, a missing repository, an unknown gate, an unknown scope.
for bad, why in ((dict(PINS, **{"Ternedal/ModelRig": "A" * 40}), "uppercase pin"),
                 (dict(PINS, **{"Ternedal/ModelRig": "abc"}), "short pin"),
                 ({k: v for k, v in PINS.items() if k != "Ternedal/VoiceRig"}, "a repository missing")):
    try:
        tool.board("v1", bad, {})
        check(False, f"refused: {why}")
    except tool.BoardError:
        check(True, f"refused: {why}")
for call, why in ((lambda: tool.board("v1", PINS, {"no_such_gate": GREEN}), "unknown gate"),
                  (lambda: tool.board("v2", PINS, {}), "unknown scope")):
    try:
        call()
        check(False, f"refused: {why}")
    except tool.BoardError:
        check(True, f"refused: {why}")

# 6. Command line: exit 0 with stale and missing gates (it reports), a report only when asked.
ARGS = ["--release-scope", "v1", "--modelrig-sha", "f" * 40, "--bodyrig-sha", B, "--visionrig-sha", V, "--voicerig-sha", O]
out = io.StringIO()
with contextlib.redirect_stdout(out):
    code = tool.main(ARGS + ["--software-exact-green-ref", GREEN])
text = out.getvalue()
check(code == 0, "exit 0 although nothing binds: a board, not a gate")
check("not a qualification" in text and "STALE" in text and "MISSING" in text and "PASS" not in text,
      "the printed board names itself and never says PASS")
with tempfile.TemporaryDirectory() as td:
    report = Path(td) / "board.json"
    with contextlib.redirect_stdout(io.StringIO()):
        tool.main(ARGS + ["--report", str(report)])
    written = json.loads(report.read_text(encoding="utf-8"))
    check(written["schema"] == "kaliv-gate-board/v1" and written["qualifies"] is False and len(written["gates"]) == 10,
          "the report is the same board as JSON")
err = io.StringIO()
with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
    code = tool.main(["--release-scope", "v1", "--modelrig-sha", "nope", "--bodyrig-sha", B, "--visionrig-sha", V, "--voicerig-sha", O])
check(code == 2 and "pin" in err.getvalue(), "a bad pin is a usage error (exit 2), not a board")

# 7. The V1 rig plan tells the operator to look at the board before the rig day.
plan = (ROOT / "docs" / "RIGDAG_V1.md").read_text(encoding="utf-8")
# The runbook's block must be runnable as written (#2485 review, P2): a "<sha>" placeholder is
# not an argument PowerShell accepts, and refs shown as if they were required lead the operator
# to pass dummy ones, which turns MISSING into STALE.
blocks = [block for block in re.findall(r"```powershell\n(.*?)```", plan, flags=re.S) if "kaliv_v1_gate_board.py" in block]
check(len(blocks) == 1, "RIGDAG_V1 has exactly one command block for the board")
block = blocks[0] if blocks else ""
call = block[block.find("python scripts"):]
check("<" not in block and ">" not in block, "no angle-bracket placeholders anywhere in the block")
names = re.findall(r"^\s*\$(\w+Sha)\s*=\s*''\s*$", block, flags=re.M)
check(names == ["modelrigSha", "bodyrigSha", "visionrigSha", "voicerigSha"], "the four pins are variables the operator fills in")
check(all(f"--{flag}-sha ${name}" in call for flag, name in zip(("modelrig", "bodyrig", "visionrig", "voicerig"), names)),
      "each pin variable is what the command passes")
check("throw" in block and "'^[0-9a-f]{40}$'" in block and block.find("throw") < block.find("python scripts"),
      "the block stops before the call when a pin is not a full SHA")
check(re.search(r"^\s*\$refs = @\(\)\s*$", block, flags=re.M) is not None and call.rstrip().endswith("@refs"),
      "refs are an empty list by default and are passed by splatting")
check("-ref" not in "\n".join(line for line in call.splitlines() if not line.lstrip().startswith("#")),
      "the command itself names no evidence-ref argument: none is shown as required")
# ... and the arguments it does pass are ones the tool has, with nothing required left out.
parser_flags = set(re.findall(r"--[a-z][a-z-]+", call))
required = {"--release-scope", "--modelrig-sha", "--bodyrig-sha", "--visionrig-sha", "--voicerig-sha"}
check(parser_flags == required, f"the command passes exactly the required arguments (got {sorted(parser_flags)})")
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    code = tool.main(["--release-scope", "v1", "--modelrig-sha", M, "--bodyrig-sha", B, "--visionrig-sha", V, "--voicerig-sha", O])
check(code == 0, "those arguments alone make a board (every ref is optional)")

print(f"\n===== KALIV V1 GATE BOARD: {passed} passed, {failed} failed =====")
sys.exit(1 if failed else 0)
