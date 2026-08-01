#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTEXT_FILE = "worker/app/agent3/memory_protected_context.py"
RUNTIME_IMPORTERS = (
    "worker/app/agent3/production_mount.py",
    "worker/app/agent3/memory_surface.py",
    "worker/app/agent3/planner.py",
    "worker/app/agent3/outcome_answer.py",
    "worker/app/agent3/outcome_context.py",
)
REQUIRED_MARKERS = (
    'PROTECTED_CONTEXT_BOUNDARY = "dormant-local-only"',
    "PRODUCTION_MOUNT = False",
    "CLOUD_CONTEXT_ALLOWED = False",
    "ContextTarget.LOCAL",
    "allow_private_cloud=False",
)
FORBIDDEN_CONTEXT_MARKERS = (
    "MemoryProtectionMigrator",
    "build_protected_memory_router",
    "production_mount",
)
checks: list[tuple[str, bool]] = []


def check(label: str, condition: object) -> None:
    checks.append((label, bool(condition)))


def findings(root: Path) -> list[str]:
    context = (root / CONTEXT_FILE).read_text(encoding="utf-8")
    result = [f"missing:{marker}" for marker in REQUIRED_MARKERS if marker not in context]
    result.extend(
        f"forbidden:{marker}" for marker in FORBIDDEN_CONTEXT_MARKERS if marker in context
    )
    for relative in RUNTIME_IMPORTERS:
        text = (root / relative).read_text(encoding="utf-8")
        if "memory_protected_context" in text or "ProtectedMemoryContextCompiler" in text:
            result.append(f"mounted:{relative}")
    return result


check(
    "current repository keeps protected context dormant and local-only",
    findings(ROOT) == [],
)

with tempfile.TemporaryDirectory(prefix="kaliv-t033-context-mount-") as raw:
    fake = Path(raw)
    for relative in (CONTEXT_FILE, *RUNTIME_IMPORTERS):
        path = fake / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# clean boundary\n", encoding="utf-8")

    context = fake / CONTEXT_FILE
    context.write_text("\n".join(REQUIRED_MARKERS) + "\n", encoding="utf-8")
    check("synthetic exact dormant boundary passes", findings(fake) == [])

    original = context.read_text(encoding="utf-8")
    context.write_text(original.replace("PRODUCTION_MOUNT = False\n", ""), encoding="utf-8")
    check(
        "missing no-mount marker fails closed",
        any(item.startswith("missing:") for item in findings(fake)),
    )

    context.write_text(original + "MemoryProtectionMigrator\n", encoding="utf-8")
    check(
        "migrator import in compiler fails closed",
        any(item.startswith("forbidden:") for item in findings(fake)),
    )

    context.write_text(original, encoding="utf-8")
    planner = fake / "worker/app/agent3/planner.py"
    planner.write_text("from .memory_protected_context import ProtectedMemoryContextCompiler\n", encoding="utf-8")
    check(
        "planner import before approved promotion fails closed",
        "mounted:worker/app/agent3/planner.py" in findings(fake),
    )

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== T-033 PROTECTED CONTEXT MOUNT GATE: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
