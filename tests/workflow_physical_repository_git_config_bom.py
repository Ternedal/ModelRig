#!/usr/bin/env python3
"""Regression: Git-config BOM must not bypass production include rejection."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "devcontrol" / "src"))

import kaliv_dev_control._improvement_physical_runtime_direct_git as direct_git
import kaliv_dev_control._improvement_physical_runtime_host_control as host_runtime


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        config = Path(directory).resolve() / "config"
        config.write_bytes(
            b"\xef\xbb\xbf[include]\n"
            b"\tpath = /tmp/caller-controlled-gitconfig\n"
        )
        try:
            direct_git._reject_config_includes(config)
        except host_runtime.PhysicalHostRuntimeError as exc:
            if "includes external state" not in str(exc):
                print(f"FAIL: BOM-prefixed include failed for wrong reason: {exc}")
                return 1
            print("PASS: BOM-prefixed include cannot bypass repository-config guard")
            return 0
        print("FAIL: BOM-prefixed include bypassed repository-config guard")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
