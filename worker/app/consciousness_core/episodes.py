"""C30-A bounded process-local experiential episode primitive.

Episodes are Core-owned temporal/reference structure only. They are not durable
autobiographical memory and never persist raw user text or model chain-of-thought.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .temporal import TemporalAnchor


UnitInterval = Annotated[
    float,
    Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False),
]
NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]

EpisodeOpenReason = Literal[
    "SESSION_START",
    "POST_WAKE_RECOVERY",
    "EXPLICIT_BOUNDARY",
]
EpisodeCloseReason = Literal[
    "FOCUS_SHIFT",
    "GOAL_TRANSITION",
    "DORMANCY",
    "SESSION_CLOSE",
    "EXPLICIT_BOUNDARY",
]
EpisodeMomentKind = Literal[
    "COGNITIVE_RUN",
    "WORLD_EVIDENCE",
    "USER_TURN",
    "MEMORY_RECALL",
    "EMBODIMENT_CHANGE",
    "PREDICTION_RESOLUTION",
    "GOAL_TRANSITION",
    "RECOVERY_COMPLETION",
]


class ExperientialEpisodeError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class EpisodeMoment(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/episode-moment/v1"
    ]
    moment_id: Annotated[
        str,
        Field(pattern=r"^moment-[a-f0-9]{32}$"),
    ]
    kind: EpisodeMomentKind
    source_ref: NonEmptyRef
    anchor: TemporalAnchor
    salience: UnitInterval
    active_goal_refs: Annotated[
        list[NonEmptyRef],
        Field(max_length=64),
    ]
    participant_refs: Annotated[
        list[NonEmptyRef],
        Field(max_length=32),
    ]
    raw_text_persisted: Literal[False]
    raw_chain_of_thought_persisted: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def unique_refs(self) -> "EpisodeMoment":
        if len(self.active_goal_refs) != len(set(self.active_goal_refs)):
            raise ValueError("active goal refs must be unique")
        if len(self.participant_refs) != len(set(self.participant_refs)):
            raise ValueError("participant refs must be unique")
        return self


class ExperienceEpisodeState(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/experience-episode-state/v1"
    ]
    episode_id: Annotated[
        str,
        Field(pattern=r"^episode-[a-f0-9]{32}$"),
    ]
    self_id: Annotated[
        str,
        Field(pattern=r"^self-[a-f0-9]{32}$"),
    ]
    person_revision: Annotated[
        str,
        Field(pattern=r"^person-r[0-9]{4,}$"),
    ]
    phase: Literal["ACTIVE", "CLOSED"]
    open_reason: EpisodeOpenReason
    close_reason: EpisodeCloseReason | None
    opened_anchor: TemporalAnchor
    closed_anchor: TemporalAnchor | None
    moments: Annotated[
        list[EpisodeMoment],
        Field(max_length=128),
    ]
    moment_count: Annotated[int, Field(ge=0, strict=True)]
    evicted_moment_count: Annotated[int, Field(ge=0, strict=True)]
    durable_memory_authority: Literal[False]
    self_state_store_write_applied: Literal[False]
    model_calls: Literal[0]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    timer_authority: Literal[False]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_shape(self) -> "ExperienceEpisodeState":
        if self.opened_anchor.runtime_epoch_id is None:
            raise ValueError("episode opening requires runtime epoch")
        if self.opened_anchor.monotonic_ms is None:
            raise ValueError("episode opening requires monotonic anchor")

        if self.phase == "ACTIVE":
            if self.close_reason is not None or self.closed_anchor is not None:
                raise ValueError("ACTIVE episode cannot be closed")
        else:
            if self.close_reason is None or self.closed_anchor is None:
                raise ValueError("CLOSED episode requires close evidence")
            if (
                self.closed_anchor.runtime_epoch_id
                != self.opened_anchor.runtime_epoch_id
            ):
                raise ValueError("episode cannot cross runtime epoch")
            if self.closed_anchor.monotonic_ms is None:
                raise ValueError("episode close requires monotonic anchor")
            if (
                self.closed_anchor.monotonic_ms
                < self.opened_anchor.monotonic_ms
            ):
                raise ValueError("episode close moved backwards")
            if (
                self.closed_anchor.sequence
                < self.opened_anchor.sequence
            ):
                raise ValueError("episode close sequence moved backwards")

        if self.moment_count != (
            self.evicted_moment_count + len(self.moments)
        ):
            raise ValueError("episode moment accounting is inconsistent")
        previous_sequence = self.opened_anchor.sequence
        previous_monotonic = self.opened_anchor.monotonic_ms
        ids: set[str] = set()
        for index, moment in enumerate(self.moments):
            if moment.moment_id in ids:
                raise ValueError("episode moment ids must be unique")
            ids.add(moment.moment_id)
            anchor = moment.anchor
            if (
                anchor.runtime_epoch_id
                != self.opened_anchor.runtime_epoch_id
            ):
                raise ValueError("episode moment crossed runtime epoch")
            if anchor.monotonic_ms is None:
                raise ValueError("episode moment requires monotonic anchor")
            if (
                anchor.sequence < previous_sequence
                or (
                    index > 0
                    and anchor.sequence == previous_sequence
                )
            ):
                raise ValueError(
                    "episode moments must advance temporal sequence"
                )
            if (
                previous_monotonic is not None
                and anchor.monotonic_ms < previous_monotonic
            ):
                raise ValueError(
                    "episode moment monotonic time moved backwards"
                )
            if (
                self.closed_anchor is not None
                and anchor.sequence > self.closed_anchor.sequence
            ):
                raise ValueError("episode moment occurs after close")
            previous_sequence = anchor.sequence
            previous_monotonic = anchor.monotonic_ms
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


def experience_episode_ref(
    episode: ExperienceEpisodeState,
) -> str:
    if not isinstance(episode, ExperienceEpisodeState):
        raise TypeError("episode must be ExperienceEpisodeState")
    return "experience-episode:" + _digest(episode)


def episode_moment_ref(moment: EpisodeMoment) -> str:
    if not isinstance(moment, EpisodeMoment):
        raise TypeError("moment must be EpisodeMoment")
    return "episode-moment:" + _digest(moment)


def open_experience_episode(
    *,
    self_id: str,
    person_revision: str,
    opening_anchor: TemporalAnchor | Mapping[str, Any],
    reason: EpisodeOpenReason,
) -> ExperienceEpisodeState:
    try:
        anchor = (
            opening_anchor
            if isinstance(opening_anchor, TemporalAnchor)
            else TemporalAnchor.model_validate(opening_anchor)
        )
    except ValidationError as exc:
        raise ExperientialEpisodeError(
            "invalid episode opening anchor"
        ) from exc
    if anchor.runtime_epoch_id is None or anchor.monotonic_ms is None:
        raise ExperientialEpisodeError(
            "episode opening requires trusted runtime anchor"
        )
    seed = {
        "self_id": self_id,
        "person_revision": person_revision,
        "opening_anchor": anchor.anchor_id,
        "reason": reason,
    }
    try:
        return ExperienceEpisodeState(
            schema=(
                "kaliv-consciousness-core/"
                "experience-episode-state/v1"
            ),
            episode_id="episode-" + _digest(seed)[:32],
            self_id=self_id,
            person_revision=person_revision,
            phase="ACTIVE",
            open_reason=reason,
            close_reason=None,
            opened_anchor=anchor,
            closed_anchor=None,
            moments=[],
            moment_count=0,
            evicted_moment_count=0,
            durable_memory_authority=False,
            self_state_store_write_applied=False,
            model_calls=0,
            execution_authority=False,
            scheduling_authority=False,
            timer_authority=False,
            production_activation=False,
        )
    except ValidationError as exc:
        raise ExperientialEpisodeError(
            "invalid experience episode identity"
        ) from exc


def build_episode_moment(
    *,
    kind: EpisodeMomentKind,
    source_ref: str,
    anchor: TemporalAnchor | Mapping[str, Any],
    salience: float,
    active_goal_refs: list[str] | None = None,
    participant_refs: list[str] | None = None,
) -> EpisodeMoment:
    try:
        temporal_anchor = (
            anchor
            if isinstance(anchor, TemporalAnchor)
            else TemporalAnchor.model_validate(anchor)
        )
        seed = {
            "kind": kind,
            "source_ref": source_ref,
            "anchor_id": temporal_anchor.anchor_id,
        }
        return EpisodeMoment(
            schema="kaliv-consciousness-core/episode-moment/v1",
            moment_id="moment-" + _digest(seed)[:32],
            kind=kind,
            source_ref=source_ref,
            anchor=temporal_anchor,
            salience=salience,
            active_goal_refs=list(
                dict.fromkeys(active_goal_refs or [])
            )[:64],
            participant_refs=list(
                dict.fromkeys(participant_refs or [])
            )[:32],
            raw_text_persisted=False,
            raw_chain_of_thought_persisted=False,
            production_activation=False,
        )
    except ValidationError as exc:
        raise ExperientialEpisodeError(
            "invalid episode moment"
        ) from exc


def append_episode_moment(
    episode: ExperienceEpisodeState | Mapping[str, Any],
    moment: EpisodeMoment | Mapping[str, Any],
) -> ExperienceEpisodeState:
    try:
        current = (
            episode
            if isinstance(episode, ExperienceEpisodeState)
            else ExperienceEpisodeState.model_validate(episode)
        )
        item = (
            moment
            if isinstance(moment, EpisodeMoment)
            else EpisodeMoment.model_validate(moment)
        )
    except ValidationError as exc:
        raise ExperientialEpisodeError(
            "invalid episode append input"
        ) from exc

    if current.phase != "ACTIVE":
        raise ExperientialEpisodeError(
            "cannot append to closed episode"
        )
    if (
        item.anchor.runtime_epoch_id
        != current.opened_anchor.runtime_epoch_id
    ):
        raise ExperientialEpisodeError(
            "episode moment crossed runtime epoch"
        )
    previous_anchor = (
        current.moments[-1].anchor
        if current.moments
        else current.opened_anchor
    )
    if (
        item.anchor.sequence < previous_anchor.sequence
        or (
            current.moments
            and item.anchor.sequence == previous_anchor.sequence
        )
    ):
        raise ExperientialEpisodeError(
            "episode moment sequence did not advance"
        )
    if (
        previous_anchor.monotonic_ms is None
        or item.anchor.monotonic_ms is None
        or item.anchor.monotonic_ms < previous_anchor.monotonic_ms
    ):
        raise ExperientialEpisodeError(
            "episode moment monotonic time did not advance"
        )
    if any(
        existing.moment_id == item.moment_id
        for existing in current.moments
    ):
        raise ExperientialEpisodeError(
            "episode moment already present"
        )

    payload = current.model_dump(mode="python")
    retained = [*current.moments, item]
    evicted = current.evicted_moment_count
    if len(retained) > 128:
        retained = retained[-128:]
        evicted += 1
    payload["moments"] = retained
    payload["moment_count"] = current.moment_count + 1
    payload["evicted_moment_count"] = evicted
    try:
        return ExperienceEpisodeState.model_validate(payload)
    except ValidationError as exc:
        raise ExperientialEpisodeError(
            "episode append produced invalid state"
        ) from exc


def close_experience_episode(
    episode: ExperienceEpisodeState | Mapping[str, Any],
    *,
    closing_anchor: TemporalAnchor | Mapping[str, Any],
    reason: EpisodeCloseReason,
) -> ExperienceEpisodeState:
    try:
        current = (
            episode
            if isinstance(episode, ExperienceEpisodeState)
            else ExperienceEpisodeState.model_validate(episode)
        )
        anchor = (
            closing_anchor
            if isinstance(closing_anchor, TemporalAnchor)
            else TemporalAnchor.model_validate(closing_anchor)
        )
    except ValidationError as exc:
        raise ExperientialEpisodeError(
            "invalid episode close input"
        ) from exc

    if current.phase != "ACTIVE":
        raise ExperientialEpisodeError(
            "episode is already closed"
        )
    if (
        anchor.runtime_epoch_id
        != current.opened_anchor.runtime_epoch_id
    ):
        raise ExperientialEpisodeError(
            "episode close crossed runtime epoch"
        )
    previous_anchor = (
        current.moments[-1].anchor
        if current.moments
        else current.opened_anchor
    )
    if anchor.sequence < previous_anchor.sequence:
        raise ExperientialEpisodeError(
            "episode close sequence moved backwards"
        )
    if (
        previous_anchor.monotonic_ms is None
        or anchor.monotonic_ms is None
        or anchor.monotonic_ms < previous_anchor.monotonic_ms
    ):
        raise ExperientialEpisodeError(
            "episode close monotonic time moved backwards"
        )

    payload = current.model_dump(mode="python")
    payload.update(
        {
            "phase": "CLOSED",
            "close_reason": reason,
            "closed_anchor": anchor,
        }
    )
    try:
        return ExperienceEpisodeState.model_validate(payload)
    except ValidationError as exc:
        raise ExperientialEpisodeError(
            "episode close produced invalid state"
        ) from exc
