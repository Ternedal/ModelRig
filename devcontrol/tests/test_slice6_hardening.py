from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import kaliv_dev_control.physical_isolation as physical_module
from kaliv_dev_control.catalog import (
    IsolationAttestation,
    IsolationBoundary,
    NetworkMode,
    Toolchain,
    modelrig_command_catalog,
)
from kaliv_dev_control.contract import DevelopmentTask
from kaliv_dev_control.physical_isolation import (
    HmacIsolationReportSigner,
    PhysicalIsolationError,
    PhysicalProbeResult,
    ProbeName,
    REQUIRED_PROBES,
    SignedWindowsIsolationReport,
    WindowsIsolationPhysicalReport,
    WindowsPhysicalIsolationVerifier,
    load_isolation_attestation,
    load_signing_secret,
    load_unsigned_report,
)

BASE_SHA = "a" * 40
NOW = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)
STARTED = "2026-08-03T10:00:00Z"
OBSERVED = "2026-08-03T10:30:00Z"
COMPLETED = "2026-08-03T11:00:00Z"


def fixture_key(label: str = "primary") -> bytes:
    return hashlib.sha256(f"dc-l04-hardening-fixture:{label}".encode("utf-8")).digest()


def task(command_id: str = "modelrig.devcontrol.tests") -> DevelopmentTask:
    return DevelopmentTask.from_mapping(
        {
            "schema": "kaliv-development-task/v1",
            "task_id": "I0B_HARDENING",
            "repository": "Ternedal/ModelRig",
            "base_sha": BASE_SHA,
            "goal": "Harden signed physical Windows isolation evidence.",
            "acceptance_criteria": ["Every DC-L04 hardening regression passes."],
            "risk": "low",
            "allowed_paths": ["devcontrol/**"],
            "protected_paths": ["devcontrol/secrets/**"],
            "allowed_command_ids": [command_id],
            "required_tests": ["DC-L04 hardening regressions"],
            "budget": {
                "max_changed_files": 20,
                "max_added_lines": 5000,
                "max_deleted_lines": 5000,
                "max_attempts": 2,
                "max_runtime_seconds": 3600,
                "max_output_bytes": 1_000_000,
            },
            "merge_authority": "human",
        }
    )


def toolchain() -> Toolchain:
    return Toolchain(())


def probe(name: ProbeName, *, passed: bool = True) -> PhysicalProbeResult:
    return PhysicalProbeResult(
        name=name,
        passed=passed,
        receipt_sha256=hashlib.sha256(name.value.encode("utf-8")).hexdigest(),
        detail=f"Physical probe {name.value} completed.",
        observed_at=OBSERVED,
    )


def report(
    *,
    failed: ProbeName | None = None,
    source_task: DevelopmentTask | None = None,
    **overrides,
) -> WindowsIsolationPhysicalReport:
    selected_task = source_task or task()
    values = {
        "report_id": "i0b-20260803-hardening",
        "task_id": selected_task.task_id,
        "task_sha256": hashlib.sha256(
            selected_task.canonical_json().encode("utf-8")
        ).hexdigest(),
        "repository": selected_task.repository,
        "base_sha": selected_task.base_sha,
        "catalog_sha256": modelrig_command_catalog().sha256,
        "toolchain_sha256": toolchain().sha256,
        "rig_id": "modelrig-primary",
        "rig_fingerprint_sha256": "2" * 64,
        "candidate_version": "1.58.147",
        "windows_build": "Windows 11 24H2 build 26100",
        "toolhost_sha256": "3" * 64,
        "workspace_root_sha256": "4" * 64,
        "collected_by": "rig-collector",
        "approved_by": "operator-approver",
        "started_at": STARTED,
        "completed_at": COMPLETED,
        "boot_marker_before_sha256": "5" * 64,
        "boot_marker_after_sha256": "6" * 64,
        "boundary": IsolationBoundary.OS_ISOLATED,
        "network_mode": NetworkMode.DENY,
        "probes": tuple(
            probe(name, passed=name is not failed) for name in REQUIRED_PROBES
        ),
    }
    values.update(overrides)
    return WindowsIsolationPhysicalReport(**values)


def signed_report(**kwargs) -> SignedWindowsIsolationReport:
    return HmacIsolationReportSigner(
        "operator-key-2026",
        fixture_key(),
    ).sign(report(**kwargs))


def attestation(
    evidence_hash: str,
    *,
    source_task: DevelopmentTask | None = None,
    **overrides,
) -> IsolationAttestation:
    selected_task = source_task or task()
    values = {
        "task_id": selected_task.task_id,
        "task_sha256": hashlib.sha256(
            selected_task.canonical_json().encode("utf-8")
        ).hexdigest(),
        "repository": selected_task.repository,
        "base_sha": selected_task.base_sha,
        "catalog_sha256": modelrig_command_catalog().sha256,
        "toolchain_sha256": toolchain().sha256,
        "boundary": IsolationBoundary.OS_ISOLATED,
        "network_mode": NetworkMode.DENY,
        "evidence_sha256": (evidence_hash,),
    }
    values.update(overrides)
    return IsolationAttestation(**values)


class Slice6HardeningTests(unittest.TestCase):
    def test_direct_constructor_rejects_non_probe_objects(self):
        with self.assertRaisesRegex(PhysicalIsolationError, "invalid result"):
            report(probes=("not-a-probe",))

    @unittest.skipIf(not hasattr(os, "symlink"), "symlink support unavailable")
    def test_evidence_root_rejects_link_component(self):
        with tempfile.TemporaryDirectory() as directory:
            outer = Path(directory).resolve()
            target = outer / "target"
            target.mkdir()
            link = outer / "evidence-link"
            try:
                os.symlink(target, link, target_is_directory=True)
            except OSError:
                self.skipTest("directory symlinks are unavailable to this account")
            with self.assertRaisesRegex(PhysicalIsolationError, "link or reparse point"):
                WindowsPhysicalIsolationVerifier(
                    link.absolute(),
                    {"operator-key-2026": fixture_key()},
                )

    @unittest.skipIf(os.name == "nt", "POSIX ownership test")
    def test_evidence_root_rejects_group_or_other_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            root.chmod(0o777)
            with self.assertRaisesRegex(PhysicalIsolationError, "custody"):
                WindowsPhysicalIsolationVerifier(
                    root,
                    {"operator-key-2026": fixture_key()},
                )

    def test_oversized_unsigned_report_is_rejected_before_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "oversized.json"
            with path.open("wb") as handle:
                handle.truncate(2_000_001)
            with self.assertRaisesRegex(PhysicalIsolationError, "size bound"):
                load_unsigned_report(path)

    @unittest.skipIf(os.name == "nt" or not hasattr(os, "mkfifo"), "FIFO unavailable")
    def test_special_file_is_rejected_without_blocking(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "report.fifo"
            os.mkfifo(path)
            with self.assertRaisesRegex(PhysicalIsolationError, "regular file"):
                load_unsigned_report(path)

    @unittest.skipIf(os.name == "nt", "POSIX replacement test")
    def test_unsigned_report_path_replacement_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / "unsigned.json"
            replacement = root / "replacement.json"
            path.write_bytes(report().canonical_json().encode("utf-8"))
            replacement.write_bytes(
                report(candidate_version="different").canonical_json().encode("utf-8")
            )
            real_read = os.read
            replaced = False

            def racing_read(descriptor: int, amount: int) -> bytes:
                nonlocal replaced
                data = real_read(descriptor, amount)
                if data and not replaced:
                    replaced = True
                    os.replace(replacement, path)
                return data

            with patch.object(physical_module.os, "read", side_effect=racing_read):
                with self.assertRaisesRegex(PhysicalIsolationError, "path changed"):
                    load_unsigned_report(path)

    @unittest.skipIf(os.name == "nt", "POSIX key custody test")
    def test_signing_key_rejects_weak_permissions_and_hardlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            key = root / "operator.key"
            key.write_bytes(fixture_key())
            key.chmod(0o640)
            with self.assertRaisesRegex(PhysicalIsolationError, "permissions"):
                load_signing_secret(key)
            key.chmod(0o600)
            alias = root / "operator-alias.key"
            try:
                os.link(key, alias)
            except OSError:
                self.skipTest("hard links are unavailable")
            with self.assertRaisesRegex(PhysicalIsolationError, "hard links"):
                load_signing_secret(key)

    def test_windows_signing_key_custody_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory).resolve() / "operator.key"
            key.write_bytes(fixture_key())
            with patch.object(physical_module.os, "name", "nt"):
                with self.assertRaisesRegex(PhysicalIsolationError, "ACL custody"):
                    load_signing_secret(key)

    def test_attestation_is_snapshotted_before_candidate_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            signed = signed_report()
            (root / "evidence.json").write_bytes(
                signed.canonical_json().encode("utf-8")
            )
            supplied = attestation(signed.sha256)
            original_loader = WindowsPhysicalIsolationVerifier._load_candidates

            def mutating_loader(verifier, allowed_hashes):
                object.__setattr__(supplied, "base_sha", "b" * 40)
                return original_loader(verifier, allowed_hashes)

            verifier = WindowsPhysicalIsolationVerifier(
                root,
                {"operator-key-2026": fixture_key()},
                now=lambda: NOW,
            )
            with patch.object(
                WindowsPhysicalIsolationVerifier,
                "_load_candidates",
                new=mutating_loader,
            ):
                verifier.verify(supplied)
            self.assertEqual(supplied.base_sha, "b" * 40)

    def test_canonical_attestation_loader_rejects_pretty_json(self):
        proof = attestation("f" * 64)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            canonical = root / "canonical.json"
            canonical.write_bytes(proof.canonical_json().encode("utf-8"))
            loaded = load_isolation_attestation(canonical)
            self.assertEqual(loaded.canonical_json(), proof.canonical_json())
            pretty = root / "pretty.json"
            pretty.write_text(json.dumps(proof.to_dict(), indent=2), encoding="utf-8")
            with self.assertRaisesRegex(PhysicalIsolationError, "not canonical"):
                load_isolation_attestation(pretty)

    def test_physical_schema_requires_each_probe_name_once(self):
        schemas = Path(__file__).resolve().parents[1] / "schemas"
        physical = json.loads(
            (schemas / "windows-isolation-physical-report-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        probes = physical["properties"]["probes"]
        self.assertEqual(probes["minItems"], 11)
        self.assertEqual(probes["maxItems"], 11)
        requirements = probes["allOf"]
        names = tuple(
            item["contains"]["properties"]["name"]["const"]
            for item in requirements
        )
        self.assertEqual(len(requirements), 11)
        self.assertEqual(len(set(names)), 11)
        self.assertTrue(
            all(
                item["minContains"] == 1 and item["maxContains"] == 1
                for item in requirements
            )
        )

    def test_signed_schema_reference_exists_locally(self):
        schemas = Path(__file__).resolve().parents[1] / "schemas"
        signed = json.loads(
            (schemas / "windows-isolation-signed-report-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        reference = signed["properties"]["report"]["$ref"]
        self.assertEqual(reference, "windows-isolation-physical-report-v1.schema.json")
        self.assertTrue((schemas / reference).is_file())


if __name__ == "__main__":
    unittest.main()
