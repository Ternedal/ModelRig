"""Deterministic retry classification and backoff for Agent 4 campaigns.

The policy in this module only makes a decision.  It does not mutate campaign
state, enqueue work or sleep, keeping automatic retries dormant until a later
scheduler-integration slice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Mapping, Protocol, runtime_checkable

from .domain import CampaignSpec, CampaignState, CampaignValidationError, JsonValue


class RetryCategory(StrEnum):
    TRANSIENT = "transient"
    RATE_LIMITED = "rate_limited"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    PERMANENT = "permanent"
    CANCELLED = "cancelled"


class RetryDisposition(StrEnum):
    RETRY = "retry"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class FailureDescriptor:
    """Persistable description of one failed execution phase."""

    error_type: str
    message: str
    phase: str
    retry_after: timedelta | None = None
    metadata: Mapping[str, JsonValue] | None = None

    def __post_init__(self) -> None:
        for field_name in ("error_type", "message", "phase"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise CampaignValidationError(f"{field_name} must not be empty")
            object.__setattr__(self, field_name, value.strip())
        if self.retry_after is not None:
            if (
                not isinstance(self.retry_after, timedelta)
                or self.retry_after < timedelta(0)
            ):
                raise CampaignValidationError(
                    "retry_after must be a non-negative timedelta"
                )
        if self.metadata is not None and not isinstance(self.metadata, Mapping):
            raise CampaignValidationError("metadata must be a mapping")


@runtime_checkable
class RetryClassifier(Protocol):
    def classify(self, failure: FailureDescriptor) -> RetryCategory:
        """Classify one failure without side effects."""


class DefaultRetryClassifier:
    """Conservative exact-type classifier with no message heuristics."""

    _RATE_LIMITED = frozenset({"RateLimitError", "TooManyRequestsError"})
    _RESOURCE_EXHAUSTED = frozenset(
        {"CampaignResourceBlockedError", "ResourceExhaustedError"}
    )
    _TRANSIENT = frozenset(
        {
            "TimeoutError",
            "ConnectionError",
            "ConnectionResetError",
            "ConnectionAbortedError",
            "BrokenPipeError",
            "TemporaryError",
            "ServiceUnavailableError",
            "OSError",
        }
    )
    _CANCELLED = frozenset({"CancelledError", "CampaignCancelledError"})

    def classify(self, failure: FailureDescriptor) -> RetryCategory:
        error_type = failure.error_type.rsplit(".", 1)[-1]
        if error_type in self._CANCELLED:
            return RetryCategory.CANCELLED
        if error_type in self._RATE_LIMITED:
            return RetryCategory.RATE_LIMITED
        if error_type in self._RESOURCE_EXHAUSTED:
            return RetryCategory.RESOURCE_EXHAUSTED
        if error_type in self._TRANSIENT:
            return RetryCategory.TRANSIENT
        return RetryCategory.PERMANENT


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    initial_delay: timedelta = timedelta(seconds=5)
    multiplier: float = 2.0
    max_delay: timedelta = timedelta(minutes=5)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.initial_delay, timedelta)
            or self.initial_delay < timedelta(0)
        ):
            raise CampaignValidationError(
                "initial_delay must be a non-negative timedelta"
            )
        if isinstance(self.multiplier, bool) or not isinstance(
            self.multiplier, (int, float)
        ):
            raise CampaignValidationError("multiplier must be numeric")
        if self.multiplier < 1:
            raise CampaignValidationError("multiplier must be at least 1")
        if not isinstance(self.max_delay, timedelta) or self.max_delay < timedelta(0):
            raise CampaignValidationError(
                "max_delay must be a non-negative timedelta"
            )
        if self.max_delay < self.initial_delay:
            raise CampaignValidationError(
                "max_delay must be greater than or equal to initial_delay"
            )

    def delay_for_attempt(self, attempt: int) -> timedelta:
        """Return the delay before the next attempt.

        ``attempt`` is the failed attempt number, starting at 1.  The result is
        deterministic and capped; jitter is intentionally deferred.
        """

        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
            raise CampaignValidationError("attempt must be an integer of at least 1")
        seconds = self.initial_delay.total_seconds() * (
            float(self.multiplier) ** (attempt - 1)
        )
        return min(timedelta(seconds=seconds), self.max_delay)


@dataclass(frozen=True, slots=True)
class RetryDecision:
    disposition: RetryDisposition
    category: RetryCategory
    failed_attempt: int
    max_attempts: int
    remaining_attempts: int
    delay: timedelta | None
    ready_at: datetime | None
    reason: str

    @property
    def should_retry(self) -> bool:
        return self.disposition is RetryDisposition.RETRY


class CampaignRetryPlanner:
    """Pure retry decision service for a failed campaign attempt."""

    _RETRYABLE = frozenset(
        {
            RetryCategory.TRANSIENT,
            RetryCategory.RATE_LIMITED,
            RetryCategory.RESOURCE_EXHAUSTED,
        }
    )

    def __init__(
        self,
        *,
        policy: RetryPolicy | None = None,
        classifier: RetryClassifier | None = None,
    ) -> None:
        self._policy = policy if policy is not None else RetryPolicy()
        self._classifier = (
            classifier if classifier is not None else DefaultRetryClassifier()
        )
        if not isinstance(self._classifier, RetryClassifier):
            raise CampaignValidationError(
                "classifier must implement the RetryClassifier contract"
            )

    def decide(
        self,
        spec: CampaignSpec,
        state: CampaignState,
        failure: FailureDescriptor,
        *,
        occurred_at: datetime,
    ) -> RetryDecision:
        occurred_at = self._aware_utc(occurred_at)
        if state.campaign_id != spec.campaign_id:
            raise CampaignValidationError(
                "campaign state and specification must reference the same id"
            )
        if state.attempt < 1:
            raise CampaignValidationError(
                "retry decisions require a failed attempt number of at least 1"
            )
        if state.attempt > spec.max_attempts:
            raise CampaignValidationError(
                "campaign attempt cannot exceed max_attempts"
            )

        category = RetryCategory(self._classifier.classify(failure))
        remaining = max(spec.max_attempts - state.attempt, 0)
        if category not in self._RETRYABLE:
            return RetryDecision(
                disposition=RetryDisposition.TERMINAL,
                category=category,
                failed_attempt=state.attempt,
                max_attempts=spec.max_attempts,
                remaining_attempts=remaining,
                delay=None,
                ready_at=None,
                reason=f"{category.value} failures are terminal",
            )
        if remaining == 0:
            return RetryDecision(
                disposition=RetryDisposition.TERMINAL,
                category=category,
                failed_attempt=state.attempt,
                max_attempts=spec.max_attempts,
                remaining_attempts=0,
                delay=None,
                ready_at=None,
                reason="retry budget exhausted",
            )

        delay = self._policy.delay_for_attempt(state.attempt)
        if failure.retry_after is not None:
            delay = max(delay, failure.retry_after)
        return RetryDecision(
            disposition=RetryDisposition.RETRY,
            category=category,
            failed_attempt=state.attempt,
            max_attempts=spec.max_attempts,
            remaining_attempts=remaining,
            delay=delay,
            ready_at=occurred_at + delay,
            reason=f"retryable {category.value} failure",
        )

    @staticmethod
    def _aware_utc(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise CampaignValidationError("occurred_at must be timezone-aware")
        return value.astimezone(timezone.utc)
