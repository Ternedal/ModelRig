"""Temporary exact diff for the generated route inventory gate."""
from __future__ import annotations

import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import route_inventory  # noqa: E402

current = (ROOT / "ROUTE_INVENTORY.md").read_text(encoding="utf-8")
generated = route_inventory.build()
if current.strip() != generated.strip():
    print("===== ROUTE INVENTORY GENERATED DIFF =====")
    print(
        "".join(
            difflib.unified_diff(
                current.splitlines(keepends=True),
                generated.splitlines(keepends=True),
                fromfile="committed/ROUTE_INVENTORY.md",
                tofile="generated/ROUTE_INVENTORY.md",
            )
        )
    )
    print("===== END ROUTE INVENTORY GENERATED DIFF =====")
else:
    print("route inventory has no drift")
