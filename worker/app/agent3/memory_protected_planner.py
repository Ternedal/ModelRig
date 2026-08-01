from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .memory import MemoryStoreError
from .memory_context import ContextTarget, MemoryContext
from .memory_protected_context import (
    ProtectedMemoryContextCompiler,
    ProtectedMemoryContextError,
)
from .memory_protected_reader import ProtectedMemoryReader

PROTECTED_PLANNER_CONTEXT_CONTRACT = "kaliv-agent3-protected-planner-context/v1"
CLOUD_CONTEXT_ALLOWED = False
LEGACY_STORE_FALLBACK = False
_CANDIDATE_MULTIPLIER = 2


@dataclass(frozen=True)
class ProtectedPlannerMemoryLimits:
    """Fixed hard limits for the promoted local-only planner adapter."""

    max_output_chars: int = 12_000
    max_output_records: int = 50
    max_candidate_chars: int = 24_000
    max_candidate_records: int = 100


class ProtectedPlannerMemoryContextProvider:
    """Adapt the proven protected compiler to the planner provider protocol.

    Route target and private-cloud consent are checked before the compiler can
    ask the protected reader to open an envelope. The provider returns only the
    bounded ``MemoryContext`` used by the planner and never exposes a preview,
    record list, provenance or fallback to the legacy plaintext store.
    """

    def __init__(
        self,
        reader: ProtectedMemoryReader,
        *,
        limits: ProtectedPlannerMemoryLimits | None = None,
    ):
        if not isinstance(reader, ProtectedMemoryReader):
            raise MemoryStoreError(
                "protected planner memory requires a ProtectedMemoryReader"
            )
        self.limits = limits or ProtectedPlannerMemoryLimits()
        self._validate_limits(self.limits)
        self.compiler = ProtectedMemoryContextCompiler(
            reader,
            candidate_multiplier=_CANDIDATE_MULTIPLIER,
        )

    def compile(
        self,
        *,
        subjects: Iterable[str] | None,
        target: ContextTarget | str,
        allow_private_cloud: bool,
        max_chars: int,
        max_records: int,
    ) -> MemoryContext:
        try:
            selected_target = ContextTarget(target)
        except (TypeError, ValueError) as exc:
            raise MemoryStoreError("protected planner target is invalid") from exc
        if selected_target is not ContextTarget.LOCAL:
            raise MemoryStoreError("protected planner memory is local-only")
        if allow_private_cloud:
            raise MemoryStoreError(
                "private-cloud consent cannot widen protected planner memory"
            )

        budget = self._bounded_int(
            "max_chars",
            max_chars,
            minimum=0,
            maximum=self.limits.max_output_chars,
        )
        record_limit = self._bounded_int(
            "max_records",
            max_records,
            minimum=0,
            maximum=self.limits.max_output_records,
        )
        try:
            result = self.compiler.compile(
                subjects=subjects,
                target=selected_target,
                max_chars=budget,
                max_records=record_limit,
            )
        except ProtectedMemoryContextError as exc:
            raise MemoryStoreError(
                f"protected planner memory failed closed: {type(exc).__name__}"
            ) from exc
        return result.context

    @staticmethod
    def _validate_limits(limits: ProtectedPlannerMemoryLimits) -> None:
        values = (
            ("max_output_chars", limits.max_output_chars, 12_000),
            ("max_output_records", limits.max_output_records, 50),
            ("max_candidate_chars", limits.max_candidate_chars, 50_000),
            ("max_candidate_records", limits.max_candidate_records, 200),
        )
        for name, value, maximum in values:
            if isinstance(value, bool) or not isinstance(value, int):
                raise MemoryStoreError(f"{name} must be an integer")
            if value <= 0 or value > maximum:
                raise MemoryStoreError(f"{name} is outside the safe bound")
        if limits.max_candidate_chars != limits.max_output_chars * _CANDIDATE_MULTIPLIER:
            raise MemoryStoreError(
                "candidate character bound must be exactly twice the output bound"
            )
        if limits.max_candidate_records != limits.max_output_records * _CANDIDATE_MULTIPLIER:
            raise MemoryStoreError(
                "candidate record bound must be exactly twice the output bound"
            )

    @staticmethod
    def _bounded_int(name: str, value: Any, *, minimum: int, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise MemoryStoreError(f"{name} must be an integer")
        if value < minimum or value > maximum:
            raise MemoryStoreError(f"{name} is outside the safe bound")
        return value
