from __future__ import annotations

import ast
import hashlib
import importlib
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "devcontrol/src/kaliv_dev_control/_tier_a_legacy_toolhost.py"
CORE_PATH = ROOT / "devcontrol/src/kaliv_dev_control/_tier_a_execution_core.py"


def _owned_symbols(path: Path) -> list[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[tuple[str, str]] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            result.extend((target.id, "constant") for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.FunctionDef):
            result.append((node.name, "function"))
    return result


class TierALegacyToolhostExtractionTests(unittest.TestCase):
    def test_module_owns_only_bundle_and_hash_function(self) -> None:
        self.assertEqual(_owned_symbols(MODULE_PATH), [("_TIER_A_BUNDLE_FILES", "constant"), ("tier_a_toolhost_sha256", "function")])
        module = importlib.import_module("kaliv_dev_control._tier_a_legacy_toolhost")
        authority = importlib.import_module("kaliv_dev_control.tier_a_authority")
        self.assertEqual(module._TIER_A_BUNDLE_FILES, authority._TIER_A_BUNDLE_FILES)
        self.assertEqual(len(module._TIER_A_BUNDLE_FILES), 50)
        self.assertEqual(len(module._TIER_A_BUNDLE_FILES), len(set(module._TIER_A_BUNDLE_FILES)))

    def test_core_reexports_exact_objects_without_executor(self) -> None:
        module = importlib.import_module("kaliv_dev_control._tier_a_legacy_toolhost")
        core = importlib.import_module("kaliv_dev_control._tier_a_execution_core")
        self.assertIs(core._TIER_A_BUNDLE_FILES, module._TIER_A_BUNDLE_FILES)
        self.assertIs(core.tier_a_toolhost_sha256, module.tier_a_toolhost_sha256)
        for name in ("_run_tier_a_launch_plan", "run_verified_tier_a_command"):
            self.assertFalse(hasattr(core, name), name)

    def test_hash_behavior_is_v7_exact_and_fail_closed(self) -> None:
        module = importlib.import_module("kaliv_dev_control._tier_a_legacy_toolhost")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = hashlib.sha256()
            expected.update(b"kaliv-tier-a-toolhost/v7\0")
            for index, relative in enumerate(module._TIER_A_BUNDLE_FILES):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                payload = f"{index}:{relative}".encode("utf-8")
                path.write_bytes(payload)
                expected.update(relative.encode("utf-8"))
                expected.update(b"\0")
                expected.update(len(payload).to_bytes(8, "big"))
                expected.update(payload)
            self.assertEqual(module.tier_a_toolhost_sha256(root), expected.hexdigest())
            (root / module._TIER_A_BUNDLE_FILES[-1]).unlink()
            with self.assertRaisesRegex(module.TierAExecutionError, "missing or unsafe"):
                module.tier_a_toolhost_sha256(root)

    def test_module_import_boundary_has_no_process_or_remote_authority(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"), filename=str(MODULE_PATH))
        absolute: set[str] = set()
        relative: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                absolute.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.module:
                    relative.add(node.module)
                elif node.module and node.module != "__future__":
                    absolute.add(node.module.split(".", 1)[0])
        self.assertEqual(absolute, {"hashlib", "pathlib"})
        self.assertEqual(relative, {"_tier_a_lease", "_tier_a_path_authority"})
        self.assertFalse(absolute & {"subprocess", "socket", "requests", "urllib", "http"})
        self.assertFalse(relative & {"github_read", "durable_publication", "streaming_publication"})


if __name__ == "__main__":
    unittest.main()
