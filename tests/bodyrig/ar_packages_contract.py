#!/usr/bin/env python3
"""Static dependency contract for BodyRig Android AR packages.

This pins the package graph used by the Unity 6000.3 renderer. It is software
configuration evidence only; no Android/ARCore runtime or production activation
is claimed.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ROOT / "renderers" / "bodyrig-unity" / "Packages"
manifest = json.loads((PACKAGES / "manifest.json").read_text(encoding="utf-8"))
lock = json.loads((PACKAGES / "packages-lock.json").read_text(encoding="utf-8"))
deps = manifest["dependencies"]
locked = lock["dependencies"]

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


for package in ("com.unity.xr.arfoundation", "com.unity.xr.arcore"):
    check(deps.get(package) == "6.3.5", f"{package} is pinned to Unity-6000.3 release 6.3.5")
    entry = locked.get(package, {})
    check(entry.get("version") == "6.3.5", f"{package} lock version matches manifest")
    check(entry.get("depth") == 0, f"{package} is a direct dependency")
    check(entry.get("source") == "registry", f"{package} comes from Unity registry")
    check(entry.get("url") == "https://packages.unity.com", f"{package} registry origin is explicit")

check(
    locked["com.unity.xr.arcore"]["dependencies"].get("com.unity.xr.arfoundation") == "6.3.5",
    "ARCore binds the exact AR Foundation version",
)
check(
    locked["com.unity.xr.arfoundation"]["dependencies"].get("com.unity.xr.core-utils") == "2.5.1",
    "AR Foundation core-utils dependency matches upstream package metadata",
)
check(
    locked["com.unity.xr.arfoundation"]["dependencies"].get("com.unity.xr.management") == "4.4.0",
    "AR Foundation XR management dependency matches upstream package metadata",
)
check(
    locked["com.unity.xr.management"]["dependencies"].get("com.unity.xr.legacyinputhelpers") == "2.1.7",
    "XR management legacy-input dependency is explicitly locked",
)

for package, version in (
    ("com.unity.editorcoroutines", "1.0.0"),
    ("com.unity.inputsystem", "1.6.3"),
    ("com.unity.ugui", "2.0.0"),
    ("com.unity.xr.core-utils", "2.5.1"),
    ("com.unity.xr.management", "4.4.0"),
    ("com.unity.xr.legacyinputhelpers", "2.1.7"),
):
    check(locked.get(package, {}).get("version") == version, f"{package} resolves to {version}")

for package in ("com.unity.xr.arfoundation", "com.unity.xr.arcore"):
    version = deps[package]
    check("pre" not in version and "*" not in version and "http" not in version,
          f"{package} uses a stable numeric pin, not preview/floating/git")

print(f"\nBodyRig AR package contract: {passed} passed, {failed} failed")
raise SystemExit(0 if failed == 0 else 1)
