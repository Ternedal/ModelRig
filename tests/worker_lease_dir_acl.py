#!/usr/bin/env python3
"""GPU lease directory ACL on Windows (gap G5, #2296): the judgment and its wiring into gpu_lease.

The judgment is pure and runs everywhere. The reader is exercised on real Windows by
tests/support/windows_lease_dir_acl_contract.py; here it is replaced by a stub, to prove
that every lock path consults it on Windows and that a refusal is a GpuLeaseError.

Run: PYTHONPATH=worker python3 tests/worker_lease_dir_acl.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app import gpu_lease  # noqa: E402
from app.credential_acl import (  # noqa: E402
    ACCESS_ALLOWED_ACE_TYPE, ACCESS_DENIED_ACE_TYPE, DELETE, GENERIC_ALL, GENERIC_WRITE, MAXIMUM_ALLOWED,
    READ_CONTROL, SYNCHRONIZE, WRITE_DAC, WRITE_OWNER, Ace,
)
from app.lease_dir_acl import (  # noqa: E402
    BENIGN_DIRECTORY_RIGHTS, FILE_ADD_FILE, FILE_ADD_SUBDIRECTORY, FILE_DELETE_CHILD, FILE_LIST_DIRECTORY,
    FILE_TRAVERSE, FILE_WRITE_ATTRIBUTES, FILE_WRITE_EA, evaluate_lease_dir_acl,
)

ME = "S-1-5-21-1111111111-2222222222-3333333333-1001"
OTHER = "S-1-5-21-1111111111-2222222222-3333333333-1002"
SYSTEM, ADMINS, OWNER_RIGHTS = "S-1-5-18", "S-1-5-32-544", "S-1-3-4"
USERS, EVERYONE, AUTH_USERS, CREATOR_OWNER = "S-1-5-32-545", "S-1-1-0", "S-1-5-11", "S-1-3-0"
FULL = 0x001F01FF
INHERIT_ONLY_CI_OI = 0x0B  # OBJECT_INHERIT | CONTAINER_INHERIT | INHERIT_ONLY


def allow(sid, mask, flags=0):
    return Ace(ACCESS_ALLOWED_ACE_TYPE, flags, mask, sid)


class JudgmentTests(unittest.TestCase):
    def ok(self, aces, owner=ME):
        return evaluate_lease_dir_acl(owner, aces, ME)

    def test_the_default_local_appdata_shape_is_accepted(self):
        accepted, reason = self.ok([allow(SYSTEM, FULL, 0x13), allow(ADMINS, FULL, 0x13), allow(ME, FULL, 0x13)])
        self.assertTrue(accepted, reason)

    def test_others_may_list_traverse_and_read_attributes(self):
        accepted, reason = self.ok([allow(ME, FULL), allow(USERS, BENIGN_DIRECTORY_RIGHTS)])
        self.assertTrue(accepted, reason)
        self.assertTrue(self.ok([allow(ME, FULL), allow(USERS, FILE_LIST_DIRECTORY | FILE_TRAVERSE | SYNCHRONIZE)])[0])

    def test_any_right_that_can_change_an_entry_refuses_for_another_principal(self):
        for name, mask in {"add file": FILE_ADD_FILE, "add subdirectory": FILE_ADD_SUBDIRECTORY,
                           "delete child": FILE_DELETE_CHILD, "write attributes": FILE_WRITE_ATTRIBUTES,
                           "write EA": FILE_WRITE_EA, "delete": DELETE, "write DAC": WRITE_DAC,
                           "write owner": WRITE_OWNER, "generic write": GENERIC_WRITE, "generic all": GENERIC_ALL,
                           "maximum allowed": MAXIMUM_ALLOWED, "an unknown bit": 0x0000_0200,
                           "full control": FULL}.items():
            for sid in (USERS, EVERYONE, AUTH_USERS, OTHER, CREATOR_OWNER):
                with self.subTest(right=name, sid=sid):
                    accepted, reason = self.ok([allow(ME, FULL), allow(sid, mask | READ_CONTROL)])
                    self.assertFalse(accepted)
                    self.assertIn(sid, reason)

    def test_inherit_only_grants_count_because_they_reach_the_lock_files(self):
        # C:\\ gives Authenticated Users Modify on everything below it, inherit-only on C:\\ itself.
        self.assertFalse(self.ok([allow(ME, FULL), allow(AUTH_USERS, 0x001301BF, INHERIT_ONLY_CI_OI)])[0])

    def test_trusted_principals_may_hold_anything(self):
        for sid in (ME, SYSTEM, ADMINS, OWNER_RIGHTS):
            with self.subTest(sid=sid):
                self.assertTrue(self.ok([allow(sid, FULL | GENERIC_ALL)])[0])

    def test_owner_must_be_this_user_system_or_administrators(self):
        for owner in (ME, SYSTEM, ADMINS):
            self.assertTrue(self.ok([allow(ME, FULL)], owner=owner)[0], owner)
        accepted, reason = self.ok([allow(ME, FULL)], owner=OTHER)
        self.assertFalse(accepted)
        self.assertIn("owned by another principal", reason)

    def test_an_untrusted_owner_refuses_even_when_only_owner_rights_is_granted(self):
        # OWNER RIGHTS stands for the owner, so it is trusted only behind a trusted owner. The
        # owner check comes first, so adding it to the trusted set earlier is an equivalent change.
        self.assertFalse(self.ok([allow(OWNER_RIGHTS, FULL)], owner=OTHER)[0])

    def test_a_deny_entry_never_rescues_a_grant(self):
        self.assertFalse(self.ok([Ace(ACCESS_DENIED_ACE_TYPE, 0, FULL, USERS), allow(USERS, FILE_ADD_FILE)])[0])
        self.assertTrue(self.ok([allow(ME, FULL), Ace(ACCESS_DENIED_ACE_TYPE, 0, FULL, USERS)])[0])

    def test_everything_unreadable_refuses(self):
        self.assertFalse(evaluate_lease_dir_acl(ME, None, ME)[0], "NULL DACL")
        self.assertFalse(evaluate_lease_dir_acl(None, [], ME)[0], "no owner")
        self.assertFalse(evaluate_lease_dir_acl(ME, [], "not-a-sid")[0], "no process SID")
        self.assertFalse(self.ok(42)[0], "not iterable")
        self.assertFalse(self.ok(["not an ace"])[0])
        self.assertFalse(self.ok([Ace(5, 0, FULL, ME)])[0], "object ACE")
        self.assertFalse(self.ok([Ace(ACCESS_ALLOWED_ACE_TYPE, 0, True, ME)])[0], "bool mask")
        self.assertFalse(self.ok([Ace(ACCESS_ALLOWED_ACE_TYPE, 0, 1 << 32, ME)])[0], "mask out of range")
        self.assertFalse(self.ok([allow("S-1-5-٣٢", 0)])[0], "non-ASCII digits in a SID")

    def test_an_empty_dacl_is_private(self):
        self.assertTrue(self.ok([])[0])


class WiringTests(unittest.TestCase):
    """On Windows every lock path goes through _check_lease_dir, which must consult the reader."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lease = os.path.join(self.tmp.name, "lease")
        os.mkdir(self.lease, 0o700)
        self.seen = []

    def windows(self, verdict):
        def reader(directory):
            self.seen.append(str(directory))
            return verdict
        return patch.multiple(gpu_lease, _IS_WINDOWS=True, _windows_lease_dir_private=reader)

    def test_a_refused_acl_is_a_lease_error_on_every_entry_point(self):
        gpu = "GPU-6a7f0c2e-1b2d-4c3e-8f9a-0123456789ab"
        with self.windows((False, "S-1-5-11 can add, replace, delete or re-permission lease files")):
            for name, call in {
                "check_lease_dir": lambda: gpu_lease.check_lease_dir(self.lease),
                "acquire_gpu_lease": lambda: gpu_lease.acquire_gpu_lease(gpu, lease_dir=self.lease),
                "acquire_executor_lock": lambda: gpu_lease.acquire_executor_lock(gpu, lease_dir=self.lease),
                "resident_lock_path": lambda: gpu_lease.resident_lock_path(gpu, lease_dir=self.lease),
            }.items():
                with self.subTest(entry=name), self.assertRaisesRegex(gpu_lease.GpuLeaseError, "S-1-5-11"):
                    call()
        self.assertEqual(len(self.seen), 4)
        self.assertEqual(os.listdir(self.lease), [], "refused before any lock file was created")

    def test_an_accepted_acl_lets_the_lease_work(self):
        gpu = "GPU-6a7f0c2e-1b2d-4c3e-8f9a-0123456789ab"
        with self.windows((True, "private")):
            gpu_lease.check_lease_dir(self.lease)
        self.assertEqual(self.seen, [self.lease])

    def test_posix_never_calls_the_windows_reader(self):
        with patch.object(gpu_lease, "_windows_lease_dir_private", side_effect=AssertionError("called")):
            gpu_lease.check_lease_dir(self.lease)

    def test_the_reader_module_imports_without_windows_and_refuses_off_windows(self):
        from app.lease_dir_acl_windows import lease_dir_private
        if os.name != "nt":
            accepted, reason = lease_dir_private(self.lease)
            self.assertFalse(accepted)
            self.assertIn("only be read on Windows", reason)


if __name__ == "__main__":
    unittest.main()
