"""Shared Tier-A execution lease model and error identity.

H10L established the exact domain-error identity here. H10M extends this
private module with the cohesive immutable lease model and its canonical
validation/hash helpers. The legacy core re-exports every object unchanged.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .catalog import (
    CatalogError,
    IsolationAttestation,
    IsolationBoundary,
    NetworkMode,
)
from .contract import DevelopmentTask
from .physical_isolation import SignedWindowsIsolationReport

LEASE_SCHEMA = "kaliv-development-execution-lease/v1"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")


class TierAExecutionError(CatalogError):
    """A signed authority could not be converted into a safe Tier-A launch."""


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _task_sha(task: DevelopmentTask) -> str:
    return _sha256(task.canonical_json().encode("utf-8"))


@dataclass(frozen=True, slots=True)
class TierAExecutionLease:
    task_id: str
    task_sha256: str
    repository: str
    base_sha: str
    catalog_sha256: str
    toolchain_sha256: str
    boundary: IsolationBoundary
    network_mode: NetworkMode
    evidence_sha256: tuple[str, ...]
    signed_report_sha256: str
    report_id: str
    rig_id: str
    rig_fingerprint_sha256: str
    toolhost_sha256: str
    workspace_root_sha256: str
    completed_at: str
    key_id: str
    schema: str = LEASE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != LEASE_SCHEMA:
            raise TierAExecutionError("unsupported execution lease schema")
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise TierAExecutionError("execution lease task id is invalid")
        if self.repository != "Ternedal/ModelRig":
            raise TierAExecutionError("execution lease repository is invalid")
        for name, value, pattern in (
            ("task_sha256", self.task_sha256, _HEX64),
            ("base_sha", self.base_sha, _HEX40),
            ("catalog_sha256", self.catalog_sha256, _HEX64),
            ("toolchain_sha256", self.toolchain_sha256, _HEX64),
            ("signed_report_sha256", self.signed_report_sha256, _HEX64),
            ("rig_fingerprint_sha256", self.rig_fingerprint_sha256, _HEX64),
            ("toolhost_sha256", self.toolhost_sha256, _HEX64),
            ("workspace_root_sha256", self.workspace_root_sha256, _HEX64),
        ):
            if not isinstance(value, str) or pattern.fullmatch(value) is None:
                raise TierAExecutionError(f"execution lease {name} is invalid")
        if self.boundary is not IsolationBoundary.OS_ISOLATED:
            raise TierAExecutionError("execution lease boundary is not OS isolated")
        if self.network_mode is not NetworkMode.DENY:
            raise TierAExecutionError("execution lease network mode is not deny")
        if (
            not isinstance(self.evidence_sha256, tuple)
            or self.signed_report_sha256 not in self.evidence_sha256
            or any(_HEX64.fullmatch(item) is None for item in self.evidence_sha256)
            or len(set(self.evidence_sha256)) != len(self.evidence_sha256)
        ):
            raise TierAExecutionError("execution lease evidence set is invalid")
        for name, value, maximum in (
            ("report_id", self.report_id, 128),
            ("rig_id", self.rig_id, 128),
            ("completed_at", self.completed_at, 20),
            ("key_id", self.key_id, 128),
        ):
            if (
                not isinstance(value, str)
                or not value
                or value.strip() != value
                or "\0" in value
                or len(value.encode("utf-8")) > maximum
            ):
                raise TierAExecutionError(f"execution lease {name} is invalid")

    @classmethod
    def from_signed_report(
        cls,
        attestation: IsolationAttestation,
        signed: SignedWindowsIsolationReport,
    ) -> "TierAExecutionLease":
        signed.report.bind_to_attestation(attestation)
        return cls(
            task_id=attestation.task_id,
            task_sha256=attestation.task_sha256,
            repository=attestation.repository,
            base_sha=attestation.base_sha,
            catalog_sha256=attestation.catalog_sha256,
            toolchain_sha256=attestation.toolchain_sha256,
            boundary=attestation.boundary,
            network_mode=attestation.network_mode,
            evidence_sha256=attestation.evidence_sha256,
            signed_report_sha256=signed.sha256,
            report_id=signed.report.report_id,
            rig_id=signed.report.rig_id,
            rig_fingerprint_sha256=signed.report.rig_fingerprint_sha256,
            toolhost_sha256=signed.report.toolhost_sha256,
            workspace_root_sha256=signed.report.workspace_root_sha256,
            completed_at=signed.report.completed_at,
            key_id=signed.key_id,
        )

    @classmethod
    def from_mapping(cls, value: Any) -> "TierAExecutionLease":
        if not isinstance(value, Mapping):
            raise TierAExecutionError("execution lease must be an object")
        fields = {
            "schema",
            "task_id",
            "task_sha256",
            "repository",
            "base_sha",
            "catalog_sha256",
            "toolchain_sha256",
            "boundary",
            "network_mode",
            "evidence_sha256",
            "signed_report_sha256",
            "report_id",
            "rig_id",
            "rig_fingerprint_sha256",
            "toolhost_sha256",
            "workspace_root_sha256",
            "completed_at",
            "key_id",
        }
        if set(value) != fields:
            raise TierAExecutionError("execution lease fields mismatch")
        evidence = value["evidence_sha256"]
        if not isinstance(evidence, list) or any(
            not isinstance(item, str) for item in evidence
        ):
            raise TierAExecutionError(
                "execution lease evidence must be a string array"
            )
        try:
            boundary = IsolationBoundary(value["boundary"])
            network_mode = NetworkMode(value["network_mode"])
        except (TypeError, ValueError) as exc:
            raise TierAExecutionError(
                "execution lease isolation mode is invalid"
            ) from exc
        return cls(
            schema=value["schema"],
            task_id=value["task_id"],
            task_sha256=value["task_sha256"],
            repository=value["repository"],
            base_sha=value["base_sha"],
            catalog_sha256=value["catalog_sha256"],
            toolchain_sha256=value["toolchain_sha256"],
            boundary=boundary,
            network_mode=network_mode,
            evidence_sha256=tuple(evidence),
            signed_report_sha256=value["signed_report_sha256"],
            report_id=value["report_id"],
            rig_id=value["rig_id"],
            rig_fingerprint_sha256=value["rig_fingerprint_sha256"],
            toolhost_sha256=value["toolhost_sha256"],
            workspace_root_sha256=value["workspace_root_sha256"],
            completed_at=value["completed_at"],
            key_id=value["key_id"],
        )

    def verify_attestation(self, attestation: IsolationAttestation) -> None:
        expected = {
            "task_id": attestation.task_id,
            "task_sha256": attestation.task_sha256,
            "repository": attestation.repository,
            "base_sha": attestation.base_sha,
            "catalog_sha256": attestation.catalog_sha256,
            "toolchain_sha256": attestation.toolchain_sha256,
            "boundary": attestation.boundary,
            "network_mode": attestation.network_mode,
            "evidence_sha256": attestation.evidence_sha256,
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
            "evidence_sha256": self.evidence_sha256,
        }
        if actual != expected:
            raise TierAExecutionError(
                "execution lease is not bound to the exact isolation attestation"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "catalog_sha256": self.catalog_sha256,
            "toolchain_sha256": self.toolchain_sha256,
            "boundary": self.boundary.value,
            "network_mode": self.network_mode.value,
            "evidence_sha256": list(self.evidence_sha256),
            "signed_report_sha256": self.signed_report_sha256,
            "report_id": self.report_id,
            "rig_id": self.rig_id,
            "rig_fingerprint_sha256": self.rig_fingerprint_sha256,
            "toolhost_sha256": self.toolhost_sha256,
            "workspace_root_sha256": self.workspace_root_sha256,
            "completed_at": self.completed_at,
            "key_id": self.key_id,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256(self.canonical_json().encode("utf-8"))
