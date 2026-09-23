#!/usr/bin/env python3
"""C30-F deterministic experiential episode boundary policy tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    ClockSample,
    EpisodeBoundaryError,
    anchor_from_clock,
    append_episode_moment,
    build_episode_boundary_signal,
    build_episode_moment,
    episode_boundary_signal_ref,
    evaluate_episode_boundary,
    open_experience_episode,
)


SELF = "self-" + "a" * 32
PERSON_REV = "person-r0007"
EPOCH_A = "epoch-" + "1" * 32
EPOCH_B = "epoch-" + "2" * 32
GOAL_A = "goal-" + "a" * 32
GOAL_B = "goal-" + "b" * 32


def anchor(sequence: int, *, epoch: str = EPOCH_A):
    sample = ClockSample(
        schema="kaliv-consciousness-core/clock-sample/v1",
        sample_id="clock-" + f"{sequence:032x}",
        wall_time_unix_ms=1_700_000_000_000 + sequence * 1000,
        timezone_name="Europe/Copenhagen",
        utc_offset_minutes=120,
        local_hour=17,
        monotonic_ms=sequence * 1000,
        runtime_epoch_id=epoch,
        sampled_sequence=sequence,
        source_ref=f"trusted:c30f:{sequence}",
        confidence=1.0,
        production_activation=False,
    )
    return anchor_from_clock(
        sample,
        event_ref=f"boundary:c30f:{sequence}",
    )


class EpisodeBoundaryPolicyTests(unittest.TestCase):
    def episode(self):
        episode = open_experience_episode(
            self_id=SELF,
            person_revision=PERSON_REV,
            opening_anchor=anchor(1),
            reason="SESSION_START",
        )
        return append_episode_moment(
            episode,
            build_episode_moment(
                kind="COGNITIVE_RUN",
                source_ref="cycle-receipt:" + "c" * 64,
                anchor=anchor(2),
                salience=0.8,
                active_goal_refs=[GOAL_A],
            ),
        )

    def signal(
        self,
        *,
        kind,
        authority,
        sequence=3,
        epoch=EPOCH_A,
        previous=None,
        next_=None,
    ):
        return build_episode_boundary_signal(
            kind=kind,
            authority=authority,
            source_ref=f"boundary-source:c30f:{kind.lower()}",
            anchor=anchor(sequence, epoch=epoch),
            previous_active_goal_refs=previous,
            next_active_goal_refs=next_,
        )

    def test_no_signal_keeps_episode_without_authority(self):
        episode = self.episode()

        decision = evaluate_episode_boundary(episode)

        self.assertEqual(decision.decision, "KEEP")
        self.assertIsNone(decision.signal_ref)
        self.assertIsNone(decision.boundary_anchor)
        self.assertIsNone(decision.close_reason)
        self.assertIsNone(decision.next_open_reason)
        self.assertEqual(decision.model_calls, 0)
        self.assertFalse(decision.episode_mutation_applied)
        self.assertFalse(decision.execution_authority)
        self.assertFalse(decision.scheduling_authority)
        self.assertFalse(decision.timer_authority)

    def test_lifecycle_signals_close_only(self):
        episode = self.episode()
        expectations = {
            "SESSION_CLOSE": "SESSION_CLOSE",
            "DORMANCY": "DORMANCY",
        }

        for kind, close_reason in expectations.items():
            with self.subTest(kind=kind):
                signal = self.signal(
                    kind=kind,
                    authority="core_lifecycle",
                )
                decision = evaluate_episode_boundary(
                    episode,
                    signal,
                )
                self.assertEqual(
                    decision.decision,
                    "CLOSE_ONLY",
                )
                self.assertEqual(
                    decision.close_reason,
                    close_reason,
                )
                self.assertIsNone(decision.next_open_reason)
                self.assertEqual(
                    decision.signal_ref,
                    episode_boundary_signal_ref(signal),
                )

    def test_goal_change_rotates_only_on_actual_set_change(self):
        episode = self.episode()
        signal = self.signal(
            kind="ACTIVE_GOAL_SET_CHANGED",
            authority="goal_transition",
            previous=[GOAL_A],
            next_=[GOAL_B],
        )

        decision = evaluate_episode_boundary(
            episode,
            signal,
        )

        self.assertEqual(
            decision.decision,
            "CLOSE_AND_ROTATE",
        )
        self.assertEqual(
            decision.close_reason,
            "GOAL_TRANSITION",
        )
        self.assertEqual(
            decision.next_open_reason,
            "GOAL_TRANSITION",
        )

        with self.assertRaises(EpisodeBoundaryError):
            self.signal(
                kind="ACTIVE_GOAL_SET_CHANGED",
                authority="goal_transition",
                previous=[GOAL_A],
                next_=[GOAL_A],
            )

    def test_focus_and_operator_boundary_have_fixed_authorities(self):
        episode = self.episode()
        focus = self.signal(
            kind="FOCUS_SHIFT",
            authority="core_focus_policy",
        )
        explicit = self.signal(
            kind="EXPLICIT_BOUNDARY",
            authority="operator_explicit",
        )

        focus_decision = evaluate_episode_boundary(
            episode,
            focus,
        )
        explicit_decision = evaluate_episode_boundary(
            episode,
            explicit,
        )

        self.assertEqual(
            focus_decision.next_open_reason,
            "FOCUS_SHIFT",
        )
        self.assertEqual(
            explicit_decision.next_open_reason,
            "EXPLICIT_BOUNDARY",
        )

        with self.assertRaises(EpisodeBoundaryError):
            self.signal(
                kind="FOCUS_SHIFT",
                authority="operator_explicit",
            )
        with self.assertRaises(EpisodeBoundaryError):
            self.signal(
                kind="EXPLICIT_BOUNDARY",
                authority="core_focus_policy",
            )

    def test_boundary_rejects_time_rollback_and_epoch_change(self):
        episode = self.episode()
        rollback = self.signal(
            kind="EXPLICIT_BOUNDARY",
            authority="operator_explicit",
            sequence=1,
        )
        cross_epoch = self.signal(
            kind="SESSION_CLOSE",
            authority="core_lifecycle",
            sequence=3,
            epoch=EPOCH_B,
        )

        with self.assertRaisesRegex(
            EpisodeBoundaryError,
            "sequence moved backwards",
        ):
            evaluate_episode_boundary(
                episode,
                rollback,
            )

        with self.assertRaisesRegex(
            EpisodeBoundaryError,
            "crossed runtime epoch",
        ):
            evaluate_episode_boundary(
                episode,
                cross_epoch,
            )

    def test_non_goal_signal_cannot_smuggle_goal_transition(self):
        with self.assertRaises(EpisodeBoundaryError):
            self.signal(
                kind="EXPLICIT_BOUNDARY",
                authority="operator_explicit",
                previous=[GOAL_A],
                next_=[GOAL_B],
            )

    def test_signal_explicitly_denies_model_segmentation_authority(self):
        signal = self.signal(
            kind="FOCUS_SHIFT",
            authority="core_focus_policy",
        )
        payload = signal.model_dump(mode="json")
        self.assertFalse(payload["thought_engine_authority"])
        self.assertFalse(payload["raw_chain_of_thought_authority"])
        self.assertFalse(payload["production_activation"])


if __name__ == "__main__":
    unittest.main()
