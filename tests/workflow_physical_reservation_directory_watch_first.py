#!/usr/bin/env python3
"""Regress production Linux directory-history watch-before-trust semantics."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import kaliv_dev_control._improvement_physical_reservation_directory_provenance as history
# Importing the public facade installs the production watch-before-trust guard.
import kaliv_dev_control.improvement_physical_reservation as reservation_module  # noqa: F401


def test_linux_watch_precedes_identity_capture_even_without_ctime_signal() -> None:
    if not history._is_linux():
        return

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        state_root = root / "host-state"
        ledger_root = state_root / "ledger"
        ledger_root.mkdir(parents=True)
        moved = root / "host-state-moved"

        original_capture = history._capture_nodes
        original_stamp = history._metadata_stamp
        calls = 0

        def constant_stamp(_observed) -> int:
            # Deliberately remove metadata-stamp evidence. The production guard
            # must still reject the race from the already-armed inotify queue.
            return 1

        def racing_capture(ledger: Path):
            nonlocal calls
            calls += 1
            state_root.rename(moved)
            moved.rename(state_root)
            return original_capture(ledger)

        history._metadata_stamp = constant_stamp
        history._capture_nodes = racing_capture
        try:
            try:
                binding = history._capture_binding(ledger_root, object())
            except history.DirectoryBoundProvenanceError as exc:
                assert "identities were captured" in str(exc)
            else:
                history._close_binding(binding)
                raise AssertionError(
                    "rename→restore after watch arming must fail without ctime evidence"
                )
        finally:
            history._capture_nodes = original_capture
            history._metadata_stamp = original_stamp

        assert calls == 1


def test_non_linux_posix_watch_before_trust_fails_closed() -> None:
    if os.name != "posix" or not history._is_linux():
        return

    with tempfile.TemporaryDirectory() as directory:
        ledger_root = Path(directory).resolve() / "ledger"
        ledger_root.mkdir()
        original_is_linux = history._is_linux
        history._is_linux = lambda: False
        try:
            try:
                history._capture_binding(ledger_root, object())
            except history.DirectoryBoundProvenanceError as exc:
                assert "race-free" in str(exc)
                assert "unsupported" in str(exc)
            else:
                raise AssertionError(
                    "production guard must fail closed without Linux watch-before-trust"
                )
        finally:
            history._is_linux = original_is_linux


def main() -> None:
    test_linux_watch_precedes_identity_capture_even_without_ctime_signal()
    test_non_linux_posix_watch_before_trust_fails_closed()
    print("physical reservation directory watch-before-trust regressions: PASS")


if __name__ == "__main__":
    main()
