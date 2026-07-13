#!/usr/bin/env python3
"""Single source of truth for the ModelRig/Kaliv version.

The semver lives in the repo-root VERSION file. Every place that hard-codes it is
kept in sync from there, and CI verifies they match -- so "bump five files by
hand and hope" becomes "edit one file, run one command, CI catches drift".

Usage:
  python scripts/version_tool.py check              # assert all sites == VERSION (CI gate; exit 1 on drift)
  python scripts/version_tool.py check --tag vX.Y.Z # also assert a release tag matches VERSION
  python scripts/version_tool.py sync               # rewrite all sites to match VERSION
  python scripts/version_tool.py set X.Y.Z          # write X.Y.Z to VERSION, then sync

Sites kept in sync (the four lockstep semver locations):
  worker/app/main.py                    VERSION = "X.Y.Z"
  backend/internal/config/config.go     const Version = "X.Y.Z"
  android/app/build.gradle.kts          versionName = "X.Y.Z"
  desktop/composeApp/build.gradle.kts   packageVersion = "X.Y.Z"

Deliberately NOT handled here:
  - Android versionCode: a monotonic integer in ONE file -- not a cross-site drift
    risk. Bump by hand, or derive from semver later (major*10000+minor*100+patch).
  - Docs (STATUS/HANDOFF/ROADMAP) and the git tag: check the tag in CI with
    `check --tag "$GITHUB_REF_NAME"`.
"""
from __future__ import annotations

import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
VERSION_FILE = REPO / "VERSION"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")

# (path, regex with exactly one capture group (group 2) around the semver)
SITES = [
    ("worker/app/main.py", re.compile(r'(VERSION = ")(\d+\.\d+\.\d+)(")')),
    ("backend/internal/config/config.go", re.compile(r'(const Version = ")(\d+\.\d+\.\d+)(")')),
    ("android/app/build.gradle.kts", re.compile(r'(versionName = ")(\d+\.\d+\.\d+)(")')),
    ("desktop/composeApp/build.gradle.kts", re.compile(r'(packageVersion = ")(\d+\.\d+\.\d+)(")')),
]


def read_version() -> str:
    v = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not SEMVER.match(v):
        sys.exit(f"VERSION file is not semver: {v!r}")
    return v


def site_version(path: str, rx: "re.Pattern[str]") -> str | None:
    m = rx.search((REPO / path).read_text(encoding="utf-8"))
    return m.group(2) if m else None


def cmd_check(argv: list[str]) -> int:
    want = read_version()
    ok = True
    for path, rx in SITES:
        got = site_version(path, rx)
        if got is None:
            print(f"FAIL  {path}: version pattern not found")
            ok = False
        elif got != want:
            print(f"FAIL  {path}: {got} != VERSION {want}")
            ok = False
        else:
            print(f"ok    {path}: {got}")
    if "--tag" in argv:
        tag = argv[argv.index("--tag") + 1].lstrip("v")
        if tag != want:
            print(f"FAIL  tag {tag} != VERSION {want}")
            ok = False
        else:
            print(f"ok    tag: v{tag}")
    if not ok:
        print(f"\nVERSION drift (source of truth: VERSION = {want}). Fix: python scripts/version_tool.py sync")
        return 1
    print(f"\nall sites match VERSION {want}")
    return 0


def cmd_sync(_argv: list[str]) -> int:
    want = read_version()
    changed = 0
    for path, rx in SITES:
        p = REPO / path
        text = p.read_text(encoding="utf-8")
        new, n = rx.subn(lambda m: m.group(1) + want + m.group(3), text)
        if n == 0:
            print(f"WARN  {path}: pattern not found, skipped")
        elif new != text:
            p.write_text(new, encoding="utf-8")
            print(f"set   {path} -> {want}")
            changed += 1
        else:
            print(f"ok    {path}: already {want}")
    print(f"\nsynced {changed} file(s) to VERSION {want}")
    return 0


def cmd_set(argv: list[str]) -> int:
    if not argv or not SEMVER.match(argv[0]):
        sys.exit("usage: version_tool.py set X.Y.Z")
    VERSION_FILE.write_text(argv[0] + "\n", encoding="utf-8")
    print(f"VERSION -> {argv[0]}")
    return cmd_sync([])


def main() -> int:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd, rest = sys.argv[1], sys.argv[2:]
    return {"check": cmd_check, "sync": cmd_sync, "set": cmd_set}.get(
        cmd, lambda a: sys.exit(__doc__)
    )(rest)


if __name__ == "__main__":
    raise SystemExit(main())
