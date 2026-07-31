"""Dormant final execution boundary for Tier-B Computer Use.

This module deliberately registers no tool, route or startup hook and reads no
environment variable.  It is the last coordinator before Win32 input: callers
must supply independently verified, candidate-bound physical gate evidence and
one fresh human approval bound to the exact signed preview plan.

Only after both proofs pass does the coordinator capture the foreground window,
atomically consume the existing one-shot :class:`DesktopActionPlanner` token,
and hand the resulting :class:`AuthorizedDesktopAction` to the hardened Win32
backend.  The physical low-integrity/UIPI gate remains external and unproven on
CI, so nothing in production imports or constructs this class yet.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .desktop_action_plan import DesktopActionPlanner
from .desktop_contract import DesktopAction, WindowTarget
from .desktop_policy import DesktopDenied
from .desktop_win32 import Win32DesktopBackend

PHYSICAL_GATE_SCHEMA = "kaliv-desktop-physical-gate/v1"
INPUT_APPROVAL_SCHEMA = "kaliv-desktop-input-approval/v1"
INPUT_EXECUTION_SCHEMA = "kaliv-desktop-input-execution/v1"

_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_NONCE = re.compile(r"^[A-Za-z0-9_-]{16,96}$")
_MAX_GATE_LIFETIME_MS = 7 * 24 * 60 * 60 * 1000
_MAX_APPROVAL_LIFETIME_MS = 30 * 1000
_MAX_USED_APPROVALS = 512


class DesktopInputContractError(ValueError):
    """Malformed evidence or inconsistent execution-boundary configuration."""


class PhysicalGateVerifier(Protocol):
    def __call__(self, evidence: "PhysicalDesktopGateEvidence") -> bool:
        ...


class InputApprovalVerifier(Protocol):
    def __call__(self, approval: "DesktopInputApproval") -> bool:
        ...


def _timestamp(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DesktopInputContractError(f"{name} must be a non-negative integer")
    return value


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _action_projection(action: DesktopAction) -> dict[str, Any]:
    if not isinstance(action, DesktopAction):
        raise DesktopInputContractError("action must be DesktopAction")
    return {
        "kind": action.kind,
        "screen_token_sha256": hashlib.sha256(
            action.screen_token.encode("utf-8")
        ).hexdigest(),
        "x": action.x,
        "y": action.y,
        "button": action.button,
        "text_sha256": (
            hashlib.sha256(action.text.encode("utf-8")).hexdigest()
            if isinstance(action.text, str)
            else None
        ),
        "text_chars": len(action.text) if isinstance(action.text, str) else None,
    }


def action_sha256(action: DesktopAction) -> str:
    """Stable digest used by approval issuers without exposing text or tokens."""
    return hashlib.sha256(_canonical(_action_projection(action))).hexdigest()


def plan_token_sha256(plan_token: str) -> str:
    if not isinstance(plan_token, str) or not 32 <= len(plan_token) <= 16 * 1024:
        raise DesktopInputContractError("plan_token is invalid")
    return hashlib.sha256(plan_token.encode("utf-8")).hexdigest()


def session_sha256(session_id: str) -> str:
    if not isinstance(session_id, str) or not _ID.fullmatch(session_id):
        raise DesktopInputContractError("session_id has an invalid format")
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PhysicalDesktopGateEvidence:
    """Externally signed/verifiable result of the real Windows safety trial."""

    candidate_sha: str
    evidence_sha256: str
    tested_at_ms: int
    expires_at_ms: int
    low_integrity_verified: bool
    uipi_verified: bool
    kill_switch_verified: bool
    schema: str = PHYSICAL_GATE_SCHEMA
    production_activation: bool = False

    def __post_init__(self) -> None:
        if self.schema != PHYSICAL_GATE_SCHEMA:
            raise DesktopInputContractError("unsupported physical gate schema")
        if not isinstance(self.candidate_sha, str) or not _SHA1.fullmatch(
            self.candidate_sha
        ):
            raise DesktopInputContractError("physical gate candidate_sha is invalid")
        if not isinstance(self.evidence_sha256, str) or not _SHA256.fullmatch(
            self.evidence_sha256
        ):
            raise DesktopInputContractError("physical gate evidence digest is invalid")
        tested = _timestamp(self.tested_at_ms, "tested_at_ms")
        expires = _timestamp(self.expires_at_ms, "expires_at_ms")
        if not tested < expires <= tested + _MAX_GATE_LIFETIME_MS:
            raise DesktopInputContractError("physical gate lifetime is invalid")
        if not all(
            value is True
            for value in (
                self.low_integrity_verified,
                self.uipi_verified,
                self.kill_switch_verified,
            )
        ):
            raise DesktopInputContractError(
                "physical gate must prove low integrity, UIPI and kill switch"
            )
        if self.production_activation is not False:
            raise DesktopInputContractError("physical gate cannot activate production")


@dataclass(frozen=True)
class DesktopInputApproval:
    """Fresh human decision bound to one exact preview token and action."""

    confirmation_id: str
    plan_token_sha256: str
    action_sha256: str
    session_sha256: str
    issued_at_ms: int
    expires_at_ms: int
    nonce: str
    schema: str = INPUT_APPROVAL_SCHEMA
    origin: str = "local"
    production_activation: bool = False

    def __post_init__(self) -> None:
        if self.schema != INPUT_APPROVAL_SCHEMA:
            raise DesktopInputContractError("unsupported input approval schema")
        if not isinstance(self.confirmation_id, str) or not _ID.fullmatch(
            self.confirmation_id
        ):
            raise DesktopInputContractError("confirmation_id has an invalid format")
        for value, name in (
            (self.plan_token_sha256, "plan_token_sha256"),
            (self.action_sha256, "action_sha256"),
            (self.session_sha256, "session_sha256"),
        ):
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise DesktopInputContractError(f"{name} is invalid")
        issued = _timestamp(self.issued_at_ms, "issued_at_ms")
        expires = _timestamp(self.expires_at_ms, "expires_at_ms")
        if not issued < expires <= issued + _MAX_APPROVAL_LIFETIME_MS:
            raise DesktopInputContractError("input approval lifetime is invalid")
        if not isinstance(self.nonce, str) or not _NONCE.fullmatch(self.nonce):
            raise DesktopInputContractError("input approval nonce is invalid")
        if self.origin != "local":
            raise DesktopInputContractError("desktop input approval must be local")
        if self.production_activation is not False:
            raise DesktopInputContractError("input approval cannot activate production")


@dataclass(frozen=True)
class DesktopInputExecutionReceipt:
    kind: str
    candidate_sha: str
    plan_token_sha256: str
    action_sha256: str
    approval_nonce_sha256: str
    process: str
    title_sha256: str
    geometry: tuple[int, int, int, int]
    executed_at_ms: int
    click_point: tuple[int, int] | None = None
    text_chars: int | None = None
    text_sha256: str | None = None
    schema: str = INPUT_EXECUTION_SCHEMA
    production_activation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "kind": self.kind,
            "candidate_sha": self.candidate_sha,
            "plan_token_sha256": self.plan_token_sha256,
            "action_sha256": self.action_sha256,
            "approval_nonce_sha256": self.approval_nonce_sha256,
            "process": self.process,
            "title_sha256": self.title_sha256,
            "geometry": list(self.geometry),
            "executed_at_ms": self.executed_at_ms,
            "click_point": list(self.click_point) if self.click_point else None,
            "text_chars": self.text_chars,
            "text_sha256": self.text_sha256,
            "input_executed": True,
            "production_activation": False,
        }


class DesktopInputExecutionCoordinator:
    """Consume verified approvals and execute through the hardened Win32 backend."""

    def __init__(
        self,
        planner: DesktopActionPlanner,
        backend: Win32DesktopBackend,
        *,
        candidate_sha: str,
        physical_gate: PhysicalDesktopGateEvidence,
        physical_gate_verifier: PhysicalGateVerifier,
        approval_verifier: InputApprovalVerifier,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not isinstance(planner, DesktopActionPlanner):
            raise DesktopInputContractError("planner must be DesktopActionPlanner")
        if not isinstance(backend, Win32DesktopBackend):
            raise DesktopInputContractError("backend must be Win32DesktopBackend")
        if backend.input_enabled is not True:
            raise DesktopDenied(
                "Win32-input er dormant; fysisk low-integrity/UIPI-gate mangler"
            )
        if not isinstance(candidate_sha, str) or not _SHA1.fullmatch(candidate_sha):
            raise DesktopInputContractError("candidate_sha is invalid")
        if not isinstance(physical_gate, PhysicalDesktopGateEvidence):
            raise DesktopInputContractError("physical_gate evidence is invalid")
        if not callable(physical_gate_verifier) or not callable(approval_verifier):
            raise DesktopInputContractError("gate verifiers must be callable")
        if not callable(clock):
            raise DesktopInputContractError("clock must be callable")
        self.planner = planner
        self.backend = backend
        self.candidate_sha = candidate_sha
        self.physical_gate = physical_gate
        self.physical_gate_verifier = physical_gate_verifier
        self.approval_verifier = approval_verifier
        self.clock = clock
        self._lock = threading.RLock()
        self._used_approvals: dict[str, int] = {}

    def _now(self) -> tuple[float, int]:
        value = self.clock()
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise DesktopInputContractError("clock returned a non-numeric value")
        timestamp = float(value)
        return timestamp, int(timestamp * 1000)

    def _verify_physical_gate(self, now_ms: int) -> None:
        gate = self.physical_gate
        if gate.candidate_sha != self.candidate_sha:
            raise DesktopDenied("den fysiske desktop-gate gælder en anden kandidat")
        if not gate.tested_at_ms <= now_ms <= gate.expires_at_ms:
            raise DesktopDenied("den fysiske desktop-gate er ikke frisk")
        try:
            verified = self.physical_gate_verifier(gate)
        except Exception as exc:
            raise DesktopDenied("den fysiske desktop-gate kunne ikke verificeres") from exc
        if verified is not True:
            raise DesktopDenied("den fysiske desktop-gate er ikke verificeret")

    def _verify_approval(
        self,
        approval: DesktopInputApproval,
        *,
        plan_token: str,
        action: DesktopAction,
        session_id: str,
        now_ms: int,
    ) -> None:
        if not isinstance(approval, DesktopInputApproval):
            raise DesktopDenied("desktop-input mangler en gyldig menneskegodkendelse")
        if approval.plan_token_sha256 != plan_token_sha256(plan_token):
            raise DesktopDenied("menneskegodkendelsen gælder et andet preview")
        if approval.action_sha256 != action_sha256(action):
            raise DesktopDenied("menneskegodkendelsen gælder en anden handling")
        if approval.session_sha256 != session_sha256(session_id):
            raise DesktopDenied("menneskegodkendelsen gælder en anden session")
        if not approval.issued_at_ms <= now_ms <= approval.expires_at_ms:
            raise DesktopDenied("menneskegodkendelsen er udløbet")
        try:
            verified = self.approval_verifier(approval)
        except Exception as exc:
            raise DesktopDenied("menneskegodkendelsen kunne ikke verificeres") from exc
        if verified is not True:
            raise DesktopDenied("menneskegodkendelsen er ikke verificeret")

    def _spend_approval(self, approval: DesktopInputApproval, now_ms: int) -> None:
        with self._lock:
            self._used_approvals = {
                nonce: expiry
                for nonce, expiry in self._used_approvals.items()
                if expiry >= now_ms
            }
            if approval.nonce in self._used_approvals:
                raise DesktopDenied("menneskegodkendelsen er allerede brugt")
            if len(self._used_approvals) >= _MAX_USED_APPROVALS:
                oldest = min(self._used_approvals, key=self._used_approvals.get)
                self._used_approvals.pop(oldest, None)
            # Spend before capture/consume. A changed desktop or native failure must
            # never turn one human click into a reusable execution authorization.
            self._used_approvals[approval.nonce] = approval.expires_at_ms

    def execute(
        self,
        plan_token: str,
        expected_action: DesktopAction,
        approval: DesktopInputApproval,
        *,
        session_id: str,
        origin: str = "local",
    ) -> DesktopInputExecutionReceipt:
        if origin != "local":
            raise DesktopDenied("desktop-input må kun udføres fra en lokal model")
        timestamp, now_ms = self._now()
        self._verify_physical_gate(now_ms)
        self._verify_approval(
            approval,
            plan_token=plan_token,
            action=expected_action,
            session_id=session_id,
            now_ms=now_ms,
        )
        self._spend_approval(approval, now_ms)

        # Fresh capture is mandatory immediately before the signed plan is spent.
        current = self.backend.capture_foreground()
        authorized = self.planner.consume(
            plan_token,
            expected_action,
            current,
            session_id=session_id,
            origin="local",
            cloud_consent=False,
            now=timestamp,
        )
        self.backend.perform(authorized)
        return self._receipt(
            plan_token,
            expected_action,
            approval,
            authorized.target,
            authorized.absolute_x,
            authorized.absolute_y,
            now_ms,
        )

    def _receipt(
        self,
        plan_token: str,
        action: DesktopAction,
        approval: DesktopInputApproval,
        target: WindowTarget,
        absolute_x: int | None,
        absolute_y: int | None,
        now_ms: int,
    ) -> DesktopInputExecutionReceipt:
        projection = _action_projection(action)
        return DesktopInputExecutionReceipt(
            kind=action.kind,
            candidate_sha=self.candidate_sha,
            plan_token_sha256=plan_token_sha256(plan_token),
            action_sha256=action_sha256(action),
            approval_nonce_sha256=hashlib.sha256(
                approval.nonce.encode("utf-8")
            ).hexdigest(),
            process=target.process,
            title_sha256=hashlib.sha256(target.title.encode("utf-8")).hexdigest(),
            geometry=(target.left, target.top, target.width, target.height),
            executed_at_ms=now_ms,
            click_point=(absolute_x, absolute_y)
            if absolute_x is not None and absolute_y is not None
            else None,
            text_chars=projection["text_chars"],
            text_sha256=projection["text_sha256"],
        )


__all__ = [
    "DesktopInputApproval",
    "DesktopInputContractError",
    "DesktopInputExecutionCoordinator",
    "DesktopInputExecutionReceipt",
    "INPUT_APPROVAL_SCHEMA",
    "INPUT_EXECUTION_SCHEMA",
    "PHYSICAL_GATE_SCHEMA",
    "PhysicalDesktopGateEvidence",
    "action_sha256",
    "plan_token_sha256",
    "session_sha256",
]
