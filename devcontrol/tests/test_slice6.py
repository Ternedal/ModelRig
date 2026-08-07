from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from kaliv_dev_control.catalog import (
    CatalogError,
    CatalogMaterializer,
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
    load_signing_secret,
    load_unsigned_report,
    write_signed_report,
)

BASE_SHA = "a" * 40
NOW = datetime(2026, 8, 3, 12, 0, 0, tzinfo=timezone.utc)
STARTED = "2026-08-03T10:00:00Z"
OBSERVED = "2026-08-03T10:30:00Z"
COMPLETED = "2026-08-03T11:00:00Z"


def fixture_key(label: str = "primary") -> bytes:
    return hashlib.sha256(f"dc-l04-unit-fixture:{label}".encode("utf-8")).digest()


def task(command_id: str = "modelrig.devcontrol.tests") -> DevelopmentTask:
    return DevelopmentTask.from_mapping(
        {
            "schema": "kaliv-development-task/v1",
            "task_id": "I0B_TEST",
            "repository": "Ternedal/ModelRig",
            "base_sha": BASE_SHA,
            "goal": "Validate signed physical Windows isolation evidence.",
            "acceptance_criteria": ["Every required I0b probe passes."],
            "risk": "low",
            "allowed_paths": ["devcontrol/**"],
            "protected_paths": ["devcontrol/secrets/**"],
            "allowed_command_ids": [command_id],
            "required_tests": ["DC-L04 physical evidence regressions"],
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
    catalog = modelrig_command_catalog()
    selected_toolchain = toolchain()
    values = {
        "report_id": "i0b-20260803-candidate",
        "task_id": selected_task.task_id,
        "task_sha256": hashlib.sha256(
            selected_task.canonical_json().encode("utf-8")
        ).hexdigest(),
        "repository": selected_task.repository,
        "base_sha": selected_task.base_sha,
        "catalog_sha256": catalog.sha256,
        "toolchain_sha256": selected_toolchain.sha256,
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


class PhysicalReportContractTests(unittest.TestCase):
    def test_required_probe_set_is_stable(self):
        self.assertEqual(len(REQUIRED_PROBES), 11)
        self.assertEqual(len(set(REQUIRED_PROBES)), 11)

    def test_report_roundtrip_is_canonical(self):
        original = report()
        loaded = WindowsIsolationPhysicalReport.from_mapping(original.to_dict())
        self.assertEqual(loaded.canonical_json(), original.canonical_json())
        self.assertEqual(loaded.sha256, original.sha256)

    def test_incomplete_probe_set_is_rejected(self):
        with self.assertRaisesRegex(PhysicalIsolationError, "probe set is incomplete"):
            report(probes=tuple(probe(name) for name in REQUIRED_PROBES[:-1]))

    def test_duplicate_probe_is_rejected(self):
        values = tuple(probe(name) for name in REQUIRED_PROBES)
        with self.assertRaisesRegex(PhysicalIsolationError, "duplicate probes"):
            report(probes=values[:-1] + (values[0],))

    def test_same_collector_and_approver_is_rejected(self):
        with self.assertRaisesRegex(PhysicalIsolationError, "different actors"):
            report(collected_by="same-actor", approved_by="same-actor")

    def test_reboot_marker_must_change(self):
        with self.assertRaisesRegex(PhysicalIsolationError, "reboot boundary"):
            report(
                boot_marker_before_sha256="5" * 64,
                boot_marker_after_sha256="5" * 64,
            )

    def test_probe_timestamp_must_be_inside_report_window(self):
        outside = PhysicalProbeResult(
            name=ProbeName.NETWORK_DENIED,
            passed=True,
            receipt_sha256="7" * 64,
            detail="Observed outside the campaign window.",
            observed_at="2026-08-03T09:59:59Z",
        )
        values = tuple(
            outside if name is ProbeName.NETWORK_DENIED else probe(name)
            for name in REQUIRED_PROBES
        )
        with self.assertRaisesRegex(PhysicalIsolationError, "outside report window"):
            report(probes=values)

    def test_failed_probe_can_be_recorded_honestly(self):
        evidence = report(failed=ProbeName.NETWORK_DENIED)
        self.assertFalse(evidence.all_probes_passed)

    def test_signed_report_roundtrip_is_canonical(self):
        original = signed_report()
        loaded = SignedWindowsIsolationReport.from_mapping(original.to_dict())
        self.assertEqual(loaded.canonical_json(), original.canonical_json())
        self.assertEqual(loaded.sha256, original.sha256)


class PhysicalVerifierTests(unittest.TestCase):
    def _write(
        self,
        root: Path,
        signed: SignedWindowsIsolationReport,
        name: str = "evidence.json",
    ) -> Path:
        path = root / name
        path.write_bytes(signed.canonical_json().encode("utf-8"))
        return path

    def _verifier(self, root: Path, **kwargs) -> WindowsPhysicalIsolationVerifier:
        return WindowsPhysicalIsolationVerifier(
            root,
            {"operator-key-2026": fixture_key()},
            now=lambda: NOW,
            **kwargs,
        )

    def test_valid_signed_exact_task_report_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            signed = signed_report()
            self._write(root, signed)
            self._verifier(root).verify(attestation(signed.sha256))

    def test_missing_evidence_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self._write(root, signed_report())
            with self.assertRaisesRegex(PhysicalIsolationError, "exactly one"):
                self._verifier(root).verify(attestation("f" * 64))

    def test_wrong_signing_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            signed = signed_report()
            self._write(root, signed)
            with self.assertRaisesRegex(PhysicalIsolationError, "signature is invalid"):
                WindowsPhysicalIsolationVerifier(
                    root,
                    {"operator-key-2026": fixture_key("different")},
                    now=lambda: NOW,
                ).verify(attestation(signed.sha256))

    def test_untrusted_key_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            signed = signed_report()
            self._write(root, signed)
            with self.assertRaisesRegex(PhysicalIsolationError, "not trusted"):
                WindowsPhysicalIsolationVerifier(
                    root,
                    {"another-key": fixture_key()},
                    now=lambda: NOW,
                ).verify(attestation(signed.sha256))

    def test_failed_probe_keeps_authority_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            signed = signed_report(failed=ProbeName.NETWORK_DENIED)
            self._write(root, signed)
            with self.assertRaisesRegex(PhysicalIsolationError, "failed probes"):
                self._verifier(root).verify(attestation(signed.sha256))

    def test_report_must_bind_to_exact_task(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            signed = signed_report(base_sha="b" * 40)
            self._write(root, signed)
            with self.assertRaisesRegex(PhysicalIsolationError, "not bound"):
                self._verifier(root).verify(attestation(signed.sha256))

    def test_stale_report_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            signed = signed_report()
            self._write(root, signed)
            with self.assertRaisesRegex(PhysicalIsolationError, "stale"):
                WindowsPhysicalIsolationVerifier(
                    root,
                    {"operator-key-2026": fixture_key()},
                    now=lambda: NOW + timedelta(days=31),
                ).verify(attestation(signed.sha256))

    def test_future_report_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            signed = signed_report()
            self._write(root, signed)
            with self.assertRaisesRegex(PhysicalIsolationError, "future"):
                WindowsPhysicalIsolationVerifier(
                    root,
                    {"operator-key-2026": fixture_key()},
                    now=lambda: datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc),
                ).verify(attestation(signed.sha256))

    def test_noncanonical_json_is_not_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            signed = signed_report()
            (root / "pretty.json").write_text(
                json.dumps(signed.to_dict(), indent=2),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(PhysicalIsolationError, "exactly one"):
                self._verifier(root).verify(attestation(signed.sha256))

    def test_duplicate_matching_files_are_rejected_as_ambiguous(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            signed = signed_report()
            self._write(root, signed, "one.json")
            self._write(root, signed, "two.json")
            with self.assertRaisesRegex(PhysicalIsolationError, "exactly one"):
                self._verifier(root).verify(attestation(signed.sha256))

    @unittest.skipIf(not hasattr(os, "symlink"), "symlink support unavailable")
    def test_symlinked_evidence_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            signed = signed_report()
            target = self._write(root, signed, "target.data")
            try:
                os.symlink(target, root / "evidence.json")
            except OSError:
                self.skipTest("symlinks are unavailable to this account")
            with self.assertRaisesRegex(PhysicalIsolationError, "exactly one"):
                self._verifier(root).verify(attestation(signed.sha256))

    def test_valid_physical_evidence_does_not_activate_empty_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            selected_task = task()
            signed = signed_report(source_task=selected_task)
            proof = attestation(signed.sha256, source_task=selected_task)
            self._write(root, signed)
            verifier = self._verifier(root)
            verifier.verify(proof)
            with self.assertRaisesRegex(CatalogError, "not in the ModelRig catalog"):
                CatalogMaterializer(
                    modelrig_command_catalog(),
                    isolation_verifier=verifier,
                ).materialize(selected_task, toolchain(), proof)


class OperatorFileTests(unittest.TestCase):
    def test_unsigned_loader_requires_canonical_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            evidence = report()
            canonical = root / "canonical.json"
            canonical.write_bytes(evidence.canonical_json().encode("utf-8"))
            self.assertEqual(load_unsigned_report(canonical).sha256, evidence.sha256)
            pretty = root / "pretty.json"
            pretty.write_text(
                json.dumps(evidence.to_dict(), indent=2),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(PhysicalIsolationError, "not canonical"):
                load_unsigned_report(pretty)

    @unittest.skipIf(os.name == "nt", "Windows key custody fails closed")
    def test_signing_key_requires_restrictive_operator_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / "operator.key"
            path.write_bytes(fixture_key())
            path.chmod(0o600)
            self.assertEqual(load_signing_secret(path), fixture_key())
            path.chmod(0o640)
            with self.assertRaisesRegex(PhysicalIsolationError, "permissions"):
                load_signing_secret(path)

    def test_signed_report_writer_is_create_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / "evidence.json"
            signed = signed_report()
            digest = write_signed_report(output, signed)
            self.assertEqual(digest, signed.sha256)
            self.assertEqual(
                output.read_bytes(),
                signed.canonical_json().encode("utf-8"),
            )
            with self.assertRaisesRegex(PhysicalIsolationError, "already exists"):
                write_signed_report(output, signed)


if __name__ == "__main__":
    unittest.main()
