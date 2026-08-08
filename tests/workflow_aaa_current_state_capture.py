#!/usr/bin/env python3
"""Temporary CI-only capture of the exact generated CURRENT_STATE.md bytes."""
from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
target = root / "CURRENT_STATE.md"
original = target.read_bytes()
try:
    subprocess.run([sys.executable, str(root / "scripts" / "current_state.py")], cwd=root, check=True)
    generated = target.read_bytes()
    print("MODELRIG_CURRENT_STATE_BASE64_BEGIN")
    print(base64.b64encode(generated).decode("ascii"))
    print("MODELRIG_CURRENT_STATE_BASE64_END")
finally:
    target.write_bytes(original)

print("temporary current-state capture: PASS")
