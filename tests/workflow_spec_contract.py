#!/usr/bin/env python3
"""The workflow specs must be internally consistent before a rig day starts.

A typo in expect.tools_all means the workflow can never complete -- and nothing
says so until a run on the rig has already cost the time. The same holds for a
duplicate id (results silently overwrite each other), a must_confirm workflow
with a zero confirmation budget (unpassable by construction), and a tool name
that no longer exists in the registry after a rename.

None of that needs Ollama, a worker or hardware. It is a property of two files
in the repo, so it belongs in CI, where it costs nothing.

Run: PYTHONPATH=worker python3 tests/workflow_spec_contract.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="kaliv-wfspec-")
os.environ.setdefault("KALIV_TOOLS_DIR", os.path.join(_tmp, "notes"))
os.environ.setdefault("KALIV_AUDIT_DB", os.path.join(_tmp, "audit.db"))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "worker"))

from app import tools  # noqa: E402

SPEC = ROOT / "eval" / "workflows_v1.json"
TOOL_KEYS = ("tools_all", "tools_any", "must_not_execute")
REQUIRED = ("id", "title", "mode", "prompt", "expect")
MODES = {"read", "write", "rag", "safety"}

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def load(path: Path = SPEC) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["workflows"] if isinstance(data, dict) and "workflows" in data else data


def named_tools(flows: list[dict]) -> set[str]:
    out: set[str] = set()
    for w in flows:
        exp = w.get("expect", {}) or {}
        for k in TOOL_KEYS:
            v = exp.get(k)
            if isinstance(v, (list, tuple)):
                out |= set(v)
    return out


# --- the contract ---------------------------------------------------------

def unknown_tools(flows) -> list[str]:
    return sorted(named_tools(flows) - set(tools.REGISTRY))


def duplicate_ids(flows) -> list[str]:
    seen, dupes = set(), []
    for w in flows:
        i = w.get("id")
        if i in seen:
            dupes.append(i)
        seen.add(i)
    return dupes


def missing_fields(flows) -> list[str]:
    return [w.get("id", "(uden id)") for w in flows
            if not all(k in w for k in REQUIRED)]


def unpassable(flows) -> list[str]:
    """must_confirm with no confirmation budget can never succeed."""
    bad = []
    for w in flows:
        exp = w.get("expect", {}) or {}
        if exp.get("must_confirm") and (w.get("max_confirmations") or 0) < 1:
            bad.append(w.get("id", "?"))
    return bad


def bad_modes(flows) -> list[str]:
    return [w.get("id", "?") for w in flows if w.get("mode") not in MODES]


flows = load()
check(len(flows) > 0, f"specen indeholder workflows ({len(flows)})")
check(not unknown_tools(flows),
      f"hvert vaerktoejsnavn findes i tools.REGISTRY (unknown: {unknown_tools(flows) or 'ingen'})")
check(not duplicate_ids(flows),
      f"alle id'er er unikke (dubletter: {duplicate_ids(flows) or 'ingen'})")
check(not missing_fields(flows),
      f"alle workflows har {', '.join(REQUIRED)} ({missing_fields(flows) or 'ingen mangler'})")
check(not unpassable(flows),
      f"ingen workflow kraever bekraeftelse uden budget til det ({unpassable(flows) or 'ingen'})")
check(not bad_modes(flows),
      f"alle modes er kendte: {sorted(MODES)} ({bad_modes(flows) or 'ingen ukendte'})")

# --- sabotage: each check must be able to go red --------------------------
# The registry is the authority, so a rename there must break the spec here.
# If these pass on broken input, the contract above is decoration.

sab = [dict(w) for w in flows]
sab[0] = dict(sab[0], expect=dict(sab[0].get("expect", {}), tools_all=["rig_statuss"]))
check(unknown_tools(sab) == ["rig_statuss"],
      "et omdoebt/tastefejlet vaerktoejsnavn fanges")

sab2 = [dict(w) for w in flows] + [dict(flows[0])]
check(duplicate_ids(sab2) == [flows[0]["id"]],
      "et gentaget id fanges")

sab3 = [dict(w) for w in flows]
sab3[0] = {k: v for k, v in sab3[0].items() if k != "prompt"}
check(missing_fields(sab3) == [flows[0]["id"]],
      "et manglende paakraevet felt fanges")

sab4 = [dict(w) for w in flows]
sab4[0] = dict(sab4[0], expect=dict(sab4[0].get("expect", {}), must_confirm=True),
               max_confirmations=0)
check(unpassable(sab4) == [flows[0]["id"]],
      "et workflow der ikke kan bestaa ved konstruktion fanges")

sab5 = [dict(w) for w in flows]
sab5[0] = dict(sab5[0], mode="skriv")
check(bad_modes(sab5) == [flows[0]["id"]],
      "en ukendt mode fanges")

print(f"\nworkflow spec contract: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
