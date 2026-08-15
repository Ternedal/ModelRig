#!/usr/bin/env python3
"""Parringslinket findes i TO implementeringer — de skal blive ved at være enige.

Telefonen LÆSER linket (Android: net/PairingLink.kt), riggen SKRIVER det
(desktop: PairingQr.kt). To sider af samme format er præcis den slags der
driver fra hinanden i stilhed: nogen retter et parameternavn ét sted, og QR-
parringen holder op med at virke uden at en eneste test bliver rød.

Derfor pinnes de fælles ord her: skema, handling og de to parameternavne.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
ANDROID = ROOT / "android/app/src/main/java/dk/ternedal/modelrig/net/PairingLink.kt"
DESKTOP = ROOT / "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/PairingQr.kt"

passed = 0
failed = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} {detail}")


def const(text: str, name: str) -> str | None:
    m = re.search(rf'{name}\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else None


def main() -> int:
    check("begge implementeringer findes", ANDROID.is_file() and DESKTOP.is_file())
    if not (ANDROID.is_file() and DESKTOP.is_file()):
        print(f"pairing link parity: {passed} passed, {failed} failed")
        return 1

    a = ANDROID.read_text(encoding="utf-8")
    d = DESKTOP.read_text(encoding="utf-8")

    a_scheme, d_scheme = const(a, "SCHEME"), const(d, "SCHEME")
    check("skemaet er erklæret begge steder", bool(a_scheme and d_scheme))
    check("skemaet er det samme", a_scheme == d_scheme, f"-- {a_scheme!r} vs {d_scheme!r}")

    a_action, d_action = const(a, "ACTION"), const(d, "ACTION")
    check("handlingen er den samme", a_action == d_action, f"-- {a_action!r} vs {d_action!r}")

    # Læseren slår parametrene op ved navn; skriveren har dem som konstanter.
    d_url, d_code = const(d, "PARAM_URL"), const(d, "PARAM_CODE")
    check("skriveren navngiver begge parametre", bool(d_url and d_code))
    check(
        f"læseren henter parameteren {d_url!r}",
        f'getQueryParameter("{d_url}")' in a,
        "-- Android læser et andet navn end riggen skriver",
    )
    check(
        f"læseren henter parameteren {d_code!r}",
        f'getQueryParameter("{d_code}")' in a,
        "-- Android læser et andet navn end riggen skriver",
    )

    # Ingen af siderne må lægge hemmeligheder i linket.
    for label, text in (("læseren", a), ("skriveren", d)):
        check(
            f"{label} bygger ikke token ind i linket",
            not re.search(r'"[^"]*token[^"]*"\s*(?:to|=)', text, re.I),
        )

    print(f"pairing link parity: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
