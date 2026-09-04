"""D7 parity gate between validation/browser evidence and direct ToolGate fetch.

Step 1 was flipped 30/07-2026: WebResearchFetcher has exactly one production
caller, ``worker/app/web_research_tool.py``.

Step 2 is flipped here. The old measured asymmetry intentionally required the
direct fetcher to have *none* of the Browser/CDP evidence classes. That was a
useful pre-convergence pin, but copying those classes into the direct path would
be wrong: Chromium has a ``Fetch.fulfillRequest`` commit point and the direct
ToolGate GET does not.

The shared authority after convergence is instead behavioral and transport-
correct:
- both paths end in the canonical ``SourceReceipt`` / deterministic-web-fetch
  verification contract;
- the direct path replays the already-fetched response in memory, so citation
  verification opens no second destination socket;
- direct ToolGate v1 has ``max_redirects=0`` because one confirmation authorizes
  exactly one outbound request;
- Browser/CDP evidence remains citeable only after its stricter CDP commit.

Stable lifecycle ordering and exact-one production caller remain pinned.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.web_research_fetch import WebResearchFetcher  # noqa: E402

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


# --- Stable lifecycle ordering ---------------------------------------------
class _Order:
    def __init__(self) -> None:
        self.calls: list[str] = []


class _Plan:
    destination_url = "https://example.com/side"
    max_bytes = 4096
    allowed_domains = ("example.com",)


class _Intent:
    plan = _Plan()
    summary = "GET https://example.com/side"


class _Boundary:
    def __init__(self, order: _Order) -> None:
        self._o = order

    def prepare(self, intent, *, now=None, receipt_ttl_seconds=120):
        self._o.calls.append("boundary.prepare")
        return "lease-1"

    def claim(self, lease, intent, *, now=None):
        self._o.calls.append("boundary.claim")
        return "evidence-1"

    def complete(self, lease, intent, *, outcome, bytes_sent, error_code, now=None):
        self._o.calls.append(f"boundary.complete:{outcome}")


class _Bridge:
    def __init__(self, order: _Order) -> None:
        self._o = order

    def prepare(self, evidence, lease, intent, url, *, now=None):
        self._o.calls.append("bridge.prepare")
        return "auth-1"


class _Binding:
    binding_id = "bind-1"
    addresses = ("93.184.216.34",)
    selected_address = "93.184.216.34"


class _Peer:
    def __init__(self, order: _Order) -> None:
        self._o = order

    def issue(self, auth, evidence, lease, intent, url, *, now=None, ttl_seconds=30):
        self._o.calls.append("peer.issue")
        return _Binding()


class _Response:
    status = 200
    body = b"<html><title>x</title><body>verified</body></html>"
    bytes_sent = 64
    headers = (("content-type", "text/html; charset=utf-8"),)
    connected_address = "93.184.216.34"


class _Transport:
    def __init__(self, order: _Order, *, execute_error: BaseException | None = None) -> None:
        self._o = order
        self._err = execute_error

    def pin(self, binding, *, cdp_request_id, network_request_id):
        self._o.calls.append("transport.pin")
        return "pin-1"

    def prepare(self, pin, *, url, method, headers, max_response_bytes):
        self._o.calls.append("transport.prepare")
        return "prepared-1"

    def execute(self, pin, prepared, *, timeout_seconds):
        self._o.calls.append("transport.execute")
        if self._err is not None:
            raise self._err
        return _Response()

    def release(self, pin):
        self._o.calls.append("transport.release")


def _run(*, execute_error: BaseException | None = None):
    order = _Order()
    fetcher = WebResearchFetcher(
        boundary=_Boundary(order),
        bridge=_Bridge(order),
        peer_ledger=_Peer(order),
        transport=_Transport(order, execute_error=execute_error),
    )
    import app.web_research_fetch as module

    original = module.build_intent
    module.build_intent = lambda url, *, purpose, **kw: _Intent()
    try:
        try:
            fetcher.fetch("https://example.com/side", purpose="parity")
        except BaseException:
            pass
    finally:
        module.build_intent = original
    return order.calls


EXPECTED = [
    "boundary.prepare",
    "boundary.claim",
    "bridge.prepare",
    "peer.issue",
    "transport.pin",
    "transport.prepare",
    "transport.execute",
    "transport.release",
    "boundary.complete:completed",
]

calls = _run()
check(calls == EXPECTED,
      f"direct fetch keeps D7 lifecycle ordering and completes last ({calls})")
check(sum(c.startswith("boundary.complete") for c in calls) == 1,
      "lease completes exactly once")

calls = _run(execute_error=TimeoutError("timeout"))
check(calls[-1] == "boundary.complete:failed" and calls[-2] == "transport.release",
      f"transport failure releases pin and completes last ({calls[-2:]})")
check(sum(c.startswith("boundary.complete") for c in calls) == 1,
      "failure also completes exactly once")

# --- Step 2 flipped: semantic source-evidence convergence ------------------
fetch_source = (ROOT / "worker" / "app" / "web_research_fetch.py").read_text(encoding="utf-8")
tool_source = (ROOT / "worker" / "app" / "web_research_tool.py").read_text(encoding="utf-8")
runtime_source = (ROOT / "worker" / "app" / "browser_peer_runtime.py").read_text(encoding="utf-8")

for marker in (
    "SourceReceipt",
    "DeterministicWebFetcher",
    "ReadOnlyBrowserPolicy",
    "_CommittedPinnedResponseTransport",
    "max_redirects=0",
):
    check(marker in fetch_source,
          f"STEP 2 FLIPPED: direct fetch carries shared verified-source contract: {marker}")

check("source_receipt=receipt" in fetch_source,
      "successful direct result cannot be built without verified source receipt")
check('"source": receipt.to_dict()' in tool_source,
      "ToolGate output exposes canonical source receipt")
check('"body_text": receipt.excerpt' in tool_source,
      "ToolGate model text comes from verified receipt excerpt, not raw wire body")
check("ClaimBoundBrowserEvidence" in runtime_source
      and "self.pending.commit" in runtime_source,
      "Browser path retains stricter commit-before-evidence semantics")
check("ClaimBoundBrowserEvidence" not in fetch_source,
      "direct path does not fake a Chromium/CDP commit point")

# --- Step 1 remains exact-one production caller ----------------------------
constructions: list[str] = []
for base in (ROOT / "worker", ROOT / "scripts"):
    for path in base.rglob("*.py"):
        if "WebResearchFetcher(" in path.read_text(encoding="utf-8"):
            constructions.append(str(path.relative_to(ROOT)).replace("\\", "/"))
check(sorted(constructions) == ["worker/app/web_research_tool.py"],
      "WebResearchFetcher still has exactly one production caller "
      f"({constructions})")

print(f"\n===== WEB RESEARCH PARITY (D7 step 2): {PASSED} passed, {FAILED} failed =====")
if FAILED:
    raise SystemExit(1)
