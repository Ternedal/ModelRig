#!/usr/bin/env python3
"""C30-O private loopback-only episode review API tests."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    ClockSample,
    EpisodeExperienceReviewMailbox,
    ExperienceCandidate,
    TrustedEpisodeExperienceReview,
    TrustedEpisodeReviewClaimService,
    anchor_from_clock,
    append_episode_moment,
    build_episode_experience_review_request,
    build_episode_moment,
    close_experience_episode,
    derive_episode_closure_evidence,
    episode_closure_evidence_ref,
    episode_experience_review_request_ref,
    open_experience_episode,
)
from app.consciousness_core.episode_review_api import (  # noqa: E402
    CONSCIOUSNESS_EPISODE_REVIEW_FLAG,
    CONSCIOUSNESS_EPISODE_REVIEW_PREFIX,
    build_consciousness_episode_review_router,
    consciousness_episode_review_enabled,
    mount_consciousness_episode_review,
)


SELF = "self-" + "a" * 32
PERSON = "person-" + "b" * 32
PERSON_REV = "person-r0007"
EPOCH = "epoch-" + "1" * 32
CYCLE = "cycle-" + "2" * 32


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
        source_ref=f"trusted:c30o:{sequence}",
        confidence=1.0,
        production_activation=False,
    )
    return anchor_from_clock(sample, event_ref=event_ref)


def review_request():
    episode = open_experience_episode(
        self_id=SELF,
        person_revision=PERSON_REV,
        opening_anchor=anchor(
            1,
            event_ref="episode-open:c30o",
        ),
        reason="SESSION_START",
    )
    episode = append_episode_moment(
        episode,
        build_episode_moment(
            kind="WORLD_EVIDENCE",
            source_ref="world:c30o",
            anchor=anchor(2, event_ref="world:c30o"),
            salience=0.8,
            active_goal_refs=["goal:review"],
            participant_refs=["actor:user"],
        ),
    )
    closed = close_experience_episode(
        episode,
        closing_anchor=anchor(
            3,
            event_ref="episode-close:c30o",
        ),
        reason="FOCUS_SHIFT",
    )
    evidence = derive_episode_closure_evidence(
        closed,
        boundary_signal_ref="episode-boundary-signal:" + "d" * 64,
    )
    built = build_episode_experience_review_request(evidence)
    if built is None:
        raise AssertionError("non-empty episode must create review request")
    return built


def candidate(request):
    evidence = request.closure_evidence
    return ExperienceCandidate(
        schema="kaliv-consciousness-core/experience-candidate/v1",
        experience_id="exp-" + "3" * 32,
        cycle_id=CYCLE,
        self_id=SELF,
        person_id=PERSON,
        person_revision=PERSON_REV,
        kind="SHARED_EVENT",
        event_ref=evidence.closed_episode_ref,
        participant_refs=["actor:user"],
        self_state_before_ref="self-state:before",
        self_state_after_ref="self-state:after",
        active_goal_refs=["goal:review"],
        intention_ref=None,
        prediction_refs=[],
        outcome_refs=[],
        prediction_error_refs=[],
        personality_state_ref="personality-state:c30o",
        world_state_delta_refs=[],
        significance=0.8,
        provenance_kind="shared_event",
        sensitivity="private",
        source_refs=[
            episode_closure_evidence_ref(evidence),
            evidence.closed_episode_ref,
        ],
        completed_turn_source_ref=None,
        production_activation=False,
    )


def review(request, item=None, *, decision="APPROVE"):
    return TrustedEpisodeExperienceReview(
        schema=(
            "kaliv-consciousness-core/"
            "trusted-episode-experience-review/v1"
        ),
        review_id="erev-" + "4" * 32,
        closure_evidence_ref=request.review_plan.closure_evidence_ref,
        decision=decision,
        authority="operator_explicit",
        reviewer_source_ref="operator-review:c30o",
        reviewed_candidate_ref=(
            None if item is None else f"experience:{item.experience_id}"
        ),
        raw_text_asserted_from_closure_evidence=False,
        completed_turn_authority_asserted=False,
        production_activation=False,
    )


class EpisodeReviewApiTests(unittest.TestCase):
    def setUp(self):
        self.request = review_request()
        self.mailbox = EpisodeExperienceReviewMailbox()
        self.mailbox.enqueue(self.request)
        self.service = TrustedEpisodeReviewClaimService(
            mailbox=self.mailbox
        )

    def app(self, *, service=True, loopback=True):
        app = FastAPI()
        if service:
            app.state.consciousness_episode_review_service = self.service
        app.include_router(
            build_consciousness_episode_review_router(
                loopback_allowed=lambda _request: loopback,
            )
        )
        return app

    def test_exact_flag_contract_and_flag_off_mounts_no_route(self):
        old = os.environ.get(CONSCIOUSNESS_EPISODE_REVIEW_FLAG)
        try:
            os.environ.pop(CONSCIOUSNESS_EPISODE_REVIEW_FLAG, None)
            self.assertFalse(consciousness_episode_review_enabled())
            for value in ("true", "yes", "on", "01", " 1 "):
                os.environ[CONSCIOUSNESS_EPISODE_REVIEW_FLAG] = value
                self.assertFalse(
                    consciousness_episode_review_enabled(),
                    value,
                )
            app = FastAPI()
            before = [route.path for route in app.router.routes]
            self.assertFalse(mount_consciousness_episode_review(app))
            self.assertEqual(
                [route.path for route in app.router.routes],
                before,
            )
            os.environ[CONSCIOUSNESS_EPISODE_REVIEW_FLAG] = "1"
            self.assertTrue(consciousness_episode_review_enabled())
        finally:
            if old is None:
                os.environ.pop(
                    CONSCIOUSNESS_EPISODE_REVIEW_FLAG,
                    None,
                )
            else:
                os.environ[CONSCIOUSNESS_EPISODE_REVIEW_FLAG] = old

    def test_loopback_rejection_happens_before_private_body_parse(self):
        response = TestClient(
            self.app(loopback=False)
        ).post(
            CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/claim",
            content=b"{PRIVATE-INVALID-BODY",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.mailbox.snapshot.pending_count, 1)

    def test_missing_service_is_503(self):
        response = TestClient(
            self.app(service=False)
        ).get(
            CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/pending"
        )
        self.assertEqual(response.status_code, 503)

    def test_pending_is_bounded_reference_only(self):
        response = TestClient(self.app()).get(
            CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/pending?limit=1"
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["pending_count"], 1)
        self.assertEqual(body["returned_count"], 1)
        item = body["items"][0]
        self.assertFalse(item["raw_text_included"])
        self.assertFalse(item["raw_chain_of_thought_included"])
        self.assertFalse(item["memory4_called"])
        self.assertNotIn("user_text", response.text)
        self.assertNotIn("assistant_text", response.text)

    def test_claim_does_not_consume_request(self):
        request_ref = episode_experience_review_request_ref(self.request)
        response = TestClient(self.app()).post(
            CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/claim",
            json={
                "request_id": self.request.request_id,
                "expected_request_ref": request_ref,
            },
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["claim"]["request_ref"], request_ref)
        self.assertFalse(body["claim"]["request_consumed"])
        self.assertTrue(body["loopback_only"])
        self.assertFalse(body["raw_chain_of_thought_included"])
        self.assertEqual(self.mailbox.snapshot.pending_count, 1)

    def test_wrong_claim_ref_is_generic_conflict_and_does_not_consume(self):
        response = TestClient(self.app()).post(
            CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/claim",
            json={
                "request_id": self.request.request_id,
                "expected_request_ref": (
                    "episode-experience-review-request:" + "f" * 64
                ),
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["detail"],
            "consciousness episode review state conflict",
        )
        self.assertEqual(self.mailbox.snapshot.pending_count, 1)

    def test_abandon_releases_claim_and_keeps_request_pending(self):
        request_ref = episode_experience_review_request_ref(self.request)
        client = TestClient(self.app())
        claimed = client.post(
            CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/claim",
            json={
                "request_id": self.request.request_id,
                "expected_request_ref": request_ref,
            },
        )
        claim_id = claimed.json()["claim"]["claim_id"]

        abandoned = client.post(
            CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/abandon",
            json={
                "claim_id": claim_id,
                "expected_request_ref": request_ref,
            },
        )

        self.assertEqual(abandoned.status_code, 200)
        self.assertTrue(abandoned.json()["request_still_pending"])
        self.assertEqual(self.mailbox.snapshot.pending_count, 1)

    def test_reject_commit_consumes_after_explicit_decision(self):
        request_ref = episode_experience_review_request_ref(self.request)
        client = TestClient(self.app())
        claimed = client.post(
            CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/claim",
            json={
                "request_id": self.request.request_id,
                "expected_request_ref": request_ref,
            },
        )
        claim_id = claimed.json()["claim"]["claim_id"]
        trusted = review(self.request, decision="REJECT")

        committed = client.post(
            CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/commit",
            json={
                "claim_id": claim_id,
                "expected_request_ref": request_ref,
                "review": trusted.model_dump(mode="json"),
                "candidate": None,
            },
        )

        self.assertEqual(committed.status_code, 200)
        body = committed.json()
        self.assertTrue(body["semantic_preflight_passed"])
        self.assertTrue(body["request_consumed_after_preflight"])
        self.assertEqual(
            body["decision_receipt"]["decision"],
            "REJECT",
        )
        self.assertFalse(body["memory4_called"])
        self.assertEqual(self.mailbox.snapshot.pending_count, 0)

    def test_approve_commit_preserves_c7_review_required(self):
        request_ref = episode_experience_review_request_ref(self.request)
        client = TestClient(self.app())
        claimed = client.post(
            CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/claim",
            json={
                "request_id": self.request.request_id,
                "expected_request_ref": request_ref,
            },
        )
        claim_id = claimed.json()["claim"]["claim_id"]
        item = candidate(self.request)
        trusted = review(self.request, item)

        committed = client.post(
            CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/commit",
            json={
                "claim_id": claim_id,
                "expected_request_ref": request_ref,
                "review": trusted.model_dump(mode="json"),
                "candidate": item.model_dump(mode="json"),
            },
        )

        self.assertEqual(committed.status_code, 200)
        body = committed.json()
        self.assertEqual(
            body["decision_receipt"]["evaluation"]["c7_handoff"]["status"],
            "trusted_review_required",
        )
        self.assertFalse(
            body["decision_receipt"][
                "durable_memory_write_authority"
            ]
        )
        self.assertEqual(self.mailbox.snapshot.pending_count, 0)

    def test_invalid_body_is_generic_and_does_not_mutate(self):
        before = self.mailbox.snapshot
        response = TestClient(self.app()).post(
            CONSCIOUSNESS_EPISODE_REVIEW_PREFIX + "/claim",
            json={
                "request_id": "PRIVATE-BAD",
                "expected_request_ref": "PRIVATE-REF",
                "extra": "PRIVATE-SENTINEL",
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"],
            "invalid consciousness episode-review request",
        )
        self.assertNotIn("PRIVATE-SENTINEL", response.text)
        self.assertEqual(self.mailbox.snapshot, before)


if __name__ == "__main__":
    unittest.main()
