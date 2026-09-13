from __future__ import annotations

import errno
import inspect
import os
import stat
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import kaliv_dev_control._improvement_physical_state_host_control as state_control
import kaliv_dev_control.improvement_physical_reservation as reservation
import kaliv_dev_control.physical_isolation as physical_module
from kaliv_dev_control.durable_publication import DurablePublicationError
from kaliv_dev_control.physical_isolation import (
    PhysicalIsolationError,
    SignedWindowsIsolationReport,
    write_signed_report,
)
from test_slice6 import signed_report


class PhysicalIsolationDurablePublicationH10BTests(unittest.TestCase):
    def test_publication_preserves_exact_canonical_bytes_and_hash(self):
        evidence = signed_report()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory).resolve() / "signed-isolation.json"
            self.assertEqual(write_signed_report(output, evidence), evidence.sha256)
            self.assertEqual(
                output.read_bytes(),
                evidence.canonical_json().encode("utf-8"),
            )
            loaded = SignedWindowsIsolationReport.from_mapping(
                __import__("json").loads(output.read_text(encoding="utf-8"))
            )
            self.assertEqual(loaded.canonical_json(), evidence.canonical_json())
            self.assertEqual(loaded.sha256, evidence.sha256)

    def test_parallel_publication_has_exactly_one_winner(self):
        evidence = signed_report()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / "signed-isolation.json"

            def publish(_: int) -> tuple[str, str]:
                try:
                    return ("ok", write_signed_report(output, evidence))
                except PhysicalIsolationError as exc:
                    return ("error", str(exc))

            with ThreadPoolExecutor(max_workers=24) as executor:
                results = tuple(executor.map(publish, range(24)))

            winners = tuple(value for status, value in results if status == "ok")
            losers = tuple(value for status, value in results if status == "error")
            self.assertEqual(winners, (evidence.sha256,))
            self.assertEqual(len(losers), 23)
            self.assertTrue(
                all(
                    "already exists" in message
                    or "durably published" in message
                    for message in losers
                )
            )
            self.assertEqual(
                output.read_bytes(),
                evidence.canonical_json().encode("utf-8"),
            )
            self.assertEqual(tuple(root.iterdir()), (output,))

    def test_durability_failure_leaves_no_artifact(self):
        evidence = signed_report()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory).resolve() / "signed-isolation.json"
            with patch.object(
                physical_module,
                "create_once_file",
                side_effect=DurablePublicationError("simulated durability failure"),
            ):
                with self.assertRaisesRegex(
                    PhysicalIsolationError,
                    "durably published",
                ):
                    write_signed_report(output, evidence)
            self.assertFalse(output.exists())
            self.assertFalse(output.is_symlink())

    def test_writer_uses_shared_durable_primitive_not_replace(self):
        source = inspect.getsource(physical_module)
        writer_source = inspect.getsource(write_signed_report)
        self.assertIn("create_once_file(output, payload)", writer_source)
        self.assertNotIn("os.replace(", source)
        self.assertNotIn("tempfile.mkstemp(", source)


class PhysicalReplayStateHostControlTests(unittest.TestCase):
    @staticmethod
    def _stat(*, uid: int = 0, mode: int = 0o700):
        return SimpleNamespace(
            st_mode=stat.S_IFDIR | mode,
            st_nlink=2,
            st_uid=uid,
            st_dev=1,
            st_ino=2,
        )

    def test_posix_directory_metadata_requires_root_owner(self):
        with self.assertRaisesRegex(
            state_control.PhysicalHostStateError,
            "not root-controlled",
        ):
            state_control._validate_posix_directory_stat(
                self._stat(uid=1000, mode=0o700)
            )

    def test_posix_directory_metadata_rejects_group_or_world_write(self):
        for mode in (0o720, 0o702, 0o777):
            with self.subTest(mode=oct(mode)):
                with self.assertRaisesRegex(
                    state_control.PhysicalHostStateError,
                    "not root-controlled",
                ):
                    state_control._validate_posix_directory_stat(
                        self._stat(uid=0, mode=mode)
                    )

    def test_posix_directory_metadata_accepts_root_owned_private_directory(self):
        state_control._validate_posix_directory_stat(
            self._stat(uid=0, mode=0o700)
        )
        state_control._validate_posix_directory_stat(
            self._stat(uid=0, mode=0o755)
        )

    @unittest.skipUnless(os.name == "posix", "POSIX operator regression")
    def test_posix_replay_writer_requires_effective_root(self):
        with patch.object(state_control.os, "geteuid", return_value=1000):
            with self.assertRaisesRegex(
                state_control.PhysicalHostStateError,
                "elevated host operator",
            ):
                state_control._require_posix_elevated_operator()
        with patch.object(state_control.os, "geteuid", return_value=0):
            state_control._require_posix_elevated_operator()

    @unittest.skipUnless(os.name == "posix", "POSIX host-state regression")
    def test_ordinary_temp_tree_cannot_be_production_replay_state(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory).resolve() / "ledger"
            ledger.mkdir(mode=0o700)
            with self.assertRaises(state_control.PhysicalHostStateError):
                state_control._require_posix_host_control(ledger)

    @unittest.skipUnless(os.name == "posix", "POSIX ACL regression")
    def test_extended_posix_acl_is_rejected(self):
        with patch.object(state_control.os, "getxattr", return_value=b"synthetic-acl"):
            with self.assertRaisesRegex(
                state_control.PhysicalHostStateError,
                "extended POSIX ACL",
            ):
                state_control._require_no_posix_acl(Path("/synthetic"))

    @unittest.skipUnless(os.name == "posix", "POSIX ACL regression")
    def test_missing_posix_acl_xattr_is_accepted(self):
        missing = OSError(errno.ENODATA, "no acl")
        with patch.object(state_control.os, "getxattr", side_effect=missing):
            state_control._require_no_posix_acl(Path("/synthetic"))

    @unittest.skipUnless(os.name == "posix", "POSIX operator regression")
    def test_canonical_ledger_checks_operator_before_host_state(self):
        events: list[str] = []
        with (
            patch.object(
                state_control,
                "_require_elevated_operator",
                side_effect=lambda: events.append("operator"),
            ),
            patch.object(
                state_control,
                "_require_posix_host_control",
                side_effect=lambda path: events.append("ledger") or path,
            ),
        ):
            self.assertEqual(
                state_control._canonical_host_controlled_ledger_root(),
                state_control._POSIX_LEDGER,
            )
        self.assertEqual(events, ["operator", "ledger"])

    def test_public_facade_uses_privilege_separated_replay_resolver(self):
        self.assertIs(
            reservation._canonical_host_ledger_root,
            state_control._canonical_host_controlled_ledger_root,
        )

    def test_public_consume_fails_closed_before_transaction_on_unsafe_ledger(self):
        with (
            patch.object(
                reservation,
                "_canonical_physical_request_authority_verifier",
                return_value=object(),
            ),
            patch.object(
                reservation,
                "_canonical_host_ledger_root",
                side_effect=state_control.PhysicalHostStateError("synthetic unsafe state"),
            ),
        ):
            with self.assertRaisesRegex(
                reservation.PhysicalQualificationReservationError,
                "host-controlled physical request replay ledger is unavailable",
            ):
                reservation.consume_physical_qualification_request_once(
                    trusted_git=object(),
                    request=object(),
                    qualification=object(),
                    snapshot_receipt=object(),
                    signature=object(),
                )

    def test_production_paths_do_not_share_service_writable_windows_state(self):
        self.assertEqual(
            state_control._POSIX_LEDGER,
            Path("/var/lib/modelrig/devcontrol/rsi-physical-request-ledger-v1"),
        )
        self.assertIn("Program Files", os.fspath(state_control._WINDOWS_LEDGER))
        self.assertNotIn("ProgramData", os.fspath(state_control._WINDOWS_LEDGER))


if __name__ == "__main__":
    unittest.main()
