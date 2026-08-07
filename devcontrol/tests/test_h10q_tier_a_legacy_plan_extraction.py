from __future__ import annotations

import ast
import importlib
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = (
    ROOT
    / "devcontrol/src/kaliv_dev_control/_tier_a_legacy_plan.py"
)
CORE_PATH = (
    ROOT
    / "devcontrol/src/kaliv_dev_control/_tier_a_execution_core.py"
)
AUTHORITY_PATH = (
    ROOT / "devcontrol/src/kaliv_dev_control/tier_a_authority.py"
)
EXPECTED_SYMBOLS = [
    ("PLAN_SCHEMA", "constant"),
    ("_COMMAND_ID", "constant"),
    ("TierALaunchPlan", "class"),
    ("build_tier_a_launch_plan", "function"),
]


def _owned_symbols(path: Path) -> list[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[tuple[str, str]] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            result.extend(
                (target.id, "constant")
                for target in node.targets
                if isinstance(target, ast.Name)
            )
        elif isinstance(node, ast.ClassDef):
            result.append((node.name, "class"))
        elif isinstance(node, ast.FunctionDef):
            result.append((node.name, "function"))
    return result


def _direct_imports(path: Path, module: str) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == module:
            result.extend(alias.name for alias in node.names)
    return result


class TierALegacyPlanExtractionTests(unittest.TestCase):
    def test_module_owns_exact_four_plan_symbols(self) -> None:
        self.assertEqual(_owned_symbols(MODULE_PATH), EXPECTED_SYMBOLS)

    def test_core_physically_removes_and_reexports_exact_objects(self) -> None:
        self.assertEqual(
            _direct_imports(CORE_PATH, "_tier_a_legacy_plan"),
            [name for name, _kind in EXPECTED_SYMBOLS],
        )
        self.assertFalse(set(EXPECTED_SYMBOLS) & set(_owned_symbols(CORE_PATH)))
        module = importlib.import_module(
            "kaliv_dev_control._tier_a_legacy_plan"
        )
        core = importlib.import_module(
            "kaliv_dev_control._tier_a_execution_core"
        )
        for name, _kind in EXPECTED_SYMBOLS:
            self.assertIs(getattr(core, name), getattr(module, name))

    def test_plan_roundtrip_and_fail_closed_validation_are_unchanged(self) -> None:
        module = importlib.import_module(
            "kaliv_dev_control._tier_a_legacy_plan"
        )
        catalog = importlib.import_module("kaliv_dev_control.catalog")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan = module.TierALaunchPlan(
                task_id="ABC",
                task_sha256="a" * 64,
                base_sha="b" * 40,
                command_id="version.check",
                argv=(str(root / "python.exe"),),
                cwd=".",
                max_timeout_seconds=60,
                catalog_sha256="c" * 64,
                toolchain_sha256="d" * 64,
                lease_sha256="e" * 64,
                signed_report_sha256="f" * 64,
                workspace_root=str(root),
                workspace_root_sha256="1" * 64,
                executable_sha256="2" * 64,
                toolhost_sha256="3" * 64,
                boundary=catalog.IsolationBoundary.OS_ISOLATED,
                network_mode=catalog.NetworkMode.DENY,
            )
            self.assertEqual(
                module.TierALaunchPlan.from_mapping(plan.to_dict()),
                plan,
            )
            with self.assertRaisesRegex(
                module.TierAExecutionError, "unsupported"
            ):
                module.TierALaunchPlan.from_mapping(
                    {**plan.to_dict(), "schema": "wrong"}
                )

    def test_authority_bundle_contains_module_once_before_core(self) -> None:
        authority = importlib.import_module(
            "kaliv_dev_control.tier_a_authority"
        )
        module_path = (
            "devcontrol/src/kaliv_dev_control/"
            "_tier_a_legacy_plan.py"
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
        absolute: set[str] = set()
        relative: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                absolute.update(
                    alias.name.split(".", 1)[0] for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.module:
                    relative.add(node.module)
                elif node.module and node.module != "__future__":
                    absolute.add(node.module.split(".", 1)[0])
        self.assertEqual(
            absolute,
            {"os", "re", "dataclasses", "pathlib", "typing"},
        )
        self.assertEqual(
            relative,
            {
                "_tier_a_environment",
                "_tier_a_lease",
                "_tier_a_legacy_toolhost",
                "_tier_a_materialization",
                "_tier_a_path_authority",
                "catalog",
                "contract",
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
        self.assertFalse(relative & forbidden)

    def test_obsolete_executors_remain_absent(self) -> None:
        core = importlib.import_module(
            "kaliv_dev_control._tier_a_execution_core"
        )
        importlib.import_module("kaliv_dev_control.tier_a_authority")
        for name in (
            "_run_tier_a_launch_plan",
            "run_verified_tier_a_command",
        ):
            self.assertFalse(hasattr(core, name))


if __name__ == "__main__":
    unittest.main()
