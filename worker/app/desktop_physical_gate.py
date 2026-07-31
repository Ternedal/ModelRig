"""Dormant evidence contract for the physical Windows Computer Use gate.

The real probe runner lives outside the worker and must execute on an interactive
Windows rig.  This module only parses and verifies its bounded report, binds the
result to one exact candidate commit, and converts it into the evidence object
required by :mod:`desktop_input_execution`.

It registers no tool, reads no environment variables and performs no native or
network I/O.  A report is green only when all three independent physical probes
are green: low-integrity launch, UIPI positive/negative control, and Job Object
kill-switch termination of a process tree.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .desktop_input_execution import PhysicalDesktopGateEvidence

REPORT_SCHEMA = "kaliv-desktop-physical-gate-report/v1"
PROBE_SCHEMA = "kaliv-desktop-physical-gate-probe/v1"
_MAX_REPORT_BYTES = 1_000_000
_MAX_RUN_MS = 15 * 60 * 1000
_MAX_KILL_MS = 10_000
_LOW_RID = 0x1000
_MEDIUM_RID = 0x2000
_HIGH_RID = 0x3000
_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RUN_ID = re.compile(r"^dpg_[a-f0-9]{24}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9._-]+)?$")


class DesktopPhysicalGateError(ValueError):
    """Malformed, stale, mismatched or incomplete physical evidence."""


def _integer(value: Any, name: str, minimum: int = 0, maximum: int = 2**63 - 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise DesktopPhysicalGateError(f"{name} is invalid")
    return value


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise DesktopPhysicalGateError(f"{name} must be boolean")
    return value


def _digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise DesktopPhysicalGateError(f"{name} is invalid")
    return value


def _exact(value: Any, keys: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise DesktopPhysicalGateError(f"{name} has an invalid shape")
    return value


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


@dataclass(frozen=True)
class LowIntegrityProbe:
    status: str
    parent_integrity_rid: int
    child_integrity_rid: int
    child_pid: int
    token_restricted: bool
    schema: str = PROBE_SCHEMA

    @classmethod
    def from_dict(cls, raw: Any) -> "LowIntegrityProbe":
        value = _exact(
            raw,
            {
                "schema",
                "status",
                "parent_integrity_rid",
                "child_integrity_rid",
                "child_pid",
                "token_restricted",
            },
            "low_integrity probe",
        )
        result = cls(**value)
        if result.schema != PROBE_SCHEMA or result.status != "passed":
            raise DesktopPhysicalGateError("low-integrity probe did not pass")
        parent = _integer(result.parent_integrity_rid, "parent_integrity_rid", _MEDIUM_RID)
        child = _integer(result.child_integrity_rid, "child_integrity_rid", _LOW_RID, _LOW_RID)
        _integer(result.child_pid, "child_pid", 1, 2**31 - 1)
        if parent <= child or _bool(result.token_restricted, "token_restricted") is not True:
            raise DesktopPhysicalGateError("low-integrity probe lacks a restricted lower token")
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "status": self.status,
            "parent_integrity_rid": self.parent_integrity_rid,
            "child_integrity_rid": self.child_integrity_rid,
            "child_pid": self.child_pid,
            "token_restricted": self.token_restricted,
        }


@dataclass(frozen=True)
class UipiProbe:
    status: str
    sender_integrity_rid: int
    control_target_integrity_rid: int
    elevated_target_integrity_rid: int
    control_received: bool
    elevated_received: bool
    canary_sha256: str
    schema: str = PROBE_SCHEMA

    @classmethod
    def from_dict(cls, raw: Any) -> "UipiProbe":
        value = _exact(
            raw,
            {
                "schema",
                "status",
                "sender_integrity_rid",
                "control_target_integrity_rid",
                "elevated_target_integrity_rid",
                "control_received",
                "elevated_received",
                "canary_sha256",
            },
            "UIPI probe",
        )
        result = cls(**value)
        if result.schema != PROBE_SCHEMA or result.status != "passed":
            raise DesktopPhysicalGateError("UIPI probe did not pass")
        sender = _integer(result.sender_integrity_rid, "sender_integrity_rid", _LOW_RID, _LOW_RID)
        control = _integer(
            result.control_target_integrity_rid,
            "control_target_integrity_rid",
            _LOW_RID,
            _LOW_RID,
        )
        elevated = _integer(
            result.elevated_target_integrity_rid,
            "elevated_target_integrity_rid",
            _HIGH_RID,
        )
        if sender != control or elevated <= sender:
            raise DesktopPhysicalGateError("UIPI probe integrity levels are inconsistent")
        if _bool(result.control_received, "control_received") is not True:
            raise DesktopPhysicalGateError("UIPI positive control did not receive input")
        if _bool(result.elevated_received, "elevated_received") is not False:
            raise DesktopPhysicalGateError("elevated target received low-integrity input")
        _digest(result.canary_sha256, "canary_sha256")
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "status": self.status,
            "sender_integrity_rid": self.sender_integrity_rid,
            "control_target_integrity_rid": self.control_target_integrity_rid,
            "elevated_target_integrity_rid": self.elevated_target_integrity_rid,
            "control_received": self.control_received,
            "elevated_received": self.elevated_received,
            "canary_sha256": self.canary_sha256,
        }


@dataclass(frozen=True)
class KillSwitchProbe:
    status: str
    job_kill_on_close: bool
    child_pid: int
    grandchild_pid: int
    process_tree_terminated: bool
    termination_ms: int
    heartbeat_sha256: str
    schema: str = PROBE_SCHEMA

    @classmethod
    def from_dict(cls, raw: Any) -> "KillSwitchProbe":
        value = _exact(
            raw,
            {
                "schema",
                "status",
                "job_kill_on_close",
                "child_pid",
                "grandchild_pid",
                "process_tree_terminated",
                "termination_ms",
                "heartbeat_sha256",
            },
            "kill-switch probe",
        )
        result = cls(**value)
        if result.schema != PROBE_SCHEMA or result.status != "passed":
            raise DesktopPhysicalGateError("kill-switch probe did not pass")
        if _bool(result.job_kill_on_close, "job_kill_on_close") is not True:
            raise DesktopPhysicalGateError("Job Object kill-on-close was not enabled")
        if _bool(result.process_tree_terminated, "process_tree_terminated") is not True:
            raise DesktopPhysicalGateError("kill switch did not terminate the process tree")
        child = _integer(result.child_pid, "child_pid", 1, 2**31 - 1)
        grandchild = _integer(result.grandchild_pid, "grandchild_pid", 1, 2**31 - 1)
        if child == grandchild:
            raise DesktopPhysicalGateError("kill-switch probe requires a real grandchild")
        _integer(result.termination_ms, "termination_ms", 0, _MAX_KILL_MS)
        _digest(result.heartbeat_sha256, "heartbeat_sha256")
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "status": self.status,
            "job_kill_on_close": self.job_kill_on_close,
            "child_pid": self.child_pid,
            "grandchild_pid": self.grandchild_pid,
            "process_tree_terminated": self.process_tree_terminated,
            "termination_ms": self.termination_ms,
            "heartbeat_sha256": self.heartbeat_sha256,
        }


@dataclass(frozen=True)
class DesktopPhysicalGateReport:
    candidate_sha: str
    version: str
    run_id: str
    started_at_ms: int
    finished_at_ms: int
    windows_build: str
    architecture: str
    low_integrity: LowIntegrityProbe
    uipi: UipiProbe
    kill_switch: KillSwitchProbe
    schema: str = REPORT_SCHEMA
    production_activation: bool = False

    @classmethod
    def from_dict(cls, raw: Any) -> "DesktopPhysicalGateReport":
        value = _exact(
            raw,
            {
                "schema",
                "candidate_sha",
                "version",
                "run_id",
                "started_at_ms",
                "finished_at_ms",
                "host",
                "probes",
                "production_activation",
            },
            "physical gate report",
        )
        if value["schema"] != REPORT_SCHEMA:
            raise DesktopPhysicalGateError("unsupported physical gate report schema")
        if value["production_activation"] is not False:
            raise DesktopPhysicalGateError("physical report cannot activate production")
        if not isinstance(value["candidate_sha"], str) or not _SHA1.fullmatch(
            value["candidate_sha"]
        ):
            raise DesktopPhysicalGateError("candidate_sha is invalid")
        if not isinstance(value["version"], str) or not _VERSION.fullmatch(value["version"]):
            raise DesktopPhysicalGateError("version is invalid")
        if not isinstance(value["run_id"], str) or not _RUN_ID.fullmatch(value["run_id"]):
            raise DesktopPhysicalGateError("run_id is invalid")
        started = _integer(value["started_at_ms"], "started_at_ms")
        finished = _integer(value["finished_at_ms"], "finished_at_ms")
        if not started < finished <= started + _MAX_RUN_MS:
            raise DesktopPhysicalGateError("physical gate run duration is invalid")
        host = _exact(value["host"], {"os", "windows_build", "architecture"}, "host")
        if host["os"] != "Windows":
            raise DesktopPhysicalGateError("physical gate must run on Windows")
        for key in ("windows_build", "architecture"):
            if not isinstance(host[key], str) or not host[key].strip() or len(host[key]) > 128:
                raise DesktopPhysicalGateError(f"host {key} is invalid")
        probes = _exact(value["probes"], {"low_integrity", "uipi", "kill_switch"}, "probes")
        return cls(
            candidate_sha=value["candidate_sha"],
            version=value["version"],
            run_id=value["run_id"],
            started_at_ms=started,
            finished_at_ms=finished,
            windows_build=host["windows_build"],
            architecture=host["architecture"],
            low_integrity=LowIntegrityProbe.from_dict(probes["low_integrity"]),
            uipi=UipiProbe.from_dict(probes["uipi"]),
            kill_switch=KillSwitchProbe.from_dict(probes["kill_switch"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "candidate_sha": self.candidate_sha,
            "version": self.version,
            "run_id": self.run_id,
            "started_at_ms": self.started_at_ms,
            "finished_at_ms": self.finished_at_ms,
            "host": {
                "os": "Windows",
                "windows_build": self.windows_build,
                "architecture": self.architecture,
            },
            "probes": {
                "low_integrity": self.low_integrity.to_dict(),
                "uipi": self.uipi.to_dict(),
                "kill_switch": self.kill_switch.to_dict(),
            },
            "production_activation": False,
        }

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()

    def evidence(self, *, expires_at_ms: int) -> PhysicalDesktopGateEvidence:
        expiry = _integer(expires_at_ms, "expires_at_ms")
        if not self.finished_at_ms < expiry <= self.finished_at_ms + 7 * 24 * 60 * 60 * 1000:
            raise DesktopPhysicalGateError("physical evidence expiry is invalid")
        return PhysicalDesktopGateEvidence(
            candidate_sha=self.candidate_sha,
            evidence_sha256=self.sha256,
            tested_at_ms=self.finished_at_ms,
            expires_at_ms=expiry,
            low_integrity_verified=True,
            uipi_verified=True,
            kill_switch_verified=True,
        )


def load_physical_gate_report(path: str | os.PathLike[str]) -> DesktopPhysicalGateReport:
    report_path = Path(path).expanduser()
    if not report_path.is_absolute():
        raise DesktopPhysicalGateError("physical gate report path must be absolute")
    try:
        resolved = report_path.resolve(strict=True)
        stat = resolved.stat()
    except OSError as exc:
        raise DesktopPhysicalGateError("physical gate report cannot be opened") from exc
    if not resolved.is_file() or stat.st_size <= 0 or stat.st_size > _MAX_REPORT_BYTES:
        raise DesktopPhysicalGateError("physical gate report size is invalid")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DesktopPhysicalGateError("physical gate report is not valid JSON") from exc
    return DesktopPhysicalGateReport.from_dict(value)


class PhysicalGateFileVerifier:
    """Verify one exact local report file against candidate and digest binding."""

    def __init__(
        self,
        report_path: str | os.PathLike[str],
        *,
        candidate_sha: str,
        report_sha256: str,
    ) -> None:
        path = Path(report_path).expanduser()
        if not path.is_absolute():
            raise DesktopPhysicalGateError("physical gate report path must be absolute")
        if not isinstance(candidate_sha, str) or not _SHA1.fullmatch(candidate_sha):
            raise DesktopPhysicalGateError("candidate_sha is invalid")
        _digest(report_sha256, "report_sha256")
        self.report_path = path
        self.candidate_sha = candidate_sha
        self.report_sha256 = report_sha256

    def __call__(self, evidence: PhysicalDesktopGateEvidence) -> bool:
        if not isinstance(evidence, PhysicalDesktopGateEvidence):
            return False
        try:
            report = load_physical_gate_report(self.report_path)
        except DesktopPhysicalGateError:
            return False
        return bool(
            report.candidate_sha == self.candidate_sha == evidence.candidate_sha
            and report.sha256 == self.report_sha256 == evidence.evidence_sha256
            and report.finished_at_ms == evidence.tested_at_ms
            and evidence.low_integrity_verified is True
            and evidence.uipi_verified is True
            and evidence.kill_switch_verified is True
            and evidence.production_activation is False
        )


__all__ = [
    "DesktopPhysicalGateError",
    "DesktopPhysicalGateReport",
    "KillSwitchProbe",
    "LowIntegrityProbe",
    "PhysicalGateFileVerifier",
    "REPORT_SCHEMA",
    "PROBE_SCHEMA",
    "UipiProbe",
    "load_physical_gate_report",
]
