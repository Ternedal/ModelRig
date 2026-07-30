"""D7 vej 3 — paritetsgaten mellem valideringsscriptet og WebResearchFetcher.

Gaten pinner den MAALTE forskel (ROADMAP D7, maalingen 29/7), ikke en paastaaet
lighed. Den fryser tre kendsgerninger, som HVER ISAER er et bevidst flip-punkt:

  FLIPPET VED TRIN 1 (30/07-2026): del E maalte, at WebResearchFetcher ikke
  blev konstrueret nogen steder uden for sin egen test. Kaldestedet er landet
  som ToolGate-vaerktoejet, og pinnen peger nu paa praecis den ene sti.
  Dukker der en anden op, er det en ny udgaaende sti -- og en ny beslutning.

  FLIP VED TRIN 2 (evidens-konvergens, mulighed (b)): del C+D maaler, at
  scriptet baerer evidenslaget (fulfillment-controller, claim-bundet evidens,
  read-only policy, dns-blok af pending.permit.binding) og at henteren INTET
  af det har. Konvergerer de to veje, skal asymmetri-pinnen flippes bevidst,
  ikke slettes (HANDOFF lektie 29: asymmetrien skal have en test der siger
  det).

  STABILT: del A+B beviser behavioralt -- ved at kalde fetch(), ikke ved at
  taelle navne (lektie 32) -- at henterens boundary-konvolut har den
  raekkefoelge D7 beskriver, og at complete() afslutter lease'en praecis een
  gang, sidst, ogsaa naar transporten fejler. Udfalds-tabellen ejes af
  tests/worker_web_research_fetch.py; her ejes RAEKKEFOELGEN.
"""
from __future__ import annotations

import importlib.util
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


# --- Del A+B: konvoluttens raekkefoelge, bevist ved kald --------------------

class _Order:
    def __init__(self) -> None:
        self.calls: list[str] = []


class _Plan:
    destination_url = "https://example.com/side"
    max_bytes = 4096


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
    selected_address = "203.0.113.7"


class _Peer:
    def __init__(self, order: _Order) -> None:
        self._o = order

    def issue(self, auth, evidence, lease, intent, url, *, now=None, ttl_seconds=30):
        self._o.calls.append("peer.issue")
        return _Binding()


class _Response:
    status = 200
    body = b"x" * 64
    bytes_sent = 64


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
    # build_intent koeres via monkeypatch, saa gaten pinner KONVOLUTTEN og ikke
    # research-kontraktens URL-regler (de har deres egne tests).
    import app.web_research_fetch as module

    original = module.build_intent
    module.build_intent = lambda url, *, purpose, **kw: _Intent()
    try:
        try:
            fetcher.fetch("https://example.com/side", purpose="paritet")
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
      f"konvolutten har D7-raekkefoelgen, og complete er sidst ({calls})")
check(sum(c.startswith("boundary.complete") for c in calls) == 1,
      "lease'en afsluttes praecis een gang")

calls = _run(execute_error=TimeoutError("timeout"))
check(calls[-1] == "boundary.complete:failed" and calls[-2] == "transport.release",
      f"ved transportfejl frigives pin og lease'en afsluttes SIDST ({calls[-2:]})")
check(sum(c.startswith("boundary.complete") for c in calls) == 1,
      "ogsaa ved fejl afsluttes lease'en praecis een gang")

# --- Del C: scriptets evidenslag, bevist ved import -------------------------

SCRIPT = ROOT / "scripts" / "browser_peer_public_validation.py"
source = SCRIPT.read_text(encoding="utf-8")
check('if __name__ == "__main__":' in source,
      "scriptet er main-guarded og kan importeres af gaten")

spec = importlib.util.spec_from_file_location("browser_peer_public_validation", SCRIPT)
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)

for name in (
    "BrowserPeerFulfillmentController",
    "ClaimBoundBrowserEvidence",
    "PinnedBrowserPeerTransport",
):
    check(hasattr(script, name),
          f"scriptet baerer evidenslaget: {name} resolver ved import")
check("pending.permit.binding" in source,
      "scriptets dns-blok bygges af pending.permit.binding")

# --- Del D: den maalte asymmetri (FLIP VED TRIN 2) ---------------------------

fetch_source = (ROOT / "worker" / "app" / "web_research_fetch.py").read_text(
    encoding="utf-8"
)
for name in (
    "ClaimBoundBrowserEvidence",
    "BrowserPeerFulfillmentController",
    "ReadOnlyBrowserPolicy",
):
    check(name not in fetch_source,
          f"MAALT ASYMMETRI (flip bevidst ved D7 trin 2): henteren har ikke {name}")

# --- Del E: intet produktionskaldested endnu (FLIP VED TRIN 1) ---------------

constructions: list[str] = []
for base in (ROOT / "worker", ROOT / "scripts"):
    for path in base.rglob("*.py"):
        if "WebResearchFetcher(" in path.read_text(encoding="utf-8"):
            constructions.append(str(path.relative_to(ROOT)).replace("\\", "/"))
check(sorted(constructions) == ["worker/app/web_research_tool.py"],
      "MAALT (flippet ved D7 trin 1, 30/07-2026): henteren konstrueres PRAECIS "
      "eet sted i produktion -- ToolGate-vaerktoejet. Dukker der flere op, er "
      f"det en ny udgaaende sti og en ny beslutning ({constructions})")

print(f"\n===== WEB RESEARCH PARITY (D7 vej 3): {PASSED} passed, {FAILED} failed =====")
if FAILED:
    raise SystemExit(1)
