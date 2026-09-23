"""C29-A durable runtime liveness witness primitive.

A liveness witness proves only that one exact durable SelfState existed while the
runtime was alive at one trusted C11 temporal anchor. It does not claim when a
later crash occurred and does not claim cognition continued after the anchor.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Annotated, Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .cycle import self_state_ref
from .self_state import PersistentSelfState
from .temporal import TemporalAnchor


NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]
SelfStateRevision = Annotated[int, Field(ge=1, strict=True)]


class RuntimeLivenessError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )


class RuntimeLivenessWitness(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/runtime-liveness-witness/v1"
    ]
    witness_id: Annotated[
        str,
        Field(pattern=r"^live-[a-f0-9]{32}$"),
    ]
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_id: Annotated[str, Field(pattern=r"^person-[a-f0-9]{32}$")]
    person_revision: Annotated[
        str,
        Field(pattern=r"^person-r[0-9]{4,}$"),
    ]
    durable_self_state_ref: NonEmptyRef
    durable_self_state_revision: SelfStateRevision
    anchor: TemporalAnchor
    source_ref: NonEmptyRef
    runtime_alive_at_anchor: Literal[True]
    cognition_after_anchor_claimed: Literal[False]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]


class RuntimeLivenessWriteReceipt(StrictModel):
    schema: Literal[
        "kaliv-consciousness-core/runtime-liveness-write-receipt/v1"
    ]
    outcome: Literal["CREATED", "UPDATED", "IDEMPOTENT"]
    previous_witness_ref: NonEmptyRef | None
    witness_ref: NonEmptyRef
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_id: Annotated[str, Field(pattern=r"^person-[a-f0-9]{32}$")]
    person_revision: Annotated[
        str,
        Field(pattern=r"^person-r[0-9]{4,}$"),
    ]
    durable_self_state_revision_before: SelfStateRevision | None
    durable_self_state_revision_after: SelfStateRevision
    store_write_applied: bool
    runtime_alive_at_anchor: Literal[True]
    cognition_after_anchor_claimed: Literal[False]
    model_calls: Literal[0]
    durable_memory_write_authority: Literal[False]
    execution_authority: Literal[False]
    scheduling_authority: Literal[False]
    production_activation: Literal[False]


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


def runtime_liveness_witness_ref(
    witness: RuntimeLivenessWitness,
) -> str:
    if not isinstance(witness, RuntimeLivenessWitness):
        raise TypeError("witness must be RuntimeLivenessWitness")
    return "runtime-liveness-witness:" + _digest(witness)


def _validate_trusted_anchor(anchor: TemporalAnchor) -> None:
    if anchor.runtime_epoch_id is None:
        raise RuntimeLivenessError(
            "liveness witness requires runtime epoch binding"
        )
    if anchor.monotonic_ms is None:
        raise RuntimeLivenessError(
            "liveness witness requires monotonic clock evidence"
        )
    if anchor.wall_time_unix_ms is None:
        raise RuntimeLivenessError(
            "liveness witness requires wall-clock evidence"
        )
    if anchor.confidence != 1.0:
        raise RuntimeLivenessError(
            "liveness witness requires trusted temporal confidence"
        )


def build_runtime_liveness_witness(
    *,
    state: PersistentSelfState | Mapping[str, Any],
    anchor: TemporalAnchor | Mapping[str, Any],
    source_ref: str,
) -> RuntimeLivenessWitness:
    """Bind one exact durable SelfState to one trusted liveness anchor."""
    try:
        durable = (
            state
            if isinstance(state, PersistentSelfState)
            else PersistentSelfState.model_validate(state)
        )
        temporal = (
            anchor
            if isinstance(anchor, TemporalAnchor)
            else TemporalAnchor.model_validate(anchor)
        )
    except ValidationError as exc:
        raise RuntimeLivenessError(
            "invalid runtime liveness witness input"
        ) from exc

    if (
        not isinstance(source_ref, str)
        or not source_ref.strip()
        or source_ref != source_ref.strip()
        or len(source_ref) > 256
    ):
        raise RuntimeLivenessError(
            "runtime liveness source_ref is invalid"
        )
    _validate_trusted_anchor(temporal)

    durable_ref = self_state_ref(durable)
    seed = {
        "self_id": durable.self_id,
        "person_id": durable.person_id,
        "person_revision": durable.person_revision,
        "durable_self_state_ref": durable_ref,
        "durable_self_state_revision": durable.revision,
        "anchor_id": temporal.anchor_id,
        "source_ref": source_ref,
        "kind": "runtime-liveness-v1",
    }
    return RuntimeLivenessWitness(
        schema=(
            "kaliv-consciousness-core/runtime-liveness-witness/v1"
        ),
        witness_id="live-" + _digest(seed)[:32],
        self_id=durable.self_id,
        person_id=durable.person_id,
        person_revision=durable.person_revision,
        durable_self_state_ref=durable_ref,
        durable_self_state_revision=durable.revision,
        anchor=temporal,
        source_ref=source_ref,
        runtime_alive_at_anchor=True,
        cognition_after_anchor_claimed=False,
        durable_memory_write_authority=False,
        execution_authority=False,
        scheduling_authority=False,
        production_activation=False,
    )


class RuntimeLivenessStore:
    """One bounded atomic liveness witness; never an event history."""

    MAX_BYTES = 256 * 1024

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def read(self) -> RuntimeLivenessWitness | None:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return None
        if len(raw) > self.MAX_BYTES:
            raise RuntimeLivenessError(
                "runtime liveness state exceeds bounded size"
            )
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeLivenessError(
                "malformed runtime liveness state"
            ) from exc
        if not isinstance(envelope, dict):
            raise RuntimeLivenessError(
                "runtime liveness envelope must be an object"
            )
        if envelope.get("schema") != (
            "kaliv-consciousness-core/runtime-liveness-envelope/v1"
        ):
            raise RuntimeLivenessError(
                "unsupported runtime liveness envelope schema"
            )
        payload = envelope.get("payload")
        digest = envelope.get("payload_sha256")
        if not isinstance(payload, dict) or not isinstance(digest, str):
            raise RuntimeLivenessError(
                "incomplete runtime liveness envelope"
            )
        if _digest(payload) != digest:
            raise RuntimeLivenessError(
                "runtime liveness digest mismatch"
            )
        try:
            witness = RuntimeLivenessWitness.model_validate(payload)
        except ValidationError as exc:
            raise RuntimeLivenessError(
                "invalid runtime liveness payload"
            ) from exc
        _validate_trusted_anchor(witness.anchor)
        return witness

    def _write(self, witness: RuntimeLivenessWitness) -> None:
        payload = witness.model_dump(mode="json")
        envelope = {
            "schema": (
                "kaliv-consciousness-core/"
                "runtime-liveness-envelope/v1"
            ),
            "payload": payload,
            "payload_sha256": _digest(payload),
        }
        encoded = _canonical_json(envelope) + b"\n"
        if len(encoded) > self.MAX_BYTES:
            raise RuntimeLivenessError(
                "runtime liveness state exceeds bounded size"
            )

        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=self.path.name + ".",
            suffix=".tmp",
            dir=str(self.path.parent),
        )
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

    @staticmethod
    def _same_identity(
        left: RuntimeLivenessWitness,
        right: RuntimeLivenessWitness,
    ) -> bool:
        return (
            left.self_id == right.self_id
            and left.person_id == right.person_id
            and left.person_revision == right.person_revision
        )

    @staticmethod
    def _validate_forward(
        current: RuntimeLivenessWitness,
        next_witness: RuntimeLivenessWitness,
    ) -> None:
        if not RuntimeLivenessStore._same_identity(
            current,
            next_witness,
        ):
            raise RuntimeLivenessError(
                "runtime liveness identity binding changed"
            )

        before = current.durable_self_state_revision
        after = next_witness.durable_self_state_revision
        if after < before:
            raise RuntimeLivenessError(
                "runtime liveness durable SelfState revision moved backwards"
            )

        if after == before:
            if (
                next_witness.durable_self_state_ref
                != current.durable_self_state_ref
            ):
                raise RuntimeLivenessError(
                    "same durable SelfState revision has conflicting ref"
                )
            if (
                next_witness.anchor.runtime_epoch_id
                != current.anchor.runtime_epoch_id
            ):
                raise RuntimeLivenessError(
                    "same durable revision cannot cross runtime epochs"
                )
            if next_witness.anchor.sequence <= current.anchor.sequence:
                raise RuntimeLivenessError(
                    "runtime liveness temporal sequence is stale"
                )
            if (
                next_witness.anchor.monotonic_ms
                < current.anchor.monotonic_ms
            ):
                raise RuntimeLivenessError(
                    "runtime liveness monotonic clock moved backwards"
                )
            return

        # Higher durable revisions may legitimately cross a process restart.
        # Within one epoch, trusted time still cannot move backwards.
        if (
            next_witness.anchor.runtime_epoch_id
            == current.anchor.runtime_epoch_id
        ):
            if next_witness.anchor.sequence <= current.anchor.sequence:
                raise RuntimeLivenessError(
                    "runtime liveness temporal sequence is stale"
                )
            if (
                next_witness.anchor.monotonic_ms
                < current.anchor.monotonic_ms
            ):
                raise RuntimeLivenessError(
                    "runtime liveness monotonic clock moved backwards"
                )

    def write_next(
        self,
        witness: RuntimeLivenessWitness,
    ) -> RuntimeLivenessWriteReceipt:
        if not isinstance(witness, RuntimeLivenessWitness):
            raise TypeError(
                "witness must be RuntimeLivenessWitness"
            )
        _validate_trusted_anchor(witness.anchor)

        current = self.read()
        witness_ref = runtime_liveness_witness_ref(witness)
        if current is None:
            self._write(witness)
            return RuntimeLivenessWriteReceipt(
                schema=(
                    "kaliv-consciousness-core/"
                    "runtime-liveness-write-receipt/v1"
                ),
                outcome="CREATED",
                previous_witness_ref=None,
                witness_ref=witness_ref,
                self_id=witness.self_id,
                person_id=witness.person_id,
                person_revision=witness.person_revision,
                durable_self_state_revision_before=None,
                durable_self_state_revision_after=(
                    witness.durable_self_state_revision
                ),
                store_write_applied=True,
                runtime_alive_at_anchor=True,
                cognition_after_anchor_claimed=False,
                model_calls=0,
                durable_memory_write_authority=False,
                execution_authority=False,
                scheduling_authority=False,
                production_activation=False,
            )

        current_ref = runtime_liveness_witness_ref(current)
        if current == witness:
            return RuntimeLivenessWriteReceipt(
                schema=(
                    "kaliv-consciousness-core/"
                    "runtime-liveness-write-receipt/v1"
                ),
                outcome="IDEMPOTENT",
                previous_witness_ref=current_ref,
                witness_ref=witness_ref,
                self_id=witness.self_id,
                person_id=witness.person_id,
                person_revision=witness.person_revision,
                durable_self_state_revision_before=(
                    current.durable_self_state_revision
                ),
                durable_self_state_revision_after=(
                    witness.durable_self_state_revision
                ),
                store_write_applied=False,
                runtime_alive_at_anchor=True,
                cognition_after_anchor_claimed=False,
                model_calls=0,
                durable_memory_write_authority=False,
                execution_authority=False,
                scheduling_authority=False,
                production_activation=False,
            )

        self._validate_forward(current, witness)
        self._write(witness)
        return RuntimeLivenessWriteReceipt(
            schema=(
                "kaliv-consciousness-core/"
                "runtime-liveness-write-receipt/v1"
            ),
            outcome="UPDATED",
            previous_witness_ref=current_ref,
            witness_ref=witness_ref,
            self_id=witness.self_id,
            person_id=witness.person_id,
            person_revision=witness.person_revision,
            durable_self_state_revision_before=(
                current.durable_self_state_revision
            ),
            durable_self_state_revision_after=(
                witness.durable_self_state_revision
            ),
            store_write_applied=True,
            runtime_alive_at_anchor=True,
            cognition_after_anchor_claimed=False,
            model_calls=0,
            durable_memory_write_authority=False,
            execution_authority=False,
            scheduling_authority=False,
            production_activation=False,
        )
