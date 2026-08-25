#!/usr/bin/env python3
"""Fail-closed contract gate: every API path the Android app calls must have a
registered backend route.

Shipping 2.0.11 proved why this must live in CI and not on the rig: the app's
tools client called POST /api/v1/tools/chat/stream, the backend never
registered that route, and the break was only caught by the physical task_ui
gate after release (#754). This gate derives both sides from the code -- it is
not a name list -- so the next route added to one side without the other fails
the PR, not the rig day.

Scope and honest limits:
* App side: string-literal URL templates of the form "$base/api/v1/..." in
  ModelRigClient.kt. Kotlin interpolation segments ($var / ${expr}) are
  normalised to a wildcard segment. Paths assembled by string concatenation
  outside one literal are NOT seen by this gate.
* Backend side: mux.Handle("METHOD /api/v1/...") registrations anywhere in
  backend/internal/httpapi (conditionally registered routes count: the gate
  checks the code surface, not runtime flags).
* Matching is path-based, not method-based: a missing path is the failure
  class this gate exists for.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_CLIENT = ROOT / "android" / "app" / "src" / "main" / "java" / "dk" / "ternedal" / "modelrig" / "net" / "ModelRigClient.kt"
BACKEND_DIR = ROOT / "backend" / "internal" / "httpapi"

APP_PATH_RE = re.compile(r'"\$base(/api/v1/[^"\s]*)"')
MUX_RE = re.compile(r'mux\.Handle(?:Func)?\(\s*"(?:[A-Z]+ )?(/api/v1/[^"]+)"')


def _normalise_app_path(raw: str) -> str:
    segments = []
    for seg in raw.strip("/").split("/"):
        if "$" in seg or "{" in seg:
            segments.append("*")
        else:
            segments.append(seg)
    return "/" + "/".join(segments)


def _normalise_backend_pattern(raw: str) -> str:
    segments = []
    for seg in raw.strip("/").split("/"):
        if seg.startswith("{") and seg.endswith("}"):
            segments.append("*")
        else:
            segments.append(seg)
    return "/" + "/".join(segments)


def app_paths() -> list[str]:
    text = APP_CLIENT.read_text(encoding="utf-8")
    found = sorted({_normalise_app_path(m) for m in APP_PATH_RE.findall(text)})
    if not found:
        raise SystemExit("FAIL: no $base/api/v1 literals found in ModelRigClient.kt -- the extractor is broken, not the app")
    return found


def backend_patterns() -> set[str]:
    patterns: set[str] = set()
    for path in sorted(BACKEND_DIR.glob("*.go")):
        if path.name.endswith("_test.go"):
            continue
        for m in MUX_RE.findall(path.read_text(encoding="utf-8")):
            patterns.add(_normalise_backend_pattern(m))
    if not patterns:
        raise SystemExit("FAIL: no mux.Handle registrations found -- the extractor is broken, not the backend")
    return patterns


def _matches(app_path: str, patterns: set[str]) -> bool:
    app_segs = app_path.strip("/").split("/")
    for pattern in patterns:
        pat_segs = pattern.strip("/").split("/")
        if len(pat_segs) != len(app_segs):
            continue
        if all(p == "*" or a == "*" or p == a for p, a in zip(pat_segs, app_segs)):
            return True
    return False


def main() -> int:
    patterns = backend_patterns()
    paths = app_paths()

    # Self-test 1: a path that cannot exist must be reported missing.
    if _matches("/api/v1/tools/chat/stream-selftest-missing", patterns):
        print("FAIL: self-test: an unregistered path was accepted")
        return 1
    print("  PASS: self-test: an unregistered path is detected")
    # Self-test 2: removing a known registration must flip its caller to failing.
    probe = paths[0]
    if _matches(probe, patterns) and not _matches(probe, {p for p in patterns if not _matches(probe, {p})}):
        print("  PASS: self-test: removing a registration is detected")
    else:
        print("FAIL: self-test: a removed registration went unnoticed")
        return 1

    failed = []
    for p in paths:
        if _matches(p, patterns):
            print(f"  PASS: app call has a backend route: {p}")
        else:
            print(f"  FAIL: app calls {p} but no backend route registers it")
            failed.append(p)

    print(f"app-backend route contract: {len(paths) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
