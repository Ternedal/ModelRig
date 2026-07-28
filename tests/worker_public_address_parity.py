#!/usr/bin/env python3
"""De fire SSRF-tjek skal vaere enige -- og forblive det.

`_public_address` findes i fire moduler: browser_peer_adapter, research_contract,
research_peer_binding og research_peer_transfer. Maalt 27/07 er de enige om alle
fjorten proeveadresser. Det er ingen garanti for i morgen: fire kopier af et
sikkerhedstjek er praecis konstruktionen hvor een bliver rettet og resten glider.

Testen OPDAGER implementeringerne frem for at have en liste. Tilfoejer nogen en
femte kopi, kommer den automatisk med -- en haardkodet liste ville gaa god for
den ved at ignorere den.

Run: PYTHONPATH=worker python3 tests/worker_public_address_parity.py
"""
from __future__ import annotations

import importlib
import os
import pkgutil
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="kaliv-par-")
os.environ.setdefault("KALIV_TOOLS_DIR", os.path.join(_tmp, "notes"))
os.environ.setdefault("KALIV_AUDIT_DB", os.path.join(_tmp, "audit.db"))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "worker"))

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def discover() -> dict[str, object]:
    """Find hver modul-level _public_address i app/."""
    found: dict[str, object] = {}
    app_dir = ROOT / "worker" / "app"
    for mod in pkgutil.iter_modules([str(app_dir)]):
        if mod.ispkg:
            continue
        try:
            module = importlib.import_module(f"app.{mod.name}")
        except Exception:  # noqa: BLE001 - et umuligt modul er ikke denne tests sag
            continue
        fn = getattr(module, "_public_address", None)
        if callable(fn):
            found[mod.name] = fn
    return found


impls = discover()

# Kontrolpunkt: opdagelsen skal faktisk finde noget. En tom dict ville lade
# resten af testen "bestaa" uden at maale en eneste implementering.
check(len(impls) >= 3,
      f"opdagede mindst tre implementeringer ({sorted(impls)})")

HOSTILE = [
    ("169.254.169.254", "cloud-metadata"),
    ("127.0.0.1", "loopback"),
    ("::1", "IPv6 loopback"),
    ("::ffff:127.0.0.1", "IPv4-mapped loopback"),
    ("10.0.0.5", "privat 10/8"),
    ("192.168.1.10", "privat 192.168/16"),
    ("172.16.0.1", "privat 172.16/12"),
    ("100.64.0.1", "CGNAT / Tailscale-omraadet"),
    ("fd00::1", "IPv6 ULA"),
    ("fe80::1", "IPv6 link-local"),
    ("0.0.0.0", "unspecified"),
    ("169.254.1.1", "link-local"),
]
PUBLIC = ["8.8.8.8", "2001:4860:4860::8888"]


def verdicts(address: str) -> dict[str, str]:
    out = {}
    for name, fn in impls.items():
        try:
            fn(address)
            out[name] = "allowed"
        except Exception:  # noqa: BLE001 - enhver afvisning taeller som afvisning
            out[name] = "denied"
    return out


for address, why in HOSTILE:
    v = verdicts(address)
    check(set(v.values()) == {"denied"},
          f"{address} afvises af ALLE ({why}) -- {v if len(set(v.values()))>1 else ''}")

# Uden disse kunne alt ovenfor bestaa fordi hver implementering afviste alt.
for address in PUBLIC:
    v = verdicts(address)
    check(set(v.values()) == {"allowed"},
          f"{address} accepteres af ALLE -- kontrolpunkt mod et tjek der "
          f"afviser alt {v if len(set(v.values()))>1 else ''}")

# --- sabotage: ville uenighed blive fanget? ------------------------------
# En kunstig implementering der slipper metadata-adressen igennem skal faelde
# pariteten. Ellers maaler testen ingenting.
sab = dict(impls)
sab["divergent_probe"] = lambda value: value
saved, impls = impls, sab
v = verdicts("169.254.169.254")
impls = saved
check(set(v.values()) == {"denied", "allowed"},
      "sabotage: en implementering der slipper metadata igennem giver uenighed")

print(f"\npublic address parity: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
