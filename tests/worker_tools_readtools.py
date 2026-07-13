"""The read tools added 2026-07-13: list_models + current_datetime.

Read tools carry no confirmation gate, so the bar is: they must (1) be exposed
to the model in the tool schema, (2) run immediately through the gate (no
confirmation_required), and (3) return useful text -- and, being read-only,
never touch or reveal anything they shouldn't. list_models fails soft when
Ollama is absent (as in CI), which is itself the behaviour under test.

Run: PYTHONPATH=worker python3 tests/worker_tools_readtools.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

_tmp = tempfile.mkdtemp(prefix="kaliv-readtools-")
os.environ["KALIV_TOOLS_DIR"] = os.path.join(_tmp, "notes")
os.environ["KALIV_AUDIT_DB"] = os.path.join(_tmp, "audit.db")

from app import tools as T  # noqa: E402

passed = failed = 0


def check(cond, name):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def fresh_gate():
    g = T.ToolGate(audit=T.AuditLog(os.environ["KALIV_AUDIT_DB"]))
    g.enabled = True
    return g


# 1. Both are exposed to the model in the tool schema (schema is registry-driven).
schema_names = {s["function"]["name"] for s in T.ollama_tool_schema(fresh_gate())}
check("list_models" in schema_names, "list_models exposed in the Ollama tool schema")
check("current_datetime" in schema_names, "current_datetime exposed in the Ollama tool schema")

# 2. current_datetime: runs immediately (read, not gated) and returns this year in Danish.
g = fresh_gate()
res = g.propose("current_datetime", {})
check(res.get("status") != "confirmation_required", "current_datetime is NOT gated (runs immediately)")
out = res.get("result", "")
check(str(time.localtime().tm_year) in out, f"current_datetime includes the current year: {out!r}")
check(any(m in out for m in T._MONTHS_DA), f"current_datetime is phrased in Danish: {out!r}")

# 3. list_models: runs immediately and returns text. Ollama is absent in CI, so
#    the soft-fail message is the expected result -- what matters is it's a
#    non-empty string and the turn was not gated or errored.
g = fresh_gate()
res = g.propose("list_models", {})
check(res.get("status") != "confirmation_required", "list_models is NOT gated (runs immediately)")
out = res.get("result", "")
check(isinstance(out, str) and len(out) > 0, f"list_models returns non-empty text: {out[:60]!r}")

# 4. Read tools declare no required params (nothing for the model to inject).
for name in ("list_models", "current_datetime"):
    tool = T.REGISTRY[name]
    check(not (tool.params or {}).get("required"), f"{name} takes no required args")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
