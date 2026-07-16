"""Child entry for isolated tool execution (ISOLATION_DESIGN.md, phase I0).

One process, one tool call, then exit. The parent (toolhost.ProcessExecutor)
writes a request on stdin and reads exactly one JSON result line from stdout:

    in : {"tool": "<name>", "args": {...}}
    out: {"ok": true,  "result": "..."}
         {"ok": false, "kind": "denied"|"error", "error": "..."}

Why a whole process for one call: only a process boundary can be killed on
timeout, cannot take the worker down with it, and can later be started with
reduced rights (restricted token / low integrity / Job Object -- the Windows
layer that phase I0 prepares but cannot prove outside the rig).

A refusal or a tool failure is a normal OUTCOME and exits 0 with ok=false. A
non-zero exit means the child itself broke, and the parent reports that as a
tool error rather than silence.
"""
from __future__ import annotations

import json
import sys


def _emit(payload: dict) -> None:
    # The result is the LAST line on stdout: anything an import prints stays
    # harmless noise the parent skips.
    sys.stdout.write("\n" + json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    try:
        req = json.loads(sys.stdin.read() or "{}")
    except Exception as e:
        _emit({"ok": False, "kind": "error", "error": f"bad request: {e}"})
        return 2

    # Imported here, not at module import: the registry pulls in the whole tool
    # surface, and a malformed request should fail before that cost.
    from .tools import REGISTRY, ToolDenied

    name = req.get("tool")
    args = req.get("args") or {}
    tool = REGISTRY.get(name)
    if tool is None:
        _emit({"ok": False, "kind": "denied", "error": f"unknown tool: {name}"})
        return 0
    try:
        result = tool.run(args)
    except ToolDenied as e:
        _emit({"ok": False, "kind": "denied", "error": str(e)})
        return 0
    except Exception as e:
        _emit({"ok": False, "kind": "error", "error": f"{type(e).__name__}: {e}"})
        return 0
    _emit({"ok": True, "result": result if isinstance(result, str) else str(result)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
