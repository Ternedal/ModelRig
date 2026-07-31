"""Signed, screenshot-bound contract for dormant Tier-B computer use.

This module performs no capture and injects no input.  It defines the trust
boundary the Windows adapter must satisfy before the first real desktop tool is
registered:

* snapshots are restricted to an allowlisted foreground window;
* an opaque HMAC proof binds session, planner origin, target identity, geometry,
  image digest, perceptual hash and issue time;
* proofs are short lived and process-ephemeral by default;
* click/type actions are accepted only against a freshly captured matching
  window and consume the shared desktop rate limiter;
* cloud planning remains denied unless the caller supplies separate session
  consent; the proof cannot be replayed under another origin or session.

The signing secret deliberately lives only in worker memory. A worker restart
invalidates every outstanding screenshot, which is safer than resurrecting a
plan against a desktop that has certainly moved.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal

from .desktop_policy import (
    DEFAULT_SCREEN_TTL_S,
    DEFAULT_TOLERANCE,
    DesktopDenied,
    RateLimiter,
    TargetAllowlist,
    hamming,
    require_local_origin,
)

SCREEN_PROOF_SCHEMA = "kaliv-desktop-screen-proof/v1"
SNAPSHOT_SCHEMA = "kaliv-desktop-snapshot/v1"
ACTION_SCHEMA = "kaliv-desktop-action/v1"
_MAX_IMAGE_BYTES = 8 * 1024 * 1024
_MAX_TITLE_CHARS = 500
_MAX_PROCESS_CHARS = 260
_MAX_TEXT_CHARS = 1_000
_MAX_TOKEN_BYTES = 16 * 1024
_SESSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$")
_PHASH_RE = re.compile(r"^[0-9a-f]{16,128}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MEDIA_TYPES = {"image/png", "image/webp"}
Origin = Literal["local", "cloud"]
ActionKind = Literal["click", "type_text"]


class DesktopContractError(ValueError):
    """Malformed input or an internally inconsistent desktop contract object."""


def _text(value: str, name: str, maximum: int, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise DesktopContractError(f"{name} must be a string")
    cleaned = value.strip() if not allow_empty else value
    if not allow_empty and not cleaned:
        raise DesktopContractError(f"{name} must not be empty")
    if len(cleaned) > maximum:
        raise DesktopContractError(f"{name} exceeds {maximum} characters")
    return cleaned


def _integer(value: int, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DesktopContractError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise DesktopContractError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return value


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64url(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise DesktopDenied("screenshot-beviset er ugyldigt")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as exc:
        raise DesktopDenied("screenshot-beviset er ugyldigt") from exc


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _session(value: str) -> str:
    if not isinstance(value, str) or not _SESSION_RE.fullmatch(value):
        raise DesktopContractError("session_id has an invalid format")
    return value


def _origin(value: str) -> Origin:
    if value not in {"local", "cloud"}:
        raise DesktopContractError("origin must be local or cloud")
    return value  # type: ignore[return-value]


@dataclass(frozen=True)
class WindowTarget:
    hwnd: int
    process: str
    title: str
    left: int
    top: int
    width: int
    height: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "hwnd", _integer(self.hwnd, "hwnd", 1, 2**63 - 1))
        process = _text(self.process, "process", _MAX_PROCESS_CHARS).lower()
        if "/" in process or "\\" in process:
            raise DesktopContractError("process must be a basename, not a path")
        object.__setattr__(self, "process", process)
        object.__setattr__(
            self,
            "title",
            _text(self.title, "title", _MAX_TITLE_CHARS, allow_empty=True),
        )
        object.__setattr__(self, "left", _integer(self.left, "left", -200_000, 200_000))
        object.__setattr__(self, "top", _integer(self.top, "top", -200_000, 200_000))
        object.__setattr__(self, "width", _integer(self.width, "width", 1, 100_000))
        object.__setattr__(self, "height", _integer(self.height, "height", 1, 100_000))

    def to_dict(self) -> dict[str, Any]:
        return {
            "hwnd": self.hwnd,
            "process": self.process,
            "title": self.title,
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "WindowTarget":
        if not isinstance(value, dict) or set(value) != {
            "hwnd",
            "process",
            "title",
            "left",
            "top",
            "width",
            "height",
        }:
            raise DesktopContractError("target has an invalid shape")
        return cls(**value)


@dataclass(frozen=True)
class CapturedWindow:
    target: WindowTarget
    image: bytes
    media_type: str
    phash: str

    def __post_init__(self) -> None:
        if not isinstance(self.target, WindowTarget):
            raise DesktopContractError("target must be WindowTarget")
        if not isinstance(self.image, bytes) or not 1 <= len(self.image) <= _MAX_IMAGE_BYTES:
            raise DesktopContractError(
                f"image must contain 1..{_MAX_IMAGE_BYTES} bytes"
            )
        if self.media_type not in _MEDIA_TYPES:
            raise DesktopContractError("media_type must be image/png or image/webp")
        if not isinstance(self.phash, str) or not _PHASH_RE.fullmatch(self.phash):
            raise DesktopContractError("phash must be lowercase hexadecimal")

    @property
    def image_sha256(self) -> str:
        return hashlib.sha256(self.image).hexdigest()


@dataclass(frozen=True)
class ScreenProof:
    session_id: str
    origin: Origin
    target: WindowTarget
    phash: str
    image_sha256: str
    issued_at_ms: int
    nonce: str
    schema: str = SCREEN_PROOF_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != SCREEN_PROOF_SCHEMA:
            raise DesktopContractError("unsupported screen proof schema")
        object.__setattr__(self, "session_id", _session(self.session_id))
        object.__setattr__(self, "origin", _origin(self.origin))
        if not isinstance(self.target, WindowTarget):
            raise DesktopContractError("proof target must be WindowTarget")
        if not isinstance(self.phash, str) or not _PHASH_RE.fullmatch(self.phash):
            raise DesktopContractError("proof phash is invalid")
        if not isinstance(self.image_sha256, str) or not _SHA256_RE.fullmatch(
            self.image_sha256
        ):
            raise DesktopContractError("proof image_sha256 is invalid")
        object.__setattr__(
            self,
            "issued_at_ms",
            _integer(self.issued_at_ms, "issued_at_ms", 0, 2**63 - 1),
        )
        if not isinstance(self.nonce, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{16,64}", self.nonce
        ):
            raise DesktopContractError("proof nonce is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "session_id": self.session_id,
            "origin": self.origin,
            "target": self.target.to_dict(),
            "phash": self.phash,
            "image_sha256": self.image_sha256,
            "issued_at_ms": self.issued_at_ms,
            "nonce": self.nonce,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "ScreenProof":
        if not isinstance(value, dict) or set(value) != {
            "schema",
            "session_id",
            "origin",
            "target",
            "phash",
            "image_sha256",
            "issued_at_ms",
            "nonce",
        }:
            raise DesktopContractError("screen proof has an invalid shape")
        data = dict(value)
        data["target"] = WindowTarget.from_dict(data["target"])
        return cls(**data)


class ScreenProofCodec:
    """Short-lived HMAC proof; default key is random and process-ephemeral."""

    def __init__(
        self,
        secret: bytes | None = None,
        *,
        ttl_s: float = DEFAULT_SCREEN_TTL_S,
        clock: Callable[[], float] = time.time,
        nonce_factory: Callable[[int], bytes] = secrets.token_bytes,
    ) -> None:
        key = secrets.token_bytes(32) if secret is None else secret
        if not isinstance(key, bytes) or len(key) < 32:
            raise DesktopContractError("screen proof secret must contain at least 32 bytes")
        if isinstance(ttl_s, bool) or not isinstance(ttl_s, (int, float)):
            raise DesktopContractError("ttl_s must be numeric")
        if not 1 <= float(ttl_s) <= 120:
            raise DesktopContractError("ttl_s must be between 1 and 120 seconds")
        if not callable(clock) or not callable(nonce_factory):
            raise DesktopContractError("clock and nonce_factory must be callable")
        self._secret = bytes(key)
        self.ttl_s = float(ttl_s)
        self.clock = clock
        self.nonce_factory = nonce_factory

    def issue(
        self,
        capture: CapturedWindow,
        *,
        session_id: str,
        origin: Origin,
        cloud_consent: bool,
        now: float | None = None,
    ) -> tuple[ScreenProof, str]:
        if not isinstance(capture, CapturedWindow):
            raise DesktopContractError("capture must be CapturedWindow")
        session = _session(session_id)
        planner_origin = _origin(origin)
        require_local_origin(planner_origin, bool(cloud_consent))
        timestamp = self.clock() if now is None else now
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            raise DesktopContractError("now must be numeric")
        proof = ScreenProof(
            session_id=session,
            origin=planner_origin,
            target=capture.target,
            phash=capture.phash,
            image_sha256=capture.image_sha256,
            issued_at_ms=int(float(timestamp) * 1000),
            nonce=_b64url(self.nonce_factory(16)),
        )
        payload = _canonical(proof.to_dict())
        signature = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return proof, f"{_b64url(payload)}.{_b64url(signature)}"

    def verify(
        self,
        token: str,
        *,
        session_id: str,
        origin: Origin,
        cloud_consent: bool,
        now: float | None = None,
    ) -> ScreenProof:
        session = _session(session_id)
        planner_origin = _origin(origin)
        require_local_origin(planner_origin, bool(cloud_consent))
        if not isinstance(token, str) or len(token) > _MAX_TOKEN_BYTES or token.count(".") != 1:
            raise DesktopDenied("screenshot-beviset er ugyldigt")
        encoded, signed = token.split(".", 1)
        payload = _unb64url(encoded)
        signature = _unb64url(signed)
        expected = hmac.new(self._secret, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise DesktopDenied("screenshot-bevisets signatur matcher ikke")
        try:
            value = json.loads(payload.decode("utf-8"))
            proof = ScreenProof.from_dict(value)
        except (UnicodeDecodeError, json.JSONDecodeError, DesktopContractError) as exc:
            raise DesktopDenied("screenshot-beviset er ugyldigt") from exc
        if proof.session_id != session:
            raise DesktopDenied("screenshot-beviset tilhører en anden session")
        if proof.origin != planner_origin:
            raise DesktopDenied("screenshot-beviset blev planlagt af en anden model-origin")
        timestamp = self.clock() if now is None else now
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            raise DesktopContractError("now must be numeric")
        age_ms = int(float(timestamp) * 1000) - proof.issued_at_ms
        if age_ms < -1_000:
            raise DesktopDenied("screenshot-beviset kommer fra fremtiden")
        if age_ms > int(self.ttl_s * 1000):
            raise DesktopDenied(
                f"screenshot-beviset er {age_ms / 1000:.1f}s gammelt — tag et nyt"
            )
        return proof


@dataclass(frozen=True)
class DesktopSnapshotReceipt:
    target: WindowTarget
    phash: str
    image_sha256: str
    media_type: str
    image_base64: str
    screen_token: str
    schema: str = SNAPSHOT_SCHEMA

    @classmethod
    def create(cls, capture: CapturedWindow, token: str) -> "DesktopSnapshotReceipt":
        if not isinstance(capture, CapturedWindow):
            raise DesktopContractError("capture must be CapturedWindow")
        if not isinstance(token, str) or not token:
            raise DesktopContractError("screen_token must not be empty")
        return cls(
            target=capture.target,
            phash=capture.phash,
            image_sha256=capture.image_sha256,
            media_type=capture.media_type,
            image_base64=base64.b64encode(capture.image).decode("ascii"),
            screen_token=token,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "target": self.target.to_dict(),
            "phash": self.phash,
            "image_sha256": self.image_sha256,
            "media_type": self.media_type,
            "image_base64": self.image_base64,
            "screen_token": self.screen_token,
            "production_activation": False,
        }


@dataclass(frozen=True)
class DesktopAction:
    kind: ActionKind
    screen_token: str
    x: int | None = None
    y: int | None = None
    text: str | None = None
    button: Literal["left"] | None = None
    schema: str = ACTION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != ACTION_SCHEMA:
            raise DesktopContractError("unsupported desktop action schema")
        if self.kind not in {"click", "type_text"}:
            raise DesktopContractError("desktop action kind is invalid")
        if not isinstance(self.screen_token, str) or not self.screen_token:
            raise DesktopContractError("screen_token must not be empty")
        if self.kind == "click":
            if self.button not in {None, "left"}:
                raise DesktopContractError("v1 only supports the left mouse button")
            if self.x is None or self.y is None:
                raise DesktopContractError("click requires x and y")
            _integer(self.x, "x", 0, 100_000)
            _integer(self.y, "y", 0, 100_000)
            if self.text is not None:
                raise DesktopContractError("click cannot include text")
        else:
            if self.x is not None or self.y is not None or self.button is not None:
                raise DesktopContractError("type_text cannot include click fields")
            if not isinstance(self.text, str) or not 1 <= len(self.text) <= _MAX_TEXT_CHARS:
                raise DesktopContractError(
                    f"text must contain 1..{_MAX_TEXT_CHARS} characters"
                )
            for char in self.text:
                if ord(char) < 32 and char not in {"\n", "\t"}:
                    raise DesktopContractError("text contains a forbidden control character")


@dataclass(frozen=True)
class AuthorizedDesktopAction:
    kind: ActionKind
    target: WindowTarget
    absolute_x: int | None = None
    absolute_y: int | None = None
    text: str | None = None
    button: Literal["left"] | None = None
    schema: str = ACTION_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "kind": self.kind,
            "target": self.target.to_dict(),
            "absolute_x": self.absolute_x,
            "absolute_y": self.absolute_y,
            "text": self.text,
            "button": self.button,
            "production_activation": False,
        }


class DesktopSessionGuard:
    """Composes signed proof, allowlist, freshness, origin and rate policy."""

    def __init__(
        self,
        allowlist: TargetAllowlist,
        *,
        codec: ScreenProofCodec | None = None,
        limiter: RateLimiter | None = None,
        tolerance: int = DEFAULT_TOLERANCE,
    ) -> None:
        if not isinstance(allowlist, TargetAllowlist):
            raise DesktopContractError("allowlist must be TargetAllowlist")
        if isinstance(tolerance, bool) or not isinstance(tolerance, int) or not 0 <= tolerance <= 64:
            raise DesktopContractError("tolerance must be an integer between 0 and 64")
        self.allowlist = allowlist
        self.codec = codec or ScreenProofCodec()
        self.limiter = limiter or RateLimiter()
        self.tolerance = tolerance

    def snapshot(
        self,
        capture: CapturedWindow,
        *,
        session_id: str,
        origin: Origin,
        cloud_consent: bool = False,
        now: float | None = None,
    ) -> DesktopSnapshotReceipt:
        if not isinstance(capture, CapturedWindow):
            raise DesktopContractError("capture must be CapturedWindow")
        self.allowlist.require(capture.target.process, capture.target.title)
        _proof, token = self.codec.issue(
            capture,
            session_id=session_id,
            origin=origin,
            cloud_consent=cloud_consent,
            now=now,
        )
        return DesktopSnapshotReceipt.create(capture, token)

    def authorize(
        self,
        action: DesktopAction,
        current: CapturedWindow,
        *,
        session_id: str,
        origin: Origin,
        cloud_consent: bool = False,
        now: float | None = None,
    ) -> AuthorizedDesktopAction:
        if not isinstance(action, DesktopAction):
            raise DesktopContractError("action must be DesktopAction")
        if not isinstance(current, CapturedWindow):
            raise DesktopContractError("current must be CapturedWindow")
        proof = self.codec.verify(
            action.screen_token,
            session_id=session_id,
            origin=origin,
            cloud_consent=cloud_consent,
            now=now,
        )
        self.allowlist.require(current.target.process, current.target.title)
        if proof.target != current.target:
            raise DesktopDenied(
                "forgrundsvinduet eller dets geometri har ændret sig — tag et nyt screenshot"
            )
        distance = hamming(proof.phash, current.phash)
        if distance > self.tolerance:
            raise DesktopDenied(
                f"vinduet har ændret sig siden screenshotet (afstand {distance} > "
                f"{self.tolerance}) — planlæg forfra"
            )
        self.limiter.require(now=now)
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


__all__ = [
    "ACTION_SCHEMA",
    "AuthorizedDesktopAction",
    "CapturedWindow",
    "DesktopAction",
    "DesktopContractError",
    "DesktopSessionGuard",
    "DesktopSnapshotReceipt",
    "SCREEN_PROOF_SCHEMA",
    "SNAPSHOT_SCHEMA",
    "ScreenProof",
    "ScreenProofCodec",
    "WindowTarget",
]
