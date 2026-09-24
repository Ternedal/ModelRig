#!/usr/bin/env python3
"""C30-I trusted episode-to-C7 review boundary tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    ClockSample,
    EpisodeExperienceReviewError,
    ExperienceCandidate,
    TrustedEpisodeExperienceReview,
    anchor_from_clock,
    append_episode_moment,
    build_episode_moment,
    close_experience_episode,
    derive_episode_closure_evidence,
    episode_closure_evidence_ref,
    evaluate_reviewed_episode_candidate,
    open_experience_episode,
    plan_episode_experience_review,
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
        source_ref=f"trusted:c30i:{sequence}",
        confidence=1.0,
        production_activation=False,
    )
    return anchor_from_clock(sample, event_ref=event_ref)


def closure_evidence(*, empty: bool = False):
    episode = open_experience_episode(
        self_id=SELF,
        person_revision=PERSON_REV,
        opening_anchor=anchor(
            1,
            event_ref="episode-open:c30i",
        ),
        reason="SESSION_START",
    )
    if not empty:
        episode = append_episode_moment(
            episode,
            build_episode_moment(
                kind="WORLD_EVIDENCE",
                source_ref="world-evidence:" + "c" * 64,
                anchor=anchor(
                    2,
                    event_ref="world-evidence:" + "c" * 64,
                ),
                salience=0.8,
                active_goal_refs=["goal:understand"],
                participant_refs=["actor:user"],
            ),
        )
    closed = close_experience_episode(
        episode,
        closing_anchor=anchor(
            3,
            event_ref="episode-close:c30i",
        ),
        reason="FOCUS_SHIFT",
    )
    return derive_episode_closure_evidence(
        closed,
        boundary_signal_ref="episode-boundary-signal:" + "d" * 64,
    )


def candidate(evidence, **overrides):
    values = dict(
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
        active_goal_refs=["goal:understand"],
        intention_ref=None,
        prediction_refs=[],
        outcome_refs=[],
        prediction_error_refs=[],
        personality_state_ref="personality-state:c30i",
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
    values.update(overrides)
    return ExperienceCandidate(**values)


def review(evidence, item=None, *, decision="APPROVE"):
    return TrustedEpisodeExperienceReview(
        schema=(
            "kaliv-consciousness-core/"
            "trusted-episode-experience-review/v1"
        ),
        review_id="erev-" + "4" * 32,
        closure_evidence_ref=episode_closure_evidence_ref(evidence),
        decision=decision,
        authority="operator_explicit",
        reviewer_source_ref="operator-review:c30i",
        reviewed_candidate_ref=(
            None
            if item is None
            else f"experience:{item.experience_id}"
        ),
        raw_text_asserted_from_closure_evidence=False,
        completed_turn_authority_asserted=False,
        production_activation=False,
    )


class EpisodeExperienceReviewTests(unittest.TestCase):
    def test_non_empty_episode_requires_trusted_review(self):
        evidence = closure_evidence()

        plan = plan_episode_experience_review(evidence)

        self.assertEqual(
            plan.disposition,
            "TRUSTED_REVIEW_REQUIRED",
        )
        self.assertFalse(plan.raw_text_available)
        self.assertFalse(plan.raw_chain_of_thought_available)
        self.assertFalse(plan.completed_turn_authority_available)
        self.assertFalse(plan.synthetic_cycle_allowed)
        self.assertFalse(plan.candidate_created)
        self.assertFalse(plan.memory4_called)
        self.assertFalse(plan.durable_memory_write_authority)

    def test_empty_episode_needs_no_review_and_cannot_be_approved(self):
        evidence = closure_evidence(empty=True)
        plan = plan_episode_experience_review(evidence)
        self.assertEqual(plan.disposition, "NO_REVIEW")

        item = candidate(
            evidence,
            participant_refs=[],
            active_goal_refs=[],
        )
        with self.assertRaisesRegex(
            EpisodeExperienceReviewError,
            "empty episode closure cannot approve",
        ):
            evaluate_reviewed_episode_candidate(
                evidence,
                review(evidence, item),
                item,
            )

    def test_rejected_review_produces_no_c7_candidate_or_handoff(self):
        evidence = closure_evidence()
        result = evaluate_reviewed_episode_candidate(
            evidence,
            review(evidence, decision="REJECT"),
        )

        self.assertFalse(result.accepted_for_c7_evaluation)
        self.assertIsNone(result.candidate_ref)
        self.assertIsNone(result.c7_handoff)
        self.assertFalse(result.memory4_called)
        self.assertFalse(result.candidate_persisted)

    def test_approved_real_candidate_reaches_c7_only_as_review_required(self):
        evidence = closure_evidence()
        item = candidate(evidence)

        result = evaluate_reviewed_episode_candidate(
            evidence,
            review(evidence, item),
            item,
        )

        self.assertTrue(result.accepted_for_c7_evaluation)
        self.assertEqual(
            result.candidate_ref,
            f"experience:{item.experience_id}",
        )
        self.assertEqual(
            result.c7_handoff.status,
            "trusted_review_required",
        )
        self.assertFalse(result.completed_turn_authority_granted)
        self.assertFalse(result.memory4_called)
        self.assertFalse(result.candidate_persisted)
        self.assertFalse(result.durable_memory_write_authority)
        self.assertEqual(item.cycle_id, CYCLE)

    def test_closure_review_cannot_reconstruct_user_stated_fact(self):
        evidence = closure_evidence()
        item = candidate(
            evidence,
            kind="USER_STATED_FACT",
            provenance_kind="inferred",
        )

        with self.assertRaisesRegex(
            EpisodeExperienceReviewError,
            "cannot reconstruct USER_STATED_FACT",
        ):
            evaluate_reviewed_episode_candidate(
                evidence,
                review(evidence, item),
                item,
            )

    def test_closure_review_cannot_assert_completed_turn_authority(self):
        evidence = closure_evidence()
        item = candidate(
            evidence,
            completed_turn_source_ref="chat-turn:forged",
        )

        with self.assertRaisesRegex(
            EpisodeExperienceReviewError,
            "cannot assert completed-turn authority",
        ):
            evaluate_reviewed_episode_candidate(
                evidence,
                review(evidence, item),
                item,
            )

    def test_candidate_must_bind_exact_closure_provenance(self):
        evidence = closure_evidence()
        item = candidate(
            evidence,
            source_refs=[evidence.closed_episode_ref],
        )

        with self.assertRaisesRegex(
            EpisodeExperienceReviewError,
            "must include closure evidence provenance",
        ):
            evaluate_reviewed_episode_candidate(
                evidence,
                review(evidence, item),
                item,
            )

    def test_candidate_cannot_introduce_unobserved_participants_or_goals(self):
        evidence = closure_evidence()
        extra_participant = candidate(
            evidence,
            participant_refs=["actor:user", "actor:other"],
        )
        with self.assertRaisesRegex(
            EpisodeExperienceReviewError,
            "unobserved episode participants",
        ):
            evaluate_reviewed_episode_candidate(
                evidence,
                review(evidence, extra_participant),
                extra_participant,
            )

        extra_goal = candidate(
            evidence,
            active_goal_refs=["goal:understand", "goal:invented"],
        )
        with self.assertRaisesRegex(
            EpisodeExperienceReviewError,
            "unobserved episode goals",
        ):
            evaluate_reviewed_episode_candidate(
                evidence,
                review(evidence, extra_goal),
                extra_goal,
            )

    def test_candidate_identity_and_episode_binding_fail_closed(self):
        evidence = closure_evidence()

        wrong_self = candidate(
            evidence,
            self_id="self-" + "f" * 32,
        )
        with self.assertRaisesRegex(
            EpisodeExperienceReviewError,
            "another self",
        ):
            evaluate_reviewed_episode_candidate(
                evidence,
                review(evidence, wrong_self),
                wrong_self,
            )

        wrong_event = candidate(
            evidence,
            event_ref="experience-episode:" + "e" * 64,
        )
        with self.assertRaisesRegex(
            EpisodeExperienceReviewError,
            "event_ref must bind the closed episode",
        ):
            evaluate_reviewed_episode_candidate(
                evidence,
                review(evidence, wrong_event),
                wrong_event,
            )

    def test_review_cannot_promote_structural_evidence_to_stronger_provenance(self):
        evidence = closure_evidence()
        item = candidate(
            evidence,
            provenance_kind="user_explicit",
        )

        with self.assertRaisesRegex(
            EpisodeExperienceReviewError,
            "cannot promote source provenance",
        ):
            evaluate_reviewed_episode_candidate(
                evidence,
                review(evidence, item),
                item,
            )

    def test_review_and_candidate_bindings_are_exact(self):
        evidence = closure_evidence()
        item = candidate(evidence)
        bad_review = TrustedEpisodeExperienceReview(
            schema=(
                "kaliv-consciousness-core/"
                "trusted-episode-experience-review/v1"
            ),
            review_id="erev-" + "5" * 32,
            closure_evidence_ref="episode-closure-evidence:" + "f" * 64,
            decision="APPROVE",
            authority="operator_explicit",
            reviewer_source_ref="operator-review:c30i",
            reviewed_candidate_ref=f"experience:{item.experience_id}",
            raw_text_asserted_from_closure_evidence=False,
            completed_turn_authority_asserted=False,
            production_activation=False,
        )
        with self.assertRaisesRegex(
            EpisodeExperienceReviewError,
            "another episode closure evidence",
        ):
            evaluate_reviewed_episode_candidate(
                evidence,
                bad_review,
                item,
            )


if __name__ == "__main__":
    unittest.main()
