#!/usr/bin/env python3
"""Bind A4-18 physical receipt audit to one non-superseded exact head."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

SUPSERSEDED_HEADS = {
    "cb9dc522066b4f34df13a89a42f7bceb51851929",
    "ce6cbbbd02003f6e35cf2986c7b24b326add5fee",
    "ab7448280135f7be575a2050123ce020639aab61",
    "42f1d9b915aa8fa5233f5cc4d8a8a881773ac3b0",
    "dc8982b2ecae47566da22b9cde180922ef228e10",
}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def git(repo_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise ValueError(f"git {' '.join(args)} fejlede")
    return completed.stdout.strip()


def validate(repo_root: Path, receipt_path: Path, expected_sha: str) -> None:
    require(bool(SHA_RE.fullmatch(expected_sha)), "Expected SHA skal være 40 lowercase hex")
    require(expected_sha not in SUPSERSEDED_HEADS, "Expected SHA er superseded og må ikke autorisere fysisk audit")
    observed = git(repo_root, "rev-parse", "HEAD").lower()
    require(observed == expected_sha, "Local HEAD matcher ikke den eksplicit forventede SHA")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    require(isinstance(receipt, dict), "Receipt skal være et JSON-objekt")
    require(
        receipt.get("expected_sha") == expected_sha
        and receipt.get("observed_head") == expected_sha,
        "Receiptens expected_sha/observed_head matcher ikke authority",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        require(len(SUPSERSEDED_HEADS) >= 5, "superseded-head self-test fejlede")
        print("A4-18 exact-head gate self-test: PASS")
        return 0
    try:
        validate(args.repo_root.resolve(), args.receipt.resolve(), args.expected_sha)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"A4-18 EXACT-HEAD GATE: FAIL: {exc}")
        return 2
    print("A4-18 EXACT-HEAD GATE: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
