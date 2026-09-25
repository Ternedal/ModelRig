#!/usr/bin/env python3
"""C30-Q privacy-safe episode review status tests."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    ClockSample,
    EPISODE_REVIEW_RUNTIME_FLAG,
    EpisodeExperienceReviewMailbox,
    EpisodeReviewRuntime,
    TrustedEpisodeReviewClaimService,
    anchor_from_clock,
    append_episode_moment,
    build_episode_experience_review_request,
    build_episode_moment,
    build_episode_review_status,
    close_experience_episode,
    derive_episode_closure_evidence,
    episode_experience_review_request_ref,
    open_experience_episode,
)
from app.consciousness_core.episode_review_api import (  # noqa: E402
    CONSCIOUSNESS_EPISODE_REVIEW_FLAG,
    CONSCIOUSNESS_EPISODE_REVIEW_PREFIX,
    build_consciousness_episode_review_router,
)


SELF = "self-" + "a" * 32
PERSON_REV = "person-r0007"
EPOCH = "epoch-" + "1" * 32


def anchor(sequence: int, *, event_ref: str):
    sample = ClockSample(
        schema="kaliv-consciousness-core/clock-sample/v1",
        sample_id="clock-" + f"{sequence:032x}",
        wall_time_unix_ms=1_700_000_000_000 + sequence * 1000,
        timezone_name="Europe/Copenhagen",
        utc_offset_minutes=120,
        local_hour=18,
        monotonic_ms=sequence * 1000,
        runtime_epoch_id=EPOCH,
        sampled_sequence=sequence,
        source_ref=f"trusted:c30q:{sequence}",
        confidence=1.0,
        production_activation=False,
    )
    return anchor_from_clock(sample, event_ref=event_ref)


def review_request(marker: str):
    start = int(marker, 16) * 10 + 1
    episode = open_experience_episode(
        self_id=SELF,
        person_revision=PERSON_REV,
        opening_anchor=anchor(
            start,
            event_ref=f"episode-open:c30q:{marker}",
        ),
        reason="SESSION_START",
    )
    episode = append_episode_moment(
        episode,
        build_episode_moment(
            kind="WORLD_EVIDENCE",
            source_ref=f"world:c30q:{marker}",
            anchor=anchor(
                start + 1,
                event_ref=f"world:c30q:{marker}",
            ),
            salience=0.8,
            active_goal_refs=["goal:review"],
            participant_refs=["actor:user"],
        ),
    )
    closed = close_experience_episode(
        episode,
        closing_anchor=anchor(
            start + 2,
            event_ref=f"episode-close:c30q:{marker}",
        ),
        reason="FOCUS_SHIFT",
    )
    evidence = derive_episode_closure_evidence(
        closed,
        boundary_signal_ref=(
            "episode-boundary-signal:" + marker * 64
        ),
    )
    built = build_episode_experience_review_request(evidence)
    if built is None:
        raise AssertionError("non-empty episode must create review request")
    return built


class Env:
    def __enter__(self):
        self.old_runtime = os.environ.get(EPISODE_REVIEW_RUNTIME_FLAG)
        self.old_transport = os.environ.get(
            CONSCIOUSNESS_EPISODE_REVIEW_FLAG
        )
        os.environ.pop(EPISODE_REVIEW_RUNTIME_FLAG, None)
        os.environ.pop(CONSCIOUSNESS_EPISODE_REVIEW_FLAG, None)
        return self

    def __exit__(self, *_args):
        if self.old_runtime is None:
            os.environ.pop(EPISODE_REVIEW_RUNTIME_FLAG, None)
        else:
            os.environ[EPISODE_REVIEW_RUNTIME_FLAG] = self.old_runtime
        if self.old_transport is None:
            os.environ.pop(CONSCIOUSNESS_EPISODE_REVIEW_FLAG, None)
        else:
            os.environ[
                CONSCIOUSNESS_EPISODE_REVIEW_FLAG
            ] = self.old_transport


class EpisodeReviewStatusTests(unittest.TestCase):
    def app(self):
        return SimpleNamespace(state=SimpleNamespace())

    def install_runtime(self, app, *, capacity=8):
        mailbox = EpisodeExperienceReviewMailbox(capacity=capacity)
        service = TrustedEpisodeReviewClaimService(mailbox=mailbox)
        runtime = EpisodeReviewRuntime(
            mailbox=mailbox,
            service=service,
        )
        app.state.consciousness_episode_review_runtime = runtime
        app.state.consciousness_episode_review_mailbox = mailbox
        app.state.consciousness_episode_review_service = service
        return runtime, mailbox, service

    def test_off_transport_only_and_runtime_unavailable_states(self):
        with Env():
            app = self.app()
            off = build_episode_review_status(app)
            self.assertEqual(off.state, "OFF")

            os.environ[CONSCIOUSNESS_EPISODE_REVIEW_FLAG] = "1"
            transport_only = build_episode_review_status(app)
            self.assertEqual(
                transport_only.state,
                "TRANSPORT_ONLY",
            )

            os.environ[EPISODE_REVIEW_RUNTIME_FLAG] = "1"
            unavailable = build_episode_review_status(app)
            self.assertEqual(
                unavailable.state,
                "RUNTIME_UNAVAILABLE",
            )

    def test_active_idle_pending_claimed_full_and_closed_states(self):
        with Env():
            os.environ[EPISODE_REVIEW_RUNTIME_FLAG] = "1"

            idle_app = self.app()
            runtime, mailbox, _ = self.install_runtime(
                idle_app,
                capacity=2,
            )
            idle = build_episode_review_status(idle_app)
            self.assertEqual(idle.state, "ACTIVE_IDLE")

            pending_request = review_request("1")
            mailbox.enqueue(pending_request)
            pending = build_episode_review_status(idle_app)
            self.assertEqual(pending.state, "ACTIVE_PENDING")
            self.assertEqual(pending.pending_count, 1)

            idle_app.state.consciousness_episode_review_service.claim_exact(
                request_id=pending_request.request_id,
                expected_request_ref=(
                    episode_experience_review_request_ref(
                        pending_request
                    )
                ),
            )
            claimed = build_episode_review_status(idle_app)
            self.assertEqual(claimed.state, "ACTIVE_CLAIMED")
            self.assertEqual(claimed.claimed_count, 1)

            full_app = self.app()
            _, full_mailbox, _ = self.install_runtime(
                full_app,
                capacity=1,
            )
            full_mailbox.enqueue(review_request("2"))
            full = build_episode_review_status(full_app)
            self.assertEqual(full.state, "MAILBOX_FULL")
            self.assertTrue(full.mailbox_full)

            runtime.close()
            closed = build_episode_review_status(idle_app)
            self.assertEqual(closed.state, "CLOSED")

    def test_status_contains_counts_only_not_request_or_claim_refs(self):
        with Env():
            os.environ[EPISODE_REVIEW_RUNTIME_FLAG] = "1"
            app = self.app()
            _, mailbox, service = self.install_runtime(
                app,
                capacity=2,
            )
            request = review_request("3")
            mailbox.enqueue(request)
            _, claim = service.claim_exact(
                request_id=request.request_id,
                expected_request_ref=(
                    episode_experience_review_request_ref(request)
                ),
            )

            status = build_episode_review_status(app)
            payload = status.model_dump_json()

            self.assertEqual(status.pending_count, 1)
            self.assertEqual(status.claimed_count, 1)
            self.assertFalse(status.request_refs_included)
            self.assertFalse(status.claim_ids_included)
            self.assertFalse(status.closure_evidence_included)
            self.assertFalse(status.raw_text_included)
            self.assertFalse(status.raw_chain_of_thought_included)
            self.assertNotIn(request.request_id, payload)
            self.assertNotIn(
                episode_experience_review_request_ref(request),
                payload,
            )
            self.assertNotIn(claim.claim_id, payload)

    def test_inconsistent_runtime_binding_is_unavailable(self):
        with Env():
            os.environ[EPISODE_REVIEW_RUNTIME_FLAG] = "1"
            app = self.app()
            runtime, _, _ = self.install_runtime(app)
            app.state.consciousness_episode_review_mailbox = (
                EpisodeExperienceReviewMailbox()
            )

            status = build_episode_review_status(app)

            self.assertIs(
                app.state.consciousness_episode_review_runtime,
                runtime,
            )
            self.assertEqual(status.state, "RUNTIME_UNAVAILABLE")

    def test_private_status_route_works_without_review_service(self):
        with Env():
            os.environ[CONSCIOUSNESS_EPISODE_REVIEW_FLAG] = "1"
            app = FastAPI()
            app.include_router(
                build_consciousness_episode_review_router(
                    loopback_allowed=lambda _request: True,
                )
            )

            response = TestClient(app).get(
                CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/status"
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json()["state"],
                "TRANSPORT_ONLY",
            )
            self.assertFalse(
                response.json()["request_refs_included"]
            )

    def test_status_route_is_loopback_only(self):
        app = FastAPI()
        app.include_router(
            build_consciousness_episode_review_router(
                loopback_allowed=lambda _request: False,
            )
        )
        response = TestClient(app).get(
            CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/status"
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
