from __future__ import annotations

import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "worker/app/tools.py",
    "worker/app/capability_schema.py",
    "backend/internal/capabilityschema/schema.go",
    "backend/internal/capabilityschema/schema_test.go",
    "contracts/kaliv-capability-v2.schema.json",
    "contracts/kaliv-capability-v2-fixtures.json",
    "tests/worker_capability_schema_v2.py",
    "CURRENT_STATE.md",
)

for relative in FILES:
    raw = (ROOT / relative).read_bytes()
    encoded = base64.b64encode(raw).decode("ascii")
    print(f"T030_SOURCE_BEGIN {relative}")
    print(encoded)
    print(f"T030_SOURCE_END {relative}")

raise SystemExit("intentional source-bundle diagnostic")
