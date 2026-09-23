"""C13-B authoritative production wiring for sleep/wake continuity.

This module is deliberately narrow:
- it derives SleepBinding only from persisted C14 SelfState plus the exact active
  Person Revision;
- it supplies a trusted process-local C11 clock;
- it grants no scheduler, tool, model, Memory 4, or execution authority.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..person_api import registry_path
from ..person_registry import PersonRegistry
from .cycle import self_state_ref
from .self_state import SelfStateStore, verify_active_person
from .sleep_lifecycle import SleepBinding, SleepLifecycleRuntime
from .temporal import ClockSample, TemporalAnchor, anchor_from_clock


def _clock_id(*parts: object) -> str:
    raw = "|".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


class TrustedRuntimeClock:
    """Trusted wall + monotonic clock scoped to one worker runtime epoch."""

    def __init__(
        self,
        *,
        wall_time_ns: Callable[[], int] = time.time_ns,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self._wall_time_ns = wall_time_ns
        self._monotonic_ns = monotonic_ns
        self._runtime_epoch_id = "epoch-" + secrets.token_hex(16)
        self._sequence = 0

    @property
    def runtime_epoch_id(self) -> str:
        return self._runtime_epoch_id

    def sample(self) -> ClockSample:
        wall_ns = int(self._wall_time_ns())
        monotonic_ns = int(self._monotonic_ns())
        if wall_ns < 0 or monotonic_ns < 0:
            raise RuntimeError("trusted runtime clock returned a negative value")

        wall_ms = wall_ns // 1_000_000
        monotonic_ms = monotonic_ns // 1_000_000
        local = datetime.fromtimestamp(wall_ms / 1000.0, tz=timezone.utc).astimezone()
        offset = local.utcoffset()
        if offset is None:
            raise RuntimeError("trusted runtime clock has no UTC offset")

        tzinfo = local.tzinfo
        timezone_name = (
            getattr(tzinfo, "key", None)
            or local.tzname()
            or "local"
        )

        self._sequence += 1
        sequence = self._sequence
        return ClockSample(
            schema="kaliv-consciousness-core/clock-sample/v1",
            sample_id="clock-" + _clock_id(
                self._runtime_epoch_id,
                sequence,
                wall_ms,
                monotonic_ms,
            ),
            wall_time_unix_ms=wall_ms,
            timezone_name=str(timezone_name),
            utc_offset_minutes=int(offset.total_seconds() // 60),
            local_hour=local.hour,
            monotonic_ms=monotonic_ms,
            runtime_epoch_id=self._runtime_epoch_id,
            sampled_sequence=sequence,
            source_ref="runtime:trusted-system-clock",
            confidence=1.0,
            production_activation=False,
        )

    def anchor(self, event_ref: str) -> TemporalAnchor:
        return anchor_from_clock(self.sample(), event_ref=event_ref)


def authoritative_sleep_binding() -> SleepBinding | None:
    """Resolve the only production-authoritative C13 binding.

    Missing state/profile is a clean "not configured" result. Corrupt or
    mismatched state is intentionally allowed to raise so enabled C13 fails
    closed instead of accepting a fabricated identity.
    """
    state = SelfStateStore().read()
    if state is None:
        return None

    person_path = Path(registry_path())
    if not person_path.exists():
        return None

    active = PersonRegistry(person_path).active_bindings()
    if active is None:
        return None

    verified = verify_active_person(
        state,
        active_person_id=str(active["person_id"]),
        active_person_revision=str(active["person_revision"]),
    )
    return SleepBinding(
        schema="kaliv-consciousness-core/sleep-binding/v1",
        self_id=verified.self_id,
        person_revision=verified.person_revision,
        durable_self_state_ref=self_state_ref(verified),
        durable_self_state_revision=verified.revision,
        open_goal_refs=list(verified.active_goal_refs),
        open_loop_refs=list(verified.active_intention_refs),
        pending_review_refs=[],
        production_activation=False,
    )


def production_sleep_runtime_factory(_app) -> SleepLifecycleRuntime:
    """Side-effect-free factory; disk reads remain behind the C13 flag."""
    clock = TrustedRuntimeClock()
    return SleepLifecycleRuntime(
        binding_provider=authoritative_sleep_binding,
        anchor_provider=clock.anchor,
    )
