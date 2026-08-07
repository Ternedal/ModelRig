from __future__ import annotations

import ast
import importlib
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "devcontrol/src/kaliv_dev_control"


class TierAEnvironmentExtractionH10KTests(unittest.TestCase):
    def test_core_and_authority_reexport_exact_extracted_objects(self) -> None:
        environment = importlib.import_module(
            "kaliv_dev_control._tier_a_environment"
        )
        core = importlib.import_module(
            "kaliv_dev_control._tier_a_execution_core"
        )
        authority = importlib.import_module(
            "kaliv_dev_control.tier_a_authority"
        )
        self.assertIs(
            core.TIER_A_APPLICATION_ENVIRONMENT,
            environment.TIER_A_APPLICATION_ENVIRONMENT,
        )
        self.assertIs(
            core._validated_application_env,
            environment._validated_application_env,
        )
        self.assertIs(
            authority.TIER_A_APPLICATION_ENVIRONMENT,
            environment.TIER_A_APPLICATION_ENVIRONMENT,
        )

    def test_validator_preserves_fail_closed_behavior(self) -> None:
        environment = importlib.import_module(
            "kaliv_dev_control._tier_a_environment"
        )
        core = importlib.import_module(
            "kaliv_dev_control._tier_a_execution_core"
        )
        clean = environment._validated_application_env(
            {"modelrig_devcontrol": "1", "CI": "1"}
        )
        self.assertIsInstance(clean, types.MappingProxyType)
        self.assertEqual(
            dict(clean),
            {"CI": "1", "MODELRIG_DEVCONTROL": "1"},
        )
        with self.assertRaises(core.TierAExecutionError):
            environment._validated_application_env({"PATH": "unsafe"})
        with self.assertRaises(core.TierAExecutionError):
            environment._validated_application_env({"CI": "0"})

    def test_core_physically_no_longer_owns_environment_policy(self) -> None:
        core_path = PKG / "_tier_a_execution_core.py"
        tree = ast.parse(
            core_path.read_text(encoding="utf-8"),
            filename=str(core_path),
        )
        owned = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        }
        assigned = {
            target.id
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        self.assertNotIn("_validated_application_env", owned)
        self.assertNotIn("TIER_A_APPLICATION_ENVIRONMENT", assigned)
        imports = [
            node
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            and node.module == "_tier_a_environment"
        ]
        self.assertEqual(len(imports), 1)
        self.assertEqual(
            {alias.name for alias in imports[0].names},
            {
                "TIER_A_APPLICATION_ENVIRONMENT",
                "_validated_application_env",
            },
        )

    def test_extracted_module_is_in_exact_authority_bundle(self) -> None:
        authority = importlib.import_module(
            "kaliv_dev_control.tier_a_authority"
        )
        path = "devcontrol/src/kaliv_dev_control/_tier_a_environment.py"
        self.assertIn(path, authority._TIER_A_BUNDLE_FILES)
        self.assertLess(
            authority._TIER_A_BUNDLE_FILES.index(path),
            authority._TIER_A_BUNDLE_FILES.index(
                "devcontrol/src/kaliv_dev_control/_tier_a_execution_core.py"
            ),
        )

    def test_environment_module_adds_no_remote_or_process_authority(self) -> None:
        path = PKG / "_tier_a_environment.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        forbidden = {
            "subprocess",
            "socket",
            "httpx",
            "requests",
            "urllib",
            "git",
            "github",
        }
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(
                    alias.name.split(".")[0] for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertTrue(forbidden.isdisjoint(imported))


if __name__ == "__main__":
    unittest.main()
