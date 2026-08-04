from __future__ import annotations

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from test_slice10_runtime_staging import (
    COMMAND_ID,
    TrustedRuntimeStager,
    make_authority,
)


class RuntimeStagingConcurrencyH10HTests(unittest.TestCase):
    def test_twenty_four_concurrent_stages_share_one_exact_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task, registry, trusted, workspace, source = make_authority(
                Path(directory)
            )
            stager = TrustedRuntimeStager(trusted, workspace)
            barrier = threading.Barrier(24)

            def stage_once(_index: int):
                barrier.wait()
                return stager.stage(registry, task, COMMAND_ID)

            with ThreadPoolExecutor(max_workers=24) as pool:
                receipts = list(pool.map(stage_once, range(24)))

            first = receipts[0]
            self.assertTrue(all(receipt == first for receipt in receipts))

            staged = workspace.joinpath(*Path(first.staged_relative_path).parts)
            self.assertEqual(staged.read_bytes(), source.read_bytes())
            self.assertEqual(staged.stat().st_nlink, 1)

            published_files = sorted(
                path.resolve() for path in workspace.rglob("*") if path.is_file()
            )
            self.assertEqual(published_files, [staged.resolve()])
            self.assertEqual(list(workspace.rglob(".kaliv-stage-*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
