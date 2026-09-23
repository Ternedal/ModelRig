#!/usr/bin/env python3
"""Deterministic, non-runtime ThoughtEngine reference for Consciousness Core C3.

This module is intentionally placed under experiments/. It has no network, model,
tool, memory, scheduler, or persistence adapter. Its only purpose is to exercise
the external ThoughtEngine boundary and model-swap invariants deterministically.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping


def _stable_id(prefix: str, payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
    return f"{prefix}-{digest}"


class MockThoughtEngine:
    """Pure proposal producer with zero authority and zero persistence."""

    def think(
        self,
        request: Mapping[str, Any],
        cognitive_profile: Mapping[str, Any],
        workspace: Mapping[str, Any],
    ) -> dict[str, Any]:
        # Defensive copies make mutation bugs observable in tests.
        request_copy = deepcopy(dict(request))
        profile_copy = deepcopy(dict(cognitive_profile))
        workspace_copy = deepcopy(dict(workspace))

        selected = set(workspace_copy.get("selected_candidate_ids", []))
        summaries = [
            item.get("summary", "")
            for item in workspace_copy.get("candidates", [])
            if item.get("candidate_id") in selected
        ]
        reasoning = float(profile_copy.get("reasoning_depth", 0.0))
        planning = float(profile_copy.get("planning_capacity", 0.0))
        capability = (reasoning + planning) / 2.0

        if capability >= 0.8:
            interpretation = "Deeply integrate the selected workspace evidence before forming an intention."
            uncertainty = 0.08
        elif capability >= 0.5:
            interpretation = "Integrate the selected workspace evidence and verify the next step."
            uncertainty = 0.2
        else:
            interpretation = "Use a narrow interpretation and decompose before committing to a complex conclusion."
            uncertainty = 0.45

        if summaries:
            interpretation += " Active evidence: " + " | ".join(summaries[:4])

        seed = {
            "request_id": request_copy["request_id"],
            "profile_id": profile_copy["profile_id"],
            "engine_instance_id": profile_copy["engine_instance_id"],
            "interpretation": interpretation,
        }

        return {
            "schema": "kaliv-consciousness-core/thought-proposal/v1",
            "proposal_id": _stable_id("thinkprop", seed),
            "request_id": request_copy["request_id"],
            "interpretation": interpretation,
            "hypotheses": [
                {
                    "summary": "The selected evidence is sufficient for a bounded next cognitive step.",
                    "confidence": max(0.0, min(1.0, 1.0 - uncertainty)),
                }
            ],
            "candidate_intentions": [
                {
                    "summary": "Continue cognition without exercising external authority.",
                    "confidence": max(0.0, min(1.0, 1.0 - uncertainty)),
                    "required_authority": "none",
                }
            ],
            "predicted_outcomes": [
                {
                    "summary": "No durable state or external action is changed by this proposal.",
                    "confidence": 1.0,
                }
            ],
            "questions": [],
            "memory_queries": [],
            "attention_suggestions": list(workspace_copy.get("selected_candidate_ids", []))[:16],
            "response_intent": None,
            "body_intent": None,
            "uncertainty": uncertainty,
            "state_mutations": [],
            "actions": [],
            "authority": {
                "identity": False,
                "persistent_state": False,
                "durable_memory": False,
                "action": False,
            },
            "production_activation": False,
        }
