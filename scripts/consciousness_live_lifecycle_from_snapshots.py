#!/usr/bin/env python3
"""Assemble lifecycle qualifier input directly from runtime snapshots."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.consciousness_live_lifecycle_evidence_assembler import (  # noqa: E402
    EvidenceAssemblyError,
    _atomic_write,
    _load,
    assemble,
)

SNAPSHOT_SCHEMA = "kaliv-consciousness-core/qualification-snapshot/v1"


def _snapshot(value: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    if value.get("schema") != SNAPSHOT_SCHEMA:
        raise EvidenceAssemblyError(f"{name} schema mismatch")
    for key in (
        "runtime_instance_ref",
        "wake_receipt",
        "session_bootstrap_receipt",
        "self_state",
        "cognitive_profile",
        "lived_continuity",
    ):
        if key not in value:
            raise EvidenceAssemblyError(f"{name} missing {key}")
    return value


def assemble_from_snapshots(
    *,
    candidate_git_sha: str,
    live_cycle: Mapping[str, Any],
    pre_restart_status: Mapping[str, Any],
    pre_swap_snapshot: Mapping[str, Any],
    post_swap_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    before = _snapshot(pre_swap_snapshot, "pre_swap_snapshot")
    after = _snapshot(post_swap_snapshot, "post_swap_snapshot")
    if before["runtime_instance_ref"] != after["runtime_instance_ref"]:
        raise EvidenceAssemblyError(
            "model-swap snapshots cross another runtime restart"
        )

    after_status = {
        "schema": "kaliv-consciousness-core/runtime-status/v1",
        "runtime_instance_ref": before["runtime_instance_ref"],
    }
    return assemble(
        candidate_git_sha=candidate_git_sha,
        live_cycle=live_cycle,
        before_status=pre_restart_status,
        after_status=after_status,
        wake_receipt=before["wake_receipt"],
        wake_orientation=before["session_bootstrap_receipt"],
        before_profile=before["cognitive_profile"],
        after_profile=after["cognitive_profile"],
        before_self_state=before["self_state"],
        after_self_state=after["self_state"],
        before_continuity=before["lived_continuity"],
        after_continuity=after["lived_continuity"],
    )


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--candidate-sha", required=True)
    p.add_argument("--live-cycle", type=Path, required=True)
    p.add_argument("--pre-restart-status", type=Path, required=True)
    p.add_argument("--pre-swap-snapshot", type=Path, required=True)
    p.add_argument("--post-swap-snapshot", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args(argv)
    try:
        bundle = assemble_from_snapshots(
            candidate_git_sha=a.candidate_sha,
            live_cycle=_load(a.live_cycle, "live_cycle"),
            pre_restart_status=_load(
                a.pre_restart_status,
                "pre_restart_status",
            ),
            pre_swap_snapshot=_load(
                a.pre_swap_snapshot,
                "pre_swap_snapshot",
            ),
            post_swap_snapshot=_load(
                a.post_swap_snapshot,
                "post_swap_snapshot",
            ),
        )
    except Exception as exc:
        print(json.dumps({
            "state": "INVALID",
            "error": str(exc),
            "production_activation": False,
        }))
        return 2
    _atomic_write(a.output, bundle)
    print(json.dumps({
        "state": "ASSEMBLED",
        "output": str(a.output),
        "production_activation": False,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
