#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent3.memory_protected_leak_gate import scan_runtime_mounts  # noqa: E402

checks: list[tuple[str, bool]] = []


def check(label: str, condition: object) -> None:
    checks.append((label, bool(condition)))


check(
    "current repository satisfies the exact promoted mount contract",
    scan_runtime_mounts(ROOT) == [],
)

with tempfile.TemporaryDirectory(prefix="kaliv-t033-mount-gate-") as raw:
    fake = Path(raw)
    helper_relative = "worker/app/agent3/memory_surface.py"
    other_relative = "worker/app/agent3/planner.py"
    helper = fake / helper_relative
    other = fake / other_relative
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text(
        "\n".join(
            (
                'PROTECTED_MEMORY_MOUNT_CONTRACT = "kaliv-agent3-protected-memory-mount/v1"',
                "AUTOMATIC_MIGRATION = False",
                "PROTECTED_TO_LEGACY_FALLBACK = False",
                "mode = memory_store_mode()",
                'if mode == "legacy":',
                "    pass",
                "signing_material = protected_memory_secret()",
                "ProtectedMemoryGrantReplayLedger",
                "planner_memory_store=None",
                "build_protected_memory_router",
                "ProtectedMemoryReader",
                "ProtectedMemoryWriter",
            )
        ),
        encoding="utf-8",
    )
    other.write_text("# clean runtime boundary\n", encoding="utf-8")
    files = (helper_relative, other_relative)
    check(
        "synthetic exact authorized boundary passes",
        scan_runtime_mounts(fake, files=files) == [],
    )

    original = helper.read_text(encoding="utf-8")
    helper.write_text(
        original.replace("PROTECTED_TO_LEGACY_FALLBACK = False\n", ""),
        encoding="utf-8",
    )
    check(
        "missing no-fallback declaration fails closed",
        any(
            item.kind == "implicit_mount"
            for item in scan_runtime_mounts(fake, files=files)
        ),
    )

    helper.write_text(original + "\nMemoryProtectionMigrator\n", encoding="utf-8")
    check(
        "migrator import in authorized boundary fails closed",
        any(
            item.kind == "implicit_mount"
            for item in scan_runtime_mounts(fake, files=files)
        ),
    )

    helper.write_text(original, encoding="utf-8")
    other.write_text("ProtectedMemoryReader\n", encoding="utf-8")
    findings = scan_runtime_mounts(fake, files=files)
    check(
        "protected symbol outside authorized boundary fails closed",
        any(
            item.location == other_relative and item.kind == "implicit_mount"
            for item in findings
        ),
    )

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== T-033 PROTECTED MOUNT GATE: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
