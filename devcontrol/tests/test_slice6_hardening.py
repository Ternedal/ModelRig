from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import kaliv_dev_control.physical_isolation as physical_module
from kaliv_dev_control.physical_isolation import (
    PhysicalIsolationError,
    WindowsPhysicalIsolationVerifier,
    load_isolation_attestation,
    load_signing_secret,
    load_unsigned_report,
)
from test_slice6 import NOW, attestation, fixture_key, report, signed_report


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
