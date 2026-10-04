"""Qualification-only end-to-end latency source receipts.

This module does not add a route, scheduler, model call or production authority.
It packages timestamps from the existing TrustedRuntimeClock into the exact
source-receipt schema consumed by scripts/kaliv_end_to_end_latency_qualifier.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .consciousness_core.production_lifecycle import TrustedRuntimeClock
from .consciousness_core.temporal import ClockSample

SOURCE_SCHEMA = "kaliv-system/end-to-end-latency-source/v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_EVENT_ID = re.compile(r"^cevt-[a-f0-9]{32}$")
_TOKEN = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")


def _token(value: str, label: str) -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a bounded token")
    return value


@dataclass(frozen=True)
class EndToEndLatencyObserver:
    candidate_git_sha: str
    event_id: str
    observer_id: str
    clock: TrustedRuntimeClock

    def __post_init__(self) -> None:
        if _SHA40.fullmatch(self.candidate_git_sha) is None:
            raise ValueError("candidate_git_sha must be lowercase 40-hex")
        if _EVENT_ID.fullmatch(self.event_id) is None:
            raise ValueError("event_id must be canonical cognition event id")
        _token(self.observer_id, "observer_id")
        if not isinstance(self.clock, TrustedRuntimeClock):
            raise TypeError("clock must be TrustedRuntimeClock")

    @property
    def runtime_epoch(self) -> str:
        return self.clock.runtime_epoch_id

    def _base(
        self,
        phase: str,
        *,
        sample: ClockSample | None = None,
    ) -> tuple[dict[str, Any], int]:
        sample = self.clock.sample() if sample is None else sample
        if not isinstance(sample, ClockSample):
            raise TypeError("sample must be ClockSample")
        if sample.runtime_epoch_id != self.clock.runtime_epoch_id:
            raise ValueError("sample belongs to another runtime epoch")
        receipt = {
            "schema": SOURCE_SCHEMA,
            "phase": phase,
            "candidate_git_sha": self.candidate_git_sha,
            "event_id": self.event_id,
            "runtime_epoch": sample.runtime_epoch_id,
            "observer_id": self.observer_id,
            "clock": {
                "kind": "monotonic",
                "unit": "milliseconds",
                "origin": "single-observer",
            },
            "observed_at_ms": sample.monotonic_ms,
            "real_event": True,
            "simulated": False,
            "replay": False,
            "details": {},
            "production_activation": False,
        }
        return receipt, sample.monotonic_ms

    def perception_received(
        self,
        *,
        input_kind: str,
        input_id: str,
        sample: ClockSample | None = None,
    ) -> dict[str, Any]:
        receipt, _ = self._base("perception_received", sample=sample)
        receipt["details"] = {
            "input_kind": _token(input_kind, "input_kind"),
            "input_id": _token(input_id, "input_id"),
        }
        return receipt

    def cognition_completed(
        self,
        *,
        transition_receipt_ref: str,
        completed_cycles: int,
    ) -> dict[str, Any]:
        if not isinstance(transition_receipt_ref, str) or not transition_receipt_ref.strip():
            raise ValueError("transition_receipt_ref must be nonblank")
        if len(transition_receipt_ref) > 512:
            raise ValueError("transition_receipt_ref must be bounded")
        if isinstance(completed_cycles, bool) or not isinstance(completed_cycles, int) or completed_cycles < 1:
            raise ValueError("completed_cycles must be >= 1")
        receipt, _ = self._base("cognition_completed")
        receipt["details"] = {
            "cognition_event_id": self.event_id,
            "transition_receipt_ref": transition_receipt_ref,
            "completed_cycles": completed_cycles,
        }
        return receipt

    def outward_binding(self) -> dict[str, str]:
        """Return the exact worker-internal identity required by BodySession."""
        return {
            "candidate_git_sha": self.candidate_git_sha,
            "cognition_event_id": self.event_id,
            "runtime_epoch": self.runtime_epoch,
            "observer_id": self.observer_id,
        }
