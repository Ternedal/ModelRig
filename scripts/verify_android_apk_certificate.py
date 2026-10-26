#!/usr/bin/env python3
"""Verify an APK signer SHA-256 certificate digest without disclosing secrets."""
import argparse
import re
import subprocess
import sys
from pathlib import Path

DIGEST = re.compile(r"^[0-9a-fA-F]{64}$")
CERT_LINE = re.compile(r"^Signer #\d+ certificate SHA-256 digest:\s*([0-9a-fA-F:]+)\s*$", re.MULTILINE)


def normalize_digest(value: str) -> str:
    digest = value.replace(":", "").strip().lower()
    if not DIGEST.fullmatch(digest):
        raise ValueError("Expected a SHA-256 certificate fingerprint (64 hex characters)")
    return digest


def extract_signer_digests(output: str) -> list[str]:
    return [normalize_digest(match) for match in CERT_LINE.findall(output)]


def verify(apksigner: str, apk: str, expected: str) -> None:
    result = subprocess.run(
        [apksigner, "verify", "--print-certs", apk],
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise ValueError("APK signature verification failed")
    actual = extract_signer_digests(result.stdout)
    if len(actual) != 1:
        raise ValueError(f"Expected exactly one APK signer, found {len(actual)}")
    if actual[0] != normalize_digest(expected):
        raise ValueError("APK signing certificate fingerprint does not match the pinned identity")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apksigner", required=True)
    parser.add_argument("--apk", required=True)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    try:
        if not Path(args.apk).is_file():
            raise ValueError("APK file does not exist")
        verify(args.apksigner, args.apk, args.expected_sha256)
    except (ValueError, OSError) as exc:
        print(f"APK certificate gate failed: {exc}", file=sys.stderr)
        return 1
    print("APK certificate fingerprint matches the pinned signing identity")
    return 0


if __name__ == "__main__":
    sys.exit(main())
