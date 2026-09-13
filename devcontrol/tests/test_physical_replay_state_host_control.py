from __future__ import annotations

import errno
import os
import stat
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import kaliv_dev_control._improvement_physical_state_host_control as state_control
import kaliv_dev_control.improvement_physical_reservation as reservation


class PhysicalReplayStateHostControlTests(unittest.TestCase):
    def _stat(self, *, uid: int = 0, mode: int = 0o700):
        return SimpleNamespace(
            st_mode=stat.S_IFDIR | mode,
            st_nlink=2,
            st_uid=uid,
            st_dev=1,
            st_ino=2,
        )

    def test_posix_directory_metadata_requires_root_owner(self) -> None:
        with self.assertRaisesRegex(
            state_control.PhysicalHostStateError,
            "not root-controlled",
        ):
            state_control._validate_posix_directory_stat(
                self._stat(uid=1000, mode=0o700)
            )

    def test_posix_directory_metadata_rejects_group_or_world_write(self) -> None:
        for mode in (0o720, 0o702, 0o777):
            with self.subTest(mode=oct(mode)):
                with self.assertRaisesRegex(
                    state_control.PhysicalHostStateError,
                    "not root-controlled",
                ):
                    state_control._validate_posix_directory_stat(
                        self._stat(uid=0, mode=mode)
                    )

    def test_posix_directory_metadata_accepts_root_owned_private_directory(self) -> None:
        state_control._validate_posix_directory_stat(
            self._stat(uid=0, mode=0o700)
        )
        state_control._validate_posix_directory_stat(
            self._stat(uid=0, mode=0o755)
        )

    @unittest.skipUnless(os.name == "posix", "POSIX host-state regression")
    def test_world_writable_ancestor_cannot_be_production_replay_state(self) -> None:
        # A temp directory may itself be private, but /tmp (or the platform's
        # equivalent temporary parent) is ordinary-user writable. Production
        # state must therefore not be accepted merely because the leaf is 0700.
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory).resolve() / "ledger"
            ledger.mkdir(mode=0o700)
            with self.assertRaises(state_control.PhysicalHostStateError):
                state_control._require_posix_host_control(ledger)

    @unittest.skipUnless(os.name == "posix", "POSIX ACL regression")
    def test_extended_posix_acl_is_rejected(self) -> None:
        with patch.object(state_control.os, "getxattr", return_value=b"synthetic-acl"):
            with self.assertRaisesRegex(
                state_control.PhysicalHostStateError,
                "extended POSIX ACL",
            ):
                state_control._require_no_posix_acl(Path("/synthetic"))

    @unittest.skipUnless(os.name == "posix", "POSIX ACL regression")
    def test_missing_posix_acl_xattr_is_accepted(self) -> None:
        missing = OSError(errno.ENODATA, "no acl")
        with patch.object(state_control.os, "getxattr", side_effect=missing):
            state_control._require_no_posix_acl(Path("/synthetic"))

    def test_public_facade_uses_privilege_separated_replay_resolver(self) -> None:
        self.assertIs(
            reservation._canonical_host_ledger_root,
            state_control._canonical_host_controlled_ledger_root,
        )

    def test_public_consume_fails_closed_before_transaction_on_unsafe_ledger(self) -> None:
        verifier = object()
        with (
            patch.object(
                reservation,
                "_canonical_physical_request_authority_verifier",
                return_value=verifier,
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

    def test_production_paths_do_not_share_service_writable_windows_state(self) -> None:
        self.assertEqual(
            state_control._POSIX_LEDGER,
            Path("/var/lib/modelrig/devcontrol/rsi-physical-request-ledger-v1"),
        )
        self.assertIn("Program Files", os.fspath(state_control._WINDOWS_LEDGER))
        self.assertNotIn("ProgramData", os.fspath(state_control._WINDOWS_LEDGER))


if __name__ == "__main__":
    unittest.main()
