"""Tests for the tool isolation substrate (ISOLATION_DESIGN.md I0).

The point of a process boundary is the guarantees it makes when a tool
misbehaves, so most of these drive ProcessExecutor with an INJECTED child
command: a hang, a flood, a crash and a refusal are all easy to produce that
way and impossible to produce reliably with a real tool. One test does run a
real registry tool through a real child process, which is what proves the
whole path (spawn, registry import, run, JSON back).

Run: PYTHONPATH=worker python3 tests/worker_toolhost.py
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import replace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app import tools as T  # noqa: E402
from app.toolhost import ProcessExecutor, child_env  # noqa: E402

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


class RecordingFallback:
    def __init__(self):
        self.calls = []

    def execute(self, tool, args):
        self.calls.append(tool.name)
        return "in-process"


def py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


# --- 1. dormant by default: a plain tool never leaves the worker -------------
fb = RecordingFallback()
ex = ProcessExecutor(fb, child_cmd=py("raise SystemExit('child must not run')"))
plain = T.REGISTRY["current_datetime"]
check(ex.execute(plain, {}) == "in-process", "isolate=False -> in-process fallback")
check(fb.calls == ["current_datetime"], "fallback actually received the call")

# --- 2. the real path: a registry tool in a real child process ---------------
real = ProcessExecutor(RecordingFallback())
isolated_clock = replace(T.REGISTRY["current_datetime"], isolate=True)
out = real.execute(isolated_clock, {})
check(str(time.gmtime().tm_year) in out,
      f"isolate=True runs in a child and returns the tool's own result ({out[:40]!r})")

# --- 3. a hang is killed at the timeout, not tolerated -----------------------
hang = ProcessExecutor(RecordingFallback(), timeout_s=1,
                       child_cmd=py("import time; time.sleep(30)"))
t0 = time.time()
try:
    hang.execute(replace(plain, isolate=True), {})
    check(False, "a hanging child must raise")
except T.ToolError as e:
    elapsed = time.time() - t0
    check("stoppet" in str(e) and elapsed < 5,
          f"hanging tool killed at the timeout ({elapsed:.1f}s, {str(e)[:44]!r})")

# --- 4. output cap holds regardless of what the tool prints ------------------
flood = ProcessExecutor(
    RecordingFallback(), output_cap=100,
    child_cmd=py('import json,sys; sys.stdout.write(json.dumps({"ok":True,"result":"x"*5000}))'),
)
capped = flood.execute(replace(plain, isolate=True), {})
check(len(capped) < 200 and "afkortet" in capped,
      f"flooding output is capped with a marker ({len(capped)} chars)")

# --- 5. a broken child is an error, never silence ----------------------------
crash = ProcessExecutor(RecordingFallback(),
                        child_cmd=py('import sys; sys.stderr.write("boom"); sys.exit(3)'))
try:
    crash.execute(replace(plain, isolate=True), {})
    check(False, "a crashing child must raise")
except T.ToolError as e:
    check("intet resultat" in str(e) and "boom" in str(e),
          "crashing child -> ToolError carrying the child's stderr")

# --- 6. a refusal stays a refusal across the boundary ------------------------
denier = ProcessExecutor(
    RecordingFallback(),
    child_cmd=py('import json,sys; sys.stdout.write(json.dumps('
                 '{"ok":False,"kind":"denied","error":"nej tak"}))'),
)
try:
    denier.execute(replace(plain, isolate=True), {})
    check(False, "a denied tool must raise")
except T.ToolDenied as e:
    check("nej tak" in str(e), "denial crosses the process boundary as ToolDenied")
except T.ToolError:
    check(False, "denial must not degrade into a generic ToolError")

# --- 7. noisy imports must not break the protocol ----------------------------
noisy = ProcessExecutor(
    RecordingFallback(),
    child_cmd=py('import json,sys; print("warning: some import said hi"); '
                 'sys.stdout.write(json.dumps({"ok":True,"result":"fint"}))'),
)
check(noisy.execute(replace(plain, isolate=True), {}) == "fint",
      "the result is the LAST json line; import noise is skipped")

# --- 8. secret hygiene: an isolated tool inherits no credentials -------------
env = child_env({
    "PATH": "/usr/bin",
    "MODELRIG_DB": "/data/rag.db",
    "KALIV_TOOLS_ENABLED": "1",
    "OLLAMA_API_KEY": "sk-should-not-travel",
    "GITHUB_TOKEN": "ghp_should-not-travel",
    "MY_PASSWORD": "hunter2",
    "RANDOM_UNRELATED": "x",
})
check("MODELRIG_DB" in env and "KALIV_TOOLS_ENABLED" in env and "PATH" in env,
      "child keeps the paths/flags it needs")
check(not any(k in env for k in ("OLLAMA_API_KEY", "GITHUB_TOKEN", "MY_PASSWORD")),
      "child inherits NO credential-shaped variables")
check("RANDOM_UNRELATED" not in env, "child env is an allowlist, not a denylist")

# --- 9. the substrate is dormant in this build ------------------------------
check(all(not t.isolate for t in T.REGISTRY.values()),
      "no tool declares isolate yet -- substrate ships unused, baseline intact")
check(isinstance(T.EXECUTOR, T.InProcessExecutor),
      "default EXECUTOR is in-process unless KALIV_TOOL_ISOLATION says otherwise")

print(f"\n===== WORKER TOOLHOST: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
