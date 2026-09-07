#!/usr/bin/env python3
"""Software contract for Slice-D rig-link resolution on the Unity renderer.

No Android build, physical network success or production activation is claimed.
Kaliv owns pairing; this gate prevents a second credential store from growing in
the Unity body app.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "support"))
from source_code import code_of  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "renderers" / "bodyrig-unity" / "Assets" / "BodyRig" / "Runtime"
LINK = RUNTIME / "BodyRigRigLink.cs"
META = RUNTIME / "BodyRigRigLink.cs.meta"
BRIDGE = ROOT / "android" / "app" / "src" / "main" / "java" / "dk" / "ternedal" / "modelrig" / "KalivBodyBridge.kt"
FRAME_SOURCE = RUNTIME / "BodyRigFrameSource.cs"

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


check(LINK.is_file() and META.is_file(), "rig-link source and committed Unity metadata exist")
link = code_of(LINK)
bootstrap = code_of(RUNTIME / "BodyRigDemoBootstrap.cs")
bridge = code_of(BRIDGE)
frame_source = code_of(FRAME_SOURCE)

start = link[link.index("private void Start()") : link.index("private SourceState TryUseSource")]
order = [start.index(token) for token in (
    'GetEnvironmentVariable("BODYRIG_RIG_URL")',
    'ReadIntentExtras(out url, out token)',
)]
check(order == sorted(order), "rig authority order is environment then Android intent")
check(start.count("state != SourceState.Absent") == 2,
      "present malformed authority stops fallback instead of using a lower-priority source")

check(
    "Uri.TryCreate" in link
    and "Uri.UriSchemeHttp" in link
    and "Uri.UriSchemeHttps" in link
    and "string.IsNullOrWhiteSpace(uri.Host)" in link,
    "rig origin accepts only absolute HTTP(S) URLs with a host",
)
check(
    "!string.IsNullOrEmpty(uri.UserInfo)" in link
    and 'uri.AbsolutePath != "/"' in link
    and "!string.IsNullOrEmpty(uri.Query)" in link
    and "!string.IsNullOrEmpty(uri.Fragment)" in link
    and "uri.GetLeftPart(UriPartial.Authority)" in link,
    "rig origin rejects userinfo/path/query/fragment and normalizes to authority only",
)
check(
    'baseUrl.TrimEnd(\'/\') + "/api/v1/body/frames"' in frame_source,
    "frame source appends a fixed API path, so rig-link supplies only a bare origin",
)

for forbidden in (
    "PlayerPrefs",
    "/api/v1/pair/claim",
    "OnGUI()",
    "GUILayout",
    "ClaimRequest",
    "ClaimResponse",
    "Forget()",
):
    check(forbidden not in link, f"Kaliv Body has no secondary pairing/persistence surface: {forbidden}")

check(
    'getStringExtra", "bodyrig_rig_url"' in link
    and 'getStringExtra", "bodyrig_rig_token"' in link
    and 'EXTRA_RIG_URL = "bodyrig_rig_url"' in bridge
    and 'EXTRA_RIG_TOKEN = "bodyrig_rig_token"' in bridge,
    "Unity intent extras match the landed Kaliv->Kaliv Body bridge exactly",
)
check(
    'PACKAGE = "dk.ternedal.kalivbody"' in bridge
    and "launch.setPackage(PACKAGE)" in bridge,
    "Kaliv pins the credential-carrying launch intent to the body package",
)
check(
    "HumanBodyBones" not in link
    and "VRM10" not in link
    and "renderer.Apply" not in link,
    "rig link resolves transport authority only; it cannot animate the body",
)
check(
    'Debug.Log("BodyRig: rig link resolved from " + source + " (" + BaseUrl + ")")' in link
    and '" + Token' not in link
    and '" + token' not in link,
    "rig-link logging never interpolates the device token",
)
check(
    "placement.Loader = loader;" in bootstrap
    and "BodyRigRigLink" in bootstrap
    and "link.Resolved +=" in bootstrap
    and bootstrap.index("link.Resolved +=") < bootstrap.index("root.AddComponent<BodyRigFrameSource>()"),
    "rig-link wiring preserves AR ownership and starts frames only after resolution",
)
check(
    "RuntimePlatform.Android" in bootstrap
    and "environmentMentioned" in bootstrap
    and 'player.ResourceName = "bodyrig-demo";' in bootstrap,
    "Android resolves host authority while unconfigured desktop keeps the fixture path",
)
check(
    "launched without rig authority" in link
    and "Start it from Kaliv" in link,
    "standalone Android without Kaliv authority fails visibly rather than pairing itself",
)

meta = META.read_text(encoding="utf-8").splitlines()
check(meta[:1] == ["fileFormatVersion: 2"]
      and len(meta) >= 2
      and meta[1].startswith("guid: ")
      and len(meta[1].removeprefix("guid: ")) == 32,
      "rig-link source has stable committed Unity GUID metadata")

print(f"\nBodyRig rig-link software contract: {passed} passed, {failed} failed")
raise SystemExit(0 if failed == 0 else 1)
