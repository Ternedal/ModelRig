"""C13-A persisted sleep boundary and inert lifecycle seam.

Default-off, route-less and scheduler-less. Persistence happens only after an
explicit enable check AND an authoritative Self/Person binding.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from contextlib import asynccontextmanager
from functools import wraps
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .. import paths as _paths
from .sleep import SleepRecord, WakeReceipt, prepare_sleep, wake_from_sleep
from .temporal import TemporalAnchor

SLEEP_LIFECYCLE_FLAG = "KALIV_CONSCIOUSNESS_SLEEP_LIFECYCLE_ENABLED"
SLEEP_STATE_ENV = "KALIV_CONSCIOUSNESS_SLEEP_STATE"
_SLEEP_STATE_DEFAULT = "./kaliv-consciousness-sleep.json"

NonEmptyRef = Annotated[str, Field(min_length=1, max_length=256)]


class SleepLifecycleError(RuntimeError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class SleepBinding(StrictModel):
    schema: Literal["kaliv-consciousness-core/sleep-binding/v1"]
    self_id: Annotated[str, Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_revision: Annotated[str, Field(pattern=r"^person-r[0-9]{4,}$")]
    durable_self_state_ref: NonEmptyRef | None = None
    durable_self_state_revision: Annotated[int, Field(ge=1, strict=True)] | None = None
    open_goal_refs: Annotated[list[NonEmptyRef], Field(max_length=64)]
    open_loop_refs: Annotated[list[NonEmptyRef], Field(max_length=64)]
    pending_review_refs: Annotated[list[NonEmptyRef], Field(max_length=64)]
    production_activation: Literal[False]

    @model_validator(mode="after")
    def exact_self_state_binding(self) -> "SleepBinding":
        if (
            self.durable_self_state_ref is None
        ) != (
            self.durable_self_state_revision is None
        ):
            raise ValueError(
                "sleep binding SelfState ref/revision must be both present or absent"
            )
        return self


def sleep_lifecycle_enabled() -> bool:
    return os.getenv(SLEEP_LIFECYCLE_FLAG, "").strip() == "1"


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


class SleepStateStore:
    """One bounded atomic lifecycle record; not autobiographical memory."""

    def __init__(self, path: str | Path | None = None) -> None:
        resolved = (
            str(path)
            if path is not None
            else _paths.resolve(_SLEEP_STATE_DEFAULT, env=SLEEP_STATE_ENV)
        )
        self.path = Path(resolved)

    def read(self) -> SleepRecord | None:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return None
        if len(raw) > 512 * 1024:
            raise SleepLifecycleError("sleep state exceeds bounded size")
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SleepLifecycleError("malformed sleep state") from exc
        if not isinstance(envelope, dict):
            raise SleepLifecycleError("sleep state envelope must be an object")
        if envelope.get("schema") != "kaliv-consciousness-core/sleep-envelope/v1":
            raise SleepLifecycleError("unsupported sleep state schema")
        payload = envelope.get("payload")
        digest = envelope.get("payload_sha256")
        if not isinstance(payload, dict) or not isinstance(digest, str):
            raise SleepLifecycleError("incomplete sleep state envelope")
        if _digest(payload) != digest:
            raise SleepLifecycleError("sleep state digest mismatch")
        try:
            return SleepRecord.model_validate(payload)
        except Exception as exc:
            raise SleepLifecycleError("invalid SleepRecord payload") from exc

    def write(self, record: SleepRecord) -> None:
        if not isinstance(record, SleepRecord):
            raise SleepLifecycleError("write requires SleepRecord")
        payload = record.model_dump(mode="json")
        envelope = {
            "schema": "kaliv-consciousness-core/sleep-envelope/v1",
            "payload": payload,
            "payload_sha256": _digest(payload),
        }
        encoded = _canonical_json(envelope) + b"\n"
        if len(encoded) > 512 * 1024:
            raise SleepLifecycleError("sleep state exceeds bounded size")

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


BindingProvider = Callable[[], SleepBinding | None]
AnchorProvider = Callable[[str], TemporalAnchor]
StoreFactory = Callable[[], SleepStateStore]


class SleepLifecycleRuntime:
    """Default-off startup/shutdown seam around C12 contracts."""

    def __init__(
        self,
        *,
        enabled_fn: Callable[[], bool] = sleep_lifecycle_enabled,
        binding_provider: BindingProvider,
        anchor_provider: AnchorProvider,
        store_factory: StoreFactory = SleepStateStore,
    ) -> None:
        self._enabled_fn = enabled_fn
        self._binding_provider = binding_provider
        self._anchor_provider = anchor_provider
        self._store_factory = store_factory
        self._store: SleepStateStore | None = None
        self.wake_receipt: WakeReceipt | None = None
        self.last_error: str | None = None
        self.configured = False

    def start(self) -> bool:
        try:
            enabled = bool(self._enabled_fn())
        except Exception as exc:
            self.last_error = f"feature flag check failed: {type(exc).__name__}: {exc}"[:500]
            return False
        if not enabled:
            self.configured = False
            self.last_error = None
            return False

        binding = self._binding_provider()
        if binding is None:
            # Never read an old record when we cannot authenticate its identity.
            self.configured = True
            self.last_error = None
            return False
        if not isinstance(binding, SleepBinding):
            raise SleepLifecycleError("binding provider must return SleepBinding or None")

        store = self._store_factory()
        prior = store.read()
        self._store = store
        self.configured = True
        self.last_error = None
        if prior is None:
            self.wake_receipt = None
            return True

        wake_anchor = self._anchor_provider("wake")
        self.wake_receipt = wake_from_sleep(
            wake_anchor=wake_anchor,
            sleep_record=prior,
            expected_self_id=binding.self_id,
            expected_person_revision=binding.person_revision,
        )
        return True

    def close(self, *, reason: Literal["app_closed", "host_shutdown", "suspend"] = "app_closed") -> bool:
        try:
            enabled = bool(self._enabled_fn())
        except Exception as exc:
            self.last_error = f"feature flag check failed: {type(exc).__name__}: {exc}"[:500]
            return False
        if not enabled:
            return False

        binding = self._binding_provider()
        if binding is None:
            # Shutdown must never fabricate a self/person binding.
            return False
        if not isinstance(binding, SleepBinding):
            raise SleepLifecycleError("binding provider must return SleepBinding or None")

        try:
            entry_anchor = self._anchor_provider("sleep")
            record = prepare_sleep(
                self_id=binding.self_id,
                person_revision=binding.person_revision,
                entry_anchor=entry_anchor,
                reason=reason,
                durable_self_state_ref=binding.durable_self_state_ref,
                durable_self_state_revision=binding.durable_self_state_revision,
                open_goal_refs=binding.open_goal_refs,
                open_loop_refs=binding.open_loop_refs,
                pending_review_refs=binding.pending_review_refs,
            )
            store = self._store or self._store_factory()
            store.write(record)
            self._store = store
            self.last_error = None
            return True
        except Exception as exc:
            self.last_error = f"sleep boundary write failed: {type(exc).__name__}: {exc}"[:500]
            return False


def compose_sleep_lifecycle_lifespan(inner_lifespan, runtime_factory):
    """Compose C13 without transferring the existing production lifespan owner."""
    if not callable(inner_lifespan):
        raise TypeError("inner lifespan must be callable")
    if not callable(runtime_factory):
        raise TypeError("runtime_factory must be callable")
    authority_owner = getattr(inner_lifespan, "__wrapped__", inner_lifespan)

    @wraps(inner_lifespan)
    @asynccontextmanager
    async def composed(app):
        async with inner_lifespan(app):
            runtime = runtime_factory(app)
            if not isinstance(runtime, SleepLifecycleRuntime):
                raise TypeError("runtime_factory must return SleepLifecycleRuntime")
            started = runtime.start()
            if started:
                app.state.consciousness_sleep_wake_receipt = runtime.wake_receipt
            try:
                yield
            finally:
                runtime.close()

    composed.__wrapped__ = authority_owner
    return composed
