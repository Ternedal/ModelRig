"""Canonical bounded-output result for one freshly verified Tier-A launch."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

RESULT_SCHEMA = "kaliv-development-tier-a-execution-result/v1"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_COMMAND_ID = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_MAX_OUTPUT_BYTES = 100_000_000


class TierAResultError(ValueError):
    """A Tier-A execution result is malformed or internally inconsistent."""


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _hex(name: str, value: Any, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise TierAResultError(f"Tier-A result {name} is invalid")
    return value


def _integer(name: str, value: Any, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise TierAResultError(f"Tier-A result {name} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class TierAOutputStream:
    """Full stream identity plus an exact bounded prefix."""

    captured: bytes
    sha256: str
    total_bytes: int
    truncated: bool

    def __post_init__(self) -> None:
        if not isinstance(self.captured, bytes):
            raise TierAResultError("Tier-A captured output must be bytes")
        _hex("stream sha256", self.sha256, _HEX64)
        _integer("stream total_bytes", self.total_bytes, 0, 2**63 - 1)
        if self.total_bytes < len(self.captured):
            raise TierAResultError("Tier-A stream prefix exceeds the total byte count")
        if not isinstance(self.truncated, bool):
            raise TierAResultError("Tier-A stream truncation flag is invalid")
        if self.truncated != (self.total_bytes > len(self.captured)):
            raise TierAResultError(
                "Tier-A stream truncation flag does not match its byte counts"
            )
        if not self.truncated and hashlib.sha256(self.captured).hexdigest() != self.sha256:
            raise TierAResultError("complete Tier-A stream bytes do not match the hash")

    @classmethod
    def from_capture(cls, value: Any) -> "TierAOutputStream":
        try:
            captured = value.captured
            sha256 = value.sha256
            total_bytes = value.total_bytes
            truncated = value.truncated
        except AttributeError as exc:
            raise TierAResultError("native Tier-A capture result is invalid") from exc
        return cls(
            captured=captured,
            sha256=sha256,
            total_bytes=total_bytes,
            truncated=truncated,
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "TierAOutputStream":
        if not isinstance(value, Mapping):
            raise TierAResultError("Tier-A output stream must be an object")
        fields = {
            "captured_base64",
            "captured_bytes",
            "sha256",
            "total_bytes",
            "truncated",
        }
        if set(value) != fields:
            raise TierAResultError("Tier-A output stream fields mismatch")
        encoded = value["captured_base64"]
        if not isinstance(encoded, str):
            raise TierAResultError("Tier-A output stream base64 must be a string")
        try:
            captured = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError) as exc:
            raise TierAResultError("Tier-A output stream base64 is invalid") from exc
        captured_bytes = _integer(
            "stream captured_bytes",
            value["captured_bytes"],
            0,
            _MAX_OUTPUT_BYTES,
        )
        if captured_bytes != len(captured):
            raise TierAResultError(
                "Tier-A output stream captured byte count does not match its bytes"
            )
        return cls(
            captured=captured,
            sha256=value["sha256"],
            total_bytes=value["total_bytes"],
            truncated=value["truncated"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "captured_base64": base64.b64encode(self.captured).decode("ascii"),
            "captured_bytes": len(self.captured),
            "sha256": self.sha256,
            "total_bytes": self.total_bytes,
            "truncated": self.truncated,
        }


@dataclass(frozen=True, slots=True)
class TierAExecutionResult:
    task_id: str
    task_sha256: str
    base_sha: str
    command_id: str
    plan_sha256: str
    lease_sha256: str
    signed_report_sha256: str
    returncode: int
    duration_ms: int
    timed_out: bool
    max_output_bytes: int
    stdout: TierAOutputStream
    stderr: TierAOutputStream
    output_bytes: int
    captured_output_bytes: int
    output_truncated: bool
    passed: bool
    schema: str = RESULT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != RESULT_SCHEMA:
            raise TierAResultError("unsupported Tier-A execution result schema")
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise TierAResultError("Tier-A result task id is invalid")
        if not isinstance(self.command_id, str) or _COMMAND_ID.fullmatch(self.command_id) is None:
            raise TierAResultError("Tier-A result command id is invalid")
        _hex("task_sha256", self.task_sha256, _HEX64)
        _hex("base_sha", self.base_sha, _HEX40)
        _hex("plan_sha256", self.plan_sha256, _HEX64)
        _hex("lease_sha256", self.lease_sha256, _HEX64)
        _hex("signed_report_sha256", self.signed_report_sha256, _HEX64)
        _integer("returncode", self.returncode, 0, 0xFFFFFFFF)
        _integer("duration_ms", self.duration_ms, 0, 2**63 - 1)
        _integer(
            "max_output_bytes",
            self.max_output_bytes,
            1_024,
            _MAX_OUTPUT_BYTES,
        )
        if not isinstance(self.timed_out, bool):
            raise TierAResultError("Tier-A result timed_out flag is invalid")
        if not isinstance(self.stdout, TierAOutputStream) or not isinstance(
            self.stderr, TierAOutputStream
        ):
            raise TierAResultError("Tier-A result streams are invalid")
        expected_output = self.stdout.total_bytes + self.stderr.total_bytes
        expected_captured = len(self.stdout.captured) + len(self.stderr.captured)
        if self.output_bytes != expected_output:
            raise TierAResultError("Tier-A result output byte count is inconsistent")
        if self.captured_output_bytes != expected_captured:
            raise TierAResultError(
                "Tier-A result captured output byte count is inconsistent"
            )
        if not 0 <= self.captured_output_bytes <= self.max_output_bytes:
            raise TierAResultError("Tier-A result exceeded its captured-output budget")
        expected_truncated = self.stdout.truncated or self.stderr.truncated
        if self.output_truncated != expected_truncated:
            raise TierAResultError("Tier-A result truncation flag is inconsistent")
        if not isinstance(self.output_truncated, bool) or not isinstance(self.passed, bool):
            raise TierAResultError("Tier-A result status flags are invalid")
        expected_passed = not self.timed_out and self.returncode == 0
        if self.passed != expected_passed:
            raise TierAResultError("Tier-A result passed flag is inconsistent")

    @classmethod
    def create(
        cls,
        *,
        task_id: str,
        task_sha256: str,
        base_sha: str,
        command_id: str,
        plan_sha256: str,
        lease_sha256: str,
        signed_report_sha256: str,
        returncode: int,
        duration_ms: int,
        timed_out: bool,
        max_output_bytes: int,
        stdout: TierAOutputStream,
        stderr: TierAOutputStream,
    ) -> "TierAExecutionResult":
        return cls(
            task_id=task_id,
            task_sha256=task_sha256,
            base_sha=base_sha,
            command_id=command_id,
            plan_sha256=plan_sha256,
            lease_sha256=lease_sha256,
            signed_report_sha256=signed_report_sha256,
            returncode=returncode,
            duration_ms=duration_ms,
            timed_out=timed_out,
            max_output_bytes=max_output_bytes,
            stdout=stdout,
            stderr=stderr,
            output_bytes=stdout.total_bytes + stderr.total_bytes,
            captured_output_bytes=len(stdout.captured) + len(stderr.captured),
            output_truncated=stdout.truncated or stderr.truncated,
            passed=not timed_out and returncode == 0,
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "TierAExecutionResult":
        if not isinstance(value, Mapping):
            raise TierAResultError("Tier-A execution result must be an object")
        fields = {
            "schema",
            "task_id",
            "task_sha256",
            "base_sha",
            "command_id",
            "plan_sha256",
            "lease_sha256",
            "signed_report_sha256",
            "returncode",
            "duration_ms",
            "timed_out",
            "max_output_bytes",
            "stdout",
            "stderr",
            "output_bytes",
            "captured_output_bytes",
            "output_truncated",
            "passed",
        }
        if set(value) != fields:
            raise TierAResultError("Tier-A execution result fields mismatch")
        return cls(
            schema=value["schema"],
            task_id=value["task_id"],
            task_sha256=value["task_sha256"],
            base_sha=value["base_sha"],
            command_id=value["command_id"],
            plan_sha256=value["plan_sha256"],
            lease_sha256=value["lease_sha256"],
            signed_report_sha256=value["signed_report_sha256"],
            returncode=value["returncode"],
            duration_ms=value["duration_ms"],
            timed_out=value["timed_out"],
            max_output_bytes=value["max_output_bytes"],
            stdout=TierAOutputStream.from_mapping(value["stdout"]),
            stderr=TierAOutputStream.from_mapping(value["stderr"]),
            output_bytes=value["output_bytes"],
            captured_output_bytes=value["captured_output_bytes"],
            output_truncated=value["output_truncated"],
            passed=value["passed"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "base_sha": self.base_sha,
            "command_id": self.command_id,
            "plan_sha256": self.plan_sha256,
            "lease_sha256": self.lease_sha256,
            "signed_report_sha256": self.signed_report_sha256,
            "returncode": self.returncode,
            "duration_ms": self.duration_ms,
            "timed_out": self.timed_out,
            "max_output_bytes": self.max_output_bytes,
            "stdout": self.stdout.to_dict(),
            "stderr": self.stderr.to_dict(),
            "output_bytes": self.output_bytes,
            "captured_output_bytes": self.captured_output_bytes,
            "output_truncated": self.output_truncated,
            "passed": self.passed,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()
