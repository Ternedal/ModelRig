#!/usr/bin/env python3
"""Assemble exact live-lifecycle qualification evidence from raw Core receipts."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core.dormancy_bridge import (  # noqa: E402
    build_dormancy_bridge,
    build_runtime_dormancy_bridge,
)
from app.consciousness_core.model_swap_continuity import (  # noqa: E402
    qualify_model_swap_continuity,
)

SCHEMA = "kaliv-consciousness-core/live-lifecycle-evidence/v1"
STATUS_SCHEMA = "kaliv-consciousness-core/runtime-status/v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_RUNTIME_REF = re.compile(r"^runtime-instance:[0-9a-f]{32}$")


class EvidenceAssemblyError(RuntimeError):
    pass


def _load(path: Path, name: str) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise EvidenceAssemblyError(f"{name} cannot be read") from exc
    if len(raw) > 2 * 1024 * 1024:
        raise EvidenceAssemblyError(f"{name} is too large")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceAssemblyError(f"{name} is not valid UTF-8 JSON") from exc
    if not isinstance(value, Mapping):
        raise EvidenceAssemblyError(f"{name} must be an object")
    return value


def _runtime_ref(status: Mapping[str, Any], name: str) -> str:
    if status.get("schema") != STATUS_SCHEMA:
        raise EvidenceAssemblyError(f"{name} schema mismatch")
    ref = status.get("runtime_instance_ref")
    if not isinstance(ref, str) or _RUNTIME_REF.fullmatch(ref) is None:
        raise EvidenceAssemblyError(f"{name} lacks a valid runtime_instance_ref")
    return ref


def assemble(
    *,
    candidate_git_sha: str,
    live_cycle: Mapping[str, Any],
    before_status: Mapping[str, Any],
    after_status: Mapping[str, Any],
    wake_receipt: Mapping[str, Any],
    wake_orientation: Mapping[str, Any],
    before_profile: Mapping[str, Any],
    after_profile: Mapping[str, Any],
    before_self_state: Mapping[str, Any],
    after_self_state: Mapping[str, Any],
    before_continuity: Mapping[str, Any],
    after_continuity: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(candidate_git_sha, str) or _SHA40.fullmatch(candidate_git_sha) is None:
        raise EvidenceAssemblyError(
            "candidate_git_sha must be a lowercase 40-hex Git SHA"
        )

    candidate = live_cycle.get("candidate")
    if not isinstance(candidate, Mapping) or candidate.get("git_sha") != candidate_git_sha:
        raise EvidenceAssemblyError("live-cycle report is bound to another candidate SHA")

    before_ref = _runtime_ref(before_status, "before_status")
    after_ref = _runtime_ref(after_status, "after_status")
    if before_ref == after_ref:
        raise EvidenceAssemblyError("runtime instance did not change; restart is not proven")

    if wake_orientation.get("schema") == "kaliv-consciousness-core/session-bootstrap-receipt/v1":
        dormancy = build_runtime_dormancy_bridge(wake_receipt, wake_orientation)
    else:
        dormancy = build_dormancy_bridge(wake_receipt, wake_orientation)
    model_swap = qualify_model_swap_continuity(
        before_profile=before_profile,
        after_profile=after_profile,
        before_self_state=before_self_state,
        after_self_state=after_self_state,
        before_continuity=before_continuity,
        after_continuity=after_continuity,
    )
    if dormancy.self_id != model_swap.self_id:
        raise EvidenceAssemblyError("dormancy and model swap belong to different Self identities")
    if dormancy.person_revision != model_swap.person_revision:
        raise EvidenceAssemblyError("dormancy and model swap belong to different Person revisions")

    return {
        "schema": SCHEMA,
        "candidate_git_sha": candidate_git_sha,
        "live_cycle": dict(live_cycle),
        "dormancy_restart": {
            "candidate_git_sha": candidate_git_sha,
            "restart_proven": True,
            "receipt": dormancy.model_dump(mode="json"),
        },
        "model_swap": {
            "candidate_git_sha": candidate_git_sha,
            "receipt": model_swap.model_dump(mode="json"),
        },
        "production_activation": False,
    }


def _atomic_write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--candidate-sha", required=True)
    p.add_argument("--live-cycle", type=Path, required=True)
    p.add_argument("--before-status", type=Path, required=True)
    p.add_argument("--after-status", type=Path, required=True)
    p.add_argument("--wake-receipt", type=Path, required=True)
    p.add_argument("--wake-orientation", type=Path, required=True)
    p.add_argument("--before-profile", type=Path, required=True)
    p.add_argument("--after-profile", type=Path, required=True)
    p.add_argument("--before-self-state", type=Path, required=True)
    p.add_argument("--after-self-state", type=Path, required=True)
    p.add_argument("--before-continuity", type=Path, required=True)
    p.add_argument("--after-continuity", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(argv)
    try:
        bundle = assemble(
            candidate_git_sha=a.candidate_sha,
            live_cycle=_load(a.live_cycle, "live_cycle"),
            before_status=_load(a.before_status, "before_status"),
            after_status=_load(a.after_status, "after_status"),
            wake_receipt=_load(a.wake_receipt, "wake_receipt"),
            wake_orientation=_load(a.wake_orientation, "wake_orientation"),
            before_profile=_load(a.before_profile, "before_profile"),
            after_profile=_load(a.after_profile, "after_profile"),
            before_self_state=_load(a.before_self_state, "before_self_state"),
            after_self_state=_load(a.after_self_state, "after_self_state"),
            before_continuity=_load(a.before_continuity, "before_continuity"),
            after_continuity=_load(a.after_continuity, "after_continuity"),
        )
    except Exception as exc:
        print(json.dumps({"state": "INVALID", "error": str(exc), "production_activation": False}))
        return 2
    _atomic_write(a.output, bundle)
    print(json.dumps({"state": "ASSEMBLED", "output": str(a.output), "production_activation": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
