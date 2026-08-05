from __future__ import annotations

import ast
import importlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEASE_PATH = ROOT / "devcontrol/src/kaliv_dev_control/_tier_a_lease.py"
CORE_PATH = ROOT / "devcontrol/src/kaliv_dev_control/_tier_a_execution_core.py"
MATERIALIZATION_PATH = (
    ROOT / "devcontrol/src/kaliv_dev_control/_tier_a_materialization.py"
)
MOVED = [
    "LEASE_SCHEMA",
    "_HEX40",
    "_HEX64",
    "_TASK_ID",
    "TierAExecutionError",
    "_canonical",
    "_sha256",
    "_task_sha",
    "TierAExecutionLease",
]
CORE_IMPORT_ORDER = [
    "LEASE_SCHEMA",
    "TierAExecutionError",
    "TierAExecutionLease",
    "_HEX40",
    "_HEX64",
    "_TASK_ID",
    "_canonical",
    "_sha256",
    "_task_sha",
]


def _owned_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            result.extend(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
        elif isinstance(node, ast.ClassDef):
            result.append(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result.append(node.name)
    return result


def _direct_imports(path: Path, module: str) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == module:
            return [alias.name for alias in node.names]
    return []


class TierALeaseModelExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lease = importlib.import_module("kaliv_dev_control._tier_a_lease")
        cls.core = importlib.import_module("kaliv_dev_control._tier_a_execution_core")
        cls.authority = importlib.import_module("kaliv_dev_control.tier_a_authority")
        cls.facade = importlib.import_module("kaliv_dev_control.tier_a_execution")
        cls.package = importlib.import_module("kaliv_dev_control")

    def test_lease_module_owns_exact_cohesive_model(self) -> None:
        self.assertEqual(_owned_names(LEASE_PATH), MOVED)
        self.assertEqual(self.lease.TierAExecutionLease.__module__, "kaliv_dev_control._tier_a_lease")
        self.assertEqual(self.lease.TierAExecutionError.__module__, "kaliv_dev_control._tier_a_lease")

    def test_core_physically_owns_none_and_reexports_exact_objects(self) -> None:
        self.assertFalse(set(_owned_names(CORE_PATH)) & set(MOVED))
        self.assertEqual(_direct_imports(CORE_PATH, "_tier_a_lease"), CORE_IMPORT_ORDER)
        for symbol in MOVED:
            self.assertIs(getattr(self.core, symbol), getattr(self.lease, symbol))

    def test_public_lease_and_error_identity_is_unchanged(self) -> None:
        for symbol in ("TierAExecutionError", "TierAExecutionLease"):
            identity = getattr(self.lease, symbol)
            self.assertIs(getattr(self.authority, symbol), identity)
            self.assertIs(getattr(self.facade, symbol), identity)
            self.assertIs(getattr(self.package, symbol), identity)

    def test_extraction_left_no_stray_dataclass_decorator(self) -> None:
        tree = ast.parse(
            MATERIALIZATION_PATH.read_text(encoding="utf-8"),
            filename=str(MATERIALIZATION_PATH),
        )
        classes = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
        }
        self.assertEqual(classes["_LeaseCapturingVerifier"].decorator_list, [])
        self.assertEqual(classes["LeasedCommandRegistry"].decorator_list, [])
        self.assertEqual(classes["LeasedCatalogMaterializer"].decorator_list, [])

    def test_lease_mapping_validation_remains_fail_closed(self) -> None:
        with self.assertRaises(self.lease.TierAExecutionError):
            self.lease.TierAExecutionLease.from_mapping({})
        with self.assertRaises(self.lease.TierAExecutionError):
            self.lease.TierAExecutionLease.from_mapping("not-an-object")

    def test_lease_module_adds_no_runtime_or_publication_authority(self) -> None:
        source = LEASE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(LEASE_PATH))
        forbidden = {"subprocess", "socket", "urllib", "http", "requests", "git", "github", "os", "pathlib"}
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
