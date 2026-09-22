#!/usr/bin/env python3
"""C4 runtime boundary tests for Consciousness Core.

Run:
    PYTHONPATH=worker python3 tests/worker_consciousness_core_runtime.py
"""
from __future__ import annotations

import asyncio
import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    CognitiveProfile,
    ConsciousnessCoreRuntime,
    OllamaThoughtEngine,
    ThoughtEngineContractError,
    ThoughtProposal,
    ThoughtRequest,
    compose_runtime,
    enabled,
)


FIXTURES = json.loads(
    (ROOT / "contracts" / "consciousness-core" / "fixtures-v1.json").read_text(
        encoding="utf-8"
    )
)


def run(coro):
    return asyncio.run(coro)


class StaticEngine:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls = 0
        self.request: ThoughtRequest | None = None
        self.profile: CognitiveProfile | None = None

    async def think(
        self,
        request: ThoughtRequest,
        cognitive_profile: CognitiveProfile,
    ) -> dict[str, Any]:
        self.calls += 1
        self.request = request
        self.profile = cognitive_profile
        return copy.deepcopy(self.payload)


class ConsciousnessCoreRuntimeTests(unittest.TestCase):
    def valid_request(self) -> dict[str, Any]:
        return copy.deepcopy(FIXTURES["thought_request"])

    def valid_profile(self) -> dict[str, Any]:
        return copy.deepcopy(FIXTURES["cognitive_profile"])

    def valid_proposal(self) -> dict[str, Any]:
        return copy.deepcopy(FIXTURES["thought_proposal"])

    def test_flag_is_exact_opt_in(self) -> None:
        self.assertFalse(enabled({}))
        self.assertFalse(enabled({"KALIV_CONSCIOUSNESS_CORE_ENABLED": "0"}))
        self.assertFalse(enabled({"KALIV_CONSCIOUSNESS_CORE_ENABLED": "true"}))
        self.assertFalse(enabled({"KALIV_CONSCIOUSNESS_CORE_ENABLED": "on"}))
        self.assertFalse(enabled({"KALIV_CONSCIOUSNESS_CORE_ENABLED": " 1 "}))
        self.assertTrue(enabled({"KALIV_CONSCIOUSNESS_CORE_ENABLED": "1"}))

    def test_flag_off_factory_returns_none_without_model_call(self) -> None:
        calls = 0

        async def forbidden_chat(messages, model):
            nonlocal calls
            calls += 1
            raise AssertionError("flag-off must not call a model")

        runtime = compose_runtime(
            env={"KALIV_CONSCIOUSNESS_CORE_ENABLED": "0"},
            chat_fn=forbidden_chat,
        )
        self.assertIsNone(runtime)
        self.assertEqual(calls, 0)

    def test_runtime_accepts_one_valid_bounded_proposal(self) -> None:
        engine = StaticEngine(self.valid_proposal())
        runtime = ConsciousnessCoreRuntime(engine)
        proposal = run(runtime.think(self.valid_request(), self.valid_profile()))
        self.assertIsInstance(proposal, ThoughtProposal)
        self.assertEqual(engine.calls, 1)
        self.assertEqual(proposal.request_id, self.valid_request()["request_id"])
        self.assertEqual(proposal.actions, [])
        self.assertEqual(proposal.state_mutations, [])
        self.assertFalse(proposal.authority.identity)
        self.assertFalse(proposal.authority.persistent_state)
        self.assertFalse(proposal.authority.durable_memory)
        self.assertFalse(proposal.authority.action)

    def test_model_swap_changes_cognition_without_identity_input(self) -> None:
        request = self.valid_request()
        self_state_before = copy.deepcopy(FIXTURES["self_state"])

        weak_profile = self.valid_profile()
        weak_profile["engine_instance_id"] = "engine:c4:weak"
        weak_profile["model"] = "weak-model"
        weak_profile["reasoning_depth"] = 0.2
        weak_profile["planning_capacity"] = 0.2

        strong_profile = self.valid_profile()
        strong_profile["engine_instance_id"] = "engine:c4:strong"
        strong_profile["model"] = "strong-model"
        strong_profile["reasoning_depth"] = 0.95
        strong_profile["planning_capacity"] = 0.95

        class ProfileAwareEngine:
            async def think(self, req, profile):
                payload = copy.deepcopy(FIXTURES["thought_proposal"])
                payload["proposal_id"] = (
                    "thinkprop-" + ("1" if profile.reasoning_depth < 0.5 else "2") * 32
                )
                payload["interpretation"] = (
                    "decompose and verify"
                    if profile.reasoning_depth < 0.5
                    else "deep integrated reasoning"
                )
                payload["uncertainty"] = (
                    0.45 if profile.reasoning_depth < 0.5 else 0.08
                )
                return payload

        runtime = ConsciousnessCoreRuntime(ProfileAwareEngine())
        weak = run(runtime.think(request, weak_profile))
        strong = run(runtime.think(request, strong_profile))

        self.assertNotEqual(weak.proposal_id, strong.proposal_id)
        self.assertNotEqual(weak.interpretation, strong.interpretation)
        self.assertGreater(weak.uncertainty, strong.uncertainty)
        self.assertEqual(FIXTURES["self_state"], self_state_before)

    def test_unknown_or_authoritative_output_fails_closed(self) -> None:
        cases = []

        extra = self.valid_proposal()
        extra["unreviewed"] = True
        cases.append(extra)

        action = self.valid_proposal()
        action["actions"] = [{"tool": "forbidden"}]
        cases.append(action)

        mutation = self.valid_proposal()
        mutation["state_mutations"] = [{"path": "person_id"}]
        cases.append(mutation)

        authority = self.valid_proposal()
        authority["authority"]["action"] = True
        cases.append(authority)

        for payload in cases:
            with self.subTest(payload=payload):
                runtime = ConsciousnessCoreRuntime(StaticEngine(payload))
                with self.assertRaises(ThoughtEngineContractError):
                    run(runtime.think(self.valid_request(), self.valid_profile()))

    def test_wrong_request_binding_fails_closed(self) -> None:
        proposal = self.valid_proposal()
        proposal["request_id"] = "thinkreq-" + "9" * 32
        runtime = ConsciousnessCoreRuntime(StaticEngine(proposal))
        with self.assertRaises(ThoughtEngineContractError):
            run(runtime.think(self.valid_request(), self.valid_profile()))

    def test_agent3_intention_remains_only_a_proposal(self) -> None:
        proposal = self.valid_proposal()
        proposal["candidate_intentions"] = [
            {
                "summary": "Inspect repository state through existing execution authority.",
                "confidence": 0.9,
                "required_authority": "agent3",
            }
        ]
        runtime = ConsciousnessCoreRuntime(StaticEngine(proposal))
        result = run(runtime.think(self.valid_request(), self.valid_profile()))
        self.assertEqual(result.candidate_intentions[0].required_authority, "agent3")
        self.assertEqual(result.actions, [])
        self.assertEqual(result.state_mutations, [])

    def test_ollama_adapter_rejects_markdown_and_duplicate_json(self) -> None:
        async def fenced(messages, model):
            return "~~~json\n" + json.dumps(self.valid_proposal()) + "\n~~~"

        request = ThoughtRequest.model_validate(self.valid_request())
        profile = CognitiveProfile.model_validate(self.valid_profile())

        # Markdown/fences are not raw JSON, regardless of fence marker.
        with self.assertRaises(ThoughtEngineContractError):
            run(OllamaThoughtEngine(fenced).think(request, profile))

        valid = json.dumps(self.valid_proposal(), separators=(",", ":"))
        duplicate = valid.replace(
            '"request_id":',
            '"request_id":"thinkreq-' + "8" * 32 + '","request_id":',
            1,
        )

        async def duplicated(messages, model):
            return duplicate

        with self.assertRaises(ThoughtEngineContractError):
            run(OllamaThoughtEngine(duplicated).think(request, profile))

    def test_ollama_adapter_uses_transient_profile_model(self) -> None:
        observed: dict[str, Any] = {}

        async def chat(messages, model):
            observed["messages"] = messages
            observed["model"] = model
            return json.dumps(self.valid_proposal())

        runtime = compose_runtime(
            env={"KALIV_CONSCIOUSNESS_CORE_ENABLED": "1"},
            chat_fn=chat,
        )
        self.assertIsNotNone(runtime)
        result = run(runtime.think(self.valid_request(), self.valid_profile()))
        self.assertEqual(result.request_id, self.valid_request()["request_id"])
        self.assertEqual(observed["model"], self.valid_profile()["model"])
        self.assertEqual(len(observed["messages"]), 2)

    def test_c4_is_not_mounted_as_a_route(self) -> None:
        entrypoint = (
            ROOT / "worker" / "app" / "entrypoint.py"
        ).read_text(encoding="utf-8")
        main_impl = (
            ROOT / "worker" / "app" / "main_impl.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("consciousness_core", entrypoint)
        self.assertNotIn("consciousness_core", main_impl)
        self.assertNotIn("KALIV_CONSCIOUSNESS_CORE_ENABLED", entrypoint)
        self.assertNotIn("KALIV_CONSCIOUSNESS_CORE_ENABLED", main_impl)

    def test_c4_package_has_no_persistence_or_executor_imports(self) -> None:
        package = ROOT / "worker" / "app" / "consciousness_core"
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(package.glob("*.py"))
        )
        for forbidden in (
            "import sqlite3",
            "from ..agent3",
            "from app.agent3",
            "MemoryStore",
            "PersonRegistry",
            "body_session",
            "schedule_service",
        ):
            self.assertNotIn(forbidden, combined)


if __name__ == "__main__":
    unittest.main(verbosity=2)
