#!/usr/bin/env python3
"""C30-A experiential episode primitive tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "worker") not in sys.path:
    sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core import (  # noqa: E402
    ClockSample,
    ExperientialEpisodeError,
    anchor_from_clock,
    append_episode_moment,
    build_episode_moment,
    close_experience_episode,
    episode_moment_ref,
    experience_episode_ref,
    open_experience_episode,
)


SELF = "self-" + "a" * 32
PERSON_REV = "person-r0007"
EPOCH_A = "epoch-" + "1" * 32
EPOCH_B = "epoch-" + "2" * 32


def anchor(marker: str, *, seq: int, mono: int, epoch: str = EPOCH_A):
    sample = ClockSample(
        schema="kaliv-consciousness-core/clock-sample/v1",
        sample_id="clock-" + f"{seq:032x}",
        wall_time_unix_ms=1_700_000_000_000 + seq * 1000,
        timezone_name="Europe/Copenhagen",
        utc_offset_minutes=120,
        local_hour=17,
        monotonic_ms=mono,
        runtime_epoch_id=epoch,
        sampled_sequence=seq,
        source_ref="trusted:c30a:" + marker,
        confidence=1.0,
        production_activation=False,
    )
    return anchor_from_clock(
        sample,
        event_ref="c30a:" + marker,
    )


class ExperientialEpisodeTests(unittest.TestCase):
    def opened(self):
        return open_experience_episode(
            self_id=SELF,
            person_revision=PERSON_REV,
            opening_anchor=anchor("1", seq=1, mono=1000),
            reason="SESSION_START",
        )

    def test_open_episode_is_empty_active_and_zero_authority(self):
        episode = self.opened()

        self.assertEqual(episode.phase, "ACTIVE")
        self.assertEqual(episode.open_reason, "SESSION_START")
        self.assertIsNone(episode.closed_anchor)
        self.assertIsNone(episode.close_reason)
        self.assertEqual(episode.moments, [])
        self.assertEqual(episode.moment_count, 0)
        self.assertEqual(episode.evicted_moment_count, 0)
        self.assertEqual(episode.model_calls, 0)
        self.assertFalse(episode.durable_memory_authority)
        self.assertFalse(episode.execution_authority)
        self.assertFalse(episode.scheduling_authority)
        self.assertFalse(episode.timer_authority)
        self.assertTrue(
            experience_episode_ref(episode).startswith(
                "experience-episode:"
            )
        )

    def test_append_orders_reference_only_moments(self):
        episode = self.opened()
        first = build_episode_moment(
            kind="USER_TURN",
            source_ref="world-evidence:" + "b" * 64,
            anchor=anchor("2", seq=1, mono=1000),
            salience=1.0,
            participant_refs=["actor:user"],
        )
        second = build_episode_moment(
            kind="COGNITIVE_RUN",
            source_ref="cycle-receipt:" + "c" * 64,
            anchor=anchor("3", seq=2, mono=2000),
            salience=0.8,
            active_goal_refs=["goal-" + "d" * 32],
        )

        episode = append_episode_moment(episode, first)
        episode = append_episode_moment(episode, second)

        self.assertEqual(
            [item.kind for item in episode.moments],
            ["USER_TURN", "COGNITIVE_RUN"],
        )
        self.assertEqual(
            [item.anchor.sequence for item in episode.moments],
            [1, 2],
        )
        self.assertEqual(episode.moment_count, 2)
        self.assertEqual(episode.evicted_moment_count, 0)
        self.assertFalse(first.raw_text_persisted)
        self.assertFalse(first.raw_chain_of_thought_persisted)
        self.assertTrue(
            episode_moment_ref(first).startswith("episode-moment:")
        )

        payload = episode.model_dump(mode="json")
        encoded = str(payload)
        self.assertNotIn("interpretation", encoded)
        # The deny flag raw_chain_of_thought_persisted is part of the
        # contract; only a raw payload field itself must be absent.
        self.assertNotIn("'chain_of_thought':", encoded)
        self.assertNotIn("user_text", encoded)

    def test_append_rejects_non_advancing_sequence(self):
        episode = self.opened()
        moment = build_episode_moment(
            kind="WORLD_EVIDENCE",
            source_ref="world-evidence:" + "b" * 64,
            anchor=anchor("2", seq=0, mono=500),
            salience=0.5,
        )

        with self.assertRaisesRegex(
            ExperientialEpisodeError,
            "sequence did not advance",
        ):
            append_episode_moment(episode, moment)

    def test_append_rejects_monotonic_rollback(self):
        episode = self.opened()
        first = build_episode_moment(
            kind="WORLD_EVIDENCE",
            source_ref="world-evidence:" + "b" * 64,
            anchor=anchor("2", seq=2, mono=2000),
            salience=0.5,
        )
        episode = append_episode_moment(episode, first)
        rollback = build_episode_moment(
            kind="COGNITIVE_RUN",
            source_ref="cycle-receipt:" + "c" * 64,
            anchor=anchor("3", seq=3, mono=1500),
            salience=0.5,
        )

        with self.assertRaisesRegex(
            ExperientialEpisodeError,
            "monotonic time did not advance",
        ):
            append_episode_moment(episode, rollback)

    def test_episode_never_crosses_runtime_epoch(self):
        episode = self.opened()
        moment = build_episode_moment(
            kind="COGNITIVE_RUN",
            source_ref="cycle-receipt:" + "c" * 64,
            anchor=anchor("2", seq=2, mono=100, epoch=EPOCH_B),
            salience=0.5,
        )

        with self.assertRaisesRegex(
            ExperientialEpisodeError,
            "crossed runtime epoch",
        ):
            append_episode_moment(episode, moment)

        with self.assertRaisesRegex(
            ExperientialEpisodeError,
            "close crossed runtime epoch",
        ):
            close_experience_episode(
                episode,
                closing_anchor=anchor(
                    "3",
                    seq=3,
                    mono=200,
                    epoch=EPOCH_B,
                ),
                reason="DORMANCY",
            )

    def test_moment_window_rolls_without_blocking_episode(self):
        episode = self.opened()
        for index in range(1, 130):
            sequence = index
            moment = build_episode_moment(
                kind="COGNITIVE_RUN",
                source_ref=(
                    "cycle-receipt:"
                    + f"{index:064x}"[-64:]
                ),
                anchor=anchor(
                    f"{(index % 15) + 1:x}"[-1],
                    seq=sequence,
                    mono=1000 + index * 10,
                ),
                salience=0.5,
            )
            episode = append_episode_moment(episode, moment)

        self.assertEqual(episode.moment_count, 129)
        self.assertEqual(episode.evicted_moment_count, 1)
        self.assertEqual(len(episode.moments), 128)
        self.assertEqual(
            episode.moments[0].anchor.sequence,
            2,
        )
        self.assertEqual(
            episode.moments[-1].anchor.sequence,
            129,
        )

    def test_close_is_exact_and_terminal(self):
        episode = self.opened()
        moment = build_episode_moment(
            kind="RECOVERY_COMPLETION",
            source_ref="continuity-recovery-completion:" + "f" * 64,
            anchor=anchor("2", seq=2, mono=2000),
            salience=0.9,
        )
        episode = append_episode_moment(episode, moment)
        closed = close_experience_episode(
            episode,
            closing_anchor=anchor("3", seq=3, mono=3000),
            reason="FOCUS_SHIFT",
        )

        self.assertEqual(closed.phase, "CLOSED")
        self.assertEqual(closed.close_reason, "FOCUS_SHIFT")
        self.assertEqual(closed.closed_anchor.sequence, 3)

        with self.assertRaisesRegex(
            ExperientialEpisodeError,
            "cannot append to closed",
        ):
            append_episode_moment(closed, build_episode_moment(
                kind="COGNITIVE_RUN",
                source_ref="cycle-receipt:" + "e" * 64,
                anchor=anchor("4", seq=4, mono=4000),
                salience=0.5,
            ))

        with self.assertRaisesRegex(
            ExperientialEpisodeError,
            "already closed",
        ):
            close_experience_episode(
                closed,
                closing_anchor=anchor("4", seq=4, mono=4000),
                reason="SESSION_CLOSE",
            )


if __name__ == "__main__":
    unittest.main()
