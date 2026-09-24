#!/usr/bin/env python3
"""C30-P separately default-off episode review runtime lifecycle tests."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    DEFAULT_EPISODE_REVIEW_MAILBOX_CAPACITY,
    EPISODE_REVIEW_RUNTIME_FLAG,
    EpisodeExperienceReviewMailbox,
    EpisodeReviewRuntime,
    TrustedEpisodeReviewClaimService,
    compose_cognitive_session_lifespan,
    compose_episode_review_lifespan,
    episode_review_runtime_enabled,
    production_episode_review_runtime_factory,
)
from app.consciousness_core.session_lifecycle import (  # noqa: E402
    CognitiveSessionLifecycleError,
)
import app.consciousness_core.session_lifecycle as session_lifecycle  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class EpisodeReviewLifecycleTests(unittest.TestCase):
    def test_exact_runtime_flag_contract(self):
        old = os.environ.get(EPISODE_REVIEW_RUNTIME_FLAG)
        try:
            os.environ.pop(EPISODE_REVIEW_RUNTIME_FLAG, None)
            self.assertFalse(episode_review_runtime_enabled())
            for value in ("true", "yes", "on", "01", " 1 "):
                os.environ[EPISODE_REVIEW_RUNTIME_FLAG] = value
                self.assertFalse(
                    episode_review_runtime_enabled(),
                    value,
                )
            os.environ[EPISODE_REVIEW_RUNTIME_FLAG] = "1"
            self.assertTrue(episode_review_runtime_enabled())
        finally:
            if old is None:
                os.environ.pop(EPISODE_REVIEW_RUNTIME_FLAG, None)
            else:
                os.environ[EPISODE_REVIEW_RUNTIME_FLAG] = old

    def test_factory_is_inert_until_exact_opt_in(self):
        old = os.environ.get(EPISODE_REVIEW_RUNTIME_FLAG)
        try:
            os.environ.pop(EPISODE_REVIEW_RUNTIME_FLAG, None)
            app = SimpleNamespace(state=SimpleNamespace())
            self.assertIsNone(
                production_episode_review_runtime_factory(app)
            )

            os.environ[EPISODE_REVIEW_RUNTIME_FLAG] = "1"
            runtime = production_episode_review_runtime_factory(app)
            self.assertIsInstance(runtime, EpisodeReviewRuntime)
            self.assertIsInstance(
                runtime.mailbox,
                EpisodeExperienceReviewMailbox,
            )
            self.assertIsInstance(
                runtime.service,
                TrustedEpisodeReviewClaimService,
            )
            self.assertEqual(
                runtime.mailbox.snapshot.capacity,
                DEFAULT_EPISODE_REVIEW_MAILBOX_CAPACITY,
            )
            self.assertFalse(runtime.closed)
            runtime.close()
            self.assertTrue(runtime.closed)
            self.assertTrue(runtime.mailbox.snapshot.closed)
            self.assertTrue(runtime.service.snapshot.closed)
        finally:
            if old is None:
                os.environ.pop(EPISODE_REVIEW_RUNTIME_FLAG, None)
            else:
                os.environ[EPISODE_REVIEW_RUNTIME_FLAG] = old

    def test_composed_lifecycle_injects_and_cleans_exact_runtime(self):
        events = []

        @asynccontextmanager
        async def inner(_app):
            events.append("inner-enter")
            yield
            events.append("inner-exit")

        mailbox = EpisodeExperienceReviewMailbox()
        runtime = EpisodeReviewRuntime(
            mailbox=mailbox,
            service=TrustedEpisodeReviewClaimService(mailbox=mailbox),
        )

        def factory(_app):
            events.append("runtime-factory")
            return runtime

        app = SimpleNamespace(state=SimpleNamespace())
        lifespan = compose_episode_review_lifespan(
            inner,
            runtime_factory=factory,
        )

        async def exercise():
            async with lifespan(app):
                events.append("yield")
                self.assertIs(
                    app.state.consciousness_episode_review_runtime,
                    runtime,
                )
                self.assertIs(
                    app.state.consciousness_episode_review_mailbox,
                    runtime.mailbox,
                )
                self.assertIs(
                    app.state.consciousness_episode_review_service,
                    runtime.service,
                )
                self.assertFalse(runtime.closed)

        run(exercise())

        self.assertEqual(
            events,
            [
                "inner-enter",
                "runtime-factory",
                "yield",
                "inner-exit",
            ],
        )
        self.assertTrue(runtime.closed)
        self.assertFalse(
            hasattr(
                app.state,
                "consciousness_episode_review_runtime",
            )
        )
        self.assertFalse(
            hasattr(
                app.state,
                "consciousness_episode_review_mailbox",
            )
        )
        self.assertFalse(
            hasattr(
                app.state,
                "consciousness_episode_review_service",
            )
        )

    def test_review_runtime_exists_before_c19_session_factory(self):
        events = []
        mailbox = EpisodeExperienceReviewMailbox()
        runtime = EpisodeReviewRuntime(
            mailbox=mailbox,
            service=TrustedEpisodeReviewClaimService(mailbox=mailbox),
        )

        @asynccontextmanager
        async def inner(_app):
            events.append("inner")
            yield

        def runtime_factory(_app):
            events.append("review-runtime")
            return runtime

        def session_factory(app):
            events.append("session-factory")
            self.assertIs(
                app.state.consciousness_episode_review_mailbox,
                mailbox,
            )
            self.assertIs(
                app.state.consciousness_episode_review_service,
                runtime.service,
            )
            return None

        app = SimpleNamespace(state=SimpleNamespace())
        lifespan = compose_cognitive_session_lifespan(
            compose_episode_review_lifespan(
                inner,
                runtime_factory=runtime_factory,
            ),
            session_factory=session_factory,
        )

        async def exercise():
            async with lifespan(app):
                events.append("yield")

        run(exercise())
        self.assertEqual(
            events,
            ["inner", "review-runtime", "session-factory", "yield"],
        )
        self.assertTrue(runtime.closed)

    def test_production_session_factory_passes_exact_app_state_mailbox(self):
        originals = {
            "ProductionSupervisorBridge": (
                session_lifecycle.ProductionSupervisorBridge
            ),
            "ProductionCognitiveSession": (
                session_lifecycle.ProductionCognitiveSession
            ),
            "active_person_binding_from_registry": (
                session_lifecycle.active_person_binding_from_registry
            ),
            "bootstrap_runtime_session": (
                session_lifecycle.bootstrap_runtime_session
            ),
        }

        class FakeBridge:
            def __init__(self):
                self.state = SimpleNamespace(
                    runtime_epoch_id="epoch-" + "1" * 32
                )

        class FakeStore:
            def read(self):
                return object()

        class FakeRegistry:
            def __init__(self, _path):
                pass

            def active_bindings(self):
                return object()

        class FakeSession:
            def __init__(
                self,
                *,
                supervisor_bridge,
                bootstrap_context,
                durable_anchor_state,
                review_mailbox=None,
                review_observability=None,
            ):
                self.supervisor_bridge = supervisor_bridge
                self.bootstrap_context = bootstrap_context
                self.durable_anchor_state = durable_anchor_state
                self.review_mailbox = review_mailbox
                self.review_observability = review_observability

        try:
            session_lifecycle.ProductionSupervisorBridge = FakeBridge
            session_lifecycle.ProductionCognitiveSession = FakeSession
            session_lifecycle.active_person_binding_from_registry = (
                lambda *_args, **_kwargs: object()
            )
            session_lifecycle.bootstrap_runtime_session = (
                lambda **_kwargs: object()
            )

            mailbox = EpisodeExperienceReviewMailbox()
            app = SimpleNamespace(
                state=SimpleNamespace(
                    consciousness_supervisor=FakeBridge(),
                    consciousness_episode_review_mailbox=mailbox,
                )
            )
            with tempfile.TemporaryDirectory() as td:
                person_path = Path(td) / "persons.json"
                person_path.write_text("{}", encoding="utf-8")
                result = (
                    session_lifecycle.production_cognitive_session_factory(
                        app,
                        self_store_factory=FakeStore,
                        registry_path_fn=lambda: str(person_path),
                        registry_factory=FakeRegistry,
                    )
                )

            self.assertIs(result.review_mailbox, mailbox)
            self.assertIsNone(result.review_observability)
        finally:
            for name, value in originals.items():
                setattr(session_lifecycle, name, value)

    def test_wrong_app_state_mailbox_type_fails_closed(self):
        originals = {
            "ProductionSupervisorBridge": (
                session_lifecycle.ProductionSupervisorBridge
            ),
            "active_person_binding_from_registry": (
                session_lifecycle.active_person_binding_from_registry
            ),
            "bootstrap_runtime_session": (
                session_lifecycle.bootstrap_runtime_session
            ),
        }

        class FakeBridge:
            def __init__(self):
                self.state = SimpleNamespace(
                    runtime_epoch_id="epoch-" + "2" * 32
                )

        class FakeStore:
            def read(self):
                return object()

        class FakeRegistry:
            def __init__(self, _path):
                pass

            def active_bindings(self):
                return object()

        try:
            session_lifecycle.ProductionSupervisorBridge = FakeBridge
            session_lifecycle.active_person_binding_from_registry = (
                lambda *_args, **_kwargs: object()
            )
            session_lifecycle.bootstrap_runtime_session = (
                lambda **_kwargs: object()
            )
            app = SimpleNamespace(
                state=SimpleNamespace(
                    consciousness_supervisor=FakeBridge(),
                    consciousness_episode_review_mailbox="wrong",
                )
            )
            with tempfile.TemporaryDirectory() as td:
                person_path = Path(td) / "persons.json"
                person_path.write_text("{}", encoding="utf-8")
                with self.assertRaisesRegex(
                    CognitiveSessionLifecycleError,
                    "review mailbox app state has unexpected type",
                ):
                    session_lifecycle.production_cognitive_session_factory(
                        app,
                        self_store_factory=FakeStore,
                        registry_path_fn=lambda: str(person_path),
                        registry_factory=FakeRegistry,
                    )
        finally:
            for name, value in originals.items():
                setattr(session_lifecycle, name, value)


if __name__ == "__main__":
    unittest.main()
