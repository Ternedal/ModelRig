from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .memory_context import ContextTarget, MemoryContext, MemoryContextCompiler
from .memory_protected_reader import (
    MemoryReadAccess,
    ProtectedMemoryReadError,
    ProtectedMemoryReader,
)


@dataclass(frozen=True)
class ProtectedPlannerMemoryLimits:
    """Hard local-decryption limits independent of API validation."""

    max_output_chars: int = 12_000
    max_output_records: int = 50
    max_candidate_chars: int = 24_000
    max_candidate_records: int = 100


class ProtectedPlannerMemoryContextProvider:
    """Compile a bounded local-only planner block from a protected store.

    The provider owns target enforcement *before* it asks the protected reader
    to decrypt anything. It exposes no record list, no plaintext preview and no
    cloud consent override; callers receive only the compiler's bounded context
    object and receipt metadata can be derived from that object.
    """

    def __init__(
        self,
        reader: ProtectedMemoryReader,
        *,
        compiler: MemoryContextCompiler | None = None,
        limits: ProtectedPlannerMemoryLimits | None = None,
    ):
        if not isinstance(reader, ProtectedMemoryReader):
            raise ProtectedMemoryReadError(
                "protected planner memory requires a protected reader"
            )
        self.reader = reader
        self.compiler = compiler or MemoryContextCompiler()
        self.limits = limits or ProtectedPlannerMemoryLimits()
        self._validate_limits(self.limits)

    def compile(
        self,
        *,
        subjects: Iterable[str] | None,
        target: ContextTarget | str,
        allow_private_cloud: bool,
        max_chars: int,
        max_records: int,
    ) -> MemoryContext:
        selected_target = ContextTarget(target)
        if selected_target is not ContextTarget.LOCAL:
            raise ProtectedMemoryReadError(
                "protected planner memory is local-only"
            )
        # This flag can never widen protected-memory egress. Rejecting it keeps
        # the receipt and the operator's intent unambiguous even on a local route.
        if allow_private_cloud:
            raise ProtectedMemoryReadError(
                "private-cloud consent is not accepted by protected planner memory"
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
        selected_subjects = self._subjects(subjects)
        if budget == 0 or record_limit == 0:
            return self.compiler.compile(
                [],
                target=ContextTarget.LOCAL,
                allow_private_cloud=False,
                max_chars=budget,
                max_records=record_limit,
            )

        # Candidate decryption is independently bounded. The wider set gives the
        # exact renderer room to skip one oversized/newer row without becoming a
        # bulk-decrypt primitive.
        candidate_limit = min(
            self.limits.max_candidate_records,
            max(record_limit * 2, record_limit),
        )
        candidate_chars = min(
            self.limits.max_candidate_chars,
            max(budget * 2, budget),
        )
        candidates = self.reader.context_records(
            access=MemoryReadAccess.LOCAL_CONTEXT,
            subjects=selected_subjects,
            include_private=True,
            limit=candidate_limit,
            max_chars=candidate_chars,
        )
        return self.compiler.compile(
            candidates,
            target=ContextTarget.LOCAL,
            allow_private_cloud=False,
            max_chars=budget,
            max_records=record_limit,
        )

    @staticmethod
    def _validate_limits(limits: ProtectedPlannerMemoryLimits) -> None:
        for name, value, maximum in (
            ("max_output_chars", limits.max_output_chars, 12_000),
            ("max_output_records", limits.max_output_records, 50),
            ("max_candidate_chars", limits.max_candidate_chars, 50_000),
            ("max_candidate_records", limits.max_candidate_records, 200),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ProtectedMemoryReadError(f"{name} must be an integer")
            if value <= 0 or value > maximum:
                raise ProtectedMemoryReadError(f"{name} is outside the safe bound")
        if limits.max_candidate_chars < limits.max_output_chars:
            raise ProtectedMemoryReadError(
                "candidate character bound must cover the output bound"
            )
        if limits.max_candidate_records < limits.max_output_records:
            raise ProtectedMemoryReadError(
                "candidate record bound must cover the output bound"
            )

    @staticmethod
    def _bounded_int(
        name: str,
        value: int,
        *,
        minimum: int,
        maximum: int,
    ) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ProtectedMemoryReadError(f"{name} must be an integer")
        if value < minimum or value > maximum:
            raise ProtectedMemoryReadError(f"{name} is outside the safe bound")
        return value

    @staticmethod
    def _subjects(subjects: Iterable[str] | None) -> tuple[str, ...] | None:
        if subjects is None:
            return None
        selected = tuple(subjects)
        if len(selected) > 20:
            raise ProtectedMemoryReadError("at most 20 memory subjects are allowed")
        if len(selected) != len(set(selected)):
            raise ProtectedMemoryReadError("memory subjects must be unique")
        for subject in selected:
            if not isinstance(subject, str):
                raise ProtectedMemoryReadError("memory subject must be text")
            if not subject or subject != subject.strip() or len(subject) > 200:
                raise ProtectedMemoryReadError("memory subject is invalid")
        return selected
