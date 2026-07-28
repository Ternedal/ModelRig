#!/usr/bin/env python3
"""Livscyklussen lukkes paa ALLE stier (T-034, D7).

Hvert trin kan fejle, og i hver af de stier skal boundary.complete() stadig
kaldes med det rigtige udfald. En halvt skrevet livscyklus er vaerre end ingen:
den ser komplet ud og efterlader en lease der aldrig blev afsluttet.

Testene bruger attrapper, saa hver fejlsti kan proeves uden at aabne en socket.
Det rigtige bevis mod det aabne internet hoerer til en rig-dag -- repoets egen
offentlige validering er med vilje holdt ude af CI.

Run: PYTHONPATH=worker python3 tests/worker_web_research_fetch.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="kaliv-wrf-")
os.environ.setdefault("KALIV_TOOLS_DIR", os.path.join(_tmp, "notes"))
os.environ.setdefault("KALIV_AUDIT_DB", os.path.join(_tmp, "audit.db"))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "worker"))

from app.browser_peer_adapter import BrowserPeerAdapterDenied  # noqa: E402
from app.browser_peer_fulfillment import BrowserPinnedTransportError  # noqa: E402
from app.web_research_fetch import (  # noqa: E402
    WebResearchFetcher,
    _outcome_for,
)
from app.web_research_intent import WebResearchIntentError  # noqa: E402

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


# --- attrapper -----------------------------------------------------------
@dataclass
class FakeResponse:
    status: int = 200
    body: bytes = b"<html>ok</html>"
    bytes_sent: int = 128


class FakeBinding:
    binding_id = "rpt_probe"
    selected_address = "93.184.216.34"


class Recorder:
    """Faelles journal, saa testene kan se HVAD der blev afsluttet med."""

    def __init__(self) -> None:
        self.completed: list[dict] = []
        self.released = 0


class FakeBoundary:
    def __init__(self, rec: Recorder, fail_at: str | None = None,
                 error: BaseException | None = None) -> None:
        self.rec, self.fail_at, self.error = rec, fail_at, error

    def prepare(self, intent, *, now=None, receipt_ttl_seconds=120):
        return "lease-1"

    def claim(self, lease, intent, *, now=None):
        if self.fail_at == "claim":
            raise self.error
        return "evidence-1"

    def complete(self, lease, intent, *, outcome, bytes_sent, error_code, now=None):
        self.rec.completed.append(
            {"outcome": outcome, "bytes_sent": bytes_sent, "error_code": error_code}
        )


class FakeBridge:
    def __init__(self, fail: BaseException | None = None) -> None:
        self.fail = fail

    def prepare(self, evidence, lease, intent, url, *, now=None):
        if self.fail:
            raise self.fail
        return "auth-1"


class FakePeer:
    def __init__(self, fail: BaseException | None = None) -> None:
        self.fail = fail

    def issue(self, auth, evidence, lease, intent, url, *, now=None, ttl_seconds=30):
        if self.fail:
            raise self.fail
        return FakeBinding()


class FakeTransport:
    def __init__(self, rec: Recorder, fail_at: str | None = None,
                 error: BaseException | None = None) -> None:
        self.rec, self.fail_at, self.error = rec, fail_at, error

    def pin(self, binding, *, cdp_request_id, network_request_id):
        if self.fail_at == "pin":
            raise self.error
        return "pin-1"

    def prepare(self, pin, *, url, method, headers, max_response_bytes):
        assert method == "GET", "v1 er GET-only"
        return {"url": url, "max": max_response_bytes}

    def execute(self, pin, prepared, *, timeout_seconds):
        if self.fail_at == "execute":
            raise self.error
        return FakeResponse()

    def release(self, pin):
        self.rec.released += 1


def build(fail_at=None, error=None):
    rec = Recorder()
    return rec, WebResearchFetcher(
        boundary=FakeBoundary(rec, fail_at if fail_at == "claim" else None, error),
        bridge=FakeBridge(error if fail_at == "bridge" else None),
        peer_ledger=FakePeer(error if fail_at == "issue" else None),
        transport=FakeTransport(rec, fail_at if fail_at in ("pin", "execute") else None, error),
    )


URL = "https://example.com/side"

# --- den lykkelige sti ---------------------------------------------------
rec, fetcher = build()
result = fetcher.fetch(URL, purpose="Slaa noget op")
check(result.status == 200 and result.bytes_received > 0, "en hentning lykkes")
check(rec.completed == [{"outcome": "completed", "bytes_sent": 128, "error_code": None}],
      f"afsluttet som completed med bytes_sent fra svaret ({rec.completed})")
check(rec.released == 1, "pin'en blev frigivet")

# --- hver fejlsti afslutter stadig --------------------------------------
for stage, error, expected in (
    ("claim", BrowserPeerAdapterDenied("naegtet"), "blocked"),
    ("bridge", BrowserPeerAdapterDenied("naegtet"), "blocked"),
    ("issue", BrowserPeerAdapterDenied("ingen offentlig peer"), "blocked"),
    ("pin", BrowserPeerAdapterDenied("ikke-offentlig peer"), "blocked"),
    ("execute", BrowserPinnedTransportError("response_framing_ambiguous"), "failed"),
    ("execute", TimeoutError("timeout"), "failed"),
):
    rec, fetcher = build(stage, error)
    raised = False
    try:
        fetcher.fetch(URL, purpose="probe")
    except BaseException:  # noqa: BLE001
        raised = True
    check(raised, f"{stage}: fejlen boblede op til kalderen")
    check(len(rec.completed) == 1,
          f"{stage}: complete() blev kaldt praecis een gang ({len(rec.completed)})")
    check(rec.completed[0]["outcome"] == expected,
          f"{stage}: udfald {expected} ({rec.completed[0]['outcome']})")
    check(rec.completed[0]["error_code"] == type(error).__name__,
          f"{stage}: koden navngiver hvad der naegtede")

# --- pin'en frigives ogsaa naar execute fejler --------------------------
rec, fetcher = build("execute", TimeoutError("t"))
try:
    fetcher.fetch(URL, purpose="probe")
except BaseException:  # noqa: BLE001
    pass
check(rec.released == 1,
      "pin'en frigives ogsaa paa fejlstien -- ellers kan naeste hentning ikke pinne")

# --- en ulovlig URL naar aldrig at lave en lease ------------------------
rec, fetcher = build()
raised = False
try:
    fetcher.fetch("http://example.com/a", purpose="probe")
except WebResearchIntentError:
    raised = True
check(raised, "http afvises")
check(rec.completed == [],
      "ingen lease blev lavet, saa der er intet at afslutte -- og intet at laekke")

# --- D7 nr. 3, kortlaegningen isoleret ----------------------------------
check(_outcome_for(BrowserPeerAdapterDenied("x"))[0] == "blocked",
      "vores afvisning er blocked, selv om den arver fra PermissionError/OSError")
check(_outcome_for(OSError("x"))[0] == "failed", "en ren OS-fejl er failed")
check(_outcome_for(RuntimeError("x"))[0] == "failed",
      "en UKENDT undtagelse er failed -- at kalde den blocked ville paastaa en "
      "beslutning vi ikke traf")

print(f"\nweb research fetch: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
