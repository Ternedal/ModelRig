#!/usr/bin/env python3
"""Fail-closed era-pin gate: every era-bearing site must agree with release authority.

The target is always VERSION. The Stage B source is an explicit published-release
authority because release numbers can be skipped: 2.0.13 was never published, so
deriving source as target-1 would invent a non-existent appliance.

A future release must update SOURCE_RELEASE_VERSION in the same reviewed change
that moves Stage B authority. This is deliberately fail-closed: CI checks every
era-bearing site against the explicit source/target pair.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FAILED = 0
SOURCE_RELEASE_VERSION = "2.0.12"


def check(ok: bool, message: str) -> None:
    global FAILED
    if ok:
        print(f"  PASS: {message}")
    else:
        print(f"  FAIL: {message}")
        FAILED = 1


def derive_versions() -> tuple[str, str]:
    target = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", target):
        raise SystemExit(f"FAIL: VERSION {target!r} is not a numeric semver")
    if not re.fullmatch(r"\d+\.\d+\.\d+", SOURCE_RELEASE_VERSION):
        raise SystemExit(
            f"FAIL: SOURCE_RELEASE_VERSION {SOURCE_RELEASE_VERSION!r} is not a numeric semver"
        )
    if SOURCE_RELEASE_VERSION == target:
        raise SystemExit("FAIL: Stage B source release must differ from target VERSION")
    return SOURCE_RELEASE_VERSION, target


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def run(source: str, target: str, reader) -> None:
    branch_pin = re.compile(r'^BRANCH = "physical-proof/(?P<v>[0-9.]+)"', re.M)
    for path in (
        "scripts/stage_a_one_click.py",
        "scripts/agent3_readonly_pilot_one_click.py",
        "scripts/scheduler_pilot_wizard.py",
    ):
        pins = branch_pin.findall(reader(path))
        check(
            bool(pins) and all(v == target for v in pins),
            f"{path}: BRANCH pins physical-proof/{target} (found {sorted(set(pins)) or 'none'})",
        )

    for path, name, want in (
        ("scripts/stage_a_physical_operator.py", "EXPECTED_VERSION", target),
        ("scripts/agent3_readonly_pilot_one_click.py", "VERSION", target),
        ("scripts/stage_b_one_click_v2.py", "EXPECTED_SOURCE_VERSION", source),
        ("scripts/stage_b_strict_evidence.py", "EXPECTED_SOURCE_VERSION", source),
        ("scripts/stage_b_strict_evidence.py", "EXPECTED_TARGET_VERSION", target),
    ):
        found = re.findall(rf'^{name} = "([0-9.]+)"', reader(path), re.M)
        check(
            bool(found) and all(v == want for v in found),
            f"{path}: {name} == {want} (found {sorted(set(found)) or 'none'})",
        )

    pair_re = re.compile(r'\("1\.58\.14(?P<old>[23])",\s*"(?P<new>[0-9.]+)"\)')
    for path in sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").glob("workflow_*.py")):
        for m in pair_re.finditer(reader(path)):
            want = target if m.group("old") == "3" else source
            check(
                m.group("new") == want,
                f"{path}: substitution 1.58.14{m.group('old')} -> {want} (found {m.group('new')})",
            )

    check(
        f"origin/physical-proof/{target}" in reader("RIGDAG_SIMPEL.md"),
        f"RIGDAG_SIMPEL.md names origin/physical-proof/{target}",
    )
    staged = reader("STAGED_PHYSICAL_PROMOTION.md")
    check(source in staged and target in staged,
          f"STAGED_PHYSICAL_PROMOTION.md keeps both source {source} and target {target} explicit")
    check(f"`{source}`" in reader("STAGE_B_UPDATER_EVIDENCE.md"),
          f"STAGE_B_UPDATER_EVIDENCE.md names source `{source}`")


def main() -> int:
    source, target = derive_versions()
    print(f"era: source {source} (explicit published release) -> target {target} (VERSION)")

    # Self-test: a stale pin must be detected before the real run counts.
    stale = {"scripts/stage_a_one_click.py": f'BRANCH = "physical-proof/{source}"\n'}
    probe_failed = []
    branch_pin = re.compile(r'^BRANCH = "physical-proof/(?P<v>[0-9.]+)"', re.M)
    pins = branch_pin.findall(stale["scripts/stage_a_one_click.py"])
    if pins and all(v == target for v in pins):
        print("  FAIL: self-test: a stale BRANCH pin was accepted")
        return 1
    print("  PASS: self-test: a stale BRANCH pin is detected")

    run(source, target, text)
    print(f"era pins: {'ALL CONSISTENT' if not FAILED else 'DRIFT DETECTED'} for {source} -> {target}")
    return FAILED


if __name__ == "__main__":
    sys.exit(main())
