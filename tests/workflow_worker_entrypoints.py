"""Contract test: every worker launcher serves the HARDENED app.

app/entrypoint.py wraps the FastAPI app in the ASGI body-limit and
temp-cleanup guard, and its docstring states the rule plainly: "process
launchers must use this module so parsing and streaming are guarded at the
ASGI boundary". Tests may import app.main directly -- they want route access,
not a socket. A process that binds a port may not.

This exists because the rule was written down and then depended on memory.
1.58.46 moved every launcher onto the guarded app; the Agent 3 branch then
added a NEW launcher that imported app.main and served it raw, and nothing
anywhere noticed -- not CI, not review, not the merge. An experimental worker
would have accepted the chunked upload that never declares a Content-Length,
which is the precise hole 1.58.46 closed.

Run: python3 tests/workflow_worker_entrypoints.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHERS = sorted((ROOT / "worker").glob("run_worker*.py"))

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


check(len(LAUNCHERS) >= 2, f"{len(LAUNCHERS)} worker launchers found: "
                           f"{', '.join(p.name for p in LAUNCHERS)}")

SERVE = re.compile(r"uvicorn\.run\(\s*([A-Za-z_][A-Za-z_0-9]*)")

for path in LAUNCHERS:
    text = path.read_text(encoding="utf-8")
    served = SERVE.findall(text)
    check(bool(served), f"{path.name}: serves something through uvicorn.run")

    # Which name is served, and where did that name come from?
    guarded_names = set()
    for m in re.finditer(r"from app\.entrypoint import app(?: as (\w+))?", text):
        guarded_names.add(m.group(1) or "app")
    for m in re.finditer(r"(\w+)\s*=\s*harden\(", text):
        guarded_names.add(m.group(1))

    for name in served:
        check(name in guarded_names,
              f"{path.name}: uvicorn.run({name}) serves the HARDENED app"
              if name in guarded_names
              else f"{path.name}: uvicorn.run({name}) serves an UNGUARDED app -- "
                   f"guarded names here are {sorted(guarded_names) or 'NONE'}")

# One predicate, not three. Both launchers and the request middleware ask about
# loopback; each used to answer for itself.
import re as _re  # noqa: E402
from pathlib import Path as _P  # noqa: E402

private = []
for py in sorted((ROOT / "worker").rglob("*.py")):
    if py.name == "netguard.py":
        continue
    for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
        if _re.match(r"\s*def _?is_loopback\(", line):
            private.append(f"{py.relative_to(ROOT)}:{i}")
check(not private,
      "loopback is defined in exactly ONE place (app/netguard.py)"
      if not private
      else f"a private loopback copy is back: {', '.join(private)}")

for path in LAUNCHERS:
    t = path.read_text(encoding="utf-8")
    check("enforce_loopback(" in t,
          f"{path.name}: refuses a non-loopback bind through the shared guard")

# Docs are a runtime instruction, not decoration (F-305). main.py's OWN
# docstring said "uvicorn app.main:app --host 0.0.0.0" -- the unguarded app,
# offered to the network, in one copy-pasteable line, in the file the rule is
# about. DEVICE_TEST.md said it too, and that is the page Anders follows with
# the rig in front of him. A launcher test cannot catch a human following a
# document.
RUN_RAW = _re.compile(r"uvicorn\s+app\.main:app")
teaching = []
# Scope was root *.md plus worker/**/*.py -- the places I happened to think of.
# A docs/ page or a .ps1 could teach the unguarded start and this would have
# said PASS, which is the same shape as fixing two files out of three and
# calling it done. Scan the repo.
_SKIP = {".git", "node_modules", "build", ".gradle", "__pycache__", "_sums"}
_SELF = Path(__file__).resolve()
_docs = [p for ext in ("*.md", "*.py", "*.ps1", "*.bat", "*.txt", "*.yml", "*.yaml")
         for p in ROOT.rglob(ext)
         if not any(part in _SKIP for part in p.parts) and p.resolve() != _SELF]
for doc in _docs:
    for i, line in enumerate(doc.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not RUN_RAW.search(line):
            continue
        # Naming it in order to forbid it is the opposite of teaching it.
        if any(w in line for w in ("NOT ", "ikke ", "IKKE ", "UDEN", "without")):
            continue
        teaching.append(f"{doc.relative_to(ROOT)}:{i}")
check(not teaching,
      "no document or docstring teaches the unguarded start command"
      if not teaching
      else f"TEACHES THE UNGUARDED WORKER: {', '.join(teaching)}")

# The detector must be able to fail, or it is decoration.
sample = "from app.main import app\nuvicorn.run(app, host=h)\n"
names = {m.group(1) or "app" for m in re.finditer(r"from app\.entrypoint import app(?: as (\w+))?", sample)}
check(SERVE.findall(sample) == ["app"] and "app" not in names,
      "self-test: a launcher serving app.main IS detected as unguarded")

print(f"\n===== WORKER ENTRYPOINTS: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
