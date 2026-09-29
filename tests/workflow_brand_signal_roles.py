#!/usr/bin/env python3
"""Contract for the unified Kaliv / ModelRig Ember + Signal brand roles."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "assets/design/kaliv-ui-guide/kaliv-ui-tokens.json"

ALLOWED_SIGNAL_LITERAL_PATHS = {
    "android/app/src/main/java/dk/ternedal/modelrig/ui/theme/KalivTokens.kt",
    "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/KalivTokens.kt",
    "vr/Assets/Scripts/KalivVrBrand.cs",
}

CANONICAL_SIGNAL_LITERALS = (
    "#48C7FF", "#73D6FF", "#159FDB", "#0B5F8C",
    "0xFF48C7FF", "0xFF73D6FF", "0xFF159FDB", "0xFF0B5F8C", "0x3848C7FF",
)

LIVE_ANDROID_SURFACES = (
    "android/app/src/main/java/dk/ternedal/modelrig/ui/ControlCenterScheduleHistoryLoader.kt",
    "android/app/src/main/java/dk/ternedal/modelrig/ui/ControlCenterScreen.kt",
    "android/app/src/main/java/dk/ternedal/modelrig/ui/ControlCenterAuditSection.kt",
    "android/app/src/main/java/dk/ternedal/modelrig/ui/ControlCenterGitHubConnectorSection.kt",
    "android/app/src/main/java/dk/ternedal/modelrig/ui/Agent4OperatorScreen.kt",
    "android/app/src/main/java/dk/ternedal/modelrig/ui/Agent4CampaignDetailScreen.kt",
    "android/app/src/main/java/dk/ternedal/modelrig/ui/Agent3TaskScreen.kt",
)

LIVE_DESKTOP_SURFACES = (
    "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/ControlCenterDialog.kt",
    "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/ControlCenterAuditSection.kt",
    "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/ControlCenterSchedulesSection.kt",
    "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/ControlCenterScheduleHistorySection.kt",
    "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/ControlCenterVisionSection.kt",
    "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/ControlCenterGitHubConnectorSection.kt",
    "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/Agent3TaskApp.kt",
)

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
    assert "RoundedCornerShape(15.dp)" in control, "Android Control Center cards must use unified shell radius"
    assert "stateBorder" in control, "Android Control Center cards must expose semantic state borders"
    rig_status = need("android/app/src/main/java/dk/ternedal/modelrig/ui/chat/RigStatusList.kt")
    agent3 = need("android/app/src/main/java/dk/ternedal/modelrig/ui/Agent3Screen.kt")
    agent3_validation = need("android/app/src/main/java/dk/ternedal/modelrig/ui/Agent3ValidationScreen.kt")
    assert "KalivTheme.colors.cognition" in rig_status, "rig telemetry and active models must use Signal"
    assert "\"running\", \"planning\", \"executing\"" in agent3 and "KalivTheme.colors.cognition" in agent3
    assert "KalivTheme.colors.success" in agent3_validation, "ready is semantic success"

    desktop = need("desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/KalivScreens.kt")
    light_chrome = need("desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/KalivLightChrome.kt")
    assert "KalivTheme.colors.Cognition" in desktop, "desktop live telemetry must use Signal"
    assert "KalivTheme.colors.CognitionLight" in desktop, "active desktop model must expose Signal runtime state"
    assert "listOf(c.Cognition, c.CognitionLight)" in light_chrome, "desktop telemetry meter must use Signal"
    assert "c.Signal.copy(alpha = if (c.isDark) 0.10f else 0.08f)" in light_chrome, "privacy seal must stay Ember"
    desktop_cc = need("desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/ControlCenterDialog.kt")
    assert "\"healthy\" -> KalivTheme.colors.Success" in desktop_cc, "health must stay semantic"
    assert "RoundedCornerShape(15.dp)" in desktop_cc, "desktop Control Center cards must use unified shell radius"
    assert "color = KalivTheme.colors.Cognition" in desktop_cc, "live Control Center progress must use Signal"

    vr_brand = need("vr/Assets/Scripts/KalivVrBrand.cs")
    vr_panel = need("vr/Assets/Scripts/KalivVrPanel.cs")
    assert '#48C7FF' in vr_brand and '#D4AB52' in vr_brand
    assert "KalivVrBrand.Signal" in vr_panel, "Quest panel is not bound to shared roles"
    assert "MinWorldButtonHeight = 56f" in vr_brand
    assert "KalivVrBrand.MinWorldButtonHeight" in vr_panel, "Quest buttons must preserve world-space target size"

    for path in LIVE_ANDROID_SURFACES:
        source = need(path)
        offset = 0
        while True:
            index = source.find("CircularProgressIndicator", offset)
            if index < 0:
                break
            block = source[index:index + 500]
            assert "KalivTheme.colors.signal" not in block, f"{path}: live progress regressed to Ember"
            offset = index + 1

    for path in LIVE_DESKTOP_SURFACES:
        source = need(path)
        offset = 0
        while True:
            index = source.find("CircularProgressIndicator", offset)
            if index < 0:
                break
            block = source[index:index + 500]
            assert "color = KalivTheme.colors.Signal" not in block, f"{path}: live progress regressed to Ember"
            offset = index + 1

    for root in (
        ROOT / "android" / "app" / "src" / "main",
        ROOT / "desktop" / "composeApp" / "src" / "main",
        ROOT / "vr" / "Assets" / "Scripts",
    ):
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".kt", ".cs"}:
                continue
            rel = path.relative_to(ROOT).as_posix()
            if rel in ALLOWED_SIGNAL_LITERAL_PATHS:
                continue
            source = path.read_text(encoding="utf-8")
            for literal in CANONICAL_SIGNAL_LITERALS:
                assert literal not in source, f"{rel}: hard-coded canonical Signal literal {literal}"

    css = need("assets/design/kaliv-ui-guide/kaliv-ui-tokens.css")
    assert "--kaliv-signal: #48C7FF;" in css

    print("unified Ember/Signal brand contract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
