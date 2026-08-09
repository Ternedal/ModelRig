#!/usr/bin/env python3
"""Fail closed when an A4-18 receipt lacks a numeric Pixel SDK."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def validate(receipt_path: Path) -> None:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    if not isinstance(receipt, dict):
        raise ValueError("receipt skal være et JSON-objekt")
    pixel = receipt.get("pixel")
    if not isinstance(pixel, dict):
        raise ValueError("pixel mangler")
    sdk = pixel.get("sdk")
    if not isinstance(sdk, str) or not sdk.isdigit():
        raise ValueError("Pixel SDK skal være en numerisk streng")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        validate(args.receipt.resolve())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"A4-18 PIXEL SDK CHECK: FAIL: {exc}")
        return 2
    print("A4-18 PIXEL SDK CHECK: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
