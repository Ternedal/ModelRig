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

# --- 4. the cap holds WHILE the output is produced, not afterwards -----------
# The old version buffered everything and truncated the corpse: a tool printing
# without end filled the worker's memory first (analysis F-202). A child that
# never stops writing must be stopped, and quickly.
endless = ProcessExecutor(
    RecordingFallback(), timeout_s=20, output_cap=50_000,
    child_cmd=py('import sys\nwhile True: sys.stdout.write("x" * 65536)'),
)
t0 = time.time()
try:
    endless.execute(replace(plain, isolate=True), {})
    check(False, "an endlessly printing child must be stopped")
except T.ToolError as e:
    elapsed = time.time() - t0
    check("output-grænsen" in str(e) and elapsed < 15,
          f"a child printing forever is KILLED at the cap, not after ({elapsed:.1f}s)")

# stderr is bounded too -- a tool that only screams into stderr is the same
# memory problem wearing a different hat.
screamer = ProcessExecutor(
    RecordingFallback(), timeout_s=20, stderr_cap=20_000,
    child_cmd=py('import sys\nwhile True: sys.stderr.write("e" * 65536)'),
)
try:
    screamer.execute(replace(plain, isolate=True), {})
    check(False, "an endless stderr must be stopped")
except T.ToolError as e:
    check("output-grænsen" in str(e), "the stderr cap is enforced during the run too")

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

# --- 7b. the tree dies, not just the child ----------------------------------
# proc.kill() reaps only the direct child: a tool that spawned a helper would
# leave it running with the socket still open. POSIX gets a process group; the
# Windows half is a Job Object and is I0b (needs the rig).
import os as _os  # noqa: E402
import subprocess as _sp  # noqa: E402
import tempfile  # noqa: E402

marker = os.path.join(tempfile.mkdtemp(prefix="kaliv-tree-"), "grandchild-alive")
grandchild = (
    "import subprocess,sys,time\n"
    f"subprocess.Popen([sys.executable,'-c',\"import time,os\\nwhile True:\\n open(r'{marker}','a').close()\\n time.sleep(0.05)\"])\n"
    "time.sleep(300)\n"
)
tree = ProcessExecutor(RecordingFallback(), timeout_s=1, child_cmd=py(grandchild))
try:
    tree.execute(replace(plain, isolate=True), {})
except T.ToolError:
    pass
time.sleep(0.4)
try:
    os.remove(marker)
except FileNotFoundError:
    pass
time.sleep(0.6)
check(not os.path.exists(marker),
      "killing a timed-out tool reaps its GRANDCHILDREN too, not just the child")

# --- 8. capability-minimal env: an allowlist, for real this time -------------
# The previous version allowed whole MODELRIG_*/KALIV_* prefixes and removed
# credentials by NAME marker -- a denylist wearing an allowlist's name, and my
# own test asserted the wrong claim (analysis F-203). A tool now names what it
# needs; everything else does not exist in the child.
src = {
    "PATH": "/usr/bin",
    "MODELRIG_DB": "/data/rag.db",
    "KALIV_TOOLS_DIR": "/docs",
    "KALIV_AUDIT_DB": "/data/audit.db",
    "OLLAMA_API_KEY": "sk-should-not-travel",
    "SESSION_ID": "sess-should-not-travel",
    "HTTP_COOKIE": "cookie-should-not-travel",
    "AUTH_HEADER": "bearer-should-not-travel",
    "CLIENT_CERT": "cert-should-not-travel",
}
bare = child_env(None, src)
check(bare == {"PATH": "/usr/bin"},
      "a tool that declares nothing gets NO application environment at all")

declaring = T.Tool(name="x", description="", risk="read", run=lambda a: "",
                   env_allow=("KALIV_TOOLS_DIR",))
env = child_env(declaring, src)
check(env.get("KALIV_TOOLS_DIR") == "/docs", "a tool receives exactly what it declared")
check("KALIV_AUDIT_DB" not in env and "MODELRIG_DB" not in env,
      "an UNDECLARED app variable is absent -- no prefix inheritance")
for leak in ("SESSION_ID", "HTTP_COOKIE", "AUTH_HEADER", "CLIENT_CERT", "OLLAMA_API_KEY"):
    check(leak not in env, f"{leak} cannot ride along (the denylist would have missed it)")

# --- 9. the substrate is dormant in this build ------------------------------
check(all(not t.isolate for t in T.REGISTRY.values()),
      "no tool declares isolate yet -- substrate ships unused, baseline intact")
check(isinstance(T.EXECUTOR, T.InProcessExecutor),
      "default EXECUTOR is in-process unless KALIV_TOOL_ISOLATION says otherwise")

print(f"\n===== WORKER TOOLHOST: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
