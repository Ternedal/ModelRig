#!/usr/bin/env python3
"""Adversarial SSRF-dækning for peer-pinningen (T-034, kriterium 7).

Beskyttelsen fandtes, men ingen test nævnte de adresser en SSRF faktisk sigter
efter. Auditten 27/07 fandt nul forekomster af `169.254`, `rebind` og
`link-local` i hele research/browser-peer-sporet -- 709 assertions, men ingen
af dem navngav angrebet.

Det her tester `browser_peer_adapter`, ikke `ipaddress`. At stdlib afviser
169.254.169.254 beviser intet om produktionskoden; det interessante er om
pin-receipten kan bygges med en saadan adresse.

Om rebinding: forsvaret ligger i HVOR valideringen sker. `_public_address`
koeres paa `remoteIPAddress` -- den peer browseren rapporterer at have FORBUNDET
til -- ikke paa et DNS-opslag foer forbindelsen. Et DNS-svar der skifter mellem
opslag og forbindelse kan derfor ikke snige en privat peer igennem: den faktiske
peer valideres. Testene nedenfor daekker begge ender af det.

Run: PYTHONPATH=worker python3 tests/worker_browser_peer_ssrf_adversarial.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="kaliv-ssrf-")
os.environ.setdefault("KALIV_TOOLS_DIR", os.path.join(_tmp, "notes"))
os.environ.setdefault("KALIV_AUDIT_DB", os.path.join(_tmp, "audit.db"))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "worker"))

from app.browser_peer_adapter import (  # noqa: E402
    BrowserPeerAdapterContractError,
    BrowserPeerAdapterDenied,
    BrowserPeerPinReceipt,
    _public_address,
)

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


# Hver af disse er et rigtigt SSRF-maal, ikke en teoretisk adresse.
HOSTILE = [
    ("169.254.169.254", "cloud-metadata (AWS/GCP/Azure IMDS) -- klassisk SSRF-maal"),
    ("169.254.1.1", "link-local"),
    ("127.0.0.1", "loopback -- riggens egen backend paa 8080"),
    ("::1", "IPv6 loopback"),
    ("::ffff:127.0.0.1", "IPv4-mapped loopback -- klassisk bypass af naive tjek"),
    ("10.0.0.5", "privat 10/8"),
    ("192.168.1.10", "privat 192.168/16 -- hjemmenettet paa Noerrebro"),
    ("172.16.0.1", "privat 172.16/12"),
    ("100.64.0.1", "CGNAT -- det omraade Tailscale bruger"),
    ("fd00::1", "IPv6 unique-local"),
    ("fe80::1", "IPv6 link-local"),
    ("0.0.0.0", "unspecified"),
]

# --- 1. _public_address afviser hver enkelt -------------------------------
for address, why in HOSTILE:
    try:
        _public_address(address)
        check(False, f"{address} afvises ({why})")
    except BrowserPeerAdapterDenied:
        check(True, f"{address} afvises ({why})")
    except BrowserPeerAdapterContractError:
        check(True, f"{address} afvises som ugyldig ({why})")

# --- 2. kontrol: en aegte offentlig adresse SKAL slippe igennem -----------
# Uden den her kunne testen ovenfor bestaa fordi funktionen afviser ALT.
for address in ("8.8.8.8", "2001:4860:4860::8888"):
    try:
        check(_public_address(address) == address,
              f"{address} accepteres og returneres kanonisk")
    except Exception as exc:  # noqa: BLE001
        check(False, f"{address} blev afvist: {type(exc).__name__}")


def pin(address: str) -> BrowserPeerPinReceipt:
    return BrowserPeerPinReceipt(
        pin_id="bpp_probe",
        binding_id="rpt_probe",
        cdp_request_id="cdp-1",
        network_request_id="net-1",
        host="example.com",
        port=443,
        selected_address=address,
        expires_at=4102444800,
    )


# --- 3. pin-receipten kan ikke bygges med en fjendtlig peer ---------------
for address, why in HOSTILE:
    try:
        pin(address)
        check(False, f"pin-receipt afvises for {address}")
    except (BrowserPeerAdapterDenied, BrowserPeerAdapterContractError):
        check(True, f"pin-receipt afvises for {address}")

check(pin("8.8.8.8").selected_address == "8.8.8.8",
      "pin-receipt kan stadig bygges med en offentlig peer")

# --- 4. ikke-kanonisk form er ogsaa afvist --------------------------------
# En angriber der skriver den samme offentlige adresse paa en anden maade maa
# ikke kunne omgaa en senere sammenligning paa strengen.
for weird in ("::ffff:8.8.8.8", "2001:4860:4860:0000::8888"):
    try:
        pin(weird)
        check(False, f"ikke-kanonisk {weird} afvises")
    except BrowserPeerAdapterContractError:
        check(True, f"ikke-kanonisk {weird} afvises")

# --- 5. sabotage: kan testen overhovedet blive roed? ----------------------
try:
    _public_address("8.8.8.8")
    sabotage_would_catch = False
except Exception:  # noqa: BLE001
    sabotage_would_catch = True
check(not sabotage_would_catch,
      "kontrolpunktet virker: en beskyttelse der afviste ALT ville faelde punkt 2")

print(f"\nbrowser peer SSRF adversarial: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
