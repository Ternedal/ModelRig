#!/usr/bin/env python3
"""Static contract for the Android BodyRig remote active-avatar source.

Software proof only: no network/device run or production activation is claimed.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "support"))
from source_code import code_of  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "renderers" / "bodyrig-unity" / "Assets" / "BodyRig" / "Runtime"
SOURCE_PATH = RUNTIME / "BodyRigRemoteAvatarSource.cs"
META_PATH = RUNTIME / "BodyRigRemoteAvatarSource.cs.meta"

source = code_of(SOURCE_PATH)
bootstrap = code_of(RUNTIME / "BodyRigDemoBootstrap.cs")

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


check(SOURCE_PATH.is_file() and META_PATH.is_file(),
      "remote avatar source and committed Unity metadata both exist")

for required in (
    '"/api/v1/body/active"',
    '"/api/v1/body/active/bodyprint.json"',
    '"/api/v1/body/active/avatar.vrm"',
    '"modelrig-body-assets/v1"',
    '"X-BodyRig-Body-ID"',
    '"X-BodyRig-Package-SHA256"',
    '"X-BodyRig-Member-SHA256"',
    "responseBodyId != manifest.body_id",
    "responsePackage != manifest.package_sha256",
    "!IsLowerHex(memberSha, 64)",
    "Sha256(avatarBytes)",
    "!string.Equals(actualSha, memberSha, StringComparison.Ordinal)",
    "Application.persistentDataPath",
    "loader.LoadAsync(path)",
    '"modelrig-bodyprint"',
    "bodyprint.version != 1",
    "float.IsNaN(value)",
    "float.IsInfinity(value)",
    "value > 4.0f",
    "instance.transform.localScale = Vector3.one * heightScale;",
):
    check(required in source, f"remote avatar source contains {required}")

check(
    source.count('"X-BodyRig-Body-ID"') >= 2
    and source.count('"X-BodyRig-Package-SHA256"') >= 2
    and source.count('"X-BodyRig-Member-SHA256"') >= 2,
    "bodyprint and avatar both bind to explicit body/package/member receipt headers",
)
check(
    "bodyprint identity/digest validation failed" in source
    and "Sha256(bodyprintBytes)" in source,
    "bodyprint bytes are digest-verified before parsing shape",
)
check(
    "request.redirectLimit = 0;" in source
    and 'request.SetRequestHeader("Authorization", "Bearer " + token.Trim());' in source
    and 'request.SetRequestHeader("Cache-Control", "no-store");' in source,
    "avatar requests are bearer-authenticated, no-store and refuse redirects",
)
check(
    "MaxAvatarBytes = 192 * 1024 * 1024" in source
    and "avatarBytes.Length > MaxAvatarBytes" in source,
    "avatar download has an explicit memory/asset size ceiling",
)
check(
    "MaxBodyprintBytes = 1024 * 1024" in source
    and "bodyprintBytes.Length > MaxBodyprintBytes" in source,
    "BodyPrint metadata has an explicit one-megabyte ceiling",
)
check(
    "Vrm10." not in source
    and "BodyRigVrmRenderer" not in source
    and "BindAvatarRoot" not in source,
    "remote source owns transport/cache only, not VRM parsing or renderer authority",
)
check(
    "Token =" not in source
    and "Bearer " in source
    and "remote avatar source failed: " in source,
    "token is consumed for Authorization but never emitted by source logging",
)

check(
    "loader.LoadOnStart = Application.platform != RuntimePlatform.Android;" in bootstrap,
    "Android disables the desktop-only local VRM path startup",
)
check(
    "root.AddComponent<BodyRigRemoteAvatarSource>()" in bootstrap
    and "avatarSource.Loader = loader;" in bootstrap
    and "avatarSource.BaseUrl = url;" in bootstrap
    and "avatarSource.Token = token;" in bootstrap
    and "avatarSource.Begin();" in bootstrap,
    "RigLink resolution starts the remote avatar source with the existing loader",
)
check(
    bootstrap.index("avatarSource.Begin();") < bootstrap.index("root.AddComponent<BodyRigFrameSource>()"),
    "avatar acquisition is initiated before creating the live frame source",
)
check(
    "production_activation" not in source,
    "remote avatar transport has no production-authority field",
)

meta = META_PATH.read_text(encoding="utf-8").splitlines()
check(
    meta[:1] == ["fileFormatVersion: 2"]
    and len(meta) >= 2
    and meta[1].startswith("guid: ")
    and len(meta[1].removeprefix("guid: ")) == 32,
    "remote avatar source has stable committed Unity GUID metadata",
)

print(f"\nBodyRig remote avatar contract: {passed} passed, {failed} failed")
raise SystemExit(0 if failed == 0 else 1)
