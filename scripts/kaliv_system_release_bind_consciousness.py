#!/usr/bin/env python3
"""Bind a qualified Consciousness lifecycle verdict into a Kaliv release manifest.

This helper has authority over exactly one manifest gate:
consciousness_live_lifecycle. It validates the lifecycle verdict against the
exact pinned ModelRig SHA and writes a new manifest. It never activates
production and never changes any other gate.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

RELEASE_SCHEMA = "kaliv-system-release-manifest/v1"
VERDICT_SCHEMA = "kaliv-consciousness-core/live-lifecycle-verdict/v1"
MODELRIG = "Ternedal/ModelRig"
GATE = "consciousness_live_lifecycle"


class ConsciousnessReleaseBindingError(RuntimeError):
    pass


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConsciousnessReleaseBindingError(f"{name} must be an object")
    return value


def _load(path: Path, name: str) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConsciousnessReleaseBindingError(f"{name} cannot be read") from exc
    if len(raw) > 2 * 1024 * 1024:
        raise ConsciousnessReleaseBindingError(f"{name} is too large")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConsciousnessReleaseBindingError(f"{name} is not valid UTF-8 JSON") from exc
    return _mapping(value, name)


def _modelrig_pin(manifest: Mapping[str, Any]) -> str:
    repositories = manifest.get("repositories")
    if not isinstance(repositories, list):
        raise ConsciousnessReleaseBindingError("manifest.repositories must be a list")
    pins = [
        item.get("git_sha")
        for item in repositories
        if isinstance(item, Mapping) and item.get("repository") == MODELRIG
    ]
    if len(pins) != 1 or not isinstance(pins[0], str):
        raise ConsciousnessReleaseBindingError("manifest must contain exactly one ModelRig pin")
    return pins[0]


def _validate_verdict(verdict: Mapping[str, Any], modelrig_sha: str) -> str:
    if verdict.get("schema") != VERDICT_SCHEMA:
        raise ConsciousnessReleaseBindingError("unsupported lifecycle verdict schema")
    if verdict.get("candidate_git_sha") != modelrig_sha:
        raise ConsciousnessReleaseBindingError(
            "lifecycle verdict is bound to another ModelRig SHA"
        )
    required_true = (
        "live_cycle_qualified",
        "dormancy_restart_qualified",
        "model_swap_qualified",
        "identity_lineage_preserved",
        "full_lifecycle_qualified",
        "consciousness_live_lifecycle_gate_satisfied",
    )
    for field in required_true:
        if verdict.get(field) is not True:
            raise ConsciousnessReleaseBindingError(
                f"lifecycle verdict did not prove {field}"
            )
    if verdict.get("state") != "QUALIFIED":
        raise ConsciousnessReleaseBindingError("lifecycle verdict is not QUALIFIED")
    for field in (
        "raw_chain_of_thought_persisted",
        "identity_authority",
        "persistent_state_authority",
        "durable_memory_write_authority",
        "execution_authority",
        "scheduling_authority",
        "model_authority",
        "production_activation",
    ):
        if verdict.get(field) is not False:
            raise ConsciousnessReleaseBindingError(
                f"lifecycle verdict overclaimed {field}"
            )
    ref = verdict.get("release_evidence_ref")
    prefix = f"consciousness-live-lifecycle:{modelrig_sha}:"
    if (
        not isinstance(ref, str)
        or not ref.startswith(prefix)
        or len(ref) != len(prefix) + 64
    ):
        raise ConsciousnessReleaseBindingError(
            "lifecycle release_evidence_ref is not bound to the pinned ModelRig SHA"
        )
    return ref


def bind(
    manifest: Mapping[str, Any],
    verdict: Mapping[str, Any],
) -> dict[str, Any]:
    if manifest.get("schema") != RELEASE_SCHEMA:
        raise ConsciousnessReleaseBindingError("unsupported release manifest schema")
    if manifest.get("production_activation") is not False:
        raise ConsciousnessReleaseBindingError(
            "release evidence binding cannot activate production"
        )
    modelrig_sha = _modelrig_pin(manifest)
    ref = _validate_verdict(verdict, modelrig_sha)

    gates = _mapping(manifest.get("gates"), "manifest.gates")
    gate = _mapping(gates.get(GATE), f"manifest.gates.{GATE}")
    status = gate.get("status")
    refs = gate.get("evidence_refs")
    if status == "FAIL":
        raise ConsciousnessReleaseBindingError(
            "cannot overwrite an explicit consciousness_live_lifecycle FAIL"
        )
    if status == "PASS":
        if refs == [ref]:
            return copy.deepcopy(dict(manifest))
        raise ConsciousnessReleaseBindingError(
            "existing consciousness_live_lifecycle PASS is bound to different evidence"
        )
    if status != "PENDING":
        raise ConsciousnessReleaseBindingError(
            "consciousness_live_lifecycle must be PENDING, PASS or FAIL"
        )
    if refs != []:
        raise ConsciousnessReleaseBindingError(
            "pending consciousness_live_lifecycle gate must not carry stale evidence"
        )

    result = copy.deepcopy(dict(manifest))
    result["gates"][GATE] = {"status": "PASS", "evidence_refs": [ref]}
    result["production_activation"] = False
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("verdict", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        bound = bind(_load(args.manifest, "manifest"), _load(args.verdict, "verdict"))
    except ConsciousnessReleaseBindingError as exc:
        print(json.dumps({"state": "INVALID", "error": str(exc), "production_activation": False}))
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(bound, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "state": "BOUND",
        "gate": GATE,
        "output": str(args.output),
        "production_activation": False,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
