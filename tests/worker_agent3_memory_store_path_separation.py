#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import runpy
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.agent3.memory_surface import mount_memory_surface  # noqa: E402

checks: list[tuple[str, bool]] = []
SIGNING_MATERIAL = hashlib.sha256(
    b"t033-store-path-separation-fixture"
).hexdigest()


def check(label: str, condition: object) -> None:
    checks.append((label, bool(condition)))


@contextmanager
def environment(**values: str):
    previous = {name: os.environ.get(name) for name in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class MustNotBeConstructed:
    def __init__(self) -> None:
        raise AssertionError("provider must not be constructed before path validation")


with tempfile.TemporaryDirectory(prefix="kaliv-t033-path-separation-") as raw:
    shared = Path(raw) / "shared.db"
    with environment(
        KALIV_AGENT3_MEMORY_STORE="protected",
        KALIV_AGENT3_MEMORY_API_SECRET=SIGNING_MATERIAL,
        KALIV_AGENT3_MEMORY_GRANT_DB=str(shared),
    ):
        try:
            mount_memory_surface(
                FastAPI(),
                memory_path=shared,
                grant_db_path=shared,
                protected_provider_factory=MustNotBeConstructed,
            )
        except RuntimeError as exc:
            check(
                "shared memory and replay-ledger path fails closed",
                "separate" in str(exc),
            )
        else:
            check("shared memory and replay-ledger path fails closed", False)
        check(
            "shared path failure happens before database/provider creation",
            not shared.exists(),
        )

# W02-B has a large focused qualification, but keeping it under tests/support
# avoids inventing another top-level suite merely to exercise one slice. The
# existing storage test remains the CI/inventory entrypoint on Linux and on the
# Windows protected-store gate.
w02b_ok = False
try:
    runpy.run_path(
        str(ROOT / "tests" / "support" / "worker_agent3_memory_consolidation_writer.py"),
        run_name="__main__",
    )
except SystemExit as exc:
    w02b_ok = exc.code in (None, 0)
except Exception as exc:
    print(f"  W02-B support suite raised {type(exc).__name__}: {exc}")
check("W02-B focused storage qualification passes", w02b_ok)

failed = [label for label, ok in checks if not ok]
for label, ok in checks:
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== T-033 STORE PATH SEPARATION + W02-B: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)
