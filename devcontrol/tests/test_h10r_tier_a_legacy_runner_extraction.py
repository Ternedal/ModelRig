from __future__ import annotations

import ast
import importlib
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "devcontrol/src/kaliv_dev_control"
LEGACY_PATH = PACKAGE_ROOT / "_tier_a_legacy_runner.py"
MODERN_PATH = PACKAGE_ROOT / "tier_a_execution_v3.py"
AUTHORITY_PATH = PACKAGE_ROOT / "tier_a_authority.py"
LEGACY_SYMBOLS = [
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
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            result.append((node.target.id, "constant"))
        elif isinstance(node, ast.ClassDef):
            result.append((node.name, "class"))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result.append((node.name, "function"))
    return result


class TierAExecutorBoundaryTests(unittest.TestCase):
    def test_legacy_runner_retains_exact_two_execution_functions(self) -> None:
        self.assertEqual(_owned_symbols(LEGACY_PATH), LEGACY_SYMBOLS)

    def test_modern_executor_is_the_only_closure_bound_implementation(self) -> None:
        symbols = set(_owned_symbols(MODERN_PATH))
        self.assertIn(("TierAExecutionTimeout", "class"), symbols)
        self.assertIn(("_run_tier_a_launch_plan", "function"), symbols)
        self.assertIn(("run_verified_tier_a_command", "function"), symbols)
        source = MODERN_PATH.read_text(encoding="utf-8")
        self.assertIn("SignedRuntimeClosureManifest", source)
        self.assertIn("RuntimeClosureVerifier", source)
        self.assertIn("WindowsRuntimeClosureLifetimeGuard", source)
        self.assertNotIn("tier_a_command_receipt", source)
        self.assertNotIn("trusted_git", source)

    def test_final_facade_routes_only_to_modern_executor(self) -> None:
        package = importlib.import_module("kaliv_dev_control")
        authority = importlib.import_module("kaliv_dev_control.tier_a_authority")
        core = importlib.import_module("kaliv_dev_control._tier_a_execution_core")
        modern = importlib.import_module("kaliv_dev_control.tier_a_execution_v3")
        facade = importlib.import_module("kaliv_dev_control.tier_a_execution")
        receipt = importlib.import_module("kaliv_dev_control.tier_a_command_receipt")

        self.assertIsNotNone(
            importlib.util.find_spec("kaliv_dev_control.tier_a_execution")
        )
        self.assertIsNotNone(
            importlib.util.find_spec("kaliv_dev_control.tier_a_command_receipt")
        )
        for surface in (package, authority, core):
            self.assertFalse(hasattr(surface, "_run_tier_a_launch_plan"))
            self.assertFalse(hasattr(surface, "run_verified_tier_a_command"))
        self.assertIs(
            facade._run_tier_a_launch_plan,
            modern._run_tier_a_launch_plan,
        )
        self.assertIs(
            facade.run_verified_tier_a_command,
            modern.run_verified_tier_a_command,
        )
        self.assertTrue(
            callable(receipt.run_single_verified_tier_a_command_with_receipt)
        )
        self.assertIs(
            facade.run_single_verified_tier_a_command_with_receipt,
            receipt.run_single_verified_tier_a_command_with_receipt,
        )

    def test_modern_executor_fails_closed_off_windows_before_spawn(self) -> None:
        modern = importlib.import_module("kaliv_dev_control.tier_a_execution_v3")
        catalog = importlib.import_module("kaliv_dev_control.catalog")
        plan_module = importlib.import_module("kaliv_dev_control.tier_a_plan")
        authority = importlib.import_module("kaliv_dev_control.tier_a_authority")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            executable = root / "probe.exe"
            executable.write_bytes(b"probe")
            plan = plan_module.TierALaunchPlan(
                task_id="A10R_EXEC",
                task_sha256="a" * 64,
                base_sha="b" * 40,
                command_id="modelrig.execution.probe",
                argv=(os.fspath(executable),),
                cwd=".",
                max_timeout_seconds=30,
                max_output_bytes=4096,
                env={"CI": "1", "MODELRIG_DEVCONTROL": "1"},
                catalog_sha256="c" * 64,
                toolchain_sha256="d" * 64,
                lease_sha256="e" * 64,
                signed_report_sha256="f" * 64,
                workspace_root=os.fspath(root),
                workspace_root_sha256="1" * 64,
                executable_sha256="2" * 64,
                toolhost_sha256="3" * 64,
                working_directory_sha256=(
                    authority.working_directory_authority_sha256(root, ".")
                ),
                runtime_closure_sha256="4" * 64,
                signed_runtime_closure_sha256="5" * 64,
                runtime_closure_staging_receipt_sha256="6" * 64,
                runtime_closure_verified=True,
                boundary=catalog.IsolationBoundary.OS_ISOLATED,
                network_mode=catalog.NetworkMode.DENY,
            )
            with mock.patch.object(modern.os, "name", "posix"):
                with self.assertRaisesRegex(
                    modern.TierAExecutionError,
                    "requires Windows",
                ):
                    modern._run_tier_a_launch_plan(
                        plan,
                        runtime_closure_receipt=object(),
                        control_plane_root=root,
                    )

    def test_toolhost_bundle_binds_complete_dc_l09_execution_chain(self) -> None:
        authority = importlib.import_module("kaliv_dev_control.tier_a_authority")
        toolhost = importlib.import_module(
            "kaliv_dev_control._tier_a_legacy_toolhost"
        )
        bundle = authority._TIER_A_BUNDLE_FILES
        self.assertEqual(bundle, toolhost._TIER_A_BUNDLE_FILES)
        required = (
            "devcontrol/src/kaliv_dev_control/_tier_a_legacy_runner.py",
            "devcontrol/src/kaliv_dev_control/tier_a_execution_v3.py",
            "devcontrol/src/kaliv_dev_control/trusted_git_runtime_model.py",
            "devcontrol/src/kaliv_dev_control/trusted_git_runtime_staging.py",
            "devcontrol/src/kaliv_dev_control/trusted_git_runtime_h4.py",
            "devcontrol/src/kaliv_dev_control/trusted_git_runtime_runner.py",
            "devcontrol/src/kaliv_dev_control/trusted_git_runtime.py",
            "devcontrol/src/kaliv_dev_control/tier_a_command_receipt.py",
            "devcontrol/src/kaliv_dev_control/tier_a_execution.py",
            "devcontrol/src/kaliv_dev_control/_tier_a_execution_core.py",
        )
        for path in required:
            self.assertEqual(bundle.count(path), 1, path)
        self.assertLess(
            bundle.index("devcontrol/src/kaliv_dev_control/tier_a_execution_v3.py"),
            bundle.index("devcontrol/src/kaliv_dev_control/tier_a_execution.py"),
        )
        self.assertLess(
            bundle.index("devcontrol/src/kaliv_dev_control/tier_a_command_receipt.py"),
            bundle.index("devcontrol/src/kaliv_dev_control/tier_a_execution.py"),
        )

    def test_private_executor_sources_contain_no_remote_or_publication_authority(self) -> None:
        forbidden = {
            "socket",
            "requests",
            "urllib",
            "http",
            "git",
            "github",
            "publisher",
            "credential",
            "tier_a_command_receipt",
            "trusted_git",
        }
        for path in (LEGACY_PATH, MODERN_PATH):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".", 1)[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".", 1)[0])
            self.assertFalse(imported & forbidden, (path.name, imported & forbidden))
            self.assertFalse(
                any(token in source for token in ("publish_once", "private_key"))
            )

    def test_authority_source_does_not_alias_private_execution_functions(self) -> None:
        tree = ast.parse(
            AUTHORITY_PATH.read_text(encoding="utf-8"),
            filename=str(AUTHORITY_PATH),
        )
        assigned = {
            target.id
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        self.assertNotIn("_run_tier_a_launch_plan", assigned)
        self.assertNotIn("run_verified_tier_a_command", assigned)


if __name__ == "__main__":
    unittest.main()
