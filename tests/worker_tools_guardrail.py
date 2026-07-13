"""Tool-registry guardrail (D3, codified 2026-07-13).

The invariant: **every model-initiated write goes through the confirmation gate.**
Today the only write tool is note_append and it is gated; nothing destructive is
reachable by the model at all. This test makes that a tripwire so it stays true:

  1. The registry is exactly the reviewed set. Adding OR changing a tool fails
     this until someone updates EXPECTED here -- forcing a conscious decision
     about the new tool's risk level (and whether it should be gated) rather
     than a tool silently shipping as risk="read".
  2. No tool carries an unknown risk value (a typo could bypass gating).
  3. Every write tool is actually gated: proposing it returns
     confirmation_required and executes nothing.

If you are here because this test went red: do not just update EXPECTED to make
it pass. First decide whether the new/changed tool is destructive, and if so
that it is risk="write" (gated). A destructive tool must NEVER be risk="read".

Run: PYTHONPATH=worker python3 tests/worker_tools_guardrail.py
"""
from __future__ import annotations

import os
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="kaliv-guardrail-")
os.environ["KALIV_TOOLS_DIR"] = os.path.join(_tmp, "notes")
os.environ["KALIV_AUDIT_DB"] = os.path.join(_tmp, "audit.db")

from app import tools as T  # noqa: E402

# The reviewed registry. name -> risk. Update ONLY after deciding the risk level
# of a new/changed tool (see module docstring).
EXPECTED = {
    "rig_status": "read",
    "note_append": "write",
    "list_models": "read",
    "current_datetime": "read",
}

KNOWN_RISKS = {"read", "write"}

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


def valid_args(tool: T.Tool) -> dict:
    """Minimal args that satisfy a tool's required params (string placeholders),
    so proposing a write tool reaches the gate rather than an arg-validation
    rejection. Generic on purpose: a new string-param tool is handled too."""
    props = (tool.params or {}).get("properties", {})
    required = (tool.params or {}).get("required", [])
    return {name: "guardrail-test" for name in required if props.get(name, {}).get("type") == "string"}


# 1. Registry is exactly the reviewed set (tripwire).
actual = {name: t.risk for name, t in T.REGISTRY.items()}
check(actual == EXPECTED,
      f"registry matches the reviewed set (got {actual})")

# 2. No unknown risk values.
check(all(t.risk in KNOWN_RISKS for t in T.REGISTRY.values()),
      "every tool has a known risk value (read|write)")

# 3. Every write tool is gated: propose -> confirmation_required, nothing runs.
for name, tool in T.REGISTRY.items():
    if tool.risk != "write":
        continue
    g = fresh_gate()
    res = g.propose(name, valid_args(tool))
    check(res.get("status") == "confirmation_required",
          f"write tool {name!r} is gated (propose -> confirmation_required)")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
