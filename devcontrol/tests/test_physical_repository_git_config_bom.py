from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import kaliv_dev_control._improvement_physical_runtime_direct_git as direct_git
import kaliv_dev_control._improvement_physical_runtime_host_control as host_runtime


class PhysicalRepositoryGitConfigBomTests(unittest.TestCase):
    def test_bom_prefixed_include_section_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory).resolve() / "config"
            config.write_bytes(
                b"\xef\xbb\xbf[include]\n"
                b"\tpath = /tmp/caller-controlled-gitconfig\n"
            )

            with self.assertRaisesRegex(
                host_runtime.PhysicalHostRuntimeError,
                "includes external state",
            ):
                direct_git._reject_config_includes(config)


if __name__ == "__main__":
    unittest.main()
