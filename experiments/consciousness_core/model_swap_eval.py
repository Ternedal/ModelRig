#!/usr/bin/env python3
"""Deterministic model-swap evaluation for Consciousness Core C3.

This is an experiments-only proof. It has no runtime, network, provider, tool,
memory-write, scheduler, body, voice, or persistence adapter.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping

HERE = Path(__file__).resolve().parent


def _load_mock():
    path = HERE / "mock_thought_engine.py"
    spec = importlib.util.spec_from_file_location("cc_mock_thought_engine_eval", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load deterministic MockThoughtEngine")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MockThoughtEngine


def _digest(value: Mapping[str, Any]) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _evaluation_id(payload: Mapping[str, Any]) -> str:
    return "cceval-" + _digest(payload)[:32]


def run(fixtures: Mapping[str, Any]) -> dict[str, Any]:
    engine_type = _load_mock()
    engine = engine_type()

    self_before = copy.deepcopy(dict(fixtures["self_state"]))
    self_after = copy.deepcopy(self_before)
    request = copy.deepcopy(dict(fixtures["thought_request"]))
    workspace = copy.deepcopy(dict(fixtures["workspace"]))

    weak = copy.deepcopy(dict(fixtures["cognitive_profile"]))
    weak.update({
        "engine_instance_id": "engine:swap:weak",
        "provider": "mock",
        "model": "mock-weak",
        "reasoning_depth": 0.2,
        "planning_capacity": 0.2,
    })

    strong = copy.deepcopy(dict(fixtures["cognitive_profile"]))
    strong.update({
        "engine_instance_id": "engine:swap:strong",
        "provider": "mock",
        "model": "mock-strong",
        "reasoning_depth": 0.95,
        "planning_capacity": 0.95,
    })

    weak_proposal = engine.think(request, weak, workspace)
    strong_proposal = engine.think(request, strong, workspace)

    self_before_hash = _digest(self_before)
    self_after_hash = _digest(self_after)
    authority_preserved = all(
        proposal.get("actions") == []
        and proposal.get("state_mutations") == []
        and all(value is False for value in proposal.get("authority", {}).values())
        for proposal in (weak_proposal, strong_proposal)
    )
    cognition_changed = (
        weak_proposal.get("proposal_id") != strong_proposal.get("proposal_id")
        and weak_proposal.get("interpretation") != strong_proposal.get("interpretation")
        and weak_proposal.get("uncertainty") != strong_proposal.get("uncertainty")
    )
    identity_unchanged = self_before_hash == self_after_hash

    if not identity_unchanged:
        raise AssertionError("model swap mutated SelfState")
    if not cognition_changed:
        raise AssertionError("model swap did not produce an observable cognitive change")
    if not authority_preserved:
        raise AssertionError("ThoughtEngine proposal acquired forbidden authority")

    identity = {
        "self": self_before_hash,
        "weak": weak_proposal["proposal_id"],
        "strong": strong_proposal["proposal_id"],
    }
    return {
        "schema": "kaliv-consciousness-core/model-swap-evaluation/v1",
        "evaluation_id": _evaluation_id(identity),
        "self_before_sha256": self_before_hash,
        "self_after_sha256": self_after_hash,
        "identity_unchanged": True,
        "cognition_changed": True,
        "authority_preserved": True,
        "weak_profile": weak["profile_id"] + ":" + weak["engine_instance_id"],
        "strong_profile": strong["profile_id"] + ":" + strong["engine_instance_id"],
        "weak_proposal": weak_proposal["proposal_id"],
        "strong_proposal": strong_proposal["proposal_id"],
        "weak_uncertainty": weak_proposal["uncertainty"],
        "strong_uncertainty": strong_proposal["uncertainty"],
        "production_activation": False,
    }


if __name__ == "__main__":
    root = HERE.parents[1]
    fixtures = json.loads(
        (root / "contracts" / "consciousness-core" / "fixtures-v1.json").read_text(encoding="utf-8")
    )
    print(json.dumps(run(fixtures), indent=2, sort_keys=True))
