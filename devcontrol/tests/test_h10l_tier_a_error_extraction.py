from __future__ import annotations

import ast
import importlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEASE_PATH = ROOT / "devcontrol/src/kaliv_dev_control/_tier_a_lease.py"
ENVIRONMENT_PATH = ROOT / "devcontrol/src/kaliv_dev_control/_tier_a_environment.py"
CORE_PATH = ROOT / "devcontrol/src/kaliv_dev_control/_tier_a_execution_core.py"
AUTHORITY_PATH = ROOT / "devcontrol/src/kaliv_dev_control/tier_a_authority.py"
LEASE_REPOSITORY_PATH = "devcontrol/src/kaliv_dev_control/_tier_a_lease.py"
ENVIRONMENT_REPOSITORY_PATH = "devcontrol/src/kaliv_dev_control/_tier_a_environment.py"
CORE_REPOSITORY_PATH = "devcontrol/src/kaliv_dev_control/_tier_a_execution_core.py"


def _direct_imports(path: Path, module: str) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == module:
            result.extend(alias.name for alias in node.names)
    return result


class TierAErrorExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lease = importlib.import_module("kaliv_dev_control._tier_a_lease")
        cls.environment = importlib.import_module(
            "kaliv_dev_control._tier_a_environment"
        )
        cls.core = importlib.import_module(
            "kaliv_dev_control._tier_a_execution_core"
        )
        cls.authority = importlib.import_module(
            "kaliv_dev_control.tier_a_authority"
        )
        cls.facade = importlib.import_module(
            "kaliv_dev_control.tier_a_execution"
        )
        cls.package = importlib.import_module("kaliv_dev_control")

    def test_error_identity_is_exact_across_every_surface(self) -> None:
        identity = self.lease.TierAExecutionError
        self.assertIs(self.core.TierAExecutionError, identity)
        self.assertIs(self.authority.TierAExecutionError, identity)
        self.assertIs(self.facade.TierAExecutionError, identity)
        self.assertIs(self.package.TierAExecutionError, identity)
        self.assertEqual(identity.__module__, "kaliv_dev_control._tier_a_lease")

    def test_core_no_longer_defines_error_and_reexports_directly(self) -> None:
        tree = ast.parse(CORE_PATH.read_text(encoding="utf-8"), filename=str(CORE_PATH))
        self.assertFalse(
            any(
                isinstance(node, ast.ClassDef)
                and node.name == "TierAExecutionError"
                for node in tree.body
            )
        )
        self.assertIn(
            "TierAExecutionError",
            _direct_imports(CORE_PATH, "_tier_a_lease"),
        )

    def test_environment_has_no_reverse_dependency_on_legacy_core(self) -> None:
        self.assertEqual(
            _direct_imports(ENVIRONMENT_PATH, "_tier_a_lease"),
            ["TierAExecutionError"],
        )
        tree = ast.parse(
            ENVIRONMENT_PATH.read_text(encoding="utf-8"),
            filename=str(ENVIRONMENT_PATH),
        )
        self.assertFalse(
            any(
                isinstance(node, ast.ImportFrom)
                and node.module == "_tier_a_execution_core"
                for node in ast.walk(tree)
            )
        )
        with self.assertRaises(self.lease.TierAExecutionError):
            self.environment._validated_application_env({"CI": "0"})

    def test_bundle_contains_lease_once_before_environment_and_core(self) -> None:
        bundle = tuple(self.authority._TIER_A_BUNDLE_FILES)
        for path in (
            LEASE_REPOSITORY_PATH,
            ENVIRONMENT_REPOSITORY_PATH,
            CORE_REPOSITORY_PATH,
        ):
            self.assertEqual(bundle.count(path), 1)
        self.assertLess(
            bundle.index(LEASE_REPOSITORY_PATH),
            bundle.index(ENVIRONMENT_REPOSITORY_PATH),
        )
        self.assertLess(
            bundle.index(ENVIRONMENT_REPOSITORY_PATH),
            bundle.index(CORE_REPOSITORY_PATH),
        )
        tree = ast.parse(
            AUTHORITY_PATH.read_text(encoding="utf-8"),
            filename=str(AUTHORITY_PATH),
        )
        literal = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name)
                and target.id == "_TIER_A_BUNDLE_FILES"
                for target in node.targets
            ):
                literal = ast.literal_eval(node.value)
                break
        self.assertEqual(literal, bundle)

    def test_lease_module_has_no_runtime_or_publication_authority(self) -> None:
        source = LEASE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(LEASE_PATH))
        owned = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        self.assertEqual(
            owned,
            [
                "TierAExecutionError",
                "_canonical",
                "_sha256",
                "_task_sha",
                "TierAExecutionLease",
            ],
        )
        forbidden = {
            "subprocess",
            "socket",
            "urllib",
            "http",
            "requests",
            "git",
            "github",
            "os",
            "pathlib",
        }
        observed: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                observed.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                observed.add(node.module.split(".", 1)[0])
        self.assertFalse(observed & forbidden)
        self.assertNotIn("open(", source)


if __name__ == "__main__":
    unittest.main()
