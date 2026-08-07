from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from kaliv_dev_control.runtime_staging import (
    RuntimeStagingError,
    TrustedRuntimeStager,
)
from test_slice10_runtime_staging import COMMAND_ID, make_authority


class RuntimeStagingLaunchBindingTests(unittest.TestCase):
    def test_verified_receipt_rebinds_only_the_executable_path(self):
        with tempfile.TemporaryDirectory() as directory:
            task, registry, trusted, workspace, source = make_authority(
                Path(directory)
            )
            stager = TrustedRuntimeStager(trusted, workspace)
            receipt = stager.stage(registry, task, COMMAND_ID)
            staged_registry = stager.bind_for_launch(
                receipt,
                registry,
                task,
                COMMAND_ID,
            )

            original = registry.resolve(task, COMMAND_ID)
            staged = staged_registry.resolve(task, COMMAND_ID)
            staged_path = Path(staged.argv[0]).resolve()

            self.assertEqual(Path(original.argv[0]).resolve(), source)
            self.assertNotEqual(staged_path, source)
            self.assertEqual(
                staged_path,
                workspace.joinpath(*Path(receipt.staged_relative_path).parts),
            )
            self.assertEqual(staged_path.read_bytes(), source.read_bytes())
            self.assertEqual(staged.argv[1:], original.argv[1:])
            self.assertEqual(staged.cwd, original.cwd)
            self.assertEqual(staged.max_timeout_seconds, original.max_timeout_seconds)
            self.assertEqual(dict(staged.env), dict(original.env))
            self.assertEqual(staged_registry.lease, registry.lease)
            self.assertEqual(staged_registry.catalog, registry.catalog)
            self.assertEqual(staged_registry.toolchain, registry.toolchain)

    def test_tampered_staged_runtime_cannot_be_bound_for_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            task, registry, trusted, workspace, _ = make_authority(Path(directory))
            stager = TrustedRuntimeStager(trusted, workspace)
            receipt = stager.stage(registry, task, COMMAND_ID)
            staged = workspace.joinpath(*Path(receipt.staged_relative_path).parts)
            os.chmod(staged, 0o755)
            staged.write_bytes(b"tampered after staging")

            with self.assertRaisesRegex(RuntimeStagingError, "no longer match"):
                stager.bind_for_launch(receipt, registry, task, COMMAND_ID)

    def test_slice_exposes_no_process_launch_entrypoint(self):
        import kaliv_dev_control.runtime_staging as runtime_staging

        self.assertFalse(hasattr(runtime_staging, "run_verified_tier_a_command"))
        self.assertFalse(hasattr(runtime_staging, "_run_tier_a_launch_plan"))


if __name__ == "__main__":
    unittest.main()
