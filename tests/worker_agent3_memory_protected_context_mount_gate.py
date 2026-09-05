#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CONTEXT_FILE = "worker/app/agent3/memory_protected_context.py"
ADAPTER_FILE = "worker/app/agent3/memory_protected_planner.py"
MOUNT_FILE = "worker/app/agent3/memory_surface.py"
FORBIDDEN_IMPORTERS = (
    "worker/app/agent3/production_mount.py",
    "worker/app/agent3/planner.py",
    "worker/app/agent3/outcome_answer.py",
    "worker/app/agent3/outcome_context.py",
)
CONTEXT_MARKERS = (
    'PROTECTED_CONTEXT_BOUNDARY = "planner-local-only"',
    "PRODUCTION_MOUNT = True",
    "CLOUD_CONTEXT_ALLOWED = False",
    "ContextTarget.LOCAL",
    "allow_private_cloud=False",
)
ADAPTER_MARKERS = (
    'PROTECTED_PLANNER_CONTEXT_CONTRACT = "kaliv-agent3-protected-planner-context/v1"',
    "CLOUD_CONTEXT_ALLOWED = False",
    "LEGACY_STORE_FALLBACK = False",
    "ProtectedMemoryContextCompiler",
    "candidate_multiplier=_CANDIDATE_MULTIPLIER",
    "if selected_target is not ContextTarget.LOCAL",
    "if allow_private_cloud",
)
MOUNT_MARKERS = (
    'PROTECTED_PLANNER_MOUNT_CONTRACT = "kaliv-agent3-protected-planner-mount/v1"',
    "PROTECTED_TO_LEGACY_FALLBACK = False",
    "PROTECTED_PLANNER_CLOUD_ALLOWED = False",
    "planner_context_provider = ProtectedPlannerMemoryContextProvider(reader)",
    "planner_memory_store=None",
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
    context = code_of(root / CONTEXT_FILE)
    adapter = code_of(root / ADAPTER_FILE)
    mount = code_of(root / MOUNT_FILE)
    result = [f"context-missing:{marker}" for marker in CONTEXT_MARKERS if marker not in context]
    result.extend(
        f"context-forbidden:{marker}"
        for marker in FORBIDDEN_CONTEXT_MARKERS
        if marker in context
    )
    result.extend(
        f"adapter-missing:{marker}" for marker in ADAPTER_MARKERS if marker not in adapter
    )
    result.extend(
        f"mount-missing:{marker}" for marker in MOUNT_MARKERS if marker not in mount
    )
    if "memory_protected_context" not in adapter:
        result.append("adapter-does-not-import-context")
    if "memory_protected_planner" not in mount:
        result.append("mount-does-not-import-adapter")
    if "ProtectedMemoryContextCompiler" in mount:
        result.append("mount-bypasses-adapter")
    for relative in FORBIDDEN_IMPORTERS:
        text = code_of(root / relative)
        if "memory_protected_context" in text or "ProtectedMemoryContextCompiler" in text:
            result.append(f"direct-context-import:{relative}")
        if "memory_protected_planner" in text or "ProtectedPlannerMemoryContextProvider" in text:
            result.append(f"direct-adapter-import:{relative}")
    return result


check(
    "current repository promotes protected context only through the exact local planner chain",
    findings(ROOT) == [],
)

with tempfile.TemporaryDirectory(prefix="kaliv-t033-context-mount-") as raw:
    fake = Path(raw)
    for relative in (CONTEXT_FILE, ADAPTER_FILE, MOUNT_FILE, *FORBIDDEN_IMPORTERS):
        path = fake / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# clean boundary\n", encoding="utf-8")

    context = fake / CONTEXT_FILE
    adapter = fake / ADAPTER_FILE
    mount = fake / MOUNT_FILE
    context.write_text("\n".join(CONTEXT_MARKERS) + "\n", encoding="utf-8")
    adapter.write_text(
        "from .memory_protected_context import ProtectedMemoryContextCompiler\n"
        + "\n".join(ADAPTER_MARKERS)
        + "\n",
        encoding="utf-8",
    )
    mount.write_text(
        "from .memory_protected_planner import ProtectedPlannerMemoryContextProvider\n"
        + "\n".join(MOUNT_MARKERS)
        + "\n",
        encoding="utf-8",
    )
    check("synthetic exact planner-only promotion passes", findings(fake) == [])

    original_adapter = adapter.read_text(encoding="utf-8")
    adapter.write_text(
        original_adapter.replace("LEGACY_STORE_FALLBACK = False\n", ""),
        encoding="utf-8",
    )
    check(
        "missing no-fallback marker fails closed",
        any(item.startswith("adapter-missing:") for item in findings(fake)),
    )

    adapter.write_text(original_adapter, encoding="utf-8")
    original_mount = mount.read_text(encoding="utf-8")
    mount.write_text(
        original_mount.replace("PROTECTED_PLANNER_CLOUD_ALLOWED = False\n", ""),
        encoding="utf-8",
    )
    check(
        "missing no-cloud mount marker fails closed",
        any(item.startswith("mount-missing:") for item in findings(fake)),
    )

    mount.write_text(original_mount, encoding="utf-8")
    planner = fake / "worker/app/agent3/planner.py"
    planner.write_text(
        "from .memory_protected_planner import ProtectedPlannerMemoryContextProvider\n",
        encoding="utf-8",
    )
    check(
        "direct planner import outside the composition boundary fails closed",
        "direct-adapter-import:worker/app/agent3/planner.py" in findings(fake),
    )

    planner.write_text("# clean boundary\n", encoding="utf-8")
    mount.write_text(
        original_mount + "\nProtectedMemoryContextCompiler\n",
        encoding="utf-8",
    )
    check(
        "mount bypassing the adapter fails closed",
        "mount-bypasses-adapter" in findings(fake),
    )

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== T-033 PROTECTED CONTEXT PROMOTION GATE: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
