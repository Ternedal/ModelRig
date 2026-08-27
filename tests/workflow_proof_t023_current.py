#!/usr/bin/env python3
"""Regression contract for the current-checkout T-023 proof wrapper."""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "proof_t023_current.py"


def main() -> int:
    if not WRAPPER.is_file():
        print("FAIL: scripts/proof_t023_current.py mangler")
        return 1

    text = WRAPPER.read_text(encoding="utf-8")
    enable = 'os.environ["KALIV_AGENT3_TASK_UI"]="1"'
    launch = "return int(op.main())"

    checks = {
        "T-023 proof opts its child stack into the dedicated task UI": enable in text,
        "task UI opt-in happens before the physical operator starts": (
            enable in text and launch in text and text.index(enable) < text.index(launch)
        ),
        "proof wrapper does not claim production activation": (
            "production_activation=true" not in text.lower()
            and "production_activation = true" not in text.lower()
        ),
    }

    failed = 0
    for name, ok in checks.items():
        print(f"  {'PASS' if ok else 'FAIL'}: {name}")
        failed += 0 if ok else 1

    print(f"T-023 current proof wrapper: {len(checks)-failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
