#!/usr/bin/env python3
"""Kant-til-kant-vagt for selvstændige skærme.

Appen kører enableEdgeToEdge, så en skærm der bare fylder vinduet tegner ind
under statuslinjen — titlen lander oven i uret. Det skete på Rig-status og
Enheder (Anders' Pixel, 15/08). Reglen er derfor maskinhåndhævet:

    enhver ui/*Screen.kt der fylder vinduet SKAL holde systemlinje-afstand,
    og den ene måde er Modifier.kalivScreenInsets().

Skærme inde i AppUi.kt er ikke omfattet: den fil har sit eget etablerede
inset-mønster pr. destination og er ikke en enkelt skærm.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
UI = ROOT / "android/app/src/main/java/dk/ternedal/modelrig/ui"
HELPER = "kalivScreenInsets"

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


def main() -> int:
    helper = UI / "components/ScreenInsets.kt"
    check("den fælles inset-modifier findes", helper.is_file())
    if helper.is_file():
        text = helper.read_text(encoding="utf-8")
        check(
            "modifieren dækker BÅDE statuslinje og navigationslinje",
            "statusBars" in text and "navigationBars" in text,
        )

    screens = sorted(p for p in UI.glob("*Screen.kt"))
    check("der findes selvstændige skærmfiler at måle", len(screens) > 0)

    for path in screens:
        src = path.read_text(encoding="utf-8")
        if "fillMaxSize()" not in src:
            # Skærmen fylder ikke vinduet; den kan ikke ramme systemlinjen.
            continue
        check(
            f"{path.name} holder systemlinje-afstand",
            HELPER in src,
            "-- tilføj Modifier.kalivScreenInsets() på skærmens rod",
        )

    print(f"screen insets: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
