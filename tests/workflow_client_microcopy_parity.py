#!/usr/bin/env python3
"""The two clients must say the same thing, byte for byte.

Design-guiden afsnit 07 og 08 foreskriver praecise strenge. De findes i to
adskilte Gradle-moduler, saa ingen Kotlin-test kan spaende over begge -- og
uden en gate driver de fra hinanden. Det er ikke hypotetisk: Android stod paa
"Skriv til modellen..." laenge efter desktop var rettet, og statusstrengene
blev foerst skrevet med Kotlin-escapes i det ene modul og literale tegn i det
andet. Samme streng, to kilderepraesentationer.

Run: python3 tests/workflow_client_microcopy_parity.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TREES = {
    "desktop": ROOT / "desktop/composeApp/src/main/kotlin",
    "android": ROOT / "android/app/src/main/java",
}

# Ordret fra Kaliv_UI_Design_Guide.pdf.
REQUIRED = {
    "composer-placeholder": "Skriv til Kaliv \u2026",
    "status-thinking": "Kaliv t\u00e6nker \u2026",
    "status-rag": "S\u00f8ger i din viden \u2026",
    "status-tools": "K\u00f8rer v\u00e6rkt\u00f8j \u2026",
}

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def sources(tree: Path) -> str:
    return "\n".join(f.read_text(encoding="utf-8", errors="replace")
                     for f in tree.rglob("*.kt"))


blobs = {name: sources(tree) for name, tree in TREES.items()}

for label, text in REQUIRED.items():
    where = [n for n, b in blobs.items() if f'"{text}"' in b]
    check(len(where) == len(TREES),
          f"{label}: findes i {sorted(where)} (kraever begge)")

# Escapes er ikke forbudt i Kotlin, men de maa ikke bruges til NETOP disse
# strenge i det ene modul og literale tegn i det andet -- saa finder et grep
# kun den ene, og det var praecis hvad der skete 27/07.
for label, text in REQUIRED.items():
    escaped = "".join(f"\\u{ord(c):04x}" if ord(c) > 127 else c for c in text)
    offenders = [n for n, b in blobs.items() if f'"{escaped}"' in b]
    check(not offenders,
          f"{label}: ingen escaped variant ({offenders or 'ingen'})")

# Den streng guiden eksplicit kalder ud som forkert maa ikke komme igen.
banned = "Skriv til modellen"
back = [n for n, b in blobs.items() if banned in b]
check(not back, f"den afviste placeholder {banned!r} er vaek ({back or 'ingen'})")

# Sabotage: en gate der ikke kan blive roed er dekoration.
sab = dict(blobs)
sab["android"] = sab["android"].replace(f'"{REQUIRED["status-rag"]}"', '"Soeger ..."')
missing = [n for n, b in sab.items() if f'"{REQUIRED["status-rag"]}"' in b]
check(len(missing) == 1, "en aendret streng i eet modul brydes af pariteten")

print(f"\nclient microcopy parity: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
