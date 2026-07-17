"""Human-controlled administration for dormant schedules.

This module is deliberately not a model tool. It validates and persists the
operator's exact request for a local API, while the runner remains behind
``KALIV_SCHEDULER`` and every execution still goes through ToolGate.

A scheduled write has two separate proofs:

* ``action_fingerprint`` stays inside the persisted schedule and binds exactly
  ``(tool, args)`` for ToolGate on every future occurrence.
* a short-lived opaque approval token is signed with an Ed25519 private key
  held only by the authenticated backend. The worker has only the public key,
  so even a future shell tool in the worker cannot mint consent.

The signed binding covers operation, schedule id, action, cadence, expiry, run
budget and enable state. Tokens are stored only as consumed hashes, expire
quickly and are accepted once.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

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
APPROVAL_BINDING_VERSION = 2
APPROVAL_TOKEN_VERSION = 1
APPROVAL_TOKEN_TTL_SECONDS = 300
APPROVAL_TOKEN_CLOCK_SKEW_SECONDS = 5
APPROVAL_TOKEN_AUDIENCE = "kaliv-scheduler"
APPROVAL_PUBLIC_KEY_ENV = "KALIV_SCHEDULER_APPROVAL_PUBLIC_KEY"
APPROVAL_TOKEN_PREFIX = "kav1"


class ScheduleAdminError(ValueError):
    """An operator request that cannot be represented safely."""


class ScheduleAdminNotFound(ScheduleAdminError):
    """A schedule or tool that does not exist."""


class ScheduleAdminConflict(ScheduleAdminError):
    """The request conflicts with the schedule's immutable approval."""


class ScheduleAdminUnavailable(ScheduleAdminError):
    """Required approval verification is not configured safely."""


@dataclass(frozen=True)
class SchedulePreview:
    operation: str
    schedule_id: str | None
    tool: str
    args: dict[str, Any]
    cadence: str
    risk: str
    sensitivity: str
    human_summary: str
    requires_approval: bool
    action_fingerprint: str
    approval_binding: str | None
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
            "risk": self.risk,
            "sensitivity": self.sensitivity,
            "human_summary": self.human_summary,
            "requires_approval": self.requires_approval,
            "action_fingerprint": self.action_fingerprint,
            # Public and non-authorising: useful for support correlation only.
            "approval_binding": self.approval_binding,
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
    replaying missed work. Approval tokens live in the same SQLite file so a
    restart cannot make an already-used token reusable.
    """

    def __init__(self, path: str | None = None) -> None:
        super().__init__(path)
        with self._lock:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS schedule_consumed_approval_tokens (
                       token_hash TEXT PRIMARY KEY,
                       expires_at REAL NOT NULL,
                       consumed REAL NOT NULL)"""
            )
            self._conn.commit()

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def consume_verified_approval_token(
        self, token: str, *, expires_at: float, now: float
    ) -> None:
        """Record one verified token exactly once across threads and restarts."""
        token_hash = self._token_hash(token)
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                self._conn.execute(
                    "DELETE FROM schedule_consumed_approval_tokens WHERE expires_at<?",
                    (now - APPROVAL_TOKEN_CLOCK_SKEW_SECONDS,),
                )
                self._conn.execute(
                    "INSERT INTO schedule_consumed_approval_tokens "
                    "(token_hash, expires_at, consumed) VALUES (?,?,?)",
                    (token_hash, expires_at, now),
                )
                self._conn.commit()
            except sqlite3.IntegrityError as exc:
                self._conn.rollback()
                raise ScheduleAdminConflict(
                    "approval token is missing, expired, already used or bound to another standing grant"
                ) from exc
            except Exception:
                self._conn.rollback()
                raise

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
        approval_public_key: str | None = None,
    ) -> None:
        self._store_factory = store_factory
        self._registry_factory = registry_factory
        self._clock = clock
        key_text = (
            os.environ.get(APPROVAL_PUBLIC_KEY_ENV, "")
            if approval_public_key is None
            else approval_public_key
        ).strip()
        self._approval_public_key = self._load_public_key(key_text)

    @staticmethod
    def _load_public_key(encoded: str) -> Ed25519PublicKey | None:
        if not encoded:
            return None
        try:
            raw = base64.b64decode(encoded, validate=True)
            if len(raw) != 32:
                return None
            return Ed25519PublicKey.from_public_bytes(raw)
        except (ValueError, binascii.Error):
            return None

    def approval_verifier_configured(self) -> bool:
        return self._approval_public_key is not None

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
        """Preview a new standing grant; execute and persist nothing."""
        return self._preview(
            operation="create",
            schedule_id=None,
            tool=tool,
            args=args,
            cadence=cadence,
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
        approval_token: str | None = None,
    ) -> dict[str, Any]:
        preview = self.preview(
            tool, args, cadence, ttl_days=ttl_days, max_runs=max_runs
        )
        verified = self._verify_approval(preview, approval_token)
        with self._store() as store:
            if verified is not None:
                expires_at, verified_at = verified
                store.consume_verified_approval_token(
                    approval_token or "", expires_at=expires_at, now=verified_at
                )
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
        return [
            self.describe(item, registry=registry, now=now) for item in schedules
        ]

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
        approval_token: str | None = None,
        enable: bool | None = None,
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
                ttl_days=ttl_days,
                max_runs=max_runs,
                enable=enable,
            )
            verified = self._verify_approval(preview, approval_token)
            if verified is not None:
                expires_at, verified_at = verified
                store.consume_verified_approval_token(
                    approval_token or "", expires_at=expires_at, now=verified_at
                )
            updated = store.renew(
                schedule_id,
                # The persisted standing grant only needs the exact action
                # fingerprint. The opaque approval token was consumed above and
                # is never used for execution.
                approved_fingerprint=(
                    preview.action_fingerprint if preview.requires_approval else None
                ),
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
        current_action = fingerprint(schedule.tool, schedule.args)
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
        ttl_days: int,
        max_runs: int,
        enable: bool | None,
    ) -> SchedulePreview:
        if operation not in ("create", "renew"):
            raise ScheduleAdminError(f"unknown schedule operation: {operation}")
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
        approval_binding = None
        if risk == "write":
            if self._approval_public_key is None:
                raise ScheduleAdminUnavailable(
                    f"scheduled writes require {APPROVAL_PUBLIC_KEY_ENV}"
                )
            approval_binding = self._grant_binding(
                operation=operation,
                schedule_id=schedule_id,
                tool=tool,
                args=args,
                cadence=cadence,
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
            risk=risk,
            sensitivity=str(getattr(spec, "sensitivity", "operational")),
            human_summary=summary,
            requires_approval=risk == "write",
            action_fingerprint=action_fp,
            approval_binding=approval_binding,
            due_at=next_run(cad, now),
            expires_at=now + ttl_days * 86400,
            ttl_days=ttl_days,
            max_runs=max_runs,
            enable=enable,
        )

    @staticmethod
    def _grant_binding(
        *,
        operation: str,
        schedule_id: str | None,
        tool: str,
        args: dict[str, Any],
        cadence: str,
        ttl_days: int,
        max_runs: int,
        enable: bool | None,
    ) -> str:
        payload = {
            "version": APPROVAL_BINDING_VERSION,
            "operation": operation,
            "schedule_id": schedule_id,
            "tool": tool,
            "args": args,
            "cadence": cadence,
            "ttl_days": ttl_days,
            "max_runs": max_runs,
            "enable": enable,
        }
        raw = json.dumps(
            payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _b64url_decode(value: str) -> bytes:
        padding = "=" * ((4 - len(value) % 4) % 4)
        return base64.urlsafe_b64decode((value + padding).encode("ascii"))

    def _verify_approval(
        self,
        preview: SchedulePreview,
        approval_token: str | None,
    ) -> tuple[float, float] | None:
        if not preview.requires_approval:
            return None
        if self._approval_public_key is None:
            raise ScheduleAdminUnavailable(
                f"scheduled writes require {APPROVAL_PUBLIC_KEY_ENV}"
            )
        generic = (
            "approval token is missing, expired, already used or bound to another standing grant"
        )
        if not approval_token or len(approval_token) > 4096:
            raise ScheduleAdminConflict(generic)
        try:
            prefix, payload_text, signature_text = approval_token.split(".")
            if prefix != APPROVAL_TOKEN_PREFIX:
                raise ValueError("wrong prefix")
            payload_raw = self._b64url_decode(payload_text)
            signature = self._b64url_decode(signature_text)
            if len(signature) != 64:
                raise ValueError("wrong signature length")
            self._approval_public_key.verify(signature, payload_raw)
            claims = json.loads(payload_raw)
            if not isinstance(claims, dict):
                raise ValueError("claims are not an object")
            now = self._clock()
            expires_at = float(claims.get("exp"))
            if claims.get("v") != APPROVAL_TOKEN_VERSION:
                raise ValueError("wrong token version")
            if claims.get("aud") != APPROVAL_TOKEN_AUDIENCE:
                raise ValueError("wrong audience")
            if claims.get("binding") != preview.approval_binding:
                raise ValueError("wrong grant binding")
            nonce = claims.get("nonce")
            if not isinstance(nonce, str) or len(nonce) < 16 or len(nonce) > 128:
                raise ValueError("bad nonce")
            if expires_at < now - APPROVAL_TOKEN_CLOCK_SKEW_SECONDS:
                raise ValueError("expired")
            if expires_at > now + APPROVAL_TOKEN_TTL_SECONDS + APPROVAL_TOKEN_CLOCK_SKEW_SECONDS:
                raise ValueError("expiry is not short-lived")
        except (
            ValueError,
            TypeError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            binascii.Error,
            InvalidSignature,
        ) as exc:
            raise ScheduleAdminConflict(generic) from exc
        return expires_at, now

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
