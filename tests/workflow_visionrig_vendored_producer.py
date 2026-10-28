#!/usr/bin/env python3
"""The vendored VisionRig producer is exactly what one VisionRig SHA contained.

ModelRig #2275 (decision 6478056078): the Android app carries VisionRig's
Kaliv producer as a pinned copy in its own module, android/visionrig-producer
(scripts/sync_visionrig_producer.py). This gate runs offline. It fails when a
vendored file is edited, added or removed by hand, when the manifest loses its
provenance or license, or when the module stops being the only place the copy
lives, so every change has to come from VisionRig at a named commit.

Run: python3 tests/workflow_visionrig_vendored_producer.py
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "android/visionrig-producer"
MANIFEST = MODULE / "VENDORED_FROM.json"
UPSTREAM_ROOTS = (
    "clients/kaliv-producer-core/src/main/kotlin",
    "clients/kaliv-android-producer/library/src/main/kotlin",
)

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
provenance = manifest.get("provenance", {})
license_ = manifest.get("license", {})
entries = manifest.get("files", [])

check(manifest.get("schema") == "modelrig/vendored-source/v1", "manifest schema")
check(provenance.get("repository") == "https://github.com/Ternedal/VisionRig", "provenance names the VisionRig repository")
check(bool(re.fullmatch(r"[0-9a-f]{40}", provenance.get("sha", ""))), "provenance pins one full 40-hex VisionRig SHA")
check(tuple(provenance.get("upstream_roots", ())) == UPSTREAM_ROOTS, "provenance lists the two upstream source roots")
check(provenance.get("synced_by") == "scripts/sync_visionrig_producer.py", "provenance names the sync script")

license_file = MODULE / license_.get("file", "")
check(license_.get("spdx") == "MIT" and license_file.is_file(), "MIT license notice is vendored alongside")
check(license_file.is_file() and sha256(license_file) == license_.get("sha256"), "license notice matches its SHA-256")
check(license_file.is_file() and "MIT License" in license_file.read_text(encoding="utf-8"), "license notice is the MIT text")

check(len(entries) >= 10, f"manifest lists the producer sources ({len(entries)})")
check(all(set(e) == {"upstream", "destination", "sha256"} for e in entries), "every entry has upstream, destination and sha256")
check(all(any(e["upstream"].startswith(r + "/") for r in UPSTREAM_ROOTS) for e in entries),
      "every upstream path lies under a declared root")
check(all(e["destination"] == "src/main/kotlin/" + e["upstream"].split("/src/main/kotlin/", 1)[1] for e in entries),
      "destination is the upstream path under src/main/kotlin (reproducible mapping)")
check(all(e["destination"].startswith("src/main/kotlin/dk/kaliv/visionrig/") for e in entries),
      "only VisionRig's own packages are vendored")

destinations = sorted(e["destination"] for e in entries)
on_disk = sorted(p.relative_to(MODULE).as_posix() for p in (MODULE / "src").rglob("*") if p.is_file())
check(on_disk == destinations, "no vendored file was added or removed by hand")
changed = [e["destination"] for e in entries
           if not (MODULE / e["destination"]).is_file() or sha256(MODULE / e["destination"]) != e["sha256"]]
check(not changed, f"every vendored file matches its SHA-256 ({changed[:3] or 'all match'})")

# The copy must live only in its module, never inside the app's own sources.
stray = sorted(p.relative_to(ROOT).as_posix()
               for p in (ROOT / "android/app/src").rglob("*.kt")
               if p.read_text(encoding="utf-8", errors="replace").lstrip().startswith("package dk.kaliv.visionrig"))
check(not stray, f"no VisionRig source is copied into the app module ({stray[:2] or 'none'})")

settings = (ROOT / "android/settings.gradle.kts").read_text(encoding="utf-8")
app_build = (ROOT / "android/app/build.gradle.kts").read_text(encoding="utf-8")
check('include(":visionrig-producer")' in settings, "the module is part of the Android build")
check('implementation(project(":visionrig-producer"))' in app_build, "the app depends on the module, not on copied sources")

# Control: the comparison can fail.
check(hashlib.sha256(b"edited").hexdigest() != entries[0]["sha256"], "control: a changed file would not match")

print(f"\n===== VISIONRIG VENDORED PRODUCER: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
