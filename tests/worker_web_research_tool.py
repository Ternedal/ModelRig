#!/usr/bin/env python3
"""D7 ToolGate contract after verified-source convergence.

Pins the existing default-off gate, inherited capability metadata, structural D4
argument boundary, D7 error mapping, and the new step-2 rule: model-visible web
content comes from a canonical SourceReceipt, not raw transport bytes.
"""
from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app import tools  # noqa: E402
from app.capability_schema import descriptor_from_tool  # noqa: E402
from app.research_contract import SourceReceipt  # noqa: E402
from app.web_research_capability import WEB_RESEARCH_SPEC as WEB_RESEARCH_CAPABILITY  # noqa: E402
from app.web_research_fetch import WebResearchResult  # noqa: E402
from app.web_research_intent import WebResearchIntentError  # noqa: E402
from app.web_research_tool import (  # noqa: E402
    TOOL_NAME,
    _run_web_research,
    register_web_research_tool,
)

PASSED = 0
FAILED = 0


def check(condition: bool, label: str) -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS: {label}")
    else:
        FAILED += 1
        print(f"  FAIL: {label}")


def expect(kind: type, fn, label: str):
    try:
        fn()
    except kind as exc:
        check(True, f"{label} ({type(exc).__name__})")
        return exc
    except BaseException as exc:  # noqa: BLE001
        check(False, f"{label} -- wrong exception: {type(exc).__name__}")
        return exc
    check(False, f"{label} -- no exception")
    return None


def source(url: str, content: bytes, *, excerpt: str | None = None) -> SourceReceipt:
    return SourceReceipt.from_content(
        url=url,
        title="Verified source",
        content=content,
        excerpt=excerpt if excerpt is not None else content.decode("utf-8", errors="replace")[:2000],
        media_type="text/plain",
        adapter="deterministic-web-fetch",
    )


# --- Gate semantics ---------------------------------------------------------
os.environ.pop("KALIV_WEB_RESEARCH_ENABLED", None)
tools.REGISTRY.pop(TOOL_NAME, None)
check(register_web_research_tool() is False, "default-off registers nothing")
check(TOOL_NAME not in tools.REGISTRY, "registry untouched while off")

os.environ["KALIV_WEB_RESEARCH_ENABLED"] = "true"
check(register_web_research_tool() is False, "only exact 1 opts in")

os.environ["KALIV_WEB_RESEARCH_ENABLED"] = "1"
check(register_web_research_tool() is True, "exact 1 registers web_research")
check(register_web_research_tool() is True, "self-registration is idempotent")

_theirs = tools.REGISTRY[TOOL_NAME]
tools.REGISTRY[TOOL_NAME] = tools.Tool(
    name=TOOL_NAME,
    risk="read",
    network="none",
    description="foreign",
    params={"type": "object", "properties": {}},
    run=lambda a: "",
)
expect(RuntimeError, register_web_research_tool, "foreign owner cannot be replaced")
tools.REGISTRY[TOOL_NAME] = _theirs

# --- Inherited capability contract -----------------------------------------
tool = tools.REGISTRY[TOOL_NAME]
check(tool.risk == "read" and tool.network == "public",
      "capability remains read + public-network")
check(tools.requires_confirmation(tool, "local") is True,
      "public read requires ToolGate confirmation")
check(tool.schedulable is False and bool(tool.unschedulable_because),
      "one approval per call: capability is not schedulable")
check(tool.params.get("additionalProperties") is False
      and sorted(tool.params.get("required", [])) == ["purpose", "url"],
      "schema exposes only url + purpose")

_inherited = {f.name for f in dataclasses.fields(tools.Tool)} - {"run", "env_allow"}
_diff = {f for f in _inherited if getattr(tool, f) != getattr(WEB_RESEARCH_CAPABILITY, f)}
check(not _diff, f"registered tool inherits canonical capability ({_diff or 'no drift'})")
check(WEB_RESEARCH_CAPABILITY.run is None,
      "capability declaration itself stays dormant")
check(tool.isolate is True and tool.env_allow == ("KALIV_WEB_RESEARCH_ENABLED",),
      "isolated child receives only its own activation flag")

descriptor = descriptor_from_tool(tool)
check(descriptor.capability_id == "tool:web_research" and descriptor.access == "read",
      "capability descriptor remains canonical read access")
check(descriptor.confirmation.mode == "required", "descriptor requires confirmation")

# --- D4 arguments + D7 verified source output -------------------------------
class _Recorder:
    def __init__(self, result: WebResearchResult) -> None:
        self.calls: list[tuple[tuple, dict]] = []
        self.result = result

    def fetch(self, url, *, purpose, max_bytes=None, now=None):
        self.calls.append(((url,), {"purpose": purpose, "max_bytes": max_bytes, "now": now}))
        return self.result


URL = "https://example.com/side"
raw = b"This is the exact source body that was verified."
receipt = source(URL, raw)
result = WebResearchResult(
    url=URL,
    status=200,
    body=raw,
    bytes_received=len(raw),
    binding_id="bind-1",
    selected_address="93.184.216.34",
    resolved_addresses=("93.184.216.34", "93.184.216.35"),
    source_receipt=receipt,
)
rec = _Recorder(result)
out = json.loads(_run_web_research(
    {"url": URL, "purpose": "test"}, fetcher_factory=lambda: rec
))
check(rec.calls == [((URL,), {"purpose": "test", "max_bytes": None, "now": None})],
      "fetch receives exactly url + purpose")
check(out["status"] == 200 and out["binding_id"] == "bind-1",
      "output preserves status and peer binding")
check(out["resolved_addresses"] == ["93.184.216.34", "93.184.216.35"],
      "output exposes the validated DNS binding")
check(out["source"]["source_id"] == receipt.source_id
      and out["source"]["content_sha256"] == receipt.content_sha256,
      "output carries canonical source receipt")
check(out["body_text"] == receipt.excerpt,
      "model-visible body_text is the verified receipt excerpt")
check(raw.decode() == out["body_text"], "small verified source is not altered")


def _explode() -> None:
    raise AssertionError("composition must not be touched for rejected input")


expect(tools.ToolDenied,
       lambda: _run_web_research(
           {"url": URL, "purpose": "x", "rag_context": "smuggled"},
           fetcher_factory=_explode),
       "extra argument is rejected before composition")
expect(tools.ToolDenied,
       lambda: _run_web_research({"url": URL}, fetcher_factory=_explode),
       "missing purpose is rejected")
expect(tools.ToolDenied,
       lambda: _run_web_research({"url": "   ", "purpose": "x"}, fetcher_factory=_explode),
       "blank URL is rejected")

# A large verified source exposes only the bounded verified excerpt, not raw bytes.
big_raw = b"a" * 30_000
big_receipt = source("https://example.com/", big_raw, excerpt="a" * 2000)
big_result = WebResearchResult(
    url="https://example.com/",
    status=200,
    body=big_raw,
    bytes_received=len(big_raw),
    binding_id="bind-2",
    selected_address="93.184.216.34",
    resolved_addresses=("93.184.216.34",),
    source_receipt=big_receipt,
)
out = json.loads(_run_web_research(
    {"url": "https://example.com/", "purpose": "x"},
    fetcher_factory=lambda: _Recorder(big_result),
))
check(out["body_clipped"] is True and len(out["body_text"]) == 2000,
      "large source is reduced to contract-bounded verified excerpt")
check(out["bytes_received"] == 30_000, "wire body size remains truthful")

# --- Error mapping ----------------------------------------------------------
class _Thrower:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def fetch(self, url, *, purpose, max_bytes=None, now=None):
        raise self._exc


exc = expect(tools.ToolDenied,
             lambda: _run_web_research(
                 {"url": URL, "purpose": "x"},
                 fetcher_factory=lambda: _Thrower(WebResearchIntentError("bad url"))),
             "our intent denial becomes ToolDenied")
check(exc is not None and "blocked" in str(exc), "ToolDenied preserves blocked class")

exc = expect(tools.ToolError,
             lambda: _run_web_research(
                 {"url": URL, "purpose": "x"},
                 fetcher_factory=lambda: _Thrower(TimeoutError("slow"))),
             "peer timeout becomes ToolError")
check(exc is not None and "failed" in str(exc), "ToolError preserves failed class")

class FakePeerAdapterDenied(PermissionError):
    pass

expect(tools.ToolDenied,
       lambda: _run_web_research(
           {"url": URL, "purpose": "x"},
           fetcher_factory=lambda: _Thrower(FakePeerAdapterDenied("ssrf"))),
       "*Denied stays our denial even when it inherits OSError")

# --- Isolated child gate ----------------------------------------------------
_req = json.dumps({"tool": TOOL_NAME, "args": {"url": "not-a-url", "purpose": "x"}})
_child = [sys.executable, "-m", "app.tool_child"]
_env = dict(os.environ, PYTHONPATH=str(ROOT / "worker"), KALIV_WEB_RESEARCH_ENABLED="1")
_out = subprocess.run(_child, input=_req, capture_output=True, text=True,
                      env=_env, cwd=str(ROOT)).stdout.strip().splitlines()
_res = json.loads(_out[-1]) if _out else {}
check(_res.get("kind") == "denied" and "unknown tool" not in _res.get("error", ""),
      f"isolated child finds gated tool ({_res})")

_env.pop("KALIV_WEB_RESEARCH_ENABLED")
_out = subprocess.run(_child, input=_req, capture_output=True, text=True,
                      env=_env, cwd=str(ROOT)).stdout.strip().splitlines()
_res = json.loads(_out[-1]) if _out else {}
check("unknown tool" in _res.get("error", ""),
      f"without flag isolated child is fail-closed ({_res})")

tools.REGISTRY.pop(TOOL_NAME, None)
os.environ.pop("KALIV_WEB_RESEARCH_ENABLED", None)

print(f"\n===== WEB RESEARCH TOOL (D7 step 2): {PASSED} passed, {FAILED} failed =====")
if FAILED:
    raise SystemExit(1)
