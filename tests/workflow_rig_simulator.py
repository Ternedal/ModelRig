#!/usr/bin/env python3
"""The rig simulator's manifest covers the V1 operators, and its judge can fail.

Three things are enforced here, on Linux, for every PR:

1. ``scripts/rig_simulator/operators.json`` is valid, and every script that
   ``docs/KALIV_SYSTEM_RELEASE_QUALIFICATION.md`` names is either run by the
   simulator or listed as pending with an issue. A new qualifier in the
   document with no manifest entry fails here.
2. The judge in ``run_operators.py`` rejects what it must: a wrong exit code,
   a traceback, missing JSON, a journal line with the wrong flags, a missing
   file. A judge that cannot fail proves nothing (HANDOFF §8).
3. The static operators (no stack) run green through the runner on this
   platform, and the Windows workflow runs the runner with ``--require-all``
   so a skipped operator cannot pass quietly there.

The Windows run itself — real backend + worker + mock Ollama, PowerShell 5.1
parse of every operator — is ``.github/workflows/rig-simulator.yml``.

Run: python3 tests/workflow_rig_simulator.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIM = ROOT / "scripts" / "rig_simulator"
MANIFEST = SIM / "operators.json"
WORKFLOW = ROOT / ".github" / "workflows" / "rig-simulator.yml"


sys.dont_write_bytecode = True
sys.path.insert(0, str(SIM))
sys.path.insert(0, str(ROOT / "tests"))
import manifest as manifest_mod  # noqa: E402
import run_operators as runner  # noqa: E402
from support.source_code import code_of  # noqa: E402

passed = failed = 0


def check(ok: bool, label: str) -> None:
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"FAIL: {label}")


def rejects(raw: dict, label: str, tmp: Path) -> None:
    path = tmp / "m.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    try:
        manifest_mod.load_manifest(path, ROOT)
    except manifest_mod.ManifestError:
        check(True, label)
        return
    check(False, f"{label} (accepted)")


# --- 1. the real manifest ---------------------------------------------------
manifest = manifest_mod.load_manifest(MANIFEST, ROOT)
check(len(manifest.operators) >= 5, "manifest runs at least five operators")
doc = (ROOT / manifest_mod.QUALIFICATION_DOC).read_text(encoding="utf-8")
referenced = manifest_mod.referenced_scripts(doc, ROOT)
check("scripts/kaliv_system_release_gate.py" in referenced, "document reference extraction finds the release gate")
gaps = manifest_mod.coverage_gaps(manifest, referenced)
check(not gaps, f"every qualification script is run or pending; gaps: {gaps}")
check(any(op.script == "scripts/kaliv_system_release_gate.py" for op in manifest.operators), "the release gate itself is run, not merely pending")
check(any(op.script == "scripts/kaliv_recovery_soak_collector.py" for op in manifest.operators), "the soak collector (gate 9) is run against the stack")
check(any(op.script == "scripts/kaliv_e2e_latency_voice_driver.py" for op in manifest.operators), "the latency driver (gate 8) is run against the stack")
check(any(op.kind == "powershell" and op.platform == "windows" for op in manifest.operators), "a Windows PowerShell 5.1 operator is in the manifest")
check(all(op.expect.assertions() >= 1 for op in manifest.operators), "every operator asserts something")
check(all(not op.expect.allow_traceback for op in manifest.operators), "no operator is allowed a traceback")
check(all(len(set(op.expect.exit_codes)) <= 2 for op in manifest.operators), "no operator accepts more than two exit codes")

# the manifest validator rejects the shapes that would let a gap hide
base = json.loads(MANIFEST.read_text(encoding="utf-8"))
with tempfile.TemporaryDirectory() as tmpdir:
    tmp = Path(tmpdir)
    bad = json.loads(json.dumps(base)); bad["operators"][1]["script"] = "scripts/does_not_exist.py"
    rejects(bad, "a python operator whose script does not exist is rejected", tmp)
    bad = json.loads(json.dumps(base)); bad["operators"][0]["script"] = "scripts/does_not_exist.ps1"
    rejects(bad, "a powershell operator whose script does not exist is rejected", tmp)
    bad = json.loads(json.dumps(base)); bad["pending"][0]["script"] = "scripts/does_not_exist.py"
    rejects(bad, "a pending script that does not exist is rejected", tmp)
    bad = json.loads(json.dumps(base)); del bad["pending"][0]["issue"]
    rejects(bad, "a pending entry without an issue is rejected", tmp)
    bad = json.loads(json.dumps(base)); bad["operators"][1]["expect"]["exit"] = []
    rejects(bad, "an operator with no allowed exit code is rejected", tmp)
    bad = json.loads(json.dumps(base)); bad["operators"][1]["args"].append("${NOT_A_VARIABLE}")
    rejects(bad, "an unknown placeholder is rejected", tmp)
    bad = json.loads(json.dumps(base)); bad["operators"][1]["why"] = "runs"
    rejects(bad, "an operator without a reason is rejected", tmp)
    bad = json.loads(json.dumps(base)); bad["operators"][1]["expect"]["stdout_contains"] = ["ok", ""]
    rejects(bad, "an empty stdout_contains string is rejected", tmp)
    bad = json.loads(json.dumps(base)); bad["operators"][1]["expect"]["stdout_contains"] = "STOPPED"
    rejects(bad, "stdout_contains must be a list, not a bare string", tmp)
    bad = json.loads(json.dumps(base)); bad["operators"][1]["expect"]["files_absent"] = ["${NOPE}/x"]
    rejects(bad, "an unknown placeholder in an expected path is rejected", tmp)
    bad = json.loads(json.dumps(base)); bad["operators"][1]["expect"]["files_absent"] = [""]
    rejects(bad, "an empty files_absent path is rejected", tmp)
    bad = json.loads(json.dumps(base)); bad["operators"][1]["expect"]["files_exist"] = ["x.json"]; bad["operators"][1]["expect"]["files_absent"] = ["x.json"]
    rejects(bad, "a path in both files_exist and files_absent is rejected", tmp)
    bad = json.loads(json.dumps(base)); bad["pending"].append({"script": base["operators"][1]["script"], "issue": 1, "why": "listed twice on purpose to test the rule"})
    rejects(bad, "a script both run and pending is rejected", tmp)
    bad = json.loads(json.dumps(base)); bad["operators"][0]["platform"] = "any"
    rejects(bad, "a powershell operator without platform windows is rejected", tmp)
    bad = json.loads(json.dumps(base)); bad["schema"] = "kaliv-rig-simulator-manifest/v0"
    rejects(bad, "a foreign schema is rejected", tmp)

# a manifest missing a referenced script shows as a gap
smaller = manifest_mod.Manifest(operators=manifest.operators, pending=tuple(p for p in manifest.pending if p.script != "scripts/freeze_check.py"), path=MANIFEST)
check("scripts/freeze_check.py" in manifest_mod.coverage_gaps(smaller, referenced), "dropping a pending script surfaces as a coverage gap")

# --- 2. the judge can fail ----------------------------------------------------
with tempfile.TemporaryDirectory() as tmpdir:
    tmp = Path(tmpdir)
    journal = tmp / "j.jsonl"
    journal.write_text(json.dumps({"a": True, "b": False}) + "\n", encoding="utf-8")

    def op(**expect) -> manifest_mod.Operator:
        return manifest_mod.Operator(
            id="probe", script="scripts/x.py", kind="python", args=(), why="judge probe operator for the gate",
            expect=manifest_mod.Expect(exit_codes=tuple(expect.pop("exit", (0,))), **expect),
        )

    j = runner.judge
    check(j(op(), exit_code=0, stdout="", stderr="", repo_root=tmp) == [], "clean exit 0 passes")
    check(j(op(), exit_code=1, stdout="", stderr="", repo_root=tmp), "exit outside the allowed set fails")
    check(j(op(), exit_code=None, stdout="", stderr="", repo_root=tmp), "a timeout fails")
    check(j(op(), exit_code=0, stdout="", stderr="Traceback (most recent call last):\n  x", repo_root=tmp), "a traceback on stderr fails even with exit 0")
    check(j(op(), exit_code=0, stdout="Traceback (most recent call last):", stderr="", repo_root=tmp), "a traceback on stdout fails")
    check(j(op(allow_traceback=True), exit_code=0, stdout="", stderr="Traceback (most recent call last):", repo_root=tmp) == [], "allow_traceback is honoured")
    check(j(op(stdout_json={}), exit_code=0, stdout="not json", stderr="", repo_root=tmp), "required JSON missing fails")
    check(j(op(stdout_json={"schema": "s/v1"}), exit_code=0, stdout='{"schema": "s/v2"}', stderr="", repo_root=tmp), "a wrong JSON field fails")
    check(j(op(stdout_json={"a.b": 1}), exit_code=0, stdout='{"a": {"b": 1}}', stderr="", repo_root=tmp) == [], "a dotted path matches a nested field")
    check(j(op(stdout_json={"a.b": 1}), exit_code=0, stdout='{"a": {"b": 2}}', stderr="", repo_root=tmp), "a dotted path mismatch fails")
    check(j(op(stdout_json={"schema": "s/v1"}), exit_code=0, stdout='noise\n{"schema": "s/v1"}\n', stderr="", repo_root=tmp) == [], "JSON on the last line is accepted")
    check(j(op(jsonl_last={"path": "j.jsonl", "fields": {"a": True}}), exit_code=0, stdout="", stderr="", repo_root=tmp) == [], "a journal line with the right flag passes")
    check(j(op(jsonl_last={"path": "j.jsonl", "fields": {"b": True}}), exit_code=0, stdout="", stderr="", repo_root=tmp), "a journal line with the wrong flag fails")
    check(j(op(jsonl_last={"path": "missing.jsonl", "fields": {"a": True}}), exit_code=0, stdout="", stderr="", repo_root=tmp), "a missing journal fails")
    check(j(op(files_exist=("nope.txt",)), exit_code=0, stdout="", stderr="", repo_root=tmp), "a missing expected file fails")
    check(j(op(exit=(2,), stdout_contains=("STOPPED: ", "not ready")), exit_code=2, stdout="STOPPED: the worker is not ready\n", stderr="", repo_root=tmp) == [],
          "every stdout_contains string present passes")
    check(j(op(exit=(2,), stdout_contains=("STOPPED: ", "not ready")), exit_code=2, stdout="STOPPED: already exists\n", stderr="", repo_root=tmp),
          "one missing stdout_contains string fails even with the right exit code")
    check(j(op(exit=(2,), stdout_contains=("STOPPED: ",)), exit_code=2, stdout="", stderr="STOPPED: on stderr", repo_root=tmp),
          "stdout_contains looks at stdout, not stderr")
    check(manifest_mod.Expect(exit_codes=(2,), stdout_contains=("x",)).assertions() == 2, "stdout_contains counts as an assertion")
    check(j(op(files_absent=("nope.txt",)), exit_code=0, stdout="", stderr="", repo_root=tmp) == [], "files_absent passes when the file was not written")
    check(j(op(files_absent=("j.jsonl",)), exit_code=0, stdout="", stderr="", repo_root=tmp), "files_absent fails when the file exists")
    (tmp / "adir").mkdir()
    check(j(op(files_absent=("adir",)), exit_code=0, stdout="", stderr="", repo_root=tmp), "files_absent also fails on a directory at that path")
    check(manifest_mod.Expect(exit_codes=(2,), files_absent=("x",)).assertions() == 2, "files_absent counts as an assertion")
    scratch_dir = tmp / "scratch-run"
    scratch_dir.mkdir()
    resolved = runner.resolved_expectations(
        op(files_absent=("${SCRATCH}/evidence",), files_exist=("${WORK_DIR}/j.jsonl",), jsonl_last={"path": "${WORK_DIR}/j.jsonl", "fields": {"a": True}}),
        {"SCRATCH": str(scratch_dir), "WORK_DIR": str(tmp)},
    )
    check(resolved.expect.files_absent == (str(scratch_dir / "evidence"),) and resolved.expect.files_exist == (str(tmp / "j.jsonl"),)
          and resolved.expect.jsonl_last["path"] == str(tmp / "j.jsonl"),
          "resolved_expectations substitutes placeholders in files_absent, files_exist and jsonl_last.path")
    check(j(resolved, exit_code=0, stdout="", stderr="", repo_root=tmp) == [], "an absolute, substituted path is judged as such (nothing written → passes)")
    (scratch_dir / "evidence").mkdir()
    check(j(resolved, exit_code=0, stdout="", stderr="", repo_root=tmp), "…and fails once the operator wrote the directory it must not write")

    # the runner reports a traceback-raising script as fail even when its exit code is allowed
    boom = tmp / "boom.py"
    boom.write_text("raise RuntimeError('rig simulator probe')\n", encoding="utf-8")
    script_rel = "boom.py"
    probe = manifest_mod.Operator(id="boom", script=script_rel, kind="python", args=(), why="raises on purpose for the gate",
                                  expect=manifest_mod.Expect(exit_codes=(0, 1)))
    result = runner.run_operator(probe, repo_root=tmp, variables={}, env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin"})
    check(result["status"] == "fail" and any("traceback" in f.lower() for f in result["failures"]), "a raising script is a fail, not a pass on exit code")

# the simulated worker is the production entrypoint, in an isolated environment (review on #2409)
check(runner.WORKER_ENTRYPOINT == "app.entrypoint:app", "the simulator starts app.entrypoint:app, the entrypoint deploy/run-windows.ps1 and the Stage A stack launch")
runner_src = code_of(SIM / "run_operators.py")
check('"-m", "uvicorn", WORKER_ENTRYPOINT' in runner_src and "app.main:app" not in runner_src, "the worker command uses the production entrypoint, not the raw app")
import os as _os
_saved = {k: _os.environ.get(k) for k in ("KALIV_AUDIT_DB", "KALIV_TOOLS_STATE", "MODELRIG_DB", "KALIV_DATA_DIR", "PATH")}
try:
    _os.environ["KALIV_AUDIT_DB"] = "/host/real/audit.db"
    _os.environ["KALIV_TOOLS_STATE"] = "/host/real/tools.json"
    _os.environ["MODELRIG_DB"] = "/host/real/worker.db"
    _os.environ["KALIV_DATA_DIR"] = "/host/real/data"
    iso = runner.isolated_environment()
    check(not any(k.startswith(("KALIV_", "MODELRIG_")) for k in iso), "isolated_environment drops every inherited KALIV_*/MODELRIG_* override")
    check("PATH" in iso, "isolated_environment keeps the rest of the host environment")
finally:
    for k, v in _saved.items():
        if v is None:
            _os.environ.pop(k, None)
        else:
            _os.environ[k] = v
stack_src = runner_src.split("class Stack", 1)[1]
check("KALIV_DATA_DIR=str(data_dir)" in stack_src and "isolated_environment()" in stack_src, "the stack pins KALIV_DATA_DIR inside the simulator directory on top of the isolated environment")
check(stack_src.count("isolated_environment()") >= 2, "both the worker and the backend start from the isolated environment")

# placeholders are substituted, unknown ones refuse
check(runner.substitute("--x ${REPO}/y", {"REPO": "/r"}) == "--x /r/y", "placeholders are substituted")
try:
    runner.substitute("${NOPE}", {})
    check(False, "an unknown placeholder refuses")
except KeyError:
    check(True, "an unknown placeholder refuses")

# platform rules
ps = next(op for op in manifest.operators if op.kind == "powershell")
check((runner.applicable(ps, with_stack=True) is None) == runner.IS_WINDOWS, "powershell operators run only on Windows")
static = next(op for op in manifest.operators if not op.needs_stack and op.kind == "python")
check(runner.applicable(static, with_stack=False) is None, "static python operators run without the stack")

# --- 3. static operators through the runner, and the Windows workflow pins -----
with tempfile.TemporaryDirectory() as tmpdir:
    report = Path(tmpdir) / "report.json"
    proc = subprocess.run(
        [sys.executable, "-B", str(SIM / "run_operators.py"), "--no-stack", "--report", str(report)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300,
    )
    check(proc.returncode == 0, f"static operators pass through the runner (exit {proc.returncode}): {proc.stdout[-600:]}")
    if report.is_file():
        data = json.loads(report.read_text(encoding="utf-8"))
        check(data["verdict"] == "PASS" and data["counts"]["fail"] == 0, "static report verdict is PASS")
        check(data["production_activation"] is False, "the report never claims activation")
        skipped_ids = {r["id"] for r in data["operators"] if r["status"] == "skipped"}
        check(all(op.id in skipped_ids for op in manifest.operators if op.needs_stack), "stack operators are reported skipped, not passed, without a stack")

# a failing operator makes the whole run fail: verdict FAIL and exit 1
scratch = ROOT / "validation" / "rig-simulator"
scratch.mkdir(parents=True, exist_ok=True)
boom_script = scratch / "gate-probe-boom.py"
boom_script.write_text("import sys\nprint('{\"ok\": true}')\nsys.exit(3)\n", encoding="utf-8")
with tempfile.TemporaryDirectory() as tmpdir:
    tmp = Path(tmpdir)
    failing = {
        "schema": manifest_mod.SCHEMA,
        "operators": [
            {"id": "gate-probe-boom", "script": "validation/rig-simulator/gate-probe-boom.py", "kind": "python", "needs_stack": False,
             "args": [], "expect": {"exit": [0]}, "why": "exits 3 on purpose so the runner's verdict must be FAIL"},
            {"id": "gate-probe-fine", "script": "validation/rig-simulator/gate-probe-boom.py", "kind": "python", "needs_stack": False,
             "args": [], "expect": {"exit": [3], "stdout_json": {"ok": True}}, "why": "the same script judged by the right expectation passes"},
        ],
        "pending": [],
    }
    fm = tmp / "failing.json"
    fm.write_text(json.dumps(failing), encoding="utf-8")
    report = tmp / "report.json"
    proc = subprocess.run(
        [sys.executable, "-B", str(SIM / "run_operators.py"), "--no-stack", "--manifest", str(fm), "--report", str(report)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=120,
    )
    check(proc.returncode == 1, f"a failing operator exits the runner with 1 (got {proc.returncode})")
    data = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {}
    check(data.get("verdict") == "FAIL", "the report says FAIL when an operator fails")
    statuses = {r["id"]: r["status"] for r in data.get("operators", [])}
    check(statuses.get("gate-probe-boom") == "fail" and statuses.get("gate-probe-fine") == "pass", "each operator is judged on its own expectation")
    proc = subprocess.run(
        [sys.executable, "-B", str(SIM / "run_operators.py"), "--manifest", str(fm), "--require-all", "--only", "gate-probe-fine", "--report", str(report)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=120,
    )
    check(proc.returncode == 0, "--only with a passing operator and no stack-needing operator exits 0")
boom_script.unlink(missing_ok=True)

text = WORKFLOW.read_text(encoding="utf-8") if WORKFLOW.is_file() else ""
check(bool(text), "the Windows workflow exists")
check("runs-on: windows-latest" in text, "the workflow runs on windows-latest")
check("shell: powershell" in text, "the workflow uses Windows PowerShell 5.1 (shell: powershell), not pwsh")
check("--require-all" in text, "the workflow passes --require-all so a skipped operator fails")
check("contents: read" in text and "contents: write" not in text, "the workflow is read-only")
# --- slice 2a: the gate 2 operator runs up to its preflight -----------------
gate2 = [op for op in manifest.operators if op.script == "scripts/consciousness_live_lifecycle_operator.py"]
check(len(gate2) == 1, "the gate 2 operator (#2407) is run against the stack")
if gate2:
    g = gate2[0]
    check(g.needs_stack and g.expect.exit_codes == (2,), "the gate 2 operator needs the stack and may only exit 2 (stopped before the qualifier)")
    check("STOPPED: the worker is not ready for the lifecycle gate" in g.expect.stdout_contains and "flags not set to 1" in g.expect.stdout_contains,
          "the expected refusal is the worker's readiness, named by the operator's own message")
    check(any(a.startswith("${SCRATCH}/") for a in g.args), "the operator's --out lives under ${SCRATCH}, so a rerun does not hit 'already exists'")
    out_arg = g.args[g.args.index("--out") + 1]
    check(g.expect.files_absent == (out_arg,), "a refusal in preflight creates no evidence directory: files_absent pins the exact --out path (review P3 on #2421)")
    fx = [a for a in g.args if a.startswith("scripts/rig_simulator/fixtures/")]
    check(len(fx) == 2 and all((ROOT / f).is_file() for f in fx), "both profile fixtures are tracked files")
    if len(fx) == 2:
        blobs = [(ROOT / f).read_bytes() for f in fx]
        check(blobs[0] != blobs[1] and all(isinstance(json.loads(b), dict) for b in blobs),
              "the fixtures are two different JSON objects, so the refusal cannot come from the 'swap equals profile' check")
# --- slice 2a: the assembler refuses before it writes ------------------------
asm = [op for op in manifest.operators if op.script == "scripts/kaliv_release_manifest_assembler.py"]
check(len(asm) == 2, "the release-manifest assembler (#2408) is run twice: no evidence, and fake evidence")
for a in asm:
    check(not a.needs_stack and a.expect.exit_codes == (2,), f"{a.id}: static, exit 2 only")
    check(a.expect.stdout_json is not None and a.expect.stdout_json.get("state") == "INVALID" and a.expect.stdout_json.get("production_activation") is False,
          f"{a.id}: pins INVALID and production_activation=false in the JSON")
    out = [a.args[i + 1] for i, x in enumerate(a.args) if x == "--manifest"]
    check(len(out) == 1 and out[0].startswith("${WORK_DIR}/") and a.expect.files_absent == (out[0].replace("${WORK_DIR}", "validation/rig-simulator"),),
          f"{a.id}: files_absent names exactly the --manifest path, below the ignored simulator directory")
    check("--release-scope" in a.args and a.args[a.args.index("--release-scope") + 1] == "v1", f"{a.id}: asks for the v1 scope")
ids = {a.id for a in asm}
check("release-assembler-no-evidence-fail-closed" in ids and "release-assembler-fake-evidence-fail-closed" in ids, "both assembler refusals are present")
fake = next((a for a in asm if a.id == "release-assembler-fake-evidence-fail-closed"), None)
if fake:
    refs = [x for x in fake.args if x.endswith("-ref")]
    check(len(refs) == 7 and "rejected by the final release gate" in fake.expect.stdout_contains,
          "the fake-evidence run passes seven refs so the refusal comes from the final gate, not from the count check")

check("SCRATCH" in manifest_mod.VARIABLES, "SCRATCH is a manifest variable")
check('"SCRATCH": str(scratch)' in runner_src and "scratch.mkdir(parents=True, exist_ok=False)" in runner_src,
      "the runner creates SCRATCH empty for every run and refuses to reuse one")
check(any(p["script"] == "scripts/consciousness_live_lifecycle_qualifier.py" and "preflight" in p["why"] for p in json.loads((SIM / "operators.json").read_text(encoding="utf-8"))["pending"]),
      "the pending entry for the gate 2 qualifier says what the simulator already covers and what is still missing")

check("/validation/rig-simulator/" in (ROOT / ".gitignore").read_text(encoding="utf-8"), "simulator output is ignored by git, so a run cannot dirty the candidate checkout")

print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
