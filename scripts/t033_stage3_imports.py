#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = "from support_memory_protector import TestMemoryProtector"
NEW = "from helpers.memory_protector import TestMemoryProtector"
PATHS = (
    "tests/worker_agent3_memory.py",
    "tests/worker_agent3_memory_api.py",
    "tests/worker_agent3_memory_context.py",
    "tests/worker_agent3_memory_storage_protection.py",
    "tests/worker_agent3_planner_memory.py",
)

for relative in PATHS:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    count = text.count(OLD)
    if count != 1:
        raise SystemExit(f"{relative}: expected one helper import, found {count}")
    path.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")

print("T-033 test helper imports relocated")
