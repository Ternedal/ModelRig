"""Contract test: Agent 3 must stay DORMANT when it merges (gate 3).

AGENT3_ANALYSE.md recommended merging PR #1 as one dormant unit after three
gates. Gate 2 (line review of the 7 wiring files) passed by inspection -- but
inspection proves today, not tomorrow. This is gate 3: the dormancy claims
become CI-enforced, and they land on main BEFORE the merge, so the merge is
gated by them automatically instead of by memory.

The four invariants, in the branch's own terms (verified against PR #1's
actual wiring diff, not guessed):
  1. normal chat routing never mentions agent3 -- an ordinary turn cannot
     reach the experimental substrate
  2. every backend agent3 route mounts INSIDE the KALIV_AGENT3_ENABLED guard
  3. the worker imports agent3 lazily -- unset flag creates no databases and
     no routes
  4. production_activation is never true anywhere

On main today there is no agent3 code at all, so every repo check passes
trivially. That is exactly why each detector is also driven against synthetic
VIOLATING samples below: a test that can only pass is not a test.

Run: python3 tests/workflow_agent3_dormant.py
"""
from __future__ import annotations

from pathlib import Path

FLAG = "KALIV_AGENT3_ENABLED"
ROUTE_MARK = "/api/v1/experimental/agent3"

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


# --- detectors (pure, so they can be driven with synthetic samples) ----------

def routing_is_agent3_free(text: str) -> bool:
    """Normal turn routing must not reference the experimental substrate."""
    return "agent3" not in text.lower()


def go_routes_are_flag_gated(text: str) -> bool:
    """Every agent3 mount must sit inside the `if os.Getenv(FLAG) == "1" {` block."""
    if ROUTE_MARK not in text:
        return True  # nothing mounted -> nothing to gate
    lines = text.splitlines()
    guard = next((i for i, l in enumerate(lines)
                  if "os.Getenv(" in l and FLAG in l and "{" in l), None)
    if guard is None:
        return False  # routes exist without any flag guard at all
    depth, end = 0, len(lines)
    for i in range(guard, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if depth == 0 and i > guard:
            end = i
            break
    return all(guard < i <= end
               for i, l in enumerate(lines) if ROUTE_MARK in l and ".Handle" in l)


def worker_import_is_lazy(text: str) -> bool:
    """No module-level agent3 import: an unset flag must create nothing."""
    for line in text.splitlines():
        if line[:1] in (" ", "\t"):
            continue  # indented -> inside a function/branch, which is the point
        if line.startswith(("import ", "from ")) and "agent3" in line.lower():
            return False
    return True


def production_activation_is_off(text: str) -> bool:
    for line in text.splitlines():
        low = line.lower()
        if "production_activation" in low and "=" in low:
            value = low.split("=", 1)[1].strip().strip(",;)")
            if value.startswith(("true", "1", "yes")):
                return False
    return True


# --- 1. the detectors actually catch violations -----------------------------

print("detector self-tests (synthetic samples):")

check(not routing_is_agent3_free('val r = if (agent3Enabled) Agent3Route else Normal'),
      "routing detector fires on an agent3 reference")
check(routing_is_agent3_free('val plan = TurnRouter.plan(input)'),
      "routing detector accepts clean routing")

gated = '''
	if os.Getenv("KALIV_AGENT3_ENABLED") == "1" {
		s.mux.Handle("GET /api/v1/experimental/agent3/status", s.authMW(h))
	}
'''
ungated = '''
	if os.Getenv("KALIV_AGENT3_ENABLED") == "1" {
		log.Printf("agent3 on")
	}
	s.mux.Handle("GET /api/v1/experimental/agent3/status", s.authMW(h))
'''
noguard = '\ts.mux.Handle("GET /api/v1/experimental/agent3/runs", s.authMW(h))\n'
check(go_routes_are_flag_gated(gated), "go detector accepts a mount inside the guard")
check(not go_routes_are_flag_gated(ungated), "go detector fires on a mount OUTSIDE the guard")
check(not go_routes_are_flag_gated(noguard), "go detector fires when no guard exists at all")

check(not worker_import_is_lazy("from app.agent3.runner import Runner\n"),
      "worker detector fires on a top-level agent3 import")
check(worker_import_is_lazy(
    'def _mount():\n    if os.getenv("KALIV_AGENT3_ENABLED", "0") != "1":\n        return\n'
    '    from app.agent3.runner import Runner\n'),
    "worker detector accepts an import inside the flag branch")

check(not production_activation_is_off("production_activation = True"),
      "activation detector fires on a true value")
check(production_activation_is_off('production_activation = False  # never automatic'),
      "activation detector accepts false")

# --- 2. the real repo honours the invariants --------------------------------

print("\nrepo invariants:")

root = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    p = root / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


for rel in ("android/app/src/main/java/dk/ternedal/modelrig/ui/AppUi.kt",
            "android/app/src/main/java/dk/ternedal/modelrig/logic/TurnRouter.kt"):
    check(routing_is_agent3_free(read(rel)), f"normal routing is agent3-free: {rel.split('/')[-1]}")

check(go_routes_are_flag_gated(read("backend/internal/httpapi/server.go")),
      f"every backend agent3 route sits inside the {FLAG} guard")
check(worker_import_is_lazy(read("worker/run_worker.py")),
      "worker mounts agent3 lazily (unset flag creates nothing)")

for rel in ("worker/run_worker.py", "backend/internal/httpapi/server.go",
            "worker/app/main.py"):
    check(production_activation_is_off(read(rel)),
          f"production_activation is never true: {rel.split('/')[-1]}")

print(f"\n===== AGENT3 DORMANCY: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
