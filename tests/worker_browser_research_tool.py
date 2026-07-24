#!/usr/bin/env python3
from __future__ import annotations

import dataclasses
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "worker"
sys.path.insert(0, str(WORKER))

_tmp = tempfile.TemporaryDirectory(prefix="kaliv-browser-tool-test-")
TMP = Path(_tmp.name)
os.environ["KALIV_AUDIT_DB"] = str(TMP / "global-audit.db")
os.environ["KALIV_TOOLS_STATE"] = str(TMP / "global-state.json")
os.environ["KALIV_JOBS_DB"] = str(TMP / "jobs.db")
os.environ["KALIV_TOOLS_DIR"] = str(TMP / "tools")
os.environ.pop("KALIV_BROWSER_RESEARCH", None)

from app import tools  # noqa: E402
from app.browser_research_tool import (  # noqa: E402
    BrowserResearchConfigurationError,
    FEATURE_ENV,
    MODEL_ENV,
    OLLAMA_ENV,
    PYTHON_ENV,
    TOOL_NAME,
    register_browser_research_tool,
    run_browser_research,
)
from app.capability_schema import CapabilitySchemaError, descriptor_from_tool, parse_descriptor  # noqa: E402

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def rejects(fn, expected, name: str, contains: str = "") -> None:
    try:
        fn()
    except expected as exc:
        check(not contains or contains in str(exc), name)
    else:
        check(False, name)


check(register_browser_research_tool() is False, "feature flag is off by default")
check(TOOL_NAME not in tools.REGISTRY, "default import does not expose browser research")

os.environ[FEATURE_ENV] = "1"
check(register_browser_research_tool() is True, "explicit flag registers browser research")
check(register_browser_research_tool() is True, "registration is idempotent")

tool = tools.REGISTRY[TOOL_NAME]
descriptor = descriptor_from_tool(tool)
check(descriptor.access == "external", "descriptor distinguishes external access from local read")
check(descriptor.impact == "write", "Agent 3 receives conservative confirmation impact")
check(descriptor.confirmation.mode == "required", "external access requires confirmation")
check(descriptor.network.mode == "public", "descriptor declares the public network boundary")
check(descriptor.network.destinations == ["public_web"], "descriptor names only stable public-web destination")
check(descriptor.scheduling.allowed is False, "browser research cannot run unattended")
check(descriptor.replay.idempotent is False, "metered web observation is not replayable")
check(descriptor.production_activation is False, "descriptor cannot activate production")

bad = descriptor.to_dict()
bad["network"] = {"mode": "none", "destinations": []}
rejects(
    lambda: parse_descriptor(bad),
    CapabilitySchemaError,
    "external descriptor without public network fails closed",
    "external access",
)

args = {
    "query": "Hvad står der på den offentlige dokumentationsside?",
    "allowed_domains": ["example.com"],
    "max_sources": 1,
    "timeout_seconds": 30,
}
rejects(
    lambda: run_browser_research(args),
    BrowserResearchConfigurationError,
    "direct runner call has no ToolGate approval binding",
    "fresh ToolGate confirmation",
)

fake_python = TMP / "browser-python.exe"
fake_python.write_bytes(b"not executed: subprocess is injected")
os.environ[PYTHON_ENV] = str(fake_python.resolve())
os.environ[MODEL_ENV] = "qwen3:14b"
os.environ[OLLAMA_ENV] = "http://127.0.0.1:11434"
os.environ["KALIV_BROWSER_DATA_DIR"] = str((TMP / "browser-data").resolve())
os.environ["OPENAI_API_KEY"] = "must-not-leak"
os.environ["ANTHROPIC_API_KEY"] = "must-not-leak"
os.environ["HTTP_PROXY"] = "http://must-not-leak.invalid"
os.environ["HTTPS_PROXY"] = "http://must-not-leak.invalid"
os.environ["COOKIE"] = "must-not-leak"

captured = {}


class FakeCompleted:
    returncode = 0
    stderr = "ignored child diagnostics"
    stdout = json.dumps(
        {
            "ok": True,
            "payload": {
                "research": {
                    "answer": "Det verificerede svar [1]",
                    "sources": [
                        {
                            "title": "Example",
                            "url": "https://example.com/",
                            "content_sha256": "a" * 64,
                        }
                    ],
                }
            },
        },
        separators=(",", ":"),
    ) + "\n"


def fake_run(command, **kwargs):
    captured["command"] = command
    captured.update(kwargs)
    return FakeCompleted()


original_run = sys.modules["app.browser_research_tool"].subprocess.run
sys.modules["app.browser_research_tool"].subprocess.run = fake_run
original_tool = tools.REGISTRY[TOOL_NAME]
try:
    # Keep the real runner in the registry.  The fake exists only at the external
    # process seam so ToolGate/context binding is exercised end to end.
    tools.REGISTRY[TOOL_NAME] = dataclasses.replace(original_tool, run=run_browser_research)
    gate = tools.ToolGate(
        audit=tools.AuditLog(str(TMP / "gate-audit.db")),
        state_file=None,
    )
    gate.enabled = True
    proposed = gate.propose(TOOL_NAME, args, conversation_id="browser-contract")
    check(proposed["status"] == "confirmation_required", "external tool stops for a card")
    check(proposed["risk"] == "external", "card names the external access class honestly")
    check("example.com" in proposed["summary"], "card shows the exact domain scope")
    check(args["query"] in proposed["summary"], "card shows the exact outbound query")
    confirmed = gate.confirm(proposed["confirmation_id"], "approve")
    check(confirmed["status"] == "executed", "fresh approval enters the runner")
    wrapped = confirmed["result"]
    check("Det verificerede svar [1]" in wrapped, "verified answer returns as untrusted tool data")
    check("sha256:aaaaaaaaaaaa" in wrapped, "source digest is surfaced in bounded form")
finally:
    tools.REGISTRY[TOOL_NAME] = original_tool
    sys.modules["app.browser_research_tool"].subprocess.run = original_run

child_env = captured.get("env", {})
check(captured.get("command", [None, None])[1:2] == ["-I"], "browser runtime starts in isolated Python mode")
check(child_env.get(MODEL_ENV) == "qwen3:14b", "only the explicit local model enters the child")
check(child_env.get(OLLAMA_ENV) == "http://127.0.0.1:11434", "child model endpoint remains loopback")
for forbidden in (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "COOKIE",
):
    check(forbidden not in child_env, f"child environment excludes {forbidden}")
check("approval_binding" in json.loads(captured["input"]), "child receives a hash-bound approval proof")
check(proposed["confirmation_id"] not in captured["input"], "raw ToolGate confirmation id never enters child")

rejects(
    lambda: tool.human_summary({"query": "x", "allowed_domains": ["localhost"]}),
    BrowserResearchConfigurationError,
    "local/internal domains are rejected before a card",
)
rejects(
    lambda: tool.human_summary({"query": "x", "allowed_domains": ["https://example.com/path"]}),
    BrowserResearchConfigurationError,
    "domain scope cannot smuggle a URL path",
)

print(f"\nBrowser research tool contracts: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
