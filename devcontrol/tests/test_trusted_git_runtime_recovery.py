from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kaliv_dev_control.durable_publication import DurablePublicationError
from kaliv_dev_control.trusted_git_runtime import (
    TRUSTED_GIT_RUNTIME_RECOVERY_SCHEMA,
    TrustedGitRuntimeError,
    TrustedGitRuntimeRecoveryReceipt,
    capture_trusted_git_runtime_manifest,
    load_trusted_git_runtime_receipt,
    recover_trusted_git_runtime_transaction,
    stage_trusted_git_runtime,
)
from kaliv_dev_control.trusted_git_runtime_model import _transaction_id

ROOT = Path(__file__).resolve().parents[2]
AUTHORIZATION = "a" * 64
OPERATOR = "operator.recovery"
RECOVERED_AT = "2026-08-04T11:00:00Z"

SCRIPT = b'''#!/bin/sh
printf 'git version recovery-test-1\n'
'''
HELPER = b'''#!/bin/sh
printf 'trusted-helper\n'
'''


def require_posix() -> None:
    if os.name == "nt":
        raise unittest.SkipTest("portable recovery fixture uses POSIX executables")


def make_source(root: Path) -> Path:
    source = root / "source"
    (source / "bin").mkdir(parents=True)
    (source / "libexec" / "git-core").mkdir(parents=True)
    (source / "lib").mkdir(parents=True)
    executable = source / "bin" / "git"
    helper = source / "libexec" / "git-core" / "git-helper"
    executable.write_bytes(SCRIPT)
    helper.write_bytes(HELPER)
    (source / "lib" / "runtime.so").write_bytes(b"library-bytes")
    executable.chmod(0o755)
    helper.chmod(0o755)
    return source.resolve()


def capture(source: Path):
    return capture_trusted_git_runtime_manifest(
        source,
        executable_relative_path="bin/git",
        exec_path_relative_path="libexec/git-core",
        path_relative_directories=("bin", "libexec/git-core", "lib"),
    )


def paths(staging: Path, manifest):
    transaction_id = _transaction_id(manifest.sha256)
    return (
        staging / transaction_id,
        staging / f".{transaction_id}.pending",
        staging / f".{transaction_id}.lock",
    )


class TrustedGitRuntimeRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        require_posix()

    def test_prepared_crash_requires_explicit_publish_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = make_source(root)
            staging = (root / "staging").resolve()
            staging.mkdir()
            manifest = capture(source)
            final, pending, lock = paths(staging, manifest)

            with patch(
                "kaliv_dev_control.trusted_git_runtime_staging.rename_directory_no_replace",
                side_effect=DurablePublicationError("simulated crash before commit"),
            ):
                with self.assertRaisesRegex(
                    TrustedGitRuntimeError,
                    "explicit recovery",
                ):
                    stage_trusted_git_runtime(
                        manifest,
                        source_root=source,
                        staging_root=staging,
                    )

            self.assertFalse(final.exists())
            self.assertTrue(pending.is_dir())
            self.assertTrue(lock.is_file())
            receipt = recover_trusted_git_runtime_transaction(
                manifest,
                staging_root=staging,
                action="publish_prepared",
                recovery_authorization_sha256=AUTHORIZATION,
                operator_actor_id=OPERATOR,
                recovered_at_utc=RECOVERED_AT,
            )
            self.assertEqual(receipt.state_before, "prepared")
            self.assertEqual(receipt.state_after, "committed")
            self.assertTrue(receipt.final_root_verified)
            self.assertFalse(pending.exists())
            self.assertFalse(lock.exists())
            self.assertEqual(
                load_trusted_git_runtime_receipt(final).manifest.sha256,
                manifest.sha256,
            )

    def test_invalid_recovery_authority_never_mutates_prepared_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = make_source(root)
            staging = (root / "staging").resolve()
            staging.mkdir()
            manifest = capture(source)
            final, pending, lock = paths(staging, manifest)
            with patch(
                "kaliv_dev_control.trusted_git_runtime_staging.rename_directory_no_replace",
                side_effect=DurablePublicationError("simulated crash before commit"),
            ):
                with self.assertRaises(TrustedGitRuntimeError):
                    stage_trusted_git_runtime(
                        manifest,
                        source_root=source,
                        staging_root=staging,
                    )

            invalid_cases = (
                {"recovery_authorization_sha256": "invalid"},
                {"operator_actor_id": "!"},
                {"recovered_at_utc": "2026-99-99T99:99:99Z"},
            )
            for replacement in invalid_cases:
                arguments = {
                    "recovery_authorization_sha256": AUTHORIZATION,
                    "operator_actor_id": OPERATOR,
                    "recovered_at_utc": RECOVERED_AT,
                }
                arguments.update(replacement)
                with self.subTest(replacement=replacement):
                    with self.assertRaises(TrustedGitRuntimeError):
                        recover_trusted_git_runtime_transaction(
                            manifest,
                            staging_root=staging,
                            action="publish_prepared",
                            **arguments,
                        )
                    self.assertFalse(final.exists())
                    self.assertTrue(pending.is_dir())
                    self.assertTrue(lock.is_file())

    def test_preexisting_pending_state_is_preserved_for_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = make_source(root)
            staging = (root / "staging").resolve()
            staging.mkdir()
            manifest = capture(source)
            _, pending, lock = paths(staging, manifest)
            pending.mkdir()
            marker = pending / "partial.bin"
            marker.write_bytes(b"partial")

            with self.assertRaisesRegex(TrustedGitRuntimeError, "explicit recovery"):
                stage_trusted_git_runtime(
                    manifest,
                    source_root=source,
                    staging_root=staging,
                )
            self.assertEqual(marker.read_bytes(), b"partial")
            self.assertFalse(lock.exists())

    def test_discard_release_and_acknowledge_transitions_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = make_source(root)
            staging = (root / "staging").resolve()
            staging.mkdir()
            manifest = capture(source)
            final, pending, lock = paths(staging, manifest)

            pending.mkdir()
            (pending / "partial.bin").write_bytes(b"partial")
            lock.write_text(manifest.sha256 + "\n", encoding="ascii")
            discarded = recover_trusted_git_runtime_transaction(
                manifest,
                staging_root=staging,
                action="discard_pending",
                recovery_authorization_sha256=AUTHORIZATION,
                operator_actor_id=OPERATOR,
                recovered_at_utc=RECOVERED_AT,
            )
            self.assertEqual((discarded.state_before, discarded.state_after), ("partial", "absent"))
            self.assertFalse(pending.exists())
            self.assertFalse(lock.exists())

            lock.write_text(manifest.sha256 + "\n", encoding="ascii")
            released = recover_trusted_git_runtime_transaction(
                manifest,
                staging_root=staging,
                action="release_reservation",
                recovery_authorization_sha256=AUTHORIZATION,
                operator_actor_id=OPERATOR,
                recovered_at_utc=RECOVERED_AT,
            )
            self.assertEqual((released.state_before, released.state_after), ("reserved", "absent"))
            self.assertFalse(lock.exists())

            transaction = stage_trusted_git_runtime(
                manifest,
                source_root=source,
                staging_root=staging,
            )
            self.assertEqual(transaction, final)
            lock.write_text(manifest.sha256 + "\n", encoding="ascii")
            acknowledged = recover_trusted_git_runtime_transaction(
                manifest,
                staging_root=staging,
                action="acknowledge_committed",
                recovery_authorization_sha256=AUTHORIZATION,
                operator_actor_id=OPERATOR,
                recovered_at_utc=RECOVERED_AT,
            )
            self.assertEqual(
                (acknowledged.state_before, acknowledged.state_after),
                ("committed_locked", "committed"),
            )
            self.assertTrue(acknowledged.final_root_verified)
            self.assertTrue(final.is_dir())
            self.assertFalse(lock.exists())

    def test_recovery_receipt_is_canonical_and_matches_schema_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = make_source(root)
            staging = (root / "staging").resolve()
            staging.mkdir()
            manifest = capture(source)
            _, _, lock = paths(staging, manifest)
            lock.write_text(manifest.sha256 + "\n", encoding="ascii")
            receipt = recover_trusted_git_runtime_transaction(
                manifest,
                staging_root=staging,
                action="release_reservation",
                recovery_authorization_sha256=AUTHORIZATION,
                operator_actor_id=OPERATOR,
                recovered_at_utc=RECOVERED_AT,
            )
            self.assertEqual(receipt.schema, TRUSTED_GIT_RUNTIME_RECOVERY_SCHEMA)
            self.assertEqual(
                TrustedGitRuntimeRecoveryReceipt.from_mapping(
                    json.loads(receipt.canonical_json())
                ),
                receipt,
            )
            schema = json.loads(
                (
                    ROOT
                    / "devcontrol"
                    / "schemas"
                    / "development-trusted-git-runtime-recovery-receipt-v1.schema.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(set(schema["required"]), set(receipt.to_dict()))
            self.assertEqual(
                schema["properties"]["schema"]["const"],
                TRUSTED_GIT_RUNTIME_RECOVERY_SCHEMA,
            )


if __name__ == "__main__":
    unittest.main()
