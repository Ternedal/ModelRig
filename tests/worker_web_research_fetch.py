#!/usr/bin/env python3
"""D7 step 2: direct ToolGate fetches must end as verified source receipts.

Every lifecycle stage can fail and boundary.complete() must still run exactly
once. The successful path additionally proves that the already-fetched pinned
response is re-verified in memory through the deterministic source contract:
no second socket, no redirect success, no unsupported/download content, and a
citation-ready SourceReceipt bound to the exact body.

Run: PYTHONPATH=worker python3 tests/worker_web_research_fetch.py
"""
from __future__ import annotations

import hashlib
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
from app.web_fetch import WebFetchError  # noqa: E402
from app.web_research_fetch import WebResearchFetcher, _outcome_for  # noqa: E402
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


@dataclass
class FakeResponse:
    status: int = 200
    body: bytes = b"<html><head><title>Test</title></head><body>Hello verified world</body></html>"
    bytes_sent: int = 128
    headers: tuple[tuple[str, str], ...] = (("content-type", "text/html; charset=utf-8"),)
    connected_address: str = "93.184.216.34"


class FakeBinding:
    binding_id = "rpt_probe"
    addresses = ("93.184.216.34", "93.184.216.35")
    selected_address = "93.184.216.34"


class Recorder:
    def __init__(self) -> None:
        self.completed: list[dict] = []
        self.released = 0
        self.executes = 0


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
    def __init__(self, fail: BaseException | None = None,
                 binding: FakeBinding | None = None) -> None:
        self.fail = fail
        self.binding = binding or FakeBinding()

    def issue(self, auth, evidence, lease, intent, url, *, now=None, ttl_seconds=30):
        if self.fail:
            raise self.fail
        return self.binding


class FakeTransport:
    def __init__(self, rec: Recorder, fail_at: str | None = None,
                 error: BaseException | None = None,
                 response: FakeResponse | None = None) -> None:
        self.rec, self.fail_at, self.error = rec, fail_at, error
        self.response = response or FakeResponse()

    def pin(self, binding, *, cdp_request_id, network_request_id):
        if self.fail_at == "pin":
            raise self.error
        return "pin-1"

    def prepare(self, pin, *, url, method, headers, max_response_bytes):
        assert method == "GET", "v1 is GET-only"
        return {"url": url, "max": max_response_bytes}

    def execute(self, pin, prepared, *, timeout_seconds):
        self.rec.executes += 1
        if self.fail_at == "execute":
            raise self.error
        return self.response

    def release(self, pin):
        self.rec.released += 1


def build(fail_at=None, error=None, *, response=None, binding=None):
    rec = Recorder()
    return rec, WebResearchFetcher(
        boundary=FakeBoundary(rec, fail_at if fail_at == "claim" else None, error),
        bridge=FakeBridge(error if fail_at == "bridge" else None),
        peer_ledger=FakePeer(error if fail_at == "issue" else None, binding=binding),
        transport=FakeTransport(
            rec,
            fail_at if fail_at in ("pin", "execute") else None,
            error,
            response=response,
        ),
    )


URL = "https://example.com/side"

# --- successful fetch produces verified citation evidence -----------------
rec, fetcher = build()
result = fetcher.fetch(URL, purpose="Look something up")
check(result.status == 200 and result.bytes_received > 0, "fetch succeeds")
check(rec.executes == 1, "exactly one real transport execution occurs")
check(result.source_receipt.url == URL, "receipt binds the canonical requested URL")
check(result.source_receipt.adapter == "deterministic-web-fetch",
      "receipt uses the shared deterministic source authority")
check(result.source_receipt.content_sha256 == hashlib.sha256(result.body).hexdigest(),
      "receipt digest binds the exact returned content bytes")
check("Hello verified world" in result.source_receipt.excerpt,
      "receipt contains verified readable source text")
check(result.resolved_addresses == FakeBinding.addresses
      and result.selected_address == FakeBinding.selected_address,
      "result preserves DNS set plus selected peer")
check(rec.completed == [{"outcome": "completed", "bytes_sent": 128, "error_code": None}],
      f"completed audit records actual sent bytes ({rec.completed})")
check(rec.released == 1, "pin is released")

# --- response verification is fail-closed after bytes were sent -----------
for label, response in (
    ("redirect", FakeResponse(status=302, headers=(("location", "https://example.com/other"),))),
    ("download", FakeResponse(headers=(("content-type", "text/html"),
                                       ("content-disposition", "attachment; filename=x")))),
    ("binary", FakeResponse(headers=(("content-type", "application/octet-stream"),))),
    ("peer mismatch", FakeResponse(connected_address="93.184.216.35")),
):
    rec, fetcher = build(response=response)
    raised = None
    try:
        fetcher.fetch(URL, purpose="probe")
    except BaseException as exc:  # noqa: BLE001
        raised = exc
    check(isinstance(raised, WebFetchError), f"{label}: verification rejects the response")
    check(rec.executes == 1, f"{label}: rejection does not perform a second network execution")
    check(rec.completed == [{
        "outcome": "blocked", "bytes_sent": response.bytes_sent,
        "error_code": "WebFetchError",
    }], f"{label}: audit is blocked but truthfully records bytes already sent")
    check(rec.released == 1, f"{label}: pin is released on verification rejection")

# selected peer must belong to the binding before verification can succeed.
bad_binding = FakeBinding()
bad_binding.addresses = ("93.184.216.35",)
rec, fetcher = build(binding=bad_binding)
try:
    fetcher.fetch(URL, purpose="probe")
except WebFetchError:
    pass
else:
    check(False, "selected peer absent from DNS binding must fail")
check(rec.completed[0]["outcome"] == "blocked",
      "malformed peer binding fails closed")

# --- every earlier lifecycle failure still completes exactly once ---------
for stage, error, expected in (
    ("claim", BrowserPeerAdapterDenied("denied"), "blocked"),
    ("bridge", BrowserPeerAdapterDenied("denied"), "blocked"),
    ("issue", BrowserPeerAdapterDenied("no public peer"), "blocked"),
    ("pin", BrowserPeerAdapterDenied("not-public peer"), "blocked"),
    ("execute", BrowserPinnedTransportError("response_framing_ambiguous"), "failed"),
    ("execute", TimeoutError("timeout"), "failed"),
):
    rec, fetcher = build(stage, error)
    raised = False
    try:
        fetcher.fetch(URL, purpose="probe")
    except BaseException:  # noqa: BLE001
        raised = True
    check(raised, f"{stage}: error bubbles to caller")
    check(len(rec.completed) == 1,
          f"{stage}: complete called exactly once ({len(rec.completed)})")
    check(rec.completed[0]["outcome"] == expected,
          f"{stage}: outcome {expected} ({rec.completed[0]['outcome']})")
    check(rec.completed[0]["error_code"] == type(error).__name__,
          f"{stage}: audit names what failed")

rec, fetcher = build("execute", TimeoutError("t"))
try:
    fetcher.fetch(URL, purpose="probe")
except BaseException:  # noqa: BLE001
    pass
check(rec.released == 1, "pin is released when execute fails")

# illegal URL fails before a lease exists.
rec, fetcher = build()
raised = False
try:
    fetcher.fetch("http://example.com/a", purpose="probe")
except WebResearchIntentError:
    raised = True
check(raised, "http is rejected before authorization")
check(rec.completed == [], "illegal URL creates no lease to complete")

# D7 error mapping: verification/contract denials are ours, OS failures are peer.
check(_outcome_for(BrowserPeerAdapterDenied("x"))[0] == "blocked",
      "our denial remains blocked even when it inherits OSError")
check(_outcome_for(WebFetchError("x"))[0] == "blocked",
      "shared source verifier rejection is blocked")
check(_outcome_for(OSError("x"))[0] == "failed", "pure OS failure is failed")
check(_outcome_for(RuntimeError("x"))[0] == "failed", "unknown failure is failed")

print(f"\nweb research fetch D7 step 2: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
