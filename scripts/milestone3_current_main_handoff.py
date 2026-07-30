#!/usr/bin/env python3
"""Build an offline handoff kit for the exact current-main Milestone 3 candidate.

The verified bundle/worktree/artifact implementation remains in
``milestone3_candidate_handoff_core.py``. This wrapper changes only the exact
candidate/builder binding and the launcher named inside the offline kit.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = Path(__file__).resolve().with_name("milestone3_candidate_handoff_core.py")
CANDIDATE_BRANCH = "agent/milestone3-current-main-v2"
BUILDER_BRANCH = "agent/milestone3-current-main-handoff-v2"
BRANCH = CANDIDATE_BRANCH
VERSION = "1.58.147"
SCHEMA = "kaliv-milestone3-current-main-handoff/v1"
PHYSICAL_LAUNCHER = "START_MILESTONE3_CURRENT_MAIN.cmd"
_ALLOWED_HELPER_DIFF = {
    "BUILD_MILESTONE3_CURRENT_MAIN_HANDOFF.cmd",
    "CURRENT_STATE.md",
    "MILESTONE3_CURRENT_MAIN_HANDOFF.md",
    "scripts/milestone3_candidate_handoff_core.py",
    "scripts/milestone3_current_main_handoff.py",
    "tests/workflow_milestone3_current_main_handoff.py",
}

_spec = importlib.util.spec_from_file_location("milestone3_candidate_handoff_core", CORE_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"cannot load handoff core: {CORE_PATH}")
core = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = core
_spec.loader.exec_module(core)

_original_write_bootstrap = core.write_bootstrap
_original_write_readme = core.write_readme


def _replace_launcher(text: str) -> str:
    old = "START_MILESTONE3_PHYSICAL.cmd"
    if text.count(old) != 1:
        raise core.HandoffError("handoff core launcher contract changed unexpectedly")
    replaced = text.replace(old, PHYSICAL_LAUNCHER)
    if old in replaced or PHYSICAL_LAUNCHER not in replaced:
        raise core.HandoffError("current-main physical launcher was not bound exactly")
    return replaced


def write_bootstrap(path: Path, *, sha: str, bundle_name: str) -> None:
    _original_write_bootstrap(path, sha=sha, bundle_name=bundle_name)
    path.write_text(_replace_launcher(path.read_text(encoding="utf-8")), encoding="utf-8", newline="")


def write_readme(path: Path, *, identity: Mapping[str, Any]) -> None:
    _original_write_readme(path, identity=identity)
    path.write_text(_replace_launcher(path.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")


# Rebind the exact candidate contract before exposing any core entrypoint.
core.CANDIDATE_BRANCH = CANDIDATE_BRANCH
core.BUILDER_BRANCH = BUILDER_BRANCH
core.BRANCH = BRANCH
core.VERSION = VERSION
core.SCHEMA = SCHEMA
core._ALLOWED_HELPER_DIFF = set(_ALLOWED_HELPER_DIFF)
core.write_bootstrap = write_bootstrap
core.write_readme = write_readme

HandoffError = core.HandoffError
run = core.run
checked_artifact = core.checked_artifact
zip_directory = core.zip_directory
ensure_builder_checkout = core.ensure_builder_checkout
build_handoff = core.build_handoff


def main(argv: list[str] | None = None) -> int:
    return int(core.main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
