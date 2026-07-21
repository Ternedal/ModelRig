"""Human-controlled administration for dormant schedules.

This module is deliberately not a model tool. It validates and persists the
operator's exact request for a local API, while the runner remains behind
``KALIV_SCHEDULER`` and every execution still goes through ToolGate.

A scheduled write has two different fingerprints, because they answer different
questions:

* ``action_fingerprint`` binds what will execute later: exactly ``(tool, args)``.
  That is what SchedulerRunner carries into ToolGate on every occurrence.
* ``approval_fingerprint`` binds what the human approved now: operation,
  schedule id, action, cadence, expiry, run budget and requested enable state.

Without the second binding, a client could preview "once" and persist "hourly"
under the same action approval. Change any part of the standing grant and the
preview approval no longer matches.
"""
from __future__ import annotations

import hashlib
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
from .scheduler_time import (
    DEFAULT_TIMEZONE,
    MISFIRE_POLICY,
    ScheduleTimeError,
    local_due_iso,
    validate_timezone,
)

MAX_TTL_DAYS = 365
MAX_RUN_BUDGET = 100_000
MAX_ARGS_JSON_BYTES = 20_000
_APPROVAL_VERSION = 2


class ScheduleAdminError(ValueError):
    """An operator request that cannot be represented safely."""


class ScheduleAdminNotFound(ScheduleAdminError):
    """A schedule or tool that does not exist."""


class ScheduleAdminConflict(ScheduleAdminError):
    """The request conflicts with the schedule's immutable approval."""


@dataclass(frozen=True)
class SchedulePreview:
    operation: str
    schedule_id: str | None
    tool: str
    args: dict[str, Any]
    cadence: str
    timezone: str
    misfire_policy: str
    due_at_local: str
    risk: str
    sensitivity: str
    human_summary: str
    requires_approval: bool
    action_fingerprint: str
    approval_fingerprint: str | None
    due_at: float
    expires_at: float
    ttl_days: int
    max_runs: int
    enable: bool | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "schedule_id": self.schedule_id,
            "tool": self.tool,
            "args": self.args,
            "cadence": self.cadence,
            "timezone": self.timezone,
            "misfire_policy": self.misfire_policy,
            "due_at_local": self.due_at_local,
            "risk": self.risk,
            "sensitivity": self.sensitivity,
            "human_summary": self.human_summary,
            "requires_approval": self.requires_approval,
            "action_fingerprint": self.action_fingerprint,
            "approval_fingerprint": self.approval_fingerprint,
            "due_at": self.due_at,
            "expires_at": self.expires_at,
            "ttl_days": self.ttl_days,
            "max_runs": self.max_runs,
            "enable": self.enable,
        }


class ScheduleAdminStore(ScheduleStore):
    """ScheduleStore extension used only by the human administration surface.

    Renewal is one atomic update: approval horizon and run budget move together,
    and an explicit re-enable starts at a fresh future occurrence instead of
    replaying missed work.
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
        receipt: dict | None = None,
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
                    if row["misfire_policy"] != MISFIRE_POLICY:
                        raise ScheduleError(
                            f"ukendt misfire-policy "
                            f"{row['misfire_policy']!r}")
                    due_at = next_run(
                        parse_cadence(row["cadence"]), now, row["timezone"])

                # Renewal is a maximal user-intent mutation: it replaces the
                # approval, resets the budget and moves the horizon. It MUST
                # bump the revision (T-013): for the same tool+args the renewed
                # fingerprint is identical to the old one, so without the bump
                # neither of the guard's other belts would catch an in-flight
                # claim taken under the OLD grant -- it would fire against the
                # FRESH budget. With the bump it cancels and refunds instead.
                self._conn.execute(
                    "UPDATE schedules SET approved_fingerprint=?, expires_at=?, "
                    "max_runs=?, runs_used=0, enabled=?, due_at=?, "
                    "revision=revision+1 WHERE id=?",
                    (
                        approved_fingerprint,
                        now + ttl_days * 86400,
                        int(max_runs),
                        1 if next_enabled else 0,
                        due_at,
                        schedule_id,
                    ),
                )
                if receipt is not None:
                    if approved_fingerprint is None:
                        raise ScheduleError(
                            "en approval-receipt uden en godkendt write giver "
                            "ikke mening")
                    # Same transaction as the renewed grant (T-014), stamped
                    # with the post-bump revision so the receipt says which
                    # incarnation of the grant it authorised.
                    self._conn.execute(
                        "INSERT INTO approval_receipts (schedule_id, kind,"
                        " fingerprint, device_id, nonce, issued_at,"
                        " consumed_at, revision) VALUES (?,?,?,?,?,?,?,?)",
                        (schedule_id, "renew", approved_fingerprint,
                         receipt["device_id"], receipt["nonce"],
                         int(receipt["issued_at"]),
                         float(receipt["consumed_at"]),
                         int(row["revision"]) + 1),
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
        timezone_name: str = DEFAULT_TIMEZONE,
        misfire_policy: str = MISFIRE_POLICY,
    ) -> SchedulePreview:
        """Preview a new standing grant; execute and persist nothing."""
        return self._preview(
            operation="create",
            schedule_id=None,
            tool=tool,
            args=args,
            cadence=cadence,
            timezone_name=timezone_name,
            misfire_policy=misfire_policy,
            ttl_days=ttl_days,
            max_runs=max_runs,
            enable=True,
        )

    def preview_renew(
        self,
        schedule_id: str,
        *,
        ttl_days: int = DEFAULT_TTL_DAYS,
        max_runs: int = DEFAULT_MAX_RUNS,
        enable: bool | None = None,
    ) -> SchedulePreview:
        """Preview renewal of the existing immutable action and cadence."""
        with self._store() as store:
            current = store.get(schedule_id)
        if current is None:
            raise ScheduleAdminNotFound(f"unknown schedule: {schedule_id}")
        return self._preview(
            operation="renew",
            schedule_id=schedule_id,
            tool=current.tool,
            args=current.args,
            cadence=current.cadence,
            timezone_name=current.timezone,
            misfire_policy=current.misfire_policy,
            ttl_days=ttl_days,
            max_runs=max_runs,
            enable=enable,
        )

    def create(
        self,
        tool: str,
        args: dict[str, Any],
        cadence: str,
        *,
        ttl_days: int = DEFAULT_TTL_DAYS,
        max_runs: int = DEFAULT_MAX_RUNS,
        timezone_name: str = DEFAULT_TIMEZONE,
        misfire_policy: str = MISFIRE_POLICY,
        approved_fingerprint: str | None = None,
        receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        preview = self.preview(
            tool, args, cadence, ttl_days=ttl_days, max_runs=max_runs,
            timezone_name=timezone_name, misfire_policy=misfire_policy,
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
                receipt=receipt,
                timezone_name=preview.timezone,
                misfire_policy=preview.misfire_policy,
            )
        return self.describe(schedule)

    def list_all(self) -> list[dict[str, Any]]:
        with self._store() as store:
            schedules = store.list_all()
        registry = self._registry_factory()
        now = self._clock()
        return [
            self.describe(item, registry=registry, now=now) for item in schedules
        ]

    def approval_receipts(self, schedule_id: str) -> list[dict[str, Any]]:
        """The consumed approvals behind a grant, for the detail view (T-014)."""
        with self._store() as store:
            return store.approval_receipts(schedule_id)

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
        receipt: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._store() as store:
            current = store.get(schedule_id)
            if current is None:
                raise ScheduleAdminNotFound(f"unknown schedule: {schedule_id}")
            preview = self._preview(
                operation="renew",
                schedule_id=schedule_id,
                tool=current.tool,
                args=current.args,
                cadence=current.cadence,
                timezone_name=current.timezone,
                misfire_policy=current.misfire_policy,
                ttl_days=ttl_days,
                max_runs=max_runs,
                enable=enable,
            )
            self._require_approval(preview, approved_fingerprint)
            updated = store.renew(
                schedule_id,
                # The persisted standing grant only needs the exact action
                # fingerprint. The broader approval fingerprint is consumed by
                # this administration boundary and is never used for execution.
                approved_fingerprint=(
                    preview.action_fingerprint if preview.requires_approval else None
                ),
                ttl_days=ttl_days,
                max_runs=max_runs,
                enabled=enable,
                receipt=receipt,
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
        current_action = fingerprint(schedule.tool, schedule.args)
        if spec is None:
            risk = "unknown"
            blocked = f"ukendt tool {schedule.tool!r}; planen kan ikke køre"
            sensitivity = "unknown"
        else:
            risk = str(getattr(spec, "risk", "unknown"))
            # "operational" is not the conservative answer -- the scale runs
            # public < operational < private < secret, so a tool that declares
            # nothing was quietly treated as less sensitive than most of the
            # registry. That is F-511 exactly: a default that LOOKS careful.
            # Unknown is unknown, and the refusal ladder below already knows
            # what to do with it.
            sensitivity = str(getattr(spec, "sensitivity", None) or "unknown")
            blocked = refusal(
                risk,
                schedule.approved_fingerprint,
                current_action,
                now=now,
                expires_at=schedule.expires_at,
                runs_used=schedule.runs_used,
                max_runs=schedule.max_runs,
                # This is standing-grant validity, not the live kill-switch.
                # SchedulerRunner checks ToolGate again immediately before claim.
                tools_enabled=True,
                tool_disabled=False,
            )

        approval_valid = (
            risk == "read"
            or (
                risk == "write"
                and schedule.approved_fingerprint == current_action
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
            "timezone": schedule.timezone,
            "misfire_policy": schedule.misfire_policy,
            "due_at_local": local_due_iso(schedule.due_at, schedule.timezone),
            "risk": risk,
            "sensitivity": sensitivity,
            "action_fingerprint": current_action,
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
            # Structural only: live ToolGate state is checked by the runner and
            # surfaced separately by /tools and /schedules/status.
            "structurally_eligible": bool(schedule.enabled and blocked is None),
            "runtime_gate_checked": False,
            "blocked_reason": blocked,
        }

    def _preview(
        self,
        *,
        operation: str,
        schedule_id: str | None,
        tool: str,
        args: dict[str, Any],
        cadence: str,
        timezone_name: str,
        misfire_policy: str,
        ttl_days: int,
        max_runs: int,
        enable: bool | None,
    ) -> SchedulePreview:
        if operation not in ("create", "renew"):
            raise ScheduleAdminError(f"unknown schedule operation: {operation}")
        self._validate_bounds(ttl_days, max_runs)
        self._validate_args(args)
        try:
            zone = validate_timezone(timezone_name).key
        except ScheduleTimeError as exc:
            raise ScheduleAdminError(str(exc)) from exc
        if misfire_policy != MISFIRE_POLICY:
            raise ScheduleAdminError(
                f"ukendt misfire-policy {misfire_policy!r}; "
                f"kun {MISFIRE_POLICY!r} støttes")
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
        # `risk` cannot answer this: note_append and delete_model are both
        # "write" (F-604). The registry says per tool, and the tool gate enforces
        # it at 03:00 regardless -- but refusing only there means the UI offers
        # the plan, the user believes it exists, and it fails months later at
        # three in the morning. A refusal is worth most where the decision is
        # made.
        if not getattr(spec, "schedulable", False):
            raise ScheduleAdminError(
                f"{tool} kan ikke planlægges: "
                + (getattr(spec, "unschedulable_because", "")
                   or "handlingen kræver et menneske til stede")
            )

        self._validate_tool_args(spec, args)
        cad = parse_cadence(cadence)
        now = self._clock()
        due_at = next_run(cad, now, zone)
        try:
            summary = str(spec.human_summary(args))[:1000]
        except Exception as exc:
            raise ScheduleAdminError(
                f"handlingen kan ikke vises sikkert til godkendelse: {type(exc).__name__}: {exc}"
            ) from exc
        if not summary.strip():
            raise ScheduleAdminError(
                "handlingen mangler en menneskeligt læsbar godkendelsestekst"
            )

        action_fp = fingerprint(tool, args)
        approval_fp = None
        if risk == "write":
            approval_fp = self._grant_fingerprint(
                operation=operation,
                schedule_id=schedule_id,
                tool=tool,
                args=args,
                cadence=cadence,
                timezone_name=zone,
                misfire_policy=misfire_policy,
                ttl_days=ttl_days,
                max_runs=max_runs,
                enable=enable,
            )
        return SchedulePreview(
            operation=operation,
            schedule_id=schedule_id,
            tool=tool,
            args=dict(args),
            cadence=cadence,
            timezone=zone,
            misfire_policy=misfire_policy,
            due_at_local=local_due_iso(due_at, zone),
            risk=risk,
            sensitivity=str(getattr(spec, "sensitivity", None) or "unknown"),
            human_summary=summary,
            requires_approval=risk == "write",
            action_fingerprint=action_fp,
            approval_fingerprint=approval_fp,
            due_at=due_at,
            expires_at=now + ttl_days * 86400,
            ttl_days=ttl_days,
            max_runs=max_runs,
            enable=enable,
        )

    @staticmethod
    def _grant_fingerprint(
        *,
        operation: str,
        schedule_id: str | None,
        tool: str,
        args: dict[str, Any],
        cadence: str,
        timezone_name: str,
        misfire_policy: str,
        ttl_days: int,
        max_runs: int,
        enable: bool | None,
    ) -> str:
        payload = {
            "version": _APPROVAL_VERSION,
            "operation": operation,
            "schedule_id": schedule_id,
            "tool": tool,
            "args": args,
            "cadence": cadence,
            "timezone": timezone_name,
            "misfire_policy": misfire_policy,
            "ttl_days": ttl_days,
            "max_runs": max_runs,
            "enable": enable,
        }
        raw = json.dumps(
            payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:32]

    @staticmethod
    def _require_approval(
        preview: SchedulePreview, approved_fingerprint: str | None
    ) -> None:
        if not preview.requires_approval:
            return
        if approved_fingerprint != preview.approval_fingerprint:
            raise ScheduleAdminConflict(
                "scheduled write approval does not match the previewed action, cadence, timezone, misfire policy, expiry, budget and enable state"
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
            raw = json.dumps(
                args, sort_keys=True, ensure_ascii=False
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ScheduleAdminError("args skal kunne serialiseres som JSON") from exc
        if len(raw) > MAX_ARGS_JSON_BYTES:
            raise ScheduleAdminError(
                f"args fylder {len(raw)} bytes; maksimum er {MAX_ARGS_JSON_BYTES}"
            )

    @staticmethod
    def _validate_tool_args(spec: Any, args: dict[str, Any]) -> None:
        """Enforce the registry's narrow JSON-schema subset before persistence.

        Tool execution remains authoritative, but a standing grant that is known
        to be malformed should never be stored and fail every morning forever.
        The current registry uses only object/properties/required/basic types;
        unsupported schema constructs are left to ToolGate at execution time.
        """
        schema = getattr(spec, "params", None)
        if not isinstance(schema, dict):
            return
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            properties = {}
        required = schema.get("required")
        if not isinstance(required, list):
            required = []

        missing = [name for name in required if name not in args]
        if missing:
            raise ScheduleAdminError(
                f"manglende tool-argumenter: {', '.join(sorted(map(str, missing)))}"
            )
        unknown = sorted(set(args) - set(properties))
        if unknown and schema.get("additionalProperties") is not True:
            raise ScheduleAdminError(
                f"ukendte tool-argumenter: {', '.join(unknown)}"
            )

        expected_types: dict[str, tuple[type, ...]] = {
            "string": (str,),
            "integer": (int,),
            "number": (int, float),
            "boolean": (bool,),
            "object": (dict,),
            "array": (list,),
        }
        for name, value in args.items():
            prop = properties.get(name)
            if not isinstance(prop, dict):
                continue
            expected = prop.get("type")
            py_types = expected_types.get(str(expected))
            if py_types is None:
                continue
            valid = isinstance(value, py_types)
            if expected in ("integer", "number") and isinstance(value, bool):
                valid = False
            if not valid:
                raise ScheduleAdminError(
                    f"tool-argument {name!r} skal have typen {expected}"
                )
