"""Signed physical Windows-isolation evidence and fail-closed verification.

DC-L04 defines evidence contracts only. It does not create Windows containment,
activate catalog execution, or grant remote publication authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from .catalog import (
    ATTESTATION_SCHEMA,
    CatalogError,
    IsolationAttestation,
    IsolationBoundary,
    NetworkMode,
)
from .durable_publication import DurablePublicationError, create_once_file

REPORT_SCHEMA = "kaliv-windows-isolation-physical-report/v1"
SIGNED_REPORT_SCHEMA = "kaliv-windows-isolation-signed-report/v1"
SIGNATURE_ALGORITHM = "hmac-sha256"
_MAX_REPORT_BYTES = 2_000_000
_MAX_KEY_BYTES = 4096
_REPARSE_POINT = 0x400
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_UTC_SECONDS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PhysicalIsolationError(CatalogError):
    """Physical isolation evidence is malformed, stale, or untrusted."""


class ProbeName(StrEnum):
    RESTRICTED_TOKEN = "restricted_token"
    WORKSPACE_ALLOWED = "workspace_allowed"
    WORKSPACE_ESCAPE_DENIED = "workspace_escape_denied"
    NETWORK_DENIED = "network_denied"
    PROCESS_TREE_TIMEOUT_CLEANUP = "process_tree_timeout_cleanup"
    PROCESS_TREE_CRASH_CLEANUP = "process_tree_crash_cleanup"
    CANCEL_CLEANUP = "cancel_cleanup"
    REBOOT_CLEANUP = "reboot_cleanup"
    MEMORY_LIMIT_ENFORCED = "memory_limit_enforced"
    PROCESS_LIMIT_ENFORCED = "process_limit_enforced"
    EXISTING_TOOLS_COMPATIBLE = "existing_tools_compatible"


REQUIRED_PROBES = tuple(ProbeName)


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strict_object(value: Any, *, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PhysicalIsolationError(f"{name} must be an object")
    if set(value) != fields:
        raise PhysicalIsolationError(f"{name} fields mismatch")
    return value


def _clean_text(value: Any, *, name: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\x00" in value
        or len(value.encode("utf-8")) > maximum
    ):
        raise PhysicalIsolationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    text = _clean_text(value, name=name, maximum=20)
    if _UTC_SECONDS.fullmatch(text) is None:
        raise PhysicalIsolationError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PhysicalIsolationError(f"{name} is not a valid timestamp") from exc


def _absolute_path(path: Path, *, name: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise PhysicalIsolationError(f"{name} must be absolute")
    return candidate


def _is_link_like(path: Path) -> bool:
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise PhysicalIsolationError(f"path component cannot be inspected: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        return True
    if getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT:
        return True
    junction = getattr(path, "is_junction", None)
    if callable(junction):
        try:
            if junction():
                return True
        except OSError as exc:
            raise PhysicalIsolationError(
                f"path junction state cannot be inspected: {path}"
            ) from exc
    return False


def _assert_link_free(path: Path, *, name: str) -> None:
    candidate = _absolute_path(path, name=name)
    chain = tuple(reversed(candidate.parents)) + (candidate,)
    for component in chain:
        if _is_link_like(component):
            raise PhysicalIsolationError(f"{name} contains a link or reparse point")


def _identity(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        getattr(metadata, "st_mtime_ns", int(metadata.st_mtime * 1_000_000_000)),
        getattr(metadata, "st_ctime_ns", int(metadata.st_ctime * 1_000_000_000)),
        stat.S_IFMT(metadata.st_mode),
    )


def _stable_regular_read(
    path: Path,
    *,
    maximum: int,
    name: str,
    allow_empty: bool = False,
) -> tuple[bytes, os.stat_result]:
    if (
        isinstance(maximum, bool)
        or not isinstance(maximum, int)
        or maximum < 1
        or maximum > 16_000_000
    ):
        raise PhysicalIsolationError(f"{name} read bound is invalid")
    candidate = _absolute_path(path, name=name)
    _assert_link_free(candidate, name=name)

    flags = os.O_RDONLY
    for flag_name in ("O_CLOEXEC", "O_NOFOLLOW", "O_NONBLOCK", "O_BINARY", "O_NOINHERIT"):
        flags |= getattr(os, flag_name, 0)
    try:
        descriptor = os.open(os.fspath(candidate), flags)
    except OSError as exc:
        raise PhysicalIsolationError(f"{name} cannot be opened safely") from exc

    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise PhysicalIsolationError(f"{name} must be a regular file")
        if before.st_size < (0 if allow_empty else 1) or before.st_size > maximum:
            raise PhysicalIsolationError(f"{name} is outside its size bound")

        chunks: list[bytes] = []
        total = 0
        while True:
            try:
                chunk = os.read(descriptor, min(1_048_576, maximum + 1 - total))
            except BlockingIOError as exc:
                raise PhysicalIsolationError(f"{name} could not be read deterministically") from exc
            if not chunk:
                break
            total += len(chunk)
            if total > maximum:
                raise PhysicalIsolationError(f"{name} is outside its size bound")
            chunks.append(chunk)

        after = os.fstat(descriptor)
        if _identity(before) != _identity(after) or total != before.st_size:
            raise PhysicalIsolationError(f"{name} changed while it was read")

        _assert_link_free(candidate, name=name)
        try:
            observed = os.stat(candidate, follow_symlinks=False)
        except OSError as exc:
            raise PhysicalIsolationError(f"{name} path disappeared after reading") from exc
        if not stat.S_ISREG(observed.st_mode) or _identity(observed) != _identity(before):
            raise PhysicalIsolationError(f"{name} path changed while it was read")
        return b"".join(chunks), before
    finally:
        os.close(descriptor)


def _snapshot_attestation(value: Any) -> IsolationAttestation:
    if not isinstance(value, IsolationAttestation) or value.schema != ATTESTATION_SCHEMA:
        raise PhysicalIsolationError(
            "physical verifier requires a valid isolation attestation"
        )
    try:
        return IsolationAttestation.from_mapping(value.to_dict())
    except (CatalogError, AttributeError, TypeError, ValueError) as exc:
        raise PhysicalIsolationError("isolation attestation snapshot is invalid") from exc


@dataclass(frozen=True, slots=True)
class PhysicalProbeResult:
    name: ProbeName
    passed: bool
    receipt_sha256: str
    detail: str
    observed_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, ProbeName):
            raise PhysicalIsolationError("probe name is invalid")
        if not isinstance(self.passed, bool):
            raise PhysicalIsolationError("probe result must be boolean")
        if (
            not isinstance(self.receipt_sha256, str)
            or _HEX64.fullmatch(self.receipt_sha256) is None
        ):
            raise PhysicalIsolationError("probe receipt hash is invalid")
        _clean_text(self.detail, name="probe.detail", maximum=2048)
        _utc(self.observed_at, name="probe.observed_at")

    @classmethod
    def from_mapping(cls, value: Any) -> "PhysicalProbeResult":
        data = _strict_object(
            value,
            fields={"name", "passed", "receipt_sha256", "detail", "observed_at"},
            name="probe",
        )
        try:
            name = ProbeName(data["name"])
        except (TypeError, ValueError) as exc:
            raise PhysicalIsolationError("probe name is unsupported") from exc
        return cls(
            name=name,
            passed=data["passed"],
            receipt_sha256=data["receipt_sha256"],
            detail=data["detail"],
            observed_at=data["observed_at"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name.value,
            "passed": self.passed,
            "receipt_sha256": self.receipt_sha256,
            "detail": self.detail,
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True, slots=True)
class WindowsIsolationPhysicalReport:
    report_id: str
    task_id: str
    task_sha256: str
    repository: str
    base_sha: str
    catalog_sha256: str
    toolchain_sha256: str
    rig_id: str
    rig_fingerprint_sha256: str
    candidate_version: str
    windows_build: str
    toolhost_sha256: str
    workspace_root_sha256: str
    collected_by: str
    approved_by: str
    started_at: str
    completed_at: str
    boot_marker_before_sha256: str
    boot_marker_after_sha256: str
    boundary: IsolationBoundary
    network_mode: NetworkMode
    probes: tuple[PhysicalProbeResult, ...]
    schema: str = REPORT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != REPORT_SCHEMA:
            raise PhysicalIsolationError("unsupported physical report schema")
        if not isinstance(self.report_id, str) or _IDENTIFIER.fullmatch(self.report_id) is None:
            raise PhysicalIsolationError("physical report id is invalid")
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise PhysicalIsolationError("physical report task id is invalid")
        if self.repository != "Ternedal/ModelRig":
            raise PhysicalIsolationError("physical report repository is invalid")
        for name, value, pattern in (
            ("task_sha256", self.task_sha256, _HEX64),
            ("base_sha", self.base_sha, _HEX40),
            ("catalog_sha256", self.catalog_sha256, _HEX64),
            ("toolchain_sha256", self.toolchain_sha256, _HEX64),
            ("rig_fingerprint_sha256", self.rig_fingerprint_sha256, _HEX64),
            ("toolhost_sha256", self.toolhost_sha256, _HEX64),
            ("workspace_root_sha256", self.workspace_root_sha256, _HEX64),
            ("boot_marker_before_sha256", self.boot_marker_before_sha256, _HEX64),
            ("boot_marker_after_sha256", self.boot_marker_after_sha256, _HEX64),
        ):
            if not isinstance(value, str) or pattern.fullmatch(value) is None:
                raise PhysicalIsolationError(f"{name} is invalid")
        if self.boot_marker_before_sha256 == self.boot_marker_after_sha256:
            raise PhysicalIsolationError("physical report does not prove a reboot boundary")
        for name, value, maximum in (
            ("rig_id", self.rig_id, 128),
            ("candidate_version", self.candidate_version, 64),
            ("windows_build", self.windows_build, 256),
            ("collected_by", self.collected_by, 128),
            ("approved_by", self.approved_by, 128),
        ):
            _clean_text(value, name=name, maximum=maximum)
        if self.collected_by == self.approved_by:
            raise PhysicalIsolationError("collector and approver must be different actors")

        started = _utc(self.started_at, name="started_at")
        completed = _utc(self.completed_at, name="completed_at")
        if completed <= started or completed - started > timedelta(days=2):
            raise PhysicalIsolationError("physical report time window is invalid")
        if (
            not isinstance(self.boundary, IsolationBoundary)
            or self.boundary is not IsolationBoundary.OS_ISOLATED
        ):
            raise PhysicalIsolationError("physical report boundary is not OS isolated")
        if (
            not isinstance(self.network_mode, NetworkMode)
            or self.network_mode is not NetworkMode.DENY
        ):
            raise PhysicalIsolationError("physical report network mode is not deny")
        if not isinstance(self.probes, tuple):
            raise PhysicalIsolationError("physical probes must be an immutable tuple")
        if any(not isinstance(probe, PhysicalProbeResult) for probe in self.probes):
            raise PhysicalIsolationError("physical probes contain an invalid result")
        names = tuple(probe.name for probe in self.probes)
        if len(names) != len(set(names)):
            raise PhysicalIsolationError("physical report contains duplicate probes")
        if set(names) != set(REQUIRED_PROBES):
            raise PhysicalIsolationError("physical report probe set is incomplete")
        for probe in self.probes:
            observed = _utc(
                probe.observed_at,
                name=f"probe.{probe.name.value}.observed_at",
            )
            if observed < started or observed > completed:
                raise PhysicalIsolationError(
                    "probe timestamp is outside report window"
                )

    @classmethod
    def from_mapping(cls, value: Any) -> "WindowsIsolationPhysicalReport":
        fields = {
            "schema",
            "report_id",
            "task_id",
            "task_sha256",
            "repository",
            "base_sha",
            "catalog_sha256",
            "toolchain_sha256",
            "rig_id",
            "rig_fingerprint_sha256",
            "candidate_version",
            "windows_build",
            "toolhost_sha256",
            "workspace_root_sha256",
            "collected_by",
            "approved_by",
            "started_at",
            "completed_at",
            "boot_marker_before_sha256",
            "boot_marker_after_sha256",
            "boundary",
            "network_mode",
            "probes",
        }
        data = _strict_object(value, fields=fields, name="physical report")
        probes = data["probes"]
        if not isinstance(probes, list):
            raise PhysicalIsolationError("physical report probes must be an array")
        try:
            boundary = IsolationBoundary(data["boundary"])
            network_mode = NetworkMode(data["network_mode"])
        except (TypeError, ValueError) as exc:
            raise PhysicalIsolationError(
                "physical report isolation mode is unsupported"
            ) from exc
        return cls(
            schema=data["schema"],
            report_id=data["report_id"],
            task_id=data["task_id"],
            task_sha256=data["task_sha256"],
            repository=data["repository"],
            base_sha=data["base_sha"],
            catalog_sha256=data["catalog_sha256"],
            toolchain_sha256=data["toolchain_sha256"],
            rig_id=data["rig_id"],
            rig_fingerprint_sha256=data["rig_fingerprint_sha256"],
            candidate_version=data["candidate_version"],
            windows_build=data["windows_build"],
            toolhost_sha256=data["toolhost_sha256"],
            workspace_root_sha256=data["workspace_root_sha256"],
            collected_by=data["collected_by"],
            approved_by=data["approved_by"],
            started_at=data["started_at"],
            completed_at=data["completed_at"],
            boot_marker_before_sha256=data["boot_marker_before_sha256"],
            boot_marker_after_sha256=data["boot_marker_after_sha256"],
            boundary=boundary,
            network_mode=network_mode,
            probes=tuple(PhysicalProbeResult.from_mapping(item) for item in probes),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "report_id": self.report_id,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "catalog_sha256": self.catalog_sha256,
            "toolchain_sha256": self.toolchain_sha256,
            "rig_id": self.rig_id,
            "rig_fingerprint_sha256": self.rig_fingerprint_sha256,
            "candidate_version": self.candidate_version,
            "windows_build": self.windows_build,
            "toolhost_sha256": self.toolhost_sha256,
            "workspace_root_sha256": self.workspace_root_sha256,
            "collected_by": self.collected_by,
            "approved_by": self.approved_by,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "boot_marker_before_sha256": self.boot_marker_before_sha256,
            "boot_marker_after_sha256": self.boot_marker_after_sha256,
            "boundary": self.boundary.value,
            "network_mode": self.network_mode.value,
            "probes": [probe.to_dict() for probe in self.probes],
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256(self.canonical_json().encode("utf-8"))

    @property
    def all_probes_passed(self) -> bool:
        return all(probe.passed for probe in self.probes)

    def bind_to_attestation(self, attestation: IsolationAttestation) -> None:
        proof = _snapshot_attestation(attestation)
        expected = {
            "task_id": proof.task_id,
            "task_sha256": proof.task_sha256,
            "repository": proof.repository,
            "base_sha": proof.base_sha,
            "catalog_sha256": proof.catalog_sha256,
            "toolchain_sha256": proof.toolchain_sha256,
            "boundary": proof.boundary,
            "network_mode": proof.network_mode,
        }
        actual = {
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "catalog_sha256": self.catalog_sha256,
            "toolchain_sha256": self.toolchain_sha256,
            "boundary": self.boundary,
            "network_mode": self.network_mode,
        }
        if actual != expected:
            raise PhysicalIsolationError(
                "physical report is not bound to the attestation"
            )


@dataclass(frozen=True, slots=True)
class SignedWindowsIsolationReport:
    report: WindowsIsolationPhysicalReport
    key_id: str
    signature_algorithm: str
    signature_sha256: str
    schema: str = SIGNED_REPORT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != SIGNED_REPORT_SCHEMA:
            raise PhysicalIsolationError("unsupported signed report schema")
        if not isinstance(self.report, WindowsIsolationPhysicalReport):
            raise PhysicalIsolationError("signed report payload is invalid")
        if not isinstance(self.key_id, str) or _IDENTIFIER.fullmatch(self.key_id) is None:
            raise PhysicalIsolationError("signed report key id is invalid")
        if self.signature_algorithm != SIGNATURE_ALGORITHM:
            raise PhysicalIsolationError("signed report algorithm is unsupported")
        if (
            not isinstance(self.signature_sha256, str)
            or _HEX64.fullmatch(self.signature_sha256) is None
        ):
            raise PhysicalIsolationError("signed report signature is invalid")

    @classmethod
    def from_mapping(cls, value: Any) -> "SignedWindowsIsolationReport":
        data = _strict_object(
            value,
            fields={
                "schema",
                "report",
                "key_id",
                "signature_algorithm",
                "signature_sha256",
            },
            name="signed physical report",
        )
        return cls(
            schema=data["schema"],
            report=WindowsIsolationPhysicalReport.from_mapping(data["report"]),
            key_id=data["key_id"],
            signature_algorithm=data["signature_algorithm"],
            signature_sha256=data["signature_sha256"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "report": self.report.to_dict(),
            "key_id": self.key_id,
            "signature_algorithm": self.signature_algorithm,
            "signature_sha256": self.signature_sha256,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256(self.canonical_json().encode("utf-8"))


class HmacIsolationReportSigner:
    """Sign canonical physical evidence with an operator-controlled secret."""

    __slots__ = ("key_id", "_secret")

    def __init__(self, key_id: str, secret: bytes) -> None:
        if not isinstance(key_id, str) or _IDENTIFIER.fullmatch(key_id) is None:
            raise PhysicalIsolationError("signing key id is invalid")
        if not isinstance(secret, bytes) or not 32 <= len(secret) <= _MAX_KEY_BYTES:
            raise PhysicalIsolationError(
                "signing secret must contain 32..4096 bytes"
            )
        self.key_id = key_id
        self._secret = bytes(secret)

    def sign(
        self, report: WindowsIsolationPhysicalReport
    ) -> SignedWindowsIsolationReport:
        if not isinstance(report, WindowsIsolationPhysicalReport):
            raise PhysicalIsolationError("only a physical report can be signed")
        signature = hmac.new(
            self._secret,
            report.canonical_json().encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return SignedWindowsIsolationReport(
            report=report,
            key_id=self.key_id,
            signature_algorithm=SIGNATURE_ALGORITHM,
            signature_sha256=signature,
        )


class WindowsPhysicalIsolationVerifier:
    """Verify one canonical signed report under an operator-owned evidence root."""

    __slots__ = (
        "evidence_root",
        "keyring",
        "max_age",
        "now",
        "max_file_bytes",
    )

    def __init__(
        self,
        evidence_root: Path,
        keyring: Mapping[str, bytes],
        *,
        max_age: timedelta = timedelta(days=30),
        now: Callable[[], datetime] | None = None,
        max_file_bytes: int = _MAX_REPORT_BYTES,
    ) -> None:
        root = _absolute_path(Path(evidence_root), name="evidence root")
        _assert_link_free(root, name="evidence root")
        try:
            metadata = os.stat(root, follow_symlinks=False)
        except OSError as exc:
            raise PhysicalIsolationError("evidence root cannot be inspected") from exc
        if not stat.S_ISDIR(metadata.st_mode):
            raise PhysicalIsolationError(
                "evidence root must be an existing non-link directory"
            )
        if os.name != "nt" and hasattr(os, "geteuid"):
            if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o022:
                raise PhysicalIsolationError(
                    "evidence root custody is not sufficiently restrictive"
                )
        if (
            not isinstance(max_age, timedelta)
            or not timedelta(0) < max_age <= timedelta(days=366)
        ):
            raise PhysicalIsolationError("physical evidence max age is invalid")
        if (
            isinstance(max_file_bytes, bool)
            or not isinstance(max_file_bytes, int)
            or not 1024 <= max_file_bytes <= 16_000_000
        ):
            raise PhysicalIsolationError(
                "physical evidence file bound is invalid"
            )
        if not isinstance(keyring, Mapping):
            raise PhysicalIsolationError("physical evidence keyring must be an object")
        clean_keys: dict[str, bytes] = {}
        for key_id, secret in keyring.items():
            if not isinstance(key_id, str) or _IDENTIFIER.fullmatch(key_id) is None:
                raise PhysicalIsolationError("physical evidence key id is invalid")
            if (
                not isinstance(secret, bytes)
                or not 32 <= len(secret) <= _MAX_KEY_BYTES
            ):
                raise PhysicalIsolationError("physical evidence key is invalid")
            clean_keys[key_id] = bytes(secret)
        if not clean_keys:
            raise PhysicalIsolationError(
                "physical evidence keyring must not be empty"
            )
        if now is not None and not callable(now):
            raise PhysicalIsolationError("physical verifier clock is invalid")
        self.evidence_root = root
        self.keyring = MappingProxyType(clean_keys)
        self.max_age = max_age
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.max_file_bytes = max_file_bytes

    def _load_candidates(
        self, allowed_hashes: set[str]
    ) -> tuple[SignedWindowsIsolationReport, ...]:
        _assert_link_free(self.evidence_root, name="evidence root")
        matches: list[SignedWindowsIsolationReport] = []
        try:
            paths = sorted(self.evidence_root.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            raise PhysicalIsolationError("evidence root cannot be enumerated") from exc
        for path in paths:
            if path.suffix != ".json":
                continue
            try:
                raw, _ = _stable_regular_read(
                    path,
                    maximum=self.max_file_bytes,
                    name="physical evidence candidate",
                )
                signed = SignedWindowsIsolationReport.from_mapping(
                    json.loads(raw.decode("utf-8"))
                )
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
                PhysicalIsolationError,
            ):
                continue
            canonical = signed.canonical_json().encode("utf-8")
            if raw != canonical:
                continue
            if _sha256(canonical) not in allowed_hashes:
                continue
            matches.append(signed)
        return tuple(matches)

    def verify(self, attestation: IsolationAttestation) -> None:
        proof = _snapshot_attestation(attestation)
        allowed_hashes = set(proof.evidence_sha256)
        candidates = self._load_candidates(allowed_hashes)
        if len(candidates) != 1:
            raise PhysicalIsolationError(
                "expected exactly one trusted physical report"
            )
        signed = candidates[0]
        try:
            secret = self.keyring[signed.key_id]
        except KeyError as exc:
            raise PhysicalIsolationError(
                "physical report signing key is not trusted"
            ) from exc
        expected = hmac.new(
            secret,
            signed.report.canonical_json().encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signed.signature_sha256):
            raise PhysicalIsolationError(
                "physical report signature is invalid"
            )
        signed.report.bind_to_attestation(proof)
        if not signed.report.all_probes_passed:
            raise PhysicalIsolationError(
                "physical isolation has one or more failed probes"
            )
        current = self.now()
        if not isinstance(current, datetime) or current.tzinfo is None:
            raise PhysicalIsolationError(
                "physical verifier clock must be timezone-aware"
            )
        current = current.astimezone(timezone.utc)
        completed = _utc(signed.report.completed_at, name="completed_at")
        if completed > current + timedelta(minutes=5):
            raise PhysicalIsolationError(
                "physical report completion time is in the future"
            )
        if current - completed > self.max_age:
            raise PhysicalIsolationError(
                "physical isolation report is stale"
            )


def load_isolation_attestation(path: Path) -> IsolationAttestation:
    """Load one canonical isolation attestation through a stable bounded handle."""

    raw, _ = _stable_regular_read(
        Path(path),
        maximum=_MAX_REPORT_BYTES,
        name="isolation attestation",
    )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhysicalIsolationError(
            "isolation attestation JSON is invalid"
        ) from exc
    proof = _snapshot_attestation(IsolationAttestation.from_mapping(value))
    if raw != proof.canonical_json().encode("utf-8"):
        raise PhysicalIsolationError(
            "isolation attestation is not canonical JSON"
        )
    return proof


def load_unsigned_report(path: Path) -> WindowsIsolationPhysicalReport:
    """Load one canonical unsigned report through a stable bounded handle."""

    raw, _ = _stable_regular_read(
        Path(path),
        maximum=_MAX_REPORT_BYTES,
        name="unsigned report",
    )
    try:
        report = WindowsIsolationPhysicalReport.from_mapping(
            json.loads(raw.decode("utf-8"))
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhysicalIsolationError("unsigned report JSON is invalid") from exc
    if raw != report.canonical_json().encode("utf-8"):
        raise PhysicalIsolationError(
            "unsigned report is not canonical JSON"
        )
    return report


def load_signing_secret(path: Path) -> bytes:
    """Load a restrictively held operator key through one stable handle."""

    if os.name == "nt":
        raise PhysicalIsolationError(
            "Windows signing-key ACL custody verification is not available"
        )
    raw, metadata = _stable_regular_read(
        Path(path),
        maximum=_MAX_KEY_BYTES,
        name="signing key",
    )
    if not 32 <= len(raw) <= _MAX_KEY_BYTES:
        raise PhysicalIsolationError(
            "signing key must contain 32..4096 bytes"
        )
    if not hasattr(os, "geteuid"):
        raise PhysicalIsolationError(
            "signing-key ownership verification is unavailable"
        )
    effective_user = os.geteuid()
    if metadata.st_uid != effective_user:
        raise PhysicalIsolationError(
            "signing key is not owned by the operator account"
        )
    if metadata.st_nlink != 1:
        raise PhysicalIsolationError(
            "signing key must not have additional hard links"
        )
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise PhysicalIsolationError(
            "signing key permissions are not restrictive"
        )
    parent = Path(path).parent
    _assert_link_free(parent, name="signing key directory")
    try:
        parent_metadata = os.stat(parent, follow_symlinks=False)
    except OSError as exc:
        raise PhysicalIsolationError(
            "signing key directory cannot be inspected"
        ) from exc
    if (
        not stat.S_ISDIR(parent_metadata.st_mode)
        or parent_metadata.st_uid != effective_user
        or stat.S_IMODE(parent_metadata.st_mode) & 0o022
    ):
        raise PhysicalIsolationError(
            "signing key directory custody is not restrictive"
        )
    return raw


def write_signed_report(
    path: Path, signed: SignedWindowsIsolationReport
) -> str:
    """Durably create one canonical evidence file and return its SHA-256."""

    output = _absolute_path(Path(path), name="signed report output")
    if not isinstance(signed, SignedWindowsIsolationReport):
        raise PhysicalIsolationError("signed report output is invalid")
    parent = output.parent
    _assert_link_free(parent, name="signed report output directory")
    try:
        parent_metadata = os.stat(parent, follow_symlinks=False)
    except OSError as exc:
        raise PhysicalIsolationError(
            "signed report output directory cannot be inspected"
        ) from exc
    if not stat.S_ISDIR(parent_metadata.st_mode):
        raise PhysicalIsolationError(
            "signed report output directory is invalid"
        )
    if output.exists() or output.is_symlink():
        raise PhysicalIsolationError(
            "signed report output path is unsafe or already exists"
        )
    payload = signed.canonical_json().encode("utf-8")
    if len(payload) > _MAX_REPORT_BYTES:
        raise PhysicalIsolationError("signed report is too large")
    try:
        create_once_file(output, payload)
    except (FileExistsError, DurablePublicationError) as exc:
        raise PhysicalIsolationError(
            "signed report could not be durably published"
        ) from exc
    return _sha256(payload)
