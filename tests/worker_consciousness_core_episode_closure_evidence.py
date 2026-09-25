#!/usr/bin/env python3
"""C30-H bounded episode-closure evidence contract tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    ClockSample,
    EpisodeClosureEvidenceError,
    anchor_from_clock,
    append_episode_moment,
    apply_episode_boundary_decision,
    build_episode_boundary_signal,
    build_episode_moment,
    close_experience_episode,
    derive_episode_closure_evidence,
    episode_closure_evidence_ref,
    evaluate_episode_boundary,
    open_experience_episode,
)


SELF = "self-" + "a" * 32
PERSON_REV = "person-r0007"
EPOCH = "epoch-" + "1" * 32
BOUNDARY_REF = "episode-boundary-signal:" + "b" * 64


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
        source_ref=f"trusted:c30h:{sequence}",
        confidence=1.0,
        production_activation=False,
    )
    return anchor_from_clock(sample, event_ref=event_ref)


def active_episode():
    episode = open_experience_episode(
        self_id=SELF,
        person_revision=PERSON_REV,
        opening_anchor=anchor(1, event_ref="episode-open:c30h"),
        reason="SESSION_START",
    )
    episode = append_episode_moment(
        episode,
        build_episode_moment(
            kind="WORLD_EVIDENCE",
            source_ref="world-evidence:" + "c" * 64,
            anchor=anchor(
                2,
                event_ref="world-evidence:" + "c" * 64,
            ),
            salience=0.4,
            active_goal_refs=["goal:learn"],
            participant_refs=["actor:user"],
        ),
    )
    return append_episode_moment(
        episode,
        build_episode_moment(
            kind="USER_TURN",
            source_ref="user-turn:" + "d" * 64,
            anchor=anchor(
                3,
                event_ref="user-turn:" + "d" * 64,
            ),
            salience=0.9,
            active_goal_refs=["goal:learn"],
            participant_refs=["actor:user"],
        ),
    )


class EpisodeClosureEvidenceTests(unittest.TestCase):
    def test_closed_episode_reduces_to_reference_only_evidence(self):
        closed = close_experience_episode(
            active_episode(),
            closing_anchor=anchor(
                4,
                event_ref="boundary:c30h",
            ),
            reason="FOCUS_SHIFT",
        )

        evidence = derive_episode_closure_evidence(
            closed,
            boundary_signal_ref=BOUNDARY_REF,
        )

        self.assertEqual(evidence.closed_episode_ref.split(":")[0], "experience-episode")
        self.assertEqual(evidence.total_moment_count, 2)
        self.assertEqual(evidence.evicted_moment_count, 0)
        self.assertEqual(evidence.retained_moment_count, 2)
        self.assertEqual(evidence.objective_elapsed_ms, 3000)
        self.assertEqual(
            [item.kind for item in evidence.retained_kind_counts],
            ["USER_TURN", "WORLD_EVIDENCE"],
        )
        self.assertEqual(
            evidence.salient_source_refs[0],
            "user-turn:" + "d" * 64,
        )
        self.assertEqual(evidence.participant_refs, ["actor:user"])
        self.assertEqual(evidence.active_goal_refs, ["goal:learn"])
        self.assertEqual(
            evidence.memory_review_disposition,
            "REFERENCE_EVIDENCE_ONLY",
        )
        self.assertFalse(evidence.raw_text_included)
        self.assertFalse(evidence.raw_chain_of_thought_included)
        self.assertFalse(evidence.closed_episode_contents_retained)
        self.assertFalse(evidence.experience_candidate_created)
        self.assertFalse(evidence.durable_memory_write_authority)
        self.assertEqual(evidence.model_calls, 0)
        self.assertTrue(
            episode_closure_evidence_ref(evidence).startswith(
                "episode-closure-evidence:"
            )
        )

    def test_active_episode_cannot_emit_closure_evidence(self):
        with self.assertRaisesRegex(
            EpisodeClosureEvidenceError,
            "requires CLOSED episode",
        ):
            derive_episode_closure_evidence(
                active_episode(),
                boundary_signal_ref=BOUNDARY_REF,
            )

    def test_empty_closed_episode_is_not_presented_as_memory_evidence(self):
        episode = open_experience_episode(
            self_id=SELF,
            person_revision=PERSON_REV,
            opening_anchor=anchor(
                10,
                event_ref="episode-open:empty:c30h",
            ),
            reason="EXPLICIT_BOUNDARY",
        )
        closed = close_experience_episode(
            episode,
            closing_anchor=anchor(
                11,
                event_ref="episode-close:empty:c30h",
            ),
            reason="EXPLICIT_BOUNDARY",
        )

        evidence = derive_episode_closure_evidence(
            closed,
            boundary_signal_ref=BOUNDARY_REF,
        )

        self.assertEqual(evidence.total_moment_count, 0)
        self.assertEqual(evidence.retained_kind_counts, [])
        self.assertEqual(evidence.salient_source_refs, [])
        self.assertEqual(evidence.max_retained_salience, 0.0)
        self.assertEqual(
            evidence.memory_review_disposition,
            "NO_MOMENTS",
        )

    def test_salient_source_projection_is_bounded_to_sixteen_refs(self):
        episode = open_experience_episode(
            self_id=SELF,
            person_revision=PERSON_REV,
            opening_anchor=anchor(
                20,
                event_ref="episode-open:bounded:c30h",
            ),
            reason="SESSION_START",
        )
        for offset in range(20):
            sequence = 21 + offset
            episode = append_episode_moment(
                episode,
                build_episode_moment(
                    kind="WORLD_EVIDENCE",
                    source_ref=f"source:c30h:{offset:02d}",
                    anchor=anchor(
                        sequence,
                        event_ref=f"source:c30h:{offset:02d}",
                    ),
                    salience=offset / 20.0,
                ),
            )
        closed = close_experience_episode(
            episode,
            closing_anchor=anchor(
                41,
                event_ref="episode-close:bounded:c30h",
            ),
            reason="SESSION_CLOSE",
        )

        evidence = derive_episode_closure_evidence(
            closed,
            boundary_signal_ref=BOUNDARY_REF,
        )

        self.assertEqual(len(evidence.salient_source_refs), 16)
        self.assertEqual(
            evidence.salient_source_refs[0],
            "source:c30h:19",
        )
        self.assertEqual(
            evidence.salient_source_refs[-1],
            "source:c30h:04",
        )

    def test_boundary_application_emits_evidence_only_when_closing(self):
        episode = active_episode()
        keep = evaluate_episode_boundary(episode)
        kept = apply_episode_boundary_decision(episode, keep)
        self.assertIsNone(kept.closure_evidence)

        signal = build_episode_boundary_signal(
            kind="FOCUS_SHIFT",
            authority="core_focus_policy",
            source_ref="focus-policy:c30h",
            anchor=anchor(
                4,
                event_ref="focus-policy:c30h",
            ),
        )
        decision = evaluate_episode_boundary(
            episode,
            signal,
        )
        rotated = apply_episode_boundary_decision(
            episode,
            decision,
        )

        self.assertIsNotNone(rotated.closure_evidence)
        self.assertEqual(
            rotated.closure_evidence.closed_episode_ref,
            rotated.receipt.closed_episode_ref,
        )
        self.assertEqual(
            rotated.closure_evidence.boundary_signal_ref,
            rotated.receipt.signal_ref,
        )
        self.assertEqual(
            rotated.closure_evidence.closed_anchor_id,
            rotated.receipt.boundary_anchor_id,
        )
        self.assertFalse(
            rotated.receipt.closed_episode_contents_retained
        )


if __name__ == "__main__":
    unittest.main()
