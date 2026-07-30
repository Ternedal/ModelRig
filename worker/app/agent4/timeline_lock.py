"""Cross-process single-writer composition for the Agent 4 durable timeline.

The lock is acquired only around an explicit caller-driven operation. It uses a
separate one-byte lock file and operating-system advisory locks, so the lock is
released automatically when the owning process exits. No thread, timer, retry
loop beyond the bounded acquisition wait, or runtime mount is created.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import os
from pathlib import Path
from threading import RLock
import time
from typing import BinaryIO, Callable, Iterator, Mapping

from .domain import (
    CampaignEvent,
    CampaignEventKind,
    CampaignValidationError,
    JsonValue,
)
from .timeline import (
    CampaignEvidence,
    CampaignTimelineEntry,
    JsonlCampaignTimelineStore,
)

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class CampaignTimelineLockError(RuntimeError):
    """Base error for cross-process timeline lock operations."""


class CampaignTimelineLockTimeout(CampaignTimelineLockError):
    """Raised when another writer retains the campaign lock past the deadline."""


def _require_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CampaignValidationError(f"{field_name} must not be empty")
    return value.strip()


def _require_positive_number(value: float, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise CampaignValidationError(f"{field_name} must be a positive number")
    return float(value)


def _try_lock(stream: BinaryIO) -> bool:
    if os.name == "nt":
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    try:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def _unlock(stream: BinaryIO) -> None:
    if os.name == "nt":
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        return
    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@dataclass(slots=True)
class CampaignTimelineFileLease:
    """One acquired operating-system lock, released idempotently."""

    campaign_id: str
    path: Path
    _stream: BinaryIO = field(repr=False)
    _released: bool = field(default=False, init=False, repr=False)

    @property
    def released(self) -> bool:
        return self._released

    def release(self) -> None:
        if self._released:
            return
        try:
            _unlock(self._stream)
        except OSError as exc:
            raise CampaignTimelineLockError(
                f"release timeline lock {self.path.name}: {exc}"
            ) from exc
        finally:
            self._stream.close()
            self._released = True

    def __enter__(self) -> "CampaignTimelineFileLease":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


class FileCampaignTimelineLockManager:
    """Portable advisory lock manager with bounded acquisition."""

    def __init__(
        self,
        timeline_directory: Path | str,
        *,
        timeout_seconds: float = 5.0,
        poll_interval_seconds: float = 0.01,
    ) -> None:
        timeline_directory = Path(timeline_directory)
        self._lock_directory = timeline_directory.parent / (
            f".{timeline_directory.name}.writer-locks"
        )
        self._timeout_seconds = _require_positive_number(
            timeout_seconds, "timeout_seconds"
        )
        self._poll_interval_seconds = _require_positive_number(
            poll_interval_seconds, "poll_interval_seconds"
        )
        if self._poll_interval_seconds > self._timeout_seconds:
            raise CampaignValidationError(
                "poll_interval_seconds must not exceed timeout_seconds"
            )

    @property
    def lock_directory(self) -> Path:
        return self._lock_directory

    @staticmethod
    def _key(campaign_id: str) -> str:
        normalized = _require_text(campaign_id, "campaign_id")
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def path_for(self, campaign_id: str) -> Path:
        return self._lock_directory / f"{self._key(campaign_id)}.lock"

    def acquire(self, campaign_id: str) -> CampaignTimelineFileLease:
        campaign_id = _require_text(campaign_id, "campaign_id")
        self._lock_directory.mkdir(parents=True, exist_ok=True)
        path = self.path_for(campaign_id)
        try:
            stream = path.open("a+b", buffering=0)
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise CampaignTimelineLockError(
                f"open timeline lock {path.name}: {exc}"
            ) from exc

        deadline = time.monotonic() + self._timeout_seconds
        while True:
            try:
                acquired = _try_lock(stream)
            except OSError as exc:
                stream.close()
                raise CampaignTimelineLockError(
                    f"acquire timeline lock {path.name}: {exc}"
                ) from exc
            if acquired:
                return CampaignTimelineFileLease(
                    campaign_id=campaign_id,
                    path=path,
                    _stream=stream,
                )
            if time.monotonic() >= deadline:
                stream.close()
                raise CampaignTimelineLockTimeout(
                    f"campaign {campaign_id!r} writer lock timed out"
                )
            time.sleep(self._poll_interval_seconds)

    @contextmanager
    def hold(self, campaign_id: str) -> Iterator[CampaignTimelineFileLease]:
        lease = self.acquire(campaign_id)
        try:
            yield lease
        finally:
            lease.release()


class ProcessSafeCampaignTimeline:
    """Durable timeline facade serialized across processes per campaign."""

    def __init__(
        self,
        directory: Path | str,
        *,
        timeout_seconds: float = 5.0,
        poll_interval_seconds: float = 0.01,
    ) -> None:
        self._timeline = JsonlCampaignTimelineStore(directory)
        self._locks = FileCampaignTimelineLockManager(
            directory,
            timeout_seconds=timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )
        self._handlers: dict[int, Callable[[CampaignEvent], None]] = {}
        self._next_handler_id = 0
        self._handler_lock = RLock()

    @property
    def lock_manager(self) -> FileCampaignTimelineLockManager:
        return self._locks

    def subscribe(self, handler: Callable[[CampaignEvent], None]) -> Callable[[], None]:
        if not callable(handler):
            raise TypeError("event handler must be callable")
        with self._handler_lock:
            self._next_handler_id += 1
            handler_id = self._next_handler_id
            self._handlers[handler_id] = handler

        def unsubscribe() -> None:
            with self._handler_lock:
                self._handlers.pop(handler_id, None)

        return unsubscribe

    def history(self, campaign_id: str) -> tuple[CampaignTimelineEntry, ...]:
        with self._locks.hold(campaign_id):
            return self._timeline.history(campaign_id)

    def events(self, campaign_id: str) -> tuple[CampaignEvent, ...]:
        with self._locks.hold(campaign_id):
            return self._timeline.events(campaign_id)

    def evidence(self, campaign_id: str) -> tuple[CampaignEvidence, ...]:
        with self._locks.hold(campaign_id):
            return self._timeline.evidence(campaign_id)

    def latest_timeline_sequence(self, campaign_id: str) -> int:
        with self._locks.hold(campaign_id):
            return self._timeline.latest_timeline_sequence(campaign_id)

    def latest_event_sequence(self, campaign_id: str) -> int:
        with self._locks.hold(campaign_id):
            return self._timeline.latest_event_sequence(campaign_id)

    def append_event(self, event: CampaignEvent) -> CampaignTimelineEntry:
        with self._locks.hold(event.campaign_id):
            return self._timeline.append_event(event)

    def append_evidence(self, evidence: CampaignEvidence) -> CampaignTimelineEntry:
        with self._locks.hold(evidence.campaign_id):
            return self._timeline.append_evidence(evidence)

    def record(
        self,
        campaign_id: str,
        kind: CampaignEventKind,
        *,
        occurred_at: datetime,
        payload: Mapping[str, JsonValue] | None = None,
    ) -> CampaignEvent:
        with self._locks.hold(campaign_id):
            event = self._timeline.record_event(
                campaign_id,
                kind,
                occurred_at=occurred_at,
                payload=payload,
            )
        self._notify(event)
        return event

    def publish(self, event: CampaignEvent) -> None:
        with self._locks.hold(event.campaign_id):
            self._timeline.append_event(event)
        self._notify(event)

    def verify(self, campaign_id: str) -> tuple[CampaignTimelineEntry, ...]:
        with self._locks.hold(campaign_id):
            return self._timeline.verify(campaign_id)

    def _notify(self, event: CampaignEvent) -> None:
        with self._handler_lock:
            handlers = tuple(self._handlers.values())
        for handler in handlers:
            handler(event)
