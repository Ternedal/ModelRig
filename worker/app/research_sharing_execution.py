"""Dormant async execution wrapper for a claimed research sharing lease.

The wrapper owns lifecycle ordering and normalized terminal audit, not networking.
It is not imported by BrowserHost, ToolGate, an API route, or a network client.
An injected operation must report the actual outbound bytes it has completed
through ``OutboundByteMeter``; the wrapper never estimates payload size.
"""
from __future__ import annotations

import asyncio
import inspect
import re
import threading
from dataclasses import dataclass
from typing import Generic, Literal, Protocol, TypeVar, cast

from .research_data_sharing import ResearchSharingIntent
from .research_sharing_boundary import ResearchSharingBoundary, ResearchSharingLease

T = TypeVar("T")
ExecutionOutcome = Literal["completed", "failed", "blocked"]
_ERROR_CODE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_MISSING = object()


class ResearchSharingExecutionContractError(ValueError):
    """The injected operation or wrapper input violated the execution contract."""


class ResearchExternalSignal(RuntimeError):
    """A normalized operation result that must be written to the terminal audit."""

    outcome: ExecutionOutcome

    def __init__(self, error_code: str) -> None:
        if not isinstance(error_code, str) or not _ERROR_CODE.fullmatch(error_code):
            raise ResearchSharingExecutionContractError("error_code has an invalid format")
        super().__init__(error_code)
        self.error_code = error_code


class ResearchExternalBlocked(ResearchExternalSignal):
    outcome: ExecutionOutcome = "blocked"


class ResearchExternalFailed(ResearchExternalSignal):
    outcome: ExecutionOutcome = "failed"


class ResearchSharingExecutionError(RuntimeError):
    """Normalized terminal failure returned after the receipt has been completed."""

    def __init__(self, outcome: ExecutionOutcome, error_code: str, bytes_sent: int) -> None:
        super().__init__(error_code)
        self.outcome = outcome
        self.error_code = error_code
        self.bytes_sent = bytes_sent


class OutboundByteMeter:
    """Thread-safe count of bytes the injected transport confirms were sent.

    ``record_sent`` must be called only after a write reports actual progress. It
    fails closed if the cumulative count would exceed the request byte ceiling.
    """

    def __init__(self, max_bytes: int) -> None:
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
            raise ResearchSharingExecutionContractError("max_bytes must be a positive integer")
        self.max_bytes = max_bytes
        self._bytes_sent = 0
        self._lock = threading.Lock()

    @property
    def bytes_sent(self) -> int:
        with self._lock:
            return self._bytes_sent

    def record_sent(self, count: int) -> int:
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ResearchSharingExecutionContractError(
                "sent byte increments must be non-negative integers"
            )
        with self._lock:
            next_total = self._bytes_sent + count
            if next_total > self.max_bytes:
                raise ResearchExternalBlocked("byte_budget_exceeded")
            self._bytes_sent = next_total
            return self._bytes_sent


class ResearchExternalOperation(Protocol[T]):
    async def run(self, meter: OutboundByteMeter) -> T:
        """Perform one injected operation after the common receipt is claimed."""

    async def close(self) -> None:
        """Release operation resources; called exactly once after ``run`` starts."""


@dataclass(frozen=True)
class ResearchSharingExecutionResult(Generic[T]):
    value: T
    bytes_sent: int
    outcome: Literal["completed"] = "completed"


async def execute_research_sharing(
    boundary: ResearchSharingBoundary,
    lease: ResearchSharingLease,
    intent: ResearchSharingIntent,
    operation: ResearchExternalOperation[T],
    *,
    now_claim: int | None = None,
    now_complete: int | None = None,
    timeout_seconds: int = 60,
    cleanup_timeout_seconds: int = 5,
) -> ResearchSharingExecutionResult[T]:
    """Claim, run, clean up, and terminalize one exact research sharing lease.

    The operation is never entered before ``boundary.claim`` succeeds. After it
    starts, cleanup is attempted exactly once and the common receipt is completed
    exactly once with the meter's actual count and a normalized outcome.
    """

    if not isinstance(boundary, ResearchSharingBoundary):
        raise ResearchSharingExecutionContractError(
            "boundary must be a ResearchSharingBoundary"
        )
    if not isinstance(lease, ResearchSharingLease):
        raise ResearchSharingExecutionContractError("lease must be a ResearchSharingLease")
    if not isinstance(intent, ResearchSharingIntent):
        raise ResearchSharingExecutionContractError("intent must be a ResearchSharingIntent")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
        raise ResearchSharingExecutionContractError("timeout_seconds must be an integer")
    if not 1 <= timeout_seconds <= 900:
        raise ResearchSharingExecutionContractError("timeout_seconds must be between 1 and 900")
    if isinstance(cleanup_timeout_seconds, bool) or not isinstance(
        cleanup_timeout_seconds, int
    ):
        raise ResearchSharingExecutionContractError(
            "cleanup_timeout_seconds must be an integer"
        )
    if not 1 <= cleanup_timeout_seconds <= 30:
        raise ResearchSharingExecutionContractError(
            "cleanup_timeout_seconds must be between 1 and 30"
        )
    run = getattr(operation, "run", None)
    close = getattr(operation, "close", None)
    if not callable(run) or not callable(close):
        raise ResearchSharingExecutionContractError(
            "operation must provide async run and close methods"
        )

    boundary.claim(lease, intent, now=now_claim)

    meter = OutboundByteMeter(intent.to_request().max_bytes)
    value: object = _MISSING
    outcome: ExecutionOutcome = "completed"
    error_code: str | None = None
    cancelled: asyncio.CancelledError | None = None

    try:
        run_result = run(meter)
        if not inspect.isawaitable(run_result):
            raise ResearchSharingExecutionContractError("operation.run must be async")
        value = await asyncio.wait_for(run_result, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        outcome = "failed"
        error_code = "operation_timeout"
    except asyncio.CancelledError as exc:
        outcome = "failed"
        error_code = "operation_cancelled"
        cancelled = exc
    except ResearchExternalSignal as exc:
        outcome = exc.outcome
        error_code = exc.error_code
    except ResearchSharingExecutionContractError:
        outcome = "blocked"
        error_code = "operation_contract_violation"
    except Exception:
        outcome = "failed"
        error_code = "operation_failed"

    try:
        close_result = close()
        if not inspect.isawaitable(close_result):
            raise ResearchSharingExecutionContractError("operation.close must be async")
        await asyncio.wait_for(close_result, timeout=cleanup_timeout_seconds)
    except asyncio.CancelledError as exc:
        outcome = "blocked"
        error_code = "cleanup_cancelled"
        if cancelled is None:
            cancelled = exc
    except asyncio.TimeoutError:
        outcome = "blocked"
        error_code = "cleanup_timeout"
    except ResearchSharingExecutionContractError:
        outcome = "blocked"
        error_code = "cleanup_contract_violation"
    except Exception:
        outcome = "blocked"
        error_code = "cleanup_failed"

    boundary.complete(
        lease,
        intent,
        outcome=outcome,
        bytes_sent=meter.bytes_sent,
        error_code=error_code,
        now=now_complete,
    )

    if cancelled is not None:
        raise cancelled
    if outcome != "completed":
        assert error_code is not None
        raise ResearchSharingExecutionError(
            outcome=outcome,
            error_code=error_code,
            bytes_sent=meter.bytes_sent,
        ) from None
    return ResearchSharingExecutionResult(
        value=cast(T, None if value is _MISSING else value),
        bytes_sent=meter.bytes_sent,
    )
