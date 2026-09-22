"""C14 persistent SelfState authority for Consciousness Core.

SelfState is model-independent continuity state. This module has no public route,
model provider, tool executor, scheduler, Memory 4 writer or automatic bootstrap.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .. import paths as _paths

SELF_STATE_ENV = "KALIV_CONSCIOUSNESS_SELF_STATE"
_SELF_STATE_DEFAULT = "./kaliv-consciousness-self-state.json"

UnitInterval = Annotated[float, Field(ge=0.0, le=1.0, strict=True, allow_inf_nan=False)]
SignedUnit = Annotated[float, Field(ge=-1.0, le=1.0, strict=True, allow_inf_nan=False)]
NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
BoundedTopic = Annotated[str, Field(min_length=1, max_length=512)]


class SelfStateError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, frozen=True)


class SelfAffect(StrictModel):
    labels: Annotated[list[str], Field(max_length=16)]
    valence: SignedUnit
    arousal: UnitInterval
    confidence: UnitInterval
    source_refs: Annotated[list[NonEmptyRef], Field(max_length=32)]


class SelfUncertainty(StrictModel):
    topic: BoundedTopic
    confidence: UnitInterval
    source_refs: Annotated[list[NonEmptyRef], Field(max_length=32)]


class SelfBootstrapAuthority(StrictModel):
    schema: Literal["kaliv-consciousness-core/self-bootstrap-authority/v1"]
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_id: Annotated[str, Field(pattern=r"^person-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    authority: Literal["operator_review"]
    authority_ref: NonEmptyRef
    source_refs: Annotated[list[NonEmptyRef], Field(min_length=1, max_length=32)]
    production_activation: Literal[False]


class PersonRevisionRebindAuthority(StrictModel):
    schema: Literal["kaliv-consciousness-core/person-revision-rebind-authority/v1"]
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_id: Annotated[str, Field(pattern=r"^person-[a-f0-9]{32}$")]
    from_person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    to_person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    authority: Literal["person_revision_activation"]
    authority_ref: NonEmptyRef
    source_refs: Annotated[list[NonEmptyRef], Field(min_length=1, max_length=32)]
    production_activation: Literal[False]


class PersistentSelfState(StrictModel):
    schema: Literal["kaliv-consciousness-core/self-state/v1"]
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    revision: Annotated[int, Field(ge=1, strict=True)]
    person_id: Annotated[str, Field(pattern=r"^person-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    personality_state_ref: NonEmptyRef
    world_state_ref: NonEmptyRef
    workspace_ref: NonEmptyRef
    active_goal_refs: Annotated[list[NonEmptyRef], Field(max_length=64)]
    active_intention_refs: Annotated[list[NonEmptyRef], Field(max_length=64)]
    affect: SelfAffect
    known_uncertainties: Annotated[list[SelfUncertainty], Field(max_length=64)]
    last_experience_ref: NonEmptyRef | None
    production_activation: Literal[False]


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _unique(values: list[str], limit: int) -> list[str]:
    return list(dict.fromkeys(values))[:limit]


def bootstrap_self_state(
    authority: SelfBootstrapAuthority | Mapping[str, Any],
    *,
    personality_state_ref: str,
    world_state_ref: str,
    workspace_ref: str,
    affect: SelfAffect | Mapping[str, Any],
    active_goal_refs: list[str] | None = None,
    active_intention_refs: list[str] | None = None,
    known_uncertainties: list[SelfUncertainty | Mapping[str, Any]] | None = None,
    last_experience_ref: str | None = None,
) -> PersistentSelfState:
    try:
        auth = authority if isinstance(authority, SelfBootstrapAuthority) else SelfBootstrapAuthority.model_validate(authority)
        affect_value = affect if isinstance(affect, SelfAffect) else SelfAffect.model_validate(affect)
        uncertainties = [
            item if isinstance(item, SelfUncertainty) else SelfUncertainty.model_validate(item)
            for item in (known_uncertainties or [])
        ]
    except ValidationError as exc:
        raise SelfStateError("invalid SelfState bootstrap input") from exc

    return PersistentSelfState(
        schema="kaliv-consciousness-core/self-state/v1",
        self_id=auth.self_id,
        revision=1,
        person_id=auth.person_id,
        person_revision=auth.person_revision,
        personality_state_ref=personality_state_ref,
        world_state_ref=world_state_ref,
        workspace_ref=workspace_ref,
        active_goal_refs=_unique(active_goal_refs or [], 64),
        active_intention_refs=_unique(active_intention_refs or [], 64),
        affect=affect_value,
        known_uncertainties=uncertainties[:64],
        last_experience_ref=last_experience_ref,
        production_activation=False,
    )


def advance_self_state(
    current: PersistentSelfState | Mapping[str, Any],
    *,
    personality_state_ref: str | None = None,
    world_state_ref: str | None = None,
    workspace_ref: str | None = None,
    active_goal_refs: list[str] | None = None,
    active_intention_refs: list[str] | None = None,
    affect: SelfAffect | Mapping[str, Any] | None = None,
    known_uncertainties: list[SelfUncertainty | Mapping[str, Any]] | None = None,
    last_experience_ref: str | None = None,
    replace_last_experience: bool = False,
) -> PersistentSelfState:
    """Advance mutable self context while identity/person binding is immutable."""
    try:
        state = current if isinstance(current, PersistentSelfState) else PersistentSelfState.model_validate(current)
        affect_value = state.affect if affect is None else affect if isinstance(affect, SelfAffect) else SelfAffect.model_validate(affect)
        uncertainties = state.known_uncertainties if known_uncertainties is None else [
            item if isinstance(item, SelfUncertainty) else SelfUncertainty.model_validate(item)
            for item in known_uncertainties
        ]
    except ValidationError as exc:
        raise SelfStateError("invalid SelfState transition input") from exc

    return PersistentSelfState(
        schema=state.schema,
        self_id=state.self_id,
        revision=state.revision + 1,
        person_id=state.person_id,
        person_revision=state.person_revision,
        personality_state_ref=personality_state_ref or state.personality_state_ref,
        world_state_ref=world_state_ref or state.world_state_ref,
        workspace_ref=workspace_ref or state.workspace_ref,
        active_goal_refs=state.active_goal_refs if active_goal_refs is None else _unique(active_goal_refs, 64),
        active_intention_refs=state.active_intention_refs if active_intention_refs is None else _unique(active_intention_refs, 64),
        affect=affect_value,
        known_uncertainties=list(uncertainties)[:64],
        last_experience_ref=last_experience_ref if replace_last_experience else state.last_experience_ref,
        production_activation=False,
    )


def rebind_person_revision(
    current: PersistentSelfState | Mapping[str, Any],
    authority: PersonRevisionRebindAuthority | Mapping[str, Any],
    *,
    personality_state_ref: str,
) -> PersistentSelfState:
    try:
        state = current if isinstance(current, PersistentSelfState) else PersistentSelfState.model_validate(current)
        auth = authority if isinstance(authority, PersonRevisionRebindAuthority) else PersonRevisionRebindAuthority.model_validate(authority)
    except ValidationError as exc:
        raise SelfStateError("invalid Person Revision rebind input") from exc

    if auth.self_id != state.self_id or auth.person_id != state.person_id:
        raise SelfStateError("Person Revision rebind belongs to another identity")
    if auth.from_person_revision != state.person_revision:
        raise SelfStateError("Person Revision rebind has stale source revision")
    if auth.to_person_revision == auth.from_person_revision:
        raise SelfStateError("Person Revision rebind must change revision")

    try:
        return PersistentSelfState(
            schema=state.schema,
            self_id=state.self_id,
            revision=state.revision + 1,
            person_id=state.person_id,
            person_revision=auth.to_person_revision,
            personality_state_ref=personality_state_ref,
            world_state_ref=state.world_state_ref,
            workspace_ref=state.workspace_ref,
            active_goal_refs=state.active_goal_refs,
            active_intention_refs=state.active_intention_refs,
            affect=state.affect,
            known_uncertainties=state.known_uncertainties,
            last_experience_ref=state.last_experience_ref,
            production_activation=False,
        )
    except ValidationError as exc:
        raise SelfStateError("invalid rebound SelfState") from exc


def verify_active_person(
    state: PersistentSelfState | Mapping[str, Any],
    *,
    active_person_id: str,
    active_person_revision: str,
) -> PersistentSelfState:
    try:
        current = state if isinstance(state, PersistentSelfState) else PersistentSelfState.model_validate(state)
    except ValidationError as exc:
        raise SelfStateError("invalid persisted SelfState") from exc
    if current.person_id != active_person_id:
        raise SelfStateError("active Person Profile belongs to another person")
    if current.person_revision != active_person_revision:
        raise SelfStateError("active Person Revision does not match SelfState")
    return current


class SelfStateStore:
    """Atomic single-current-state authority; no history or autobiographical memory."""

    def __init__(self, path: str | Path | None = None) -> None:
        resolved = str(path) if path is not None else _paths.resolve(_SELF_STATE_DEFAULT, env=SELF_STATE_ENV)
        self.path = Path(resolved)

    def read(self) -> PersistentSelfState | None:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return None
        if len(raw) > 512 * 1024:
            raise SelfStateError("SelfState exceeds bounded size")
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SelfStateError("malformed SelfState envelope") from exc
        if not isinstance(envelope, dict) or envelope.get("schema") != "kaliv-consciousness-core/self-state-envelope/v1":
            raise SelfStateError("unsupported SelfState envelope")
        payload = envelope.get("payload")
        digest = envelope.get("payload_sha256")
        if not isinstance(payload, dict) or not isinstance(digest, str):
            raise SelfStateError("incomplete SelfState envelope")
        if _digest(payload) != digest:
            raise SelfStateError("SelfState digest mismatch")
        try:
            return PersistentSelfState.model_validate(payload)
        except ValidationError as exc:
            raise SelfStateError("invalid persisted SelfState") from exc

    def bootstrap(
        self,
        state: PersistentSelfState,
        authority: SelfBootstrapAuthority,
    ) -> None:
        if self.path.exists():
            raise SelfStateError("SelfState already exists")
        if state.revision != 1:
            raise SelfStateError("bootstrap state must start at revision 1")
        if state.self_id != authority.self_id or state.person_id != authority.person_id or state.person_revision != authority.person_revision:
            raise SelfStateError("bootstrap authority does not match SelfState")
        self._write_atomic(state)

    def write_next(
        self,
        state: PersistentSelfState,
        *,
        rebind_authority: PersonRevisionRebindAuthority | None = None,
    ) -> None:
        current = self.read()
        if current is None:
            raise SelfStateError("cannot advance missing SelfState")
        if state.revision != current.revision + 1:
            raise SelfStateError("SelfState revision must advance exactly by one")
        if state.self_id != current.self_id or state.person_id != current.person_id:
            raise SelfStateError("SelfState identity cannot change")
        if state.person_revision != current.person_revision:
            if rebind_authority is None:
                raise SelfStateError("Person Revision change requires rebind authority")
            if (
                rebind_authority.self_id != current.self_id
                or rebind_authority.person_id != current.person_id
                or rebind_authority.from_person_revision != current.person_revision
                or rebind_authority.to_person_revision != state.person_revision
            ):
                raise SelfStateError("rebind authority does not match transition")
        self._write_atomic(state)

    def _write_atomic(self, state: PersistentSelfState) -> None:
        payload = state.model_dump(mode="json")
        envelope = {
            "schema": "kaliv-consciousness-core/self-state-envelope/v1",
            "payload": payload,
            "payload_sha256": _digest(payload),
        }
        encoded = _canonical_json(envelope) + b"\n"
        if len(encoded) > 512 * 1024:
            raise SelfStateError("SelfState exceeds bounded size")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "wb", closefd=True) as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise
