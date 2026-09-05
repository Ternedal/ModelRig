#!/usr/bin/env python3
"""Brand.kt maa ikke gentage en tokenvaerdi som literal.

Foer 27/7-2026 stod alle 24 tokenfarver som haandtastede hex i Brand.kt, med en
kommentar om at man skulle "change the tokens file and re-apply". Re-apply var
manuelt. Konsekvensen blev synlig samme dag: da light.muted skulle moerknes for
at naa WCAG AA, aendrede JSON'en og de genererede filer sig -- men desktop
renderede stadig den gamle vaerdi, fordi Brand.kt havde sin egen kopi.

Nu laeser Brand.kt KalivTokens. Denne gate holder den der: ingen Color-literal i
Brand.kt maa have samme vaerdi som et token, for saa er duplikatet tilbage.

CodeSurface og onPrimary er undtaget ved konstruktion -- de findes ikke i
tokensaettet, saa de kan ikke kollidere.

Run: python3 tests/workflow_brand_no_token_duplicates.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "assets" / "design" / "kaliv-ui-guide" / "kaliv-ui-tokens.json"
BRAND = ROOT / "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/Brand.kt"

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def token_hexes() -> dict[str, str]:
    color = json.loads(code_of(TOKENS))["color"]
    return {h.lstrip("#").upper(): f"{g}.{n}"
            for g, entries in color.items() for n, h in entries.items()}


def literals(src: str) -> list[str]:
    return [m.upper() for m in re.findall(r"Color\(0xFF([0-9A-Fa-f]{6})\)", src)]


tokens = token_hexes()
src = code_of(BRAND)

check(bool(tokens), f"tokensaettet kunne laeses ({len(tokens)} unikke farver)")
check("KalivTokens." in src, "Brand.kt refererer KalivTokens")

dupes = sorted({h for h in literals(src) if h in tokens})
check(not dupes,
      "ingen Color-literal i Brand.kt gentager et token "
      f"({[f'#{h} = {tokens[h]}' for h in dupes] or 'ingen'})")

# De tre tilbageblevne literaler skal fortsat ligge UDEN for tokensaettet.
rest = sorted(set(literals(src)))
check(all(h not in tokens for h in rest),
      f"de resterende literaler er alle uden for tokensaettet ({len(rest)} stk.)")

# Sabotage: en gate der ikke kan blive roed er dekoration.
some_token = next(iter(tokens))
sab = src.replace("CodeSurface = Color(0xFF14100C)", f"CodeSurface = Color(0xFF{some_token})", 1)
check(any(h in tokens for h in literals(sab)),
      f"et genindfoert duplikat (#{some_token}) fanges")

print(f"\nbrand token duplicates: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
