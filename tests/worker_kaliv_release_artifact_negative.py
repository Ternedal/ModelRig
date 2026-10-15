"""Adversarial filesystem and attestation checks with the real structural gate."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from worker_kaliv_release_artifact_preflight import PreflightFixture, module


class ArtifactNegativeTests(PreflightFixture):
    def test_incomplete_and_extra_gate_sets(self):
        for change in ("missing", "extra"):
            with self.subTest(change=change):
                items = copy.deepcopy(self.attestations)
                if change == "missing":
                    del items[self.first]
                else:
                    items["invented_gate"] = dict(self.item)
                with self.assertRaisesRegex(module.AttestationError, "exactly cover"):
                    module.preflight(self.manifest, items, self.root)

    def test_inexact_attestation_fields(self):
        for item in (None, [], {**self.item, "extra": True},
                     {key: value for key, value in self.item.items() if key != "path"}):
            with self.subTest(item=item):
                self.attestations[self.first] = item
                with self.assertRaisesRegex(module.AttestationError, "invalid attestation fields"):
                    self.verify()

    def test_reference_and_digest_validation(self):
        original = copy.deepcopy(self.item)
        cases = (
            ("reference", "receipt:wrong", "reference mismatch"),
            ("reference", [], "reference mismatch"),
            ("sha256", "f" * 64, "byte hash mismatch"),
            ("sha256", "A" * 64, "invalid SHA-256"),
            ("sha256", "a" * 63, "invalid SHA-256"),
            ("sha256", None, "invalid SHA-256"),
            ("sha256", [], "invalid SHA-256"),
        )
        for field, value, reason in cases:
            with self.subTest(field=field, value=value):
                self.item.clear()
                self.item.update(original)
                self.item[field] = value
                with self.assertRaisesRegex(module.AttestationError, reason):
                    self.verify()

    def test_missing_file_and_directory_are_not_evidence(self):
        self.path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.verify()
        self.path.mkdir()
        with self.assertRaisesRegex(module.AttestationError, "unsafe or missing artifact"):
            self.verify()

    def symlink_or_skip(self, link, target, *, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError):
            self.skipTest("filesystem cannot create symlinks")

    def test_leaf_symlink_to_internal_file_is_rejected(self):
        link = self.root / "linked.json"
        self.symlink_or_skip(link, self.path)
        self.item["path"] = link.name
        with self.assertRaisesRegex(module.AttestationError, "symlink artifact path"):
            self.verify()

    def test_leaf_symlink_to_outside_file_is_rejected(self):
        outside = self.directory / "outside.json"
        outside.write_bytes(self.path.read_bytes())
        self.path.unlink()
        self.symlink_or_skip(self.path, outside)
        with self.assertRaisesRegex(module.AttestationError, "symlink artifact path"):
            self.verify()

    def test_directory_symlinks_inside_and_outside_are_rejected(self):
        for target in (self.root, self.directory):
            with self.subTest(target=target):
                link = self.root / "directory-link"
                self.symlink_or_skip(link, target, directory=True)
                self.item["path"] = f"{link.name}/{self.path.name}"
                with self.assertRaisesRegex(module.AttestationError, "symlink artifact path"):
                    self.verify()
                link.unlink()

    def test_windows_reparse_attribute_is_rejected(self):
        original = Path.lstat

        def reparse(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == self.path:
                return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
            return info

        with patch.object(Path, "lstat", reparse):
            with self.assertRaisesRegex(module.AttestationError, "reparse point"):
                self.verify()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO files unavailable")
    def test_named_pipe_is_rejected_without_blocking(self):
        self.path.unlink()
        os.mkfifo(self.path)
        with self.assertRaisesRegex(module.AttestationError, "unsafe or missing artifact"):
            self.verify()

    def test_artifact_size_boundary(self):
        # A small injected budget tests both boundaries without allocating
        # sixteen megabytes for each ordinary regression execution.
        with patch.object(module, "MAX_BYTES", 1024):
            data = b"x" * 1024
            self.path.write_bytes(data)
            self.item["sha256"] = hashlib.sha256(data).hexdigest()
            self.assertEqual(self.verify()["state"], "BYTE_HASHES_VERIFIED_ONLY")
            self.path.write_bytes(data + b"x")
            with self.assertRaisesRegex(module.AttestationError, "exceeds size limit"):
                self.verify()

    def test_file_growth_during_read_obeys_byte_budget(self):
        original_fstat = os.fstat
        changed = False

        def grow(fd):
            nonlocal changed
            info = original_fstat(fd)
            if not changed:
                self.path.write_bytes(b"x" * 2048)
                changed = True
            return info

        with patch.object(module, "MAX_BYTES", 1024):
            with patch.object(module.os, "fstat", side_effect=grow):
                with self.assertRaisesRegex(module.AttestationError, "exceeds size limit"):
                    self.verify()

    def test_cli_missing_input_returns_json(self):
        missing = self.directory / "missing.json"
        completed = subprocess.run(
            [sys.executable, str(Path(module.__file__)), str(missing),
             str(missing), str(self.root)],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(completed.stderr, "")
        result = json.loads(completed.stdout)
        self.assertEqual(result["state"], "INVALID")
        self.assertIs(result["release_ready"], False)
        self.assertIs(result["production_activation"], False)


if __name__ == "__main__":
    unittest.main()

