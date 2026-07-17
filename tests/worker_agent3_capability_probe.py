"""The rig is measured, not described from memory (F-302).

Agent 3 planned against rig_reachable=True, worker_ready=True and rag_ready=True
-- hardcoded in the request handler -- while cloud_ready arrived in the client's
own request body. A plan is a promise about what will work; a promise built on
unmeasured facts is a guess with a receipt. The worker already measures this for
/health and /capabilities, so the fix was not to invent a probe but to stop
skipping the one that existed.

Run: PYTHONPATH=worker python3 tests/worker_agent3_capability_probe.py
"""
from __future__ import annotations

import os
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="kaliv-probe-")
os.environ.setdefault("KALIV_AUDIT_DB", os.path.join(_tmp, "a.db"))
os.environ.setdefault("KALIV_TOOLS_STATE", os.path.join(_tmp, "s.json"))
os.environ.setdefault("KALIV_JOBS_DB", os.path.join(_tmp, "j.db"))
os.environ.setdefault("KALIV_TOOLS_DIR", _tmp)
os.environ["MODELRIG_OLLAMA_URL"] = "http://127.0.0.1:1"  # nothing listens here
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.agent3 import capability_probe as P  # noqa: E402

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


# --- fail closed ------------------------------------------------------------

P.invalidate()
caps = P.measure(timeout_s=0.5, now=1000.0)

check(caps["rig_reachable"] is False,
      "an unreachable Ollama measures as NOT reachable -- the old code said True")
check(caps["rag_ready"] is False,
      "rag_ready is False without Ollama: a store nobody can embed against cannot answer")
check(caps["worker_ready"] is True,
      "worker_ready is True and now MEANS it -- this code is executing inside the worker")
check(caps["measured_at"] == 1000.0, "the snapshot says when it was taken")

# --- the cache exists so a plan does not ping Ollama per step ---------------

calls = {"n": 0}
real = P._ollama_reachable
P._ollama_reachable = lambda t: (calls.__setitem__("n", calls["n"] + 1), False)[1]
try:
    P.invalidate()
    P.measure(now=2000.0)
    P.measure(now=2000.5)
    P.measure(now=2009.0)
    check(calls["n"] == 1, f"three measurements inside the TTL probe ONCE ({calls['n']})")

    P.measure(now=2000.0 + P.PROBE_TTL_S + 1)
    check(calls["n"] == 2, "past the TTL it probes again -- a cache that outlives the truth is a bug")

    calls["n"] = 0
    P.measure(now=3000.0, use_cache=False)
    check(calls["n"] == 1, "use_cache=False always measures")
finally:
    P._ollama_reachable = real
    P.invalidate()

# --- a reachable rig, and the store's own answer ----------------------------

P._ollama_reachable = lambda t: True
try:
    P.invalidate()
    caps = P.measure(now=4000.0)
    check(caps["rig_reachable"] is True, "a reachable Ollama measures as reachable")
    check(caps["rag_ready"] is False,
          "rag_ready is still False on an EMPTY store -- answering with nothing "
          "indexed is not answering")
finally:
    P._ollama_reachable = real
    P.invalidate()

# --- the probe must never raise into a plan --------------------------------

P._ollama_reachable = lambda t: (_ for _ in ()).throw(RuntimeError("boom"))
try:
    P.invalidate()
    try:
        P.measure(now=5000.0)
        check(False, "a probe that raises would take the plan down with it")
    except RuntimeError:
        check(True, "a raising probe surfaces rather than silently reporting True "
                    "(the caller decides, not a bare except)")
finally:
    P._ollama_reachable = real
    P.invalidate()

print(f"\n===== CAPABILITY PROBE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
