"""Dormant signed action-preview boundary for Computer Use I4.

This module issues short-lived one-shot plans for an exact screenshot-bound click
or text action. It performs no capture, registers no tool and injects no input.
A future Windows executor must call :meth:`DesktopActionPlanner.consume`, which
re-runs the existing ``DesktopSessionGuard.authorize`` against a fresh capture and
returns only ``AuthorizedDesktopAction``. The actual SendInput boundary remains
absent and physically gated.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal

from .desktop_contract import (
    ACTION_SCHEMA,
    AuthorizedDesktopAction,
    CapturedWindow,
    DesktopAction,
    DesktopContractError,
    DesktopSessionGuard,
    WindowTarget,
)
from .desktop_policy import DesktopDenied, hamming

ACTION_PLAN_SCHEMA = "kaliv-desktop-action-plan/v1"
ACTION_PREVIEW_SCHEMA = "kaliv-desktop-action-preview/v1"
_MAX_TOKEN_BYTES = 16 * 1024
_MAX_USED_NONCES = 512
_SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")
_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
Origin = Literal["local", "cloud"]


class DesktopActionPlanError(DesktopContractError):
    """Malformed plan or inconsistent planner configuration."""


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64url(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise DesktopDenied("desktop-handlingsplanen er ugyldig")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as exc:
        raise DesktopDenied("desktop-handlingsplanen er ugyldig") from exc


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _session(value: str) -> str:
    if not isinstance(value, str) or not _SESSION_RE.fullmatch(value):
        raise DesktopActionPlanError("session_id has an invalid format")
    return value


def _origin(value: str) -> Origin:
    if value not in {"local", "cloud"}:
        raise DesktopActionPlanError("origin must be local or cloud")
    return value  # type: ignore[return-value]


def _action_dict(action: DesktopAction) -> dict[str, Any]:
    if not isinstance(action, DesktopAction):
        raise DesktopActionPlanError("action must be DesktopAction")
    return {
        "schema": ACTION_SCHEMA,
        "kind": action.kind,
        "screen_token": action.screen_token,
        "x": action.x,
        "y": action.y,
        "text": action.text,
        "button": action.button,
    }


def _action_from_dict(value: Any) -> DesktopAction:
    if not isinstance(value, dict) or set(value) != {
        "schema",
        "kind",
        "screen_token",
        "x",
        "y",
        "text",
        "button",
    }:
        raise DesktopActionPlanError("action has an invalid shape")
    return DesktopAction(**value)


def _preview_authorized(
    guard: DesktopSessionGuard,
    action: DesktopAction,
    current: CapturedWindow,
    *,
    session_id: str,
    origin: Origin,
    cloud_consent: bool,
    now: float,
) -> AuthorizedDesktopAction:
    """Non-consuming preview; final consume re-runs the authoritative guard.

    This deliberately mirrors the public guard checks but cannot weaken final
    execution: :meth:`consume` always calls ``guard.authorize`` again, including
    the rate limiter. A preview bug can therefore produce a useless plan, never a
    successful action.
    """
    proof = guard.codec.verify(
        action.screen_token,
        session_id=session_id,
        origin=origin,
        cloud_consent=cloud_consent,
        now=now,
    )
    guard.allowlist.require(current.target.process, current.target.title)
    if proof.target != current.target:
        raise DesktopDenied(
            "forgrundsvinduet eller dets geometri har ændret sig — tag et nyt screenshot"
        )
    distance = hamming(proof.phash, current.phash)
    if distance > guard.tolerance:
        raise DesktopDenied(
            f"vinduet har ændret sig siden screenshotet (afstand {distance} > "
            f"{guard.tolerance}) — planlæg forfra"
        )
    if action.kind == "click":
        assert action.x is not None and action.y is not None
        if action.x >= current.target.width or action.y >= current.target.height:
            raise DesktopDenied("klikpunktet ligger uden for det godkendte vindue")
        return AuthorizedDesktopAction(
            kind="click",
            target=current.target,
            absolute_x=current.target.left + action.x,
            absolute_y=current.target.top + action.y,
            button="left",
        )
    return AuthorizedDesktopAction(
        kind="type_text",
        target=current.target,
        text=action.text,
    )


@dataclass(frozen=True)
class DesktopActionPlan:
    session_id: str
    origin: Origin
    action: DesktopAction
    target: WindowTarget
    current_phash: str
    screen_token_sha256: str
    issued_at_ms: int
    expires_at_ms: int
    nonce: str
    schema: str = ACTION_PLAN_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != ACTION_PLAN_SCHEMA:
            raise DesktopActionPlanError("unsupported desktop action plan schema")
        object.__setattr__(self, "session_id", _session(self.session_id))
        object.__setattr__(self, "origin", _origin(self.origin))
        if not isinstance(self.action, DesktopAction):
            raise DesktopActionPlanError("plan action must be DesktopAction")
        if not isinstance(self.target, WindowTarget):
            raise DesktopActionPlanError("plan target must be WindowTarget")
        if not isinstance(self.current_phash, str) or not re.fullmatch(
            r"[0-9a-f]{16,128}", self.current_phash
        ):
            raise DesktopActionPlanError("plan current_phash is invalid")
        if not isinstance(self.screen_token_sha256, str) or not _SHA256_RE.fullmatch(
            self.screen_token_sha256
        ):
            raise DesktopActionPlanError("plan screen_token_sha256 is invalid")
        for value, name in (
            (self.issued_at_ms, "issued_at_ms"),
            (self.expires_at_ms, "expires_at_ms"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise DesktopActionPlanError(f"{name} must be a non-negative integer")
        if self.expires_at_ms <= self.issued_at_ms:
            raise DesktopActionPlanError("plan expiry must follow issue time")
        if not isinstance(self.nonce, str) or not _NONCE_RE.fullmatch(self.nonce):
            raise DesktopActionPlanError("plan nonce is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "session_id": self.session_id,
            "origin": self.origin,
            "action": _action_dict(self.action),
            "target": self.target.to_dict(),
            "current_phash": self.current_phash,
            "screen_token_sha256": self.screen_token_sha256,
            "issued_at_ms": self.issued_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "nonce": self.nonce,
            "production_activation": False,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "DesktopActionPlan":
        if not isinstance(value, dict) or set(value) != {
            "schema",
            "session_id",
            "origin",
            "action",
            "target",
            "current_phash",
            "screen_token_sha256",
            "issued_at_ms",
            "expires_at_ms",
            "nonce",
            "production_activation",
        }:
            raise DesktopActionPlanError("desktop action plan has an invalid shape")
        if value["production_activation"] is not False:
            raise DesktopActionPlanError("desktop action plan cannot activate production")
        data = dict(value)
        data.pop("production_activation")
        data["action"] = _action_from_dict(data["action"])
        data["target"] = WindowTarget.from_dict(data["target"])
        return cls(**data)


@dataclass(frozen=True)
class DesktopActionPreviewReceipt:
    plan_token: str
    action: DesktopAction
    authorized: AuthorizedDesktopAction
    expires_in_seconds: int
    schema: str = ACTION_PREVIEW_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "plan_token": self.plan_token,
            "action": _action_dict(self.action),
            "preview": self.authorized.to_dict(),
            "expires_in_seconds": self.expires_in_seconds,
            "execution_enabled": False,
            "production_activation": False,
        }


class DesktopActionPlanner:
    """Issue and atomically consume process-ephemeral one-shot action plans."""

    def __init__(
        self,
        guard: DesktopSessionGuard,
        *,
        secret: bytes | None = None,
        ttl_s: float = 10.0,
        clock: Callable[[], float] = time.time,
        nonce_factory: Callable[[int], bytes] = secrets.token_bytes,
    ) -> None:
        if not isinstance(guard, DesktopSessionGuard):
            raise DesktopActionPlanError("planner requires DesktopSessionGuard")
        key = secrets.token_bytes(32) if secret is None else secret
        if not isinstance(key, bytes) or len(key) < 32:
            raise DesktopActionPlanError("action plan secret must contain at least 32 bytes")
        if isinstance(ttl_s, bool) or not isinstance(ttl_s, (int, float)) or not 1 <= float(ttl_s) <= 30:
            raise DesktopActionPlanError("action plan ttl_s must be between 1 and 30 seconds")
        if not callable(clock) or not callable(nonce_factory):
            raise DesktopActionPlanError("clock and nonce_factory must be callable")
        self.guard = guard
        self._secret = bytes(key)
        self.ttl_s = float(ttl_s)
        self.clock = clock
        self.nonce_factory = nonce_factory
        self._lock = threading.RLock()
        self._used_nonces: dict[str, int] = {}

    def _now(self, now: float | None) -> float:
        value = self.clock() if now is None else now
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise DesktopActionPlanError("now must be numeric")
        return float(value)

    def _encode(self, plan: DesktopActionPlan) -> str:
        payload = _canonical(plan.to_dict())
        signature = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return f"{_b64url(payload)}.{_b64url(signature)}"

    def _decode(
        self,
        token: str,
        *,
        session_id: str,
        origin: Origin,
        now: float,
    ) -> DesktopActionPlan:
        if not isinstance(token, str) or len(token) > _MAX_TOKEN_BYTES or token.count(".") != 1:
            raise DesktopDenied("desktop-handlingsplanen er ugyldig")
        encoded, signed = token.split(".", 1)
        payload = _unb64url(encoded)
        signature = _unb64url(signed)
        expected = hmac.new(self._secret, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise DesktopDenied("desktop-handlingsplanens signatur matcher ikke")
        try:
            plan = DesktopActionPlan.from_dict(json.loads(payload.decode("utf-8")))
        except (UnicodeDecodeError, json.JSONDecodeError, DesktopContractError) as exc:
            raise DesktopDenied("desktop-handlingsplanen er ugyldig") from exc
        if plan.session_id != _session(session_id):
            raise DesktopDenied("desktop-handlingsplanen tilhører en anden session")
        if plan.origin != _origin(origin):
            raise DesktopDenied("desktop-handlingsplanen tilhører en anden model-origin")
        now_ms = int(now * 1000)
        if now_ms < plan.issued_at_ms - 1_000:
            raise DesktopDenied("desktop-handlingsplanen kommer fra fremtiden")
        if now_ms > plan.expires_at_ms:
            raise DesktopDenied("desktop-handlingsplanen er udløbet — planlæg igen")
        return plan

    def preview(
        self,
        action: DesktopAction,
        current: CapturedWindow,
        *,
        session_id: str,
        origin: Origin,
        cloud_consent: bool = False,
        now: float | None = None,
    ) -> DesktopActionPreviewReceipt:
        timestamp = self._now(now)
        session = _session(session_id)
        planner_origin = _origin(origin)
        authorized = _preview_authorized(
            self.guard,
            action,
            current,
            session_id=session,
            origin=planner_origin,
            cloud_consent=cloud_consent,
            now=timestamp,
        )
        issued_at_ms = int(timestamp * 1000)
        plan = DesktopActionPlan(
            session_id=session,
            origin=planner_origin,
            action=action,
            target=current.target,
            current_phash=current.phash,
            screen_token_sha256=hashlib.sha256(
                action.screen_token.encode("utf-8")
            ).hexdigest(),
            issued_at_ms=issued_at_ms,
            expires_at_ms=issued_at_ms + int(self.ttl_s * 1000),
            nonce=_b64url(self.nonce_factory(16)),
        )
        return DesktopActionPreviewReceipt(
            plan_token=self._encode(plan),
            action=action,
            authorized=authorized,
            expires_in_seconds=max(1, int(self.ttl_s)),
        )

    def consume(
        self,
        plan_token: str,
        expected_action: DesktopAction,
        current: CapturedWindow,
        *,
        session_id: str,
        origin: Origin,
        cloud_consent: bool = False,
        now: float | None = None,
    ) -> AuthorizedDesktopAction:
        timestamp = self._now(now)
        plan = self._decode(
            plan_token,
            session_id=session_id,
            origin=origin,
            now=timestamp,
        )
        if _canonical(_action_dict(plan.action)) != _canonical(_action_dict(expected_action)):
            raise DesktopDenied("desktop-handlingen matcher ikke det viste preview")
        if plan.screen_token_sha256 != hashlib.sha256(
            expected_action.screen_token.encode("utf-8")
        ).hexdigest():
            raise DesktopDenied("desktop-handlingens screenshot-bevis er ændret")
        if plan.target != current.target or plan.current_phash != current.phash:
            raise DesktopDenied(
                "skærmen har ændret sig siden previewet — tag et nyt screenshot"
            )
        with self._lock:
            now_ms = int(timestamp * 1000)
            self._used_nonces = {
                nonce: expiry
                for nonce, expiry in self._used_nonces.items()
                if expiry >= now_ms
            }
            if plan.nonce in self._used_nonces:
                raise DesktopDenied("desktop-handlingsplanen er allerede brugt")
            if len(self._used_nonces) >= _MAX_USED_NONCES:
                oldest = min(self._used_nonces, key=self._used_nonces.get)
                self._used_nonces.pop(oldest, None)
            # Spend before the final guard. A changed desktop cannot turn a failed
            # attempt into a replay opportunity.
            self._used_nonces[plan.nonce] = plan.expires_at_ms
        return self.guard.authorize(
            expected_action,
            current,
            session_id=session_id,
            origin=origin,
            cloud_consent=cloud_consent,
            now=timestamp,
        )


__all__ = [
    "ACTION_PLAN_SCHEMA",
    "ACTION_PREVIEW_SCHEMA",
    "DesktopActionPlan",
    "DesktopActionPlanError",
    "DesktopActionPlanner",
    "DesktopActionPreviewReceipt",
]
