from __future__ import annotations

import ast
import dataclasses
import importlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = (
    ROOT / "devcontrol/src/kaliv_dev_control/_tier_a_materialization.py"
)
CORE_PATH = (
    ROOT / "devcontrol/src/kaliv_dev_control/_tier_a_execution_core.py"
)
AUTHORITY_PATH = (
    ROOT / "devcontrol/src/kaliv_dev_control/tier_a_authority.py"
)
EXPECTED = [
    "_LeaseCapturingVerifier",
    "LeasedCommandRegistry",
    "LeasedCatalogMaterializer",
]


def _owned_classes(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [node.name for node in tree.body if isinstance(node, ast.ClassDef)]


def _direct_imports(path: Path, module: str) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == module:
            result.extend(alias.name for alias in node.names)
    return result


class TierAMaterializationExtractionTests(unittest.TestCase):
    def test_module_owns_exact_three_mutable_service_classes(self) -> None:
        self.assertEqual(_owned_classes(MODULE_PATH), EXPECTED)
        tree = ast.parse(
            MODULE_PATH.read_text(encoding="utf-8"),
            filename=str(MODULE_PATH),
        )
        classes = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
        }
        for name in EXPECTED:
            self.assertEqual(classes[name].decorator_list, [])
        module = importlib.import_module(
            "kaliv_dev_control._tier_a_materialization"
        )
        for name in EXPECTED:
            self.assertFalse(dataclasses.is_dataclass(getattr(module, name)))

    def test_core_physically_removes_and_directly_reexports_classes(
        self,
    ) -> None:
        self.assertEqual(
            _direct_imports(CORE_PATH, "_tier_a_materialization"),
            EXPECTED,
        )
        self.assertFalse(set(EXPECTED) & set(_owned_classes(CORE_PATH)))
        module = importlib.import_module(
            "kaliv_dev_control._tier_a_materialization"
        )
        core = importlib.import_module(
            "kaliv_dev_control._tier_a_execution_core"
        )
        for name in EXPECTED:
            self.assertIs(getattr(core, name), getattr(module, name))

    def test_dc_l06_identity_chains_remain_exact(self) -> None:
        module = importlib.import_module(
            "kaliv_dev_control._tier_a_materialization"
        )
        core = importlib.import_module(
            "kaliv_dev_control._tier_a_execution_core"
        )
        authority = importlib.import_module(
            "kaliv_dev_control.tier_a_authority"
        )
        self.assertIs(
            core._LeaseCapturingVerifier,
            module._LeaseCapturingVerifier,
        )
        for name in (
            "LeasedCommandRegistry",
            "LeasedCatalogMaterializer",
        ):
            identity = getattr(module, name)
            self.assertIs(getattr(core, name), identity)
            self.assertIs(getattr(authority, name), identity)

    def test_constructor_guards_remain_fail_closed(self) -> None:
        module = importlib.import_module(
            "kaliv_dev_control._tier_a_materialization"
        )
        error = importlib.import_module(
            "kaliv_dev_control._tier_a_lease"
        ).TierAExecutionError
        with self.assertRaisesRegex(
            error,
            "requires WindowsPhysicalIsolationVerifier",
        ):
            module._LeaseCapturingVerifier(object())
        with self.assertRaisesRegex(
            error,
            "requires a command registry",
        ):
            module.LeasedCommandRegistry(
                object(),
                object(),
                task=object(),
                catalog=object(),
                toolchain=object(),
                attestation=object(),
            )
        with self.assertRaisesRegex(
            error,
            "requires WindowsPhysicalIsolationVerifier",
        ):
            module.LeasedCatalogMaterializer(object(), object())

    def test_bundle_contains_module_once_before_importing_core(self) -> None:
        authority = importlib.import_module(
            "kaliv_dev_control.tier_a_authority"
        )
        module_path = (
            "devcontrol/src/kaliv_dev_control/"
            "_tier_a_materialization.py"
        )
        core_path = (
            "devcontrol/src/kaliv_dev_control/"
            "_tier_a_execution_core.py"
        )
        bundle = authority._TIER_A_BUNDLE_FILES
        self.assertEqual(bundle.count(module_path), 1)
        self.assertLess(bundle.index(module_path), bundle.index(core_path))
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

    def test_module_boundary_has_no_reverse_or_remote_authority(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(MODULE_PATH))
        absolute_imports: set[str] = set()
        relative_modules: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.level:
                if node.module:
                    relative_modules.add(node.module)
            elif node.module and node.module != "__future__":
                absolute_imports.add(node.module.split(".", 1)[0])
        self.assertEqual(absolute_imports, set())
        self.assertEqual(
            relative_modules,
            {
                "_tier_a_lease",
                "catalog",
                "commands",
                "contract",
                "physical_isolation",
            },
        )
        self.assertNotIn("_tier_a_execution_core", source)
        forbidden = {
            "subprocess",
            "socket",
            "requests",
            "urllib",
            "http",
            "git",
            "github",
            "durable_publication",
            "streaming_publication",
        }
        self.assertFalse(relative_modules & forbidden)
        call_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
        }
        self.assertFalse(
            call_names
            & {
                "open",
                "exec",
                "eval",
                "compile",
                "create_once_file",
                "publish_stream_once",
            }
        )

    def test_obsolete_executors_remain_absent_from_dc_l06_core(self) -> None:
        core = importlib.import_module(
            "kaliv_dev_control._tier_a_execution_core"
        )
        for name in (
            "_run_tier_a_launch_plan",
            "run_verified_tier_a_command",
        ):
            self.assertFalse(hasattr(core, name))


if __name__ == "__main__":
    unittest.main()
