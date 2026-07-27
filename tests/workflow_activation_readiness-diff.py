"""Temporary exact diff for the generated activation-readiness gate."""
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
strip = lambda value: re.sub(r"\*\*Genereret:\*\*.*", "", value)  # noqa: E731
if strip(current) != strip(generated):
    print("===== ACTIVATION READINESS GENERATED DIFF =====")
    print(
        "".join(
            difflib.unified_diff(
                current.splitlines(keepends=True),
                generated.splitlines(keepends=True),
                fromfile="committed/ACTIVATION_READINESS.md",
                tofile="generated/ACTIVATION_READINESS.md",
            )
        )
    )
    print("===== END ACTIVATION READINESS GENERATED DIFF =====")
else:
    print("activation readiness has no non-timestamp drift")
