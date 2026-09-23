"""C30-F deterministic experiential-episode boundary policy.

The replaceable ThoughtEngine has no episode segmentation authority. This module
only validates trusted boundary evidence and returns a pure zero-authority
decision; it does not mutate episode state.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .episodes import (
    EpisodeCloseReason,
    EpisodeOpenReason,
    ExperienceEpisodeState,
    experience_episode_ref,
)
from .temporal import TemporalAnchor


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
BoundarySignalKind = Literal[
    "SESSION_CLOSE",
    "DORMANCY",
    "ACTIVE_GOAL_SET_CHANGED",
    "FOCUS_SHIFT",
    "EXPLICIT_BOUNDARY",
]
BoundaryAuthority = Literal[
    "core_lifecycle",
    "goal_transition",
    "core_focus_policy",
    "operator_explicit",
]
BoundaryDecision = Literal[
    "KEEP",
    "CLOSE_ONLY",
    "CLOSE_AND_ROTATE",
]


class EpisodeBoundaryError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class EpisodeBoundarySignal(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-boundary-signal/v1"
    ]
    signal_id: Annotated[
        str,
        Field(pattern=r"^ebsig-[a-f0-9]{32}$"),
    ]
    kind: BoundarySignalKind
    authority: BoundaryAuthority
    source_ref: NonEmptyRef
    anchor: TemporalAnchor
    previous_active_goal_refs: Annotated[
        list[NonEmptyRef],
        Field(max_length=64),
    ]
    next_active_goal_refs: Annotated[
        list[NonEmptyRef],
        Field(max_length=64),
    ]
    thought_engine_authority: Literal[False]
    raw_chain_of_thought_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_authority(self) -> "EpisodeBoundarySignal":
        expected = {
            "SESSION_CLOSE": "core_lifecycle",
            "DORMANCY": "core_lifecycle",
            "ACTIVE_GOAL_SET_CHANGED": "goal_transition",
            "FOCUS_SHIFT": "core_focus_policy",
            "EXPLICIT_BOUNDARY": "operator_explicit",
        }[self.kind]
        if self.authority != expected:
            raise ValueError(
                "episode boundary signal has invalid authority"
            )
        if len(self.previous_active_goal_refs) != len(
            set(self.previous_active_goal_refs)
        ):
            raise ValueError("previous active goal refs must be unique")
        if len(self.next_active_goal_refs) != len(
            set(self.next_active_goal_refs)
        ):
            raise ValueError("next active goal refs must be unique")

        if self.kind == "ACTIVE_GOAL_SET_CHANGED":
            if set(self.previous_active_goal_refs) == set(
                self.next_active_goal_refs
            ):
                raise ValueError(
                    "goal-set boundary requires an actual goal-set change"
                )
        elif (
            self.previous_active_goal_refs
            or self.next_active_goal_refs
        ):
            raise ValueError(
                "non-goal boundary cannot carry active-goal transition data"
            )
        return self


class EpisodeBoundaryPolicyDecision(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-boundary-decision/v1"
    ]
    episode_ref: NonEmptyRef
    decision: BoundaryDecision
    signal_ref: NonEmptyRef | None
    boundary_anchor: TemporalAnchor | None
    close_reason: EpisodeCloseReason | None
    next_open_reason: EpisodeOpenReason | None
    model_calls: Literal[0]
    episode_mutation_applied: Literal[False]
    durable_memory_write_authority: Literal[False]
    self_state_store_write_applied: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    timer_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "EpisodeBoundaryPolicyDecision":
        if self.decision == "KEEP":
            if any(
                value is not None
                for value in (
                    self.signal_ref,
                    self.boundary_anchor,
                    self.close_reason,
                    self.next_open_reason,
                )
            ):
                raise ValueError(
                    "KEEP boundary decision cannot carry close evidence"
                )
        elif self.decision == "CLOSE_ONLY":
            if (
                self.signal_ref is None
                or self.boundary_anchor is None
                or self.close_reason is None
                or self.next_open_reason is not None
            ):
                raise ValueError(
                    "CLOSE_ONLY boundary decision shape is invalid"
                )
        else:
            if (
                self.signal_ref is None
                or self.boundary_anchor is None
                or self.close_reason is None
                or self.next_open_reason is None
            ):
                raise ValueError(
                    "CLOSE_AND_ROTATE boundary decision shape is invalid"
                )
        return self


def _canonical_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def episode_boundary_signal_ref(
    signal: EpisodeBoundarySignal,
) -> str:
    if not isinstance(signal, EpisodeBoundarySignal):
        raise TypeError("signal must be EpisodeBoundarySignal")
    return "episode-boundary-signal:" + _digest(signal)


def build_episode_boundary_signal(
    *,
    kind: BoundarySignalKind,
    authority: BoundaryAuthority,
    source_ref: str,
    anchor: TemporalAnchor | Mapping[str, Any],
    previous_active_goal_refs: list[str] | None = None,
    next_active_goal_refs: list[str] | None = None,
) -> EpisodeBoundarySignal:
    try:
        temporal_anchor = (
            anchor
            if isinstance(anchor, TemporalAnchor)
            else TemporalAnchor.model_validate(anchor)
        )
        seed = {
            "kind": kind,
            "authority": authority,
            "source_ref": source_ref,
            "anchor_id": temporal_anchor.anchor_id,
            "previous_active_goal_refs": sorted(
                previous_active_goal_refs or []
            ),
            "next_active_goal_refs": sorted(
                next_active_goal_refs or []
            ),
        }
        return EpisodeBoundarySignal(
            schema=(
                "kaliv-consciousness-core/"
                "episode-boundary-signal/v1"
            ),
            signal_id="ebsig-" + _digest(seed)[:32],
            kind=kind,
            authority=authority,
            source_ref=source_ref,
            anchor=temporal_anchor,
            previous_active_goal_refs=list(
                dict.fromkeys(previous_active_goal_refs or [])
            )[:64],
            next_active_goal_refs=list(
                dict.fromkeys(next_active_goal_refs or [])
            )[:64],
            thought_engine_authority=False,
            raw_chain_of_thought_authority=False,
            production_activation=False,
        )
    except ValidationError as exc:
        raise EpisodeBoundaryError(
            "invalid episode boundary signal"
        ) from exc


def evaluate_episode_boundary(
    episode: ExperienceEpisodeState | Mapping[str, Any],
    signal: EpisodeBoundarySignal | Mapping[str, Any] | None = None,
) -> EpisodeBoundaryPolicyDecision:
    """Validate boundary evidence and return a pure deterministic decision."""
    try:
        current = (
            episode
            if isinstance(episode, ExperienceEpisodeState)
            else ExperienceEpisodeState.model_validate(episode)
        )
        boundary = (
            None
            if signal is None
            else signal
            if isinstance(signal, EpisodeBoundarySignal)
            else EpisodeBoundarySignal.model_validate(signal)
        )
    except ValidationError as exc:
        raise EpisodeBoundaryError(
            "invalid episode boundary policy input"
        ) from exc

    if current.phase != "ACTIVE":
        raise EpisodeBoundaryError(
            "episode boundary policy requires ACTIVE episode"
        )

    current_ref = experience_episode_ref(current)
    if boundary is None:
        return EpisodeBoundaryPolicyDecision(
            schema=(
                "kaliv-consciousness-core/"
                "episode-boundary-decision/v1"
            ),
            episode_ref=current_ref,
            decision="KEEP",
            signal_ref=None,
            boundary_anchor=None,
            close_reason=None,
            next_open_reason=None,
            model_calls=0,
            episode_mutation_applied=False,
            durable_memory_write_authority=False,
            self_state_store_write_applied=False,
            execution_authority=False,
            scheduling_authority=False,
            timer_authority=False,
            production_activation=False,
        )

    anchor = boundary.anchor
    if anchor.runtime_epoch_id != current.opened_anchor.runtime_epoch_id:
        raise EpisodeBoundaryError(
            "episode boundary crossed runtime epoch"
        )
    previous_anchor = (
        current.moments[-1].anchor
        if current.moments
        else current.opened_anchor
    )
    if anchor.sequence < previous_anchor.sequence:
        raise EpisodeBoundaryError(
            "episode boundary sequence moved backwards"
        )
    if (
        previous_anchor.monotonic_ms is None
        or anchor.monotonic_ms is None
        or anchor.monotonic_ms < previous_anchor.monotonic_ms
    ):
        raise EpisodeBoundaryError(
            "episode boundary monotonic time moved backwards"
        )

    mapping: dict[
        str,
        tuple[
            BoundaryDecision,
            EpisodeCloseReason,
            EpisodeOpenReason | None,
        ],
    ] = {
        "SESSION_CLOSE": (
            "CLOSE_ONLY",
            "SESSION_CLOSE",
            None,
        ),
        "DORMANCY": (
            "CLOSE_ONLY",
            "DORMANCY",
            None,
        ),
        "ACTIVE_GOAL_SET_CHANGED": (
            "CLOSE_AND_ROTATE",
            "GOAL_TRANSITION",
            "GOAL_TRANSITION",
        ),
        "FOCUS_SHIFT": (
            "CLOSE_AND_ROTATE",
            "FOCUS_SHIFT",
            "FOCUS_SHIFT",
        ),
        "EXPLICIT_BOUNDARY": (
            "CLOSE_AND_ROTATE",
            "EXPLICIT_BOUNDARY",
            "EXPLICIT_BOUNDARY",
        ),
    }
    decision, close_reason, next_open_reason = mapping[boundary.kind]
    return EpisodeBoundaryPolicyDecision(
        schema=(
            "kaliv-consciousness-core/"
            "episode-boundary-decision/v1"
        ),
        episode_ref=current_ref,
        decision=decision,
        signal_ref=episode_boundary_signal_ref(boundary),
        boundary_anchor=anchor,
        close_reason=close_reason,
        next_open_reason=next_open_reason,
        model_calls=0,
        episode_mutation_applied=False,
        durable_memory_write_authority=False,
        self_state_store_write_applied=False,
        execution_authority=False,
        scheduling_authority=False,
        timer_authority=False,
        production_activation=False,
    )
