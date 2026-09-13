"""Shared synchronization for process-local RSI reservation provenance registries.

File-descriptor provenance and directory-history provenance compose one live
authority decision. They therefore share one re-entrant lock so registration,
validation, weakref cleanup, transaction revocation, and retained-publication
cleanup cannot observe or mutate their process-global registries concurrently.

The lock is replaceable after fork: a child must never inherit an RLock that was
owned by a thread which no longer exists in the child process.
"""
from __future__ import annotations

import threading
from typing import Any

_REGISTRY_LOCK: Any = threading.RLock()


def registry_lock() -> Any:
    """Return the current process-local re-entrant provenance registry lock."""

    return _REGISTRY_LOCK


def reset_registry_lock_after_fork() -> None:
    """Replace inherited synchronization state in a fork child."""

    global _REGISTRY_LOCK
    _REGISTRY_LOCK = threading.RLock()


__all__: list[str] = []
