from __future__ import annotations

import ast
import importlib
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "devcontrol/src/kaliv_dev_control"
MODULE_PATH = PACKAGE_ROOT / "_tier_a_legacy_runner.py"
CORE_PATH = PACKAGE_ROOT / "_tier_a_execution_core.py"
AUTHORITY_PATH = PACKAGE_ROOT / "tier_a_authority.py"
EXPECTED_SYMBOLS = [
    ("_run_tier_a_launch_plan", "function"),
    ("run_verified_tier_a_command", "function"),
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
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result.append((node.name, "function"))
    return result


def _direct_imports(path: Path, module: str) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == module:
            result.extend(alias.name for alias in node.names)
    return result


class TierALegacyRunnerExtractionTests(unittest.TestCase):
    def test_runner_owns_exact_final_two_core_symbols(self) -> None:
        self.assertEqual(_owned_symbols(MODULE_PATH), EXPECTED_SYMBOLS)
        self.assertEqual(_owned_symbols(CORE_PATH), [])

    def test_core_source_imports_exact_runner_objects(self) -> None:
        self.assertEqual(
            _direct_imports(CORE_PATH, "_tier_a_legacy_runner"),
            [
                "_run_tier_a_launch_plan",
                "run_verified_tier_a_command",
            ],
        )
        script = textwrap.dedent(
            f"""
            import importlib
            import sys
            import types

            package = types.ModuleType("kaliv_dev_control")
            package.__package__ = "kaliv_dev_control"
            package.__path__ = [{str(PACKAGE_ROOT)!r}]
            sys.modules["kaliv_dev_control"] = package

            runner = importlib.import_module(
                "kaliv_dev_control._tier_a_legacy_runner"
            )
            core = importlib.import_module(
                "kaliv_dev_control._tier_a_execution_core"
            )
            assert core._run_tier_a_launch_plan is runner._run_tier_a_launch_plan
            assert (
                core.run_verified_tier_a_command
                is runner.run_verified_tier_a_command
            )
            """
        )
        subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(ROOT / "devcontrol/src")},
        )

    def test_modern_authority_removes_both_legacy_executor_names(self) -> None:
        runner = importlib.import_module(
            "kaliv_dev_control._tier_a_legacy_runner"
        )
        package = importlib.import_module("kaliv_dev_control")
        authority = importlib.import_module(
            "kaliv_dev_control.tier_a_authority"
        )
        facade = importlib.import_module(
            "kaliv_dev_control.tier_a_execution"
        )
        core = importlib.import_module(
            "kaliv_dev_control._tier_a_execution_core"
        )
        modern = importlib.import_module(
            "kaliv_dev_control.tier_a_execution_v3"
        )
        for name, _kind in EXPECTED_SYMBOLS:
            self.assertTrue(hasattr(runner, name))
            self.assertFalse(hasattr(core, name))
            self.assertFalse(hasattr(authority, name))
        self.assertIs(
            facade._run_tier_a_launch_plan,
            modern._run_tier_a_launch_plan,
        )
        self.assertIs(
            facade.run_verified_tier_a_command,
            modern.run_verified_tier_a_command,
        )
        self.assertIsNot(
            facade._run_tier_a_launch_plan,
            runner._run_tier_a_launch_plan,
        )
        self.assertIsNot(
            facade.run_verified_tier_a_command,
            runner.run_verified_tier_a_command,
        )
        self.assertFalse(hasattr(package, "_run_tier_a_launch_plan"))
        self.assertIs(
            package.run_verified_tier_a_command,
            facade.run_verified_tier_a_command,
        )

    def test_non_windows_execution_remains_fail_closed(self) -> None:
        runner = importlib.import_module(
            "kaliv_dev_control._tier_a_legacy_runner"
        )
        plan_module = importlib.import_module(
            "kaliv_dev_control._tier_a_legacy_plan"
        )
        catalog = importlib.import_module("kaliv_dev_control.catalog")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan = plan_module.TierALaunchPlan(
                task_id="ABC",
                task_sha256="a" * 64,
                base_sha="b" * 40,
                command_id="version.check",
                argv=(os.fspath(root / "python.exe"),),
                cwd=".",
                max_timeout_seconds=60,
                catalog_sha256="c" * 64,
                toolchain_sha256="d" * 64,
                lease_sha256="e" * 64,
                signed_report_sha256="f" * 64,
                workspace_root=os.fspath(root),
                workspace_root_sha256="1" * 64,
                executable_sha256="2" * 64,
                toolhost_sha256="3" * 64,
                boundary=catalog.IsolationBoundary.OS_ISOLATED,
                network_mode=catalog.NetworkMode.DENY,
            )
            with mock.patch.object(runner.os, "name", "posix"):
                with self.assertRaisesRegex(
                    runner.TierAExecutionError,
                    "requires Windows",
                ):
                    runner._run_tier_a_launch_plan(
                        plan,
                        control_plane_root=root,
                    )

    def test_runtime_staging_import_stays_local_to_verified_entrypoint(self) -> None:
        tree = ast.parse(
            MODULE_PATH.read_text(encoding="utf-8"),
            filename=str(MODULE_PATH),
        )
        top_level_runtime_imports = [
            node
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            and node.module == "runtime_staging"
        ]
        self.assertEqual(top_level_runtime_imports, [])
        function = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "run_verified_tier_a_command"
        )
        local_imports = [
            node
            for node in ast.walk(function)
            if isinstance(node, ast.ImportFrom)
            and node.module == "runtime_staging"
        ]
        self.assertEqual(len(local_imports), 1)
        self.assertEqual(
            [alias.name for alias in local_imports[0].names],
            ["TrustedRuntimeStager"],
        )

    def test_authority_bundle_contains_runner_once_before_core(self) -> None:
        authority = importlib.import_module(
            "kaliv_dev_control.tier_a_authority"
        )
        runner_path = (
            "devcontrol/src/kaliv_dev_control/_tier_a_legacy_runner.py"
        )
        core_path = (
            "devcontrol/src/kaliv_dev_control/_tier_a_execution_core.py"
        )
        bundle = authority._TIER_A_BUNDLE_FILES
        self.assertEqual(bundle.count(runner_path), 1)
        self.assertLess(bundle.index(runner_path), bundle.index(core_path))
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

    def test_runner_boundary_has_execution_but_no_remote_authority(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(MODULE_PATH))
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
        self.assertEqual(
            absolute,
            {"app", "os", "subprocess", "pathlib", "typing"},
        )
        self.assertEqual(
            relative,
            {
                "_tier_a_lease",
                "_tier_a_legacy_plan",
                "_tier_a_legacy_toolhost",
                "_tier_a_materialization",
                "_tier_a_path_authority",
                "catalog",
                "contract",
                "physical_isolation",
                "runtime_staging",
            },
        )
        self.assertNotIn("_tier_a_execution_core", source)
        forbidden = {
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
        names = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        }
        self.assertFalse(
            names
            & {
                "publish_once",
                "publish_stream_once",
                "sign",
                "private_key",
                "credential",
            }
        )


if __name__ == "__main__":
    unittest.main()
