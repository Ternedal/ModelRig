"""In-memory ordered event bus used by the Agent 4 foundation."""

from __future__ import annotations

from collections import defaultdict
from threading import RLock
from typing import Callable

from .contracts import CampaignEventHandler
from .domain import CampaignEvent, CampaignValidationError


class CampaignEventOrderError(ValueError):
    """Raised when an event would break per-campaign ordering."""


class InMemoryCampaignEventBus:
    """Synchronous event bus with validated per-campaign sequence ordering."""

    def __init__(self, *, history_limit: int = 1000) -> None:
        if isinstance(history_limit, bool) or history_limit < 1:
            raise CampaignValidationError("history_limit must be at least 1")
        self._history_limit = history_limit
        self._history: dict[str, list[CampaignEvent]] = defaultdict(list)
        self._event_ids: set[str] = set()
        self._handlers: dict[int, CampaignEventHandler] = {}
        self._next_handler_id = 0
        self._lock = RLock()

    def subscribe(self, handler: CampaignEventHandler) -> Callable[[], None]:
        if not callable(handler):
            raise TypeError("event handler must be callable")
        with self._lock:
            self._next_handler_id += 1
            handler_id = self._next_handler_id
            self._handlers[handler_id] = handler

        def unsubscribe() -> None:
            with self._lock:
                self._handlers.pop(handler_id, None)

        return unsubscribe

    def publish(self, event: CampaignEvent) -> None:
        with self._lock:
            if event.event_id in self._event_ids:
                raise CampaignEventOrderError(
                    f"event id {event.event_id!r} has already been published"
                )
            history = self._history[event.campaign_id]
            expected_sequence = history[-1].sequence + 1 if history else 1
            if event.sequence != expected_sequence:
                raise CampaignEventOrderError(
                    f"campaign {event.campaign_id!r} expected event sequence "
                    f"{expected_sequence}, got {event.sequence}"
                )

            history.append(event)
            self._event_ids.add(event.event_id)
            if len(history) > self._history_limit:
                history.pop(0)
            handlers = tuple(self._handlers.values())

        for handler in handlers:
            handler(event)

    def history(self, campaign_id: str) -> tuple[CampaignEvent, ...]:
        with self._lock:
            return tuple(self._history.get(campaign_id, ()))

    def latest_sequence(self, campaign_id: str) -> int:
        with self._lock:
            history = self._history.get(campaign_id)
            return history[-1].sequence if history else 0
