#!/usr/bin/env python3
"""Temporary CI probe: print the exact generated readiness diff."""
from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import activation_readiness as readiness  # noqa: E402

current = (ROOT / "ACTIVATION_READINESS.md").read_text(encoding="utf-8")
generated = readiness.render()
strip_timestamp = lambda text: re.sub(r"\*\*Genereret:\*\*.*", "", text)

if strip_timestamp(current) == strip_timestamp(generated):
    print("READINESS_PROBE_MATCH")
    raise SystemExit(0)

print("READINESS_PROBE_DIFF_BEGIN")
print(
    "".join(
        difflib.unified_diff(
            current.splitlines(keepends=True),
            generated.splitlines(keepends=True),
            fromfile="committed/ACTIVATION_READINESS.md",
            tofile="generated/ACTIVATION_READINESS.md",
        )
    ),
    end="",
)
print("READINESS_PROBE_DIFF_END")
raise SystemExit(1)
