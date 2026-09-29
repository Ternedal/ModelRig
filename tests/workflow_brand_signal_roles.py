#!/usr/bin/env python3
"""Contract for the unified Kaliv / ModelRig Ember + Signal brand roles."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "assets/design/kaliv-ui-guide/kaliv-ui-tokens.json"

EXPECTED_SIGNAL = {
    "primary": "#48C7FF",
    "light": "#73D6FF",
    "strong": "#159FDB",
    "deep": "#0B5F8C",
    "glow": "#3848C7FF",
}


def need(path: str) -> str:
    p = ROOT / path
    if not p.is_file():
        raise AssertionError(f"missing brand surface: {path}")
    return p.read_text(encoding="utf-8")


def main() -> int:
    tokens = json.loads(TOKENS.read_text(encoding="utf-8"))
    assert tokens["meta"]["version"] == "2.1", "unified brand requires token schema 2.1"
    assert tokens["color"]["signal"] == EXPECTED_SIGNAL, "Signal palette drifted"

    generator = need("scripts/design_tokens.py")
    assert '"signal"' in generator, "Kotlin generator does not emit Signal tokens"

    for path in (
        "android/app/src/main/java/dk/ternedal/modelrig/ui/theme/KalivTokens.kt",
        "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/KalivTokens.kt",
    ):
        source = need(path)
        assert 'VERSION: String = "2.1"' in source, f"{path}: stale token version"
        assert "object Signal" in source, f"{path}: missing generated Signal object"
        assert "0xFF48C7FF" in source, f"{path}: missing Signal primary"

    android_theme = need("android/app/src/main/java/dk/ternedal/modelrig/ui/theme/Theme.kt")
    assert "val cognition: Color" in android_theme
    assert "KalivTokens.Signal.primary" in android_theme
    assert "KalivTokens.Signal.deep" in android_theme

    desktop_theme = need("desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/Brand.kt")
    assert "val Cognition: Color" in desktop_theme
    assert "KalivTokens.Signal.primary" in desktop_theme

    voice = need("android/app/src/main/java/dk/ternedal/modelrig/ui/chat/VoiceScreen.kt")
    assert "KalivTheme.colors.cognition" in voice, "voice activity must use Signal"
    app_ui = need("android/app/src/main/java/dk/ternedal/modelrig/ui/AppUi.kt")
    assert "pillDot = KalivTheme.colors.cognition" in app_ui, "active voice route must use Signal"
    control = need("android/app/src/main/java/dk/ternedal/modelrig/ui/ControlCenterScreen.kt")
    assert "color = KalivTheme.colors.cognition" in control, "Control Center progress must use Signal"

    desktop = need("desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/KalivScreens.kt")
    assert "KalivTheme.colors.Cognition" in desktop, "desktop live telemetry must use Signal"
    desktop_cc = need("desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/ControlCenterDialog.kt")
    assert "\"healthy\" -> KalivTheme.colors.Success" in desktop_cc, "health must stay semantic"
    assert "color = KalivTheme.colors.Cognition" in desktop_cc, "live Control Center progress must use Signal"

    vr_brand = need("vr/Assets/Scripts/KalivVrBrand.cs")
    vr_panel = need("vr/Assets/Scripts/KalivVrPanel.cs")
    assert '#48C7FF' in vr_brand and '#D4AB52' in vr_brand
    assert "KalivVrBrand.Signal" in vr_panel, "Quest panel is not bound to shared roles"

    css = need("assets/design/kaliv-ui-guide/kaliv-ui-tokens.css")
    assert "--kaliv-signal: #48C7FF;" in css

    print("unified Ember/Signal brand contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
