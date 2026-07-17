"""Human-controlled administration for dormant schedules.

This module is deliberately not a model tool.  It validates and persists the
operator's exact request for a later local API, while the runner remains behind
``KALIV_SCHEDULER`` and every execution still goes through ToolGate.

Scheduled writes use a two-step contract: preview returns a fingerprint of the
exact ``(tool, args)`` pair, and create/renew must send that same fingerprint
back.  Change one argument and the approval no longer matches.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Mapping

from .scheduler import (
    DEFAULT_MAX_RUNS,
    DEFAULT_TTL_DAYS,
    Schedule,
    ScheduleError,
    ScheduleStore,
    fingerprint,
    next_run,
    parse_cadence,
    refusal,
)

MAX_TTL_DAYS = 365
MAX_RUN_BUDGET = 100_000
MAX_ARGS_JSON_BYTES = 20_000


class ScheduleAdminError(ValueError):
    """An operator request that cannot be represented safely."""


class ScheduleAdminNotFound(ScheduleAdminError):
    """A schedule or tool that does not exist."""


class ScheduleAdminConflict(ScheduleAdminError):
    """The request conflicts with the schedule's immutable approval."""


@dataclass(frozen=True)
class SchedulePreview:
    tool: str
    args: dict[str, Any]
    cadence: str
    risk: str
    sensitivity: str
    human_summary: str
    requires_approval: bool
    approval_fingerprint: str | None
    due_at: float
    expires_at: float
    ttl_days: int
    max_runs: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "args": self.args,
            "cadence": self.cadence,
            "risk": self.risk,
            "sensitivity": self.sensitivity,
            "human_summary": self.human_summary,
            "requires_approval": self.requires_approval,
            "approval_fingerprint": self.approval_fingerprint,
            "due_at": self.due_at,
            "expires_at": self.expires_at,
            "ttl_days": self.ttl_days,
            "max_runs": self.max_runs,
        }


class ScheduleAdminStore(ScheduleStore):
    """ScheduleStore extension used only by the human administration surface.

    The execution path needs no renewal primitive, so the runner keeps the
    smaller base API.  Renewal is one atomic update here: approval horizon and
    run budget move together, and an explicit re-enable starts at a fresh future
    occurrence instead of replaying missed work.
    """

    def renew(
        self,
        schedule_id: str,
        *,
        approved_fingerprint: str | None,
        ttl_days: int = DEFAULT_TTL_DAYS,
        max_runs: int = DEFAULT_MAX_RUNS,
        enabled: bool | None = None,
        now: float | None = None,
    ) -> Schedule | None:
        now = time.time() if now is None else now
        if ttl_days <= 0:
            raise ScheduleError("en plan skal have et udløb — det er hele pointen")
        if max_runs < 0:
            raise ScheduleError("max_runs kan ikke være negativ")

        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute(
                    "SELECT * FROM schedules WHERE id=?", (schedule_id,)
                ).fetchone()
                if row is None:
                    self._conn.rollback()
                    return None

                current_enabled = bool(row["enabled"])
                next_enabled = current_enabled if enabled is None else bool(enabled)
                due_at = float(row["due_at"])
                if enabled is True:
                    # Explicitly starting a renewed schedule is a fresh promise,
                    # not permission to replay whatever became due while paused.
                    due_at = next_run(parse_cadence(row["cadence"]), now)

                self._conn.execute(
                    "UPDATE schedules SET approved_fingerprint=?, expires_at=?, "
                    "max_runs=?, runs_used=0, enabled=?, due_at=? WHERE id=?",
                    (
                        approved_fingerprint,
                        now + ttl_days * 86400,
                        int(max_runs),
                        1 if next_enabled else 0,
                        due_at,
                        schedule_id,
                    ),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return self.get(schedule_id)


def _default_registry() -> Mapping[str, Any]:
    # Lazy on purpose. Importing tools creates ToolGate and its audit connection;
    # a dormant worker must not do that merely because the router exists.
    from . import tools

    return tools.REGISTRY


def _default_store() -> ScheduleAdminStore:
    return ScheduleAdminStore()


class ScheduleAdmin:
    """Validate and persist operator-owned schedules without executing them."""

    def __init__(
        self,
        *,
        store_factory: Callable[[], ScheduleAdminStore] = _default_store,
        registry_factory: Callable[[], Mapping[str, Any]] = _default_registry,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store_factory = store_factory
        self._registry_factory = registry_factory
        self._clock = clock

    @contextmanager
    def _store(self) -> Iterator[ScheduleAdminStore]:
        store = self._store_factory()
        try:
            yield store
        finally:
            store.close()

    def preview(
        self,
        tool: str,
        args: dict[str, Any],
        cadence: str,
        *,
        ttl_days: int = DEFAULT_TTL_DAYS,
        max_runs: int = DEFAULT_MAX_RUNS,
    ) -> SchedulePreview:
        self._validate_bounds(ttl_days, max_runs)
        self._validate_args(args)
        registry = self._registry_factory()
        spec = registry.get(tool)
        if spec is None:
            raise ScheduleAdminNotFound(f"unknown tool: {tool}")

        risk = str(getattr(spec, "risk", "unknown"))
        if risk == "desktop":
            raise ScheduleAdminError(
                "desktop-handlinger kan ikke planlægges; skærmen ved kørsel er ikke den skærm der blev godkendt"
            )
        if risk not in ("read", "write"):
            raise ScheduleAdminError(f"ukendt tool-risk {risk!r}; afvist fail-closed")

        cad = parse_cadence(cadence)
        now = self._clock()
        try:
            summary = str(spec.human_summary(args))[:1000]
        except Exception as exc:
            raise ScheduleAdminError(
                f"handlingen kan ikke vises sikkert til godkendelse: {type(exc).__name__}: {exc}"
            ) from exc
        if not summary.strip():
            raise ScheduleAdminError("handlingen mangler en menneskeligt læsbar godkendelsestekst")

        approval = fingerprint(tool, args) if risk == "write" else None
        return SchedulePreview(
            tool=tool,
            args=dict(args),
            cadence=cadence,
            risk=risk,
            sensitivity=str(getattr(spec, "sensitivity", "operational")),
            human_summary=summary,
            requires_approval=risk == "write",
            approval_fingerprint=approval,
            due_at=next_run(cad, now),
            expires_at=now + ttl_days * 86400,
            ttl_days=ttl_days,
            max_runs=max_runs,
        )

    def create(
        self,
        tool: str,
        args: dict[str, Any],
        cadence: str,
        *,
        ttl_days: int = DEFAULT_TTL_DAYS,
        max_runs: int = DEFAULT_MAX_RUNS,
        approved_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        preview = self.preview(
            tool, args, cadence, ttl_days=ttl_days, max_runs=max_runs
        )
        self._require_approval(preview, approved_fingerprint)
        with self._store() as store:
            schedule = store.create(
                tool,
                args,
                cadence,
                approve_write=preview.requires_approval,
                ttl_days=ttl_days,
                max_runs=max_runs,
                now=self._clock(),
            )
        return self.describe(schedule)

    def list_all(self) -> list[dict[str, Any]]:
        with self._store() as store:
            schedules = store.list_all()
        registry = self._registry_factory()
        now = self._clock()
        return [self.describe(item, registry=registry, now=now) for item in schedules]

    def get(self, schedule_id: str) -> dict[str, Any]:
        with self._store() as store:
            schedule = store.get(schedule_id)
        if schedule is None:
            raise ScheduleAdminNotFound(f"unknown schedule: {schedule_id}")
        return self.describe(schedule)

    def set_enabled(self, schedule_id: str, enabled: bool) -> dict[str, Any]:
        with self._store() as store:
            schedule = store.get(schedule_id)
            if schedule is None:
                raise ScheduleAdminNotFound(f"unknown schedule: {schedule_id}")
            if enabled:
                state = self.describe(schedule)
                if state["blocked_reason"]:
                    raise ScheduleAdminConflict(
                        f"planen kan ikke aktiveres: {state['blocked_reason']}"
                    )
            store.set_enabled(schedule_id, enabled, now=self._clock())
            updated = store.get(schedule_id)
        assert updated is not None
        return self.describe(updated)

    def renew(
        self,
        schedule_id: str,
        *,
        ttl_days: int = DEFAULT_TTL_DAYS,
        max_runs: int = DEFAULT_MAX_RUNS,
        approved_fingerprint: str | None = None,
        enable: bool | None = None,
    ) -> dict[str, Any]:
        with self._store() as store:
            current = store.get(schedule_id)
            if current is None:
                raise ScheduleAdminNotFound(f"unknown schedule: {schedule_id}")
            preview = self.preview(
                current.tool,
                current.args,
                current.cadence,
                ttl_days=ttl_days,
                max_runs=max_runs,
            )
            self._require_approval(preview, approved_fingerprint)
            updated = store.renew(
                schedule_id,
                approved_fingerprint=preview.approval_fingerprint,
                ttl_days=ttl_days,
                max_runs=max_runs,
                enabled=enable,
                now=self._clock(),
            )
        assert updated is not None
        return self.describe(updated)

    def describe(
        self,
        schedule: Schedule,
        *,
        registry: Mapping[str, Any] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        registry = self._registry_factory() if registry is None else registry
        now = self._clock() if now is None else now
        spec = registry.get(schedule.tool)
        if spec is None:
            risk = "unknown"
            blocked = f"ukendt tool {schedule.tool!r}; planen kan ikke køre"
            sensitivity = "unknown"
        else:
            risk = str(getattr(spec, "risk", "unknown"))
            sensitivity = str(getattr(spec, "sensitivity", "operational"))
            blocked = refusal(
                risk,
                schedule.approved_fingerprint,
                fingerprint(schedule.tool, schedule.args),
                now=now,
                expires_at=schedule.expires_at,
                runs_used=schedule.runs_used,
                max_runs=schedule.max_runs,
                tools_enabled=True,
                tool_disabled=False,
            )

        approval_valid = (
            risk == "read"
            or (
                risk == "write"
                and schedule.approved_fingerprint
                == fingerprint(schedule.tool, schedule.args)
            )
        )
        expired = now >= schedule.expires_at
        budget_exhausted = bool(
            schedule.max_runs and schedule.runs_used >= schedule.max_runs
        )
        return {
            "schedule_id": schedule.schedule_id,
            "tool": schedule.tool,
            "args": schedule.args,
            "cadence": schedule.cadence,
            "risk": risk,
            "sensitivity": sensitivity,
            "approved_fingerprint": schedule.approved_fingerprint,
            "approval_valid": bool(approval_valid),
            "expires_at": schedule.expires_at,
            "expired": expired,
            "max_runs": schedule.max_runs,
            "runs_used": schedule.runs_used,
            "budget_exhausted": budget_exhausted,
            "due_at": schedule.due_at,
            "missed": schedule.missed,
            "enabled": schedule.enabled,
            "eligible": bool(schedule.enabled and blocked is None),
            "blocked_reason": blocked,
        }

    @staticmethod
    def _require_approval(
        preview: SchedulePreview, approved_fingerprint: str | None
    ) -> None:
        if not preview.requires_approval:
            return
        if approved_fingerprint != preview.approval_fingerprint:
            raise ScheduleAdminConflict(
                "scheduled write approval does not match the previewed tool and arguments"
            )

    @staticmethod
    def _validate_bounds(ttl_days: int, max_runs: int) -> None:
        if ttl_days < 1 or ttl_days > MAX_TTL_DAYS:
            raise ScheduleAdminError(
                f"ttl_days skal være mellem 1 og {MAX_TTL_DAYS}"
            )
        if max_runs < 0 or max_runs > MAX_RUN_BUDGET:
            raise ScheduleAdminError(
                f"max_runs skal være mellem 0 og {MAX_RUN_BUDGET}"
            )

    @staticmethod
    def _validate_args(args: dict[str, Any]) -> None:
        if not isinstance(args, dict):
            raise ScheduleAdminError("args skal være et JSON-objekt")
        try:
            raw = json.dumps(args, sort_keys=True, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ScheduleAdminError("args skal kunne serialiseres som JSON") from exc
        if len(raw) > MAX_ARGS_JSON_BYTES:
            raise ScheduleAdminError(
                f"args fylder {len(raw)} bytes; maksimum er {MAX_ARGS_JSON_BYTES}"
            )
