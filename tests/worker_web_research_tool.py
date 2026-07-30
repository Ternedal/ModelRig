#!/usr/bin/env python3
"""D7 trin 1: web_research-vaerktoejet -- kaldestedets kontrakt (30/07-2026).

Fire ting pinnes, og hver af dem er en beslutning, ikke en observation:

  1. GATEN er den eksisterende flade-gate og dens semantik: KUN praecis "1"
     taender. "true" og "on" er slukket, som web_research_mount definerede det.
     Registreringen er fail-closed fra enhver import-sti og naegter at
     overtage et navn en anden komponent har taget.
  2. DEKLARATIONEN er den todelte models foerste rigtige public-vaerktoej:
     risk=read PLUS network=public, og kortet foelger af akserne
     (requires_confirmation), ikke af en loejet write. Descriptoren valideres
     af mains capability_schema -- den `external`-klasse pr-163 bar, findes
     ikke og skal ikke findes.
  3. D4 STRUKTURELT: run() modtager kun url og purpose. En ekstra noegle er
     afvist FOER kompositionen roeres -- der findes ingen kanal RAG-kontekst
     kan rejse i.
  4. D7 nr. 3-oversaettelsen genbruger fetch-modulets tabel: vores nej bliver
     ToolDenied, modpartens fejl ToolError -- ogsaa for en *Denied der arver
     fra OSError (navn foer type; fetch-modulets maalte faelde fra 27/07).

Run: PYTHONPATH=worker python3 tests/worker_web_research_tool.py
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
        check(False, f"{label} -- forkert undtagelse: {type(exc).__name__}")
        return exc
    check(False, f"{label} -- ingen undtagelse")
    return None


# --- Del 1: gaten og dens semantik ------------------------------------------

os.environ.pop("KALIV_WEB_RESEARCH_ENABLED", None)
tools.REGISTRY.pop(TOOL_NAME, None)
check(register_web_research_tool() is False,
      "uden flag registreres intet (fail-closed default)")
check(TOOL_NAME not in tools.REGISTRY, "REGISTRY er uroert uden flag")

os.environ["KALIV_WEB_RESEARCH_ENABLED"] = "true"
check(register_web_research_tool() is False,
      "'true' taender IKKE -- kun praecis '1' (mount-modulets semantik)")

os.environ["KALIV_WEB_RESEARCH_ENABLED"] = "1"
check(register_web_research_tool() is True, "flag '1' registrerer")
check(TOOL_NAME in tools.REGISTRY, "web_research staar i REGISTRY")
check(register_web_research_tool() is True,
      "genregistrering af os selv er idempotent")

_theirs = tools.REGISTRY[TOOL_NAME]
tools.REGISTRY[TOOL_NAME] = tools.Tool(
    name=TOOL_NAME, risk="read", network="none",
    description="fremmed", params={"type": "object", "properties": {}},
    run=lambda a: "",
)
expect(RuntimeError, register_web_research_tool,
       "et fremmed vaerktoej paa navnet overtages ikke")
tools.REGISTRY[TOOL_NAME] = _theirs

# --- Del 2: deklarationen -- den todelte models foerste public-vaerktoej ----

tool = tools.REGISTRY[TOOL_NAME]
check(tool.risk == "read", "risk=read: en hentning skriver intet")
check(tool.network == "public", "network=public: handlingen forlader maskinen")
check(tools.requires_confirmation(tool, "local") is True,
      "kortet foelger af akserne read+public -- ikke af en loejet write")
check(tool.schedulable is False and bool(tool.unschedulable_because),
      "ikke schedulable, med begrundelse (D7 nr. 5: eet ja per kald)")
check(tool.params.get("additionalProperties") is False
      and sorted(tool.params.get("required", [])) == ["purpose", "url"],
      "params: kun url+purpose, lukket skema")

# Arven, ikke en kopi: aendrer nogen kontrakten, skal vaerktoejet foelge med.
# Uden denne pin kan de to udgaver glide fra hinanden uden at noget faelder.
_inherited = {f.name for f in dataclasses.fields(tools.Tool)} - {
    "run", "env_allow"}
_diff = {f for f in _inherited
         if getattr(tool, f) != getattr(WEB_RESEARCH_CAPABILITY, f)}
check(not _diff,
      f"vaerktoejet ARVER kontrakten paa alle felter undtagen run+env_allow "
      f"({_diff or 'ingen afvigelse'})")
check(WEB_RESEARCH_CAPABILITY.run is None,
      "og kontrakten selv bliver dvalende -- registreringen er stadig en "
      "beslutning, ikke en import")
check(tool.isolate is True
      and tool.env_allow == ("KALIV_WEB_RESEARCH_ENABLED",),
      "isoleret, og barnet ser praecis sit eget flag -- ellers ville et "
      "isoleret kald svare 'unknown tool' paa et godkendt vaerktoej")

descriptor = descriptor_from_tool(tool)
check(descriptor.capability_id == "tool:web_research"
      and descriptor.access == "read",
      "descriptor validerer paa main: access=read, ingen 'external'-klasse")
check(descriptor.confirmation.mode == "required",
      "descriptorens confirmation er 'required' for public-network read")

# --- Del 3: D4 strukturelt --------------------------------------------------

class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple, dict]] = []

    def fetch(self, url, *, purpose, max_bytes=None, now=None):
        self.calls.append(((url,), {"purpose": purpose,
                                    "max_bytes": max_bytes, "now": now}))
        return WebResearchResult(
            url=url, status=200, body=b"<html>ok</html>",
            bytes_received=14, binding_id="bind-1",
            selected_address="203.0.113.7",
        )


rec = _Recorder()
out = json.loads(_run_web_research(
    {"url": "https://example.com/side", "purpose": "test"},
    fetcher_factory=lambda: rec,
))
check(rec.calls == [(("https://example.com/side",),
                     {"purpose": "test", "max_bytes": None, "now": None})],
      "fetch modtager PRAECIS url+purpose -- ingen andre kanaler")
check(out["status"] == 200 and out["binding_id"] == "bind-1"
      and out["body_clipped"] is False,
      "svaret baerer status, binding_id og uklippet krop")


def _explode() -> None:
    raise AssertionError("kompositionen maa ikke roeres ved afvist input")


expect(tools.ToolDenied,
       lambda: _run_web_research(
           {"url": "https://example.com", "purpose": "x",
            "rag_context": "smuglet"},
           fetcher_factory=_explode),
       "ekstra noegle afvises FOER kompositionen bygges (D4)")
expect(tools.ToolDenied,
       lambda: _run_web_research({"url": "https://example.com"},
                                 fetcher_factory=_explode),
       "manglende purpose afvises")
expect(tools.ToolDenied,
       lambda: _run_web_research({"url": "   ", "purpose": "x"},
                                 fetcher_factory=_explode),
       "tom url afvises")

# --- Del 4: D7 nr. 3-oversaettelsen -----------------------------------------

class _Thrower:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def fetch(self, url, *, purpose, max_bytes=None, now=None):
        raise self._exc


exc = expect(tools.ToolDenied,
             lambda: _run_web_research(
                 {"url": "https://example.com", "purpose": "x"},
                 fetcher_factory=lambda: _Thrower(
                     WebResearchIntentError("ulovlig url"))),
             "vores nej (intent) bliver ToolDenied")
check(exc is not None and "blocked" in str(exc),
      "ToolDenied baerer 'blocked' fra fetch-modulets tabel")

exc = expect(tools.ToolError,
             lambda: _run_web_research(
                 {"url": "https://example.com", "purpose": "x"},
                 fetcher_factory=lambda: _Thrower(TimeoutError("langsom"))),
             "modpartens timeout bliver ToolError")
check(exc is not None and "failed" in str(exc),
      "ToolError baerer 'failed' fra fetch-modulets tabel")


class FakePeerAdapterDenied(PermissionError):
    """Arver OSError, som den rigtige. Navnet skal vinde over typen."""


exc = expect(tools.ToolDenied,
             lambda: _run_web_research(
                 {"url": "https://example.com", "purpose": "x"},
                 fetcher_factory=lambda: _Thrower(
                     FakePeerAdapterDenied("ssrf"))),
             "*Denied der arver OSError er stadig VORES nej (navn foer type)")

# --- Del 5: krops-loftet ----------------------------------------------------

class _Big:
    def fetch(self, url, *, purpose, max_bytes=None, now=None):
        return WebResearchResult(
            url=url, status=200, body=b"a" * 30_000,
            bytes_received=30_000, binding_id="bind-2",
            selected_address="203.0.113.7",
        )


out = json.loads(_run_web_research(
    {"url": "https://example.com", "purpose": "x"},
    fetcher_factory=lambda: _Big(),
))
check(out["body_clipped"] is True and len(out["body_text"]) == 20_000
      and out["bytes_received"] == 30_000,
      "kroppen klippes for samtalen; bytes_received siger sandheden")

# --- Del 6: det isolerede barn finder vaerktoejet ---------------------------
# isolate=True er ikke gratis: barnet bygger sin EGEN REGISTRY, og et
# gate-registreret vaerktoej findes ikke der medmindre barnet bootstrapper det.
# Uden pinnen ville et isoleret kald svare "unknown tool" paa noget forael deren
# lige har faaet et ja til -- og det ville foerst vise sig den dag nogen saetter
# KALIV_TOOL_ISOLATION=process. Hermetisk: en ugyldig URL afvises af intent'en,
# saa der aabnes ingen forbindelse.
_req = json.dumps({"tool": TOOL_NAME,
                   "args": {"url": "ikke-en-url", "purpose": "x"}})
_child = [sys.executable, "-m", "app.tool_child"]
_env = dict(os.environ, PYTHONPATH=str(ROOT / "worker"),
            KALIV_WEB_RESEARCH_ENABLED="1")
_out = subprocess.run(_child, input=_req, capture_output=True, text=True,
                      env=_env, cwd=str(ROOT)).stdout.strip().splitlines()
_res = json.loads(_out[-1]) if _out else {}
check(_res.get("kind") == "denied" and "unknown tool" not in _res.get("error", ""),
      f"barnet FINDER vaerktoejet og afviser paa vores egen graense ({_res})")

_env.pop("KALIV_WEB_RESEARCH_ENABLED")
_out = subprocess.run(_child, input=_req, capture_output=True, text=True,
                      env=_env, cwd=str(ROOT)).stdout.strip().splitlines()
_res = json.loads(_out[-1]) if _out else {}
check("unknown tool" in _res.get("error", ""),
      f"uden flag er barnet fail-closed -- vaerktoejet findes ikke ({_res})")

# --- Oprydning og dom -------------------------------------------------------

tools.REGISTRY.pop(TOOL_NAME, None)
os.environ.pop("KALIV_WEB_RESEARCH_ENABLED", None)

print(f"\n===== WEB RESEARCH TOOL (D7 trin 1): "
      f"{PASSED} passed, {FAILED} failed =====")
if FAILED:
    raise SystemExit(1)
