from __future__ import annotations

import ast
import hashlib
import importlib
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = (
    ROOT
    / "devcontrol/src/kaliv_dev_control/_tier_a_legacy_toolhost.py"
)
CORE_PATH = (
    ROOT
    / "devcontrol/src/kaliv_dev_control/_tier_a_execution_core.py"
)
AUTHORITY_PATH = (
    ROOT / "devcontrol/src/kaliv_dev_control/tier_a_authority.py"
)
EXPECTED_SYMBOLS = [
    ("_TIER_A_BUNDLE_FILES", "constant"),
    ("tier_a_toolhost_sha256", "function"),
]
EXPECTED_BUNDLE = (
    "worker/app/__init__.py",
    "worker/app/windows_job.py",
    "worker/app/windows_restricted.py",
    "worker/app/windows_tier_a.py",
    "devcontrol/src/kaliv_dev_control/__init__.py",
    "devcontrol/src/kaliv_dev_control/catalog.py",
    "devcontrol/src/kaliv_dev_control/commands.py",
    "devcontrol/src/kaliv_dev_control/contract.py",
    "devcontrol/src/kaliv_dev_control/physical_isolation.py",
    "devcontrol/src/kaliv_dev_control/runtime_staging.py",
    "devcontrol/src/kaliv_dev_control/tier_a_execution.py",
    "devcontrol/src/kaliv_dev_control/workspace.py",
)


def _owned_symbols(path: Path) -> list[tuple[str, str]]:
    tree = ast.parse(
        path.read_text(encoding="utf-8"), filename=str(path)
    )
    result: list[tuple[str, str]] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            result.extend(
                (target.id, "constant")
                for target in node.targets
                if isinstance(target, ast.Name)
            )
        elif isinstance(node, ast.FunctionDef):
            result.append((node.name, "function"))
    return result


def _direct_imports(path: Path, module: str) -> list[str]:
    tree = ast.parse(
        path.read_text(encoding="utf-8"), filename=str(path)
    )
    result: list[str] = []
    for node in tree.body:
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == module
        ):
            result.extend(alias.name for alias in node.names)
    return result


class TierALegacyToolhostExtractionTests(unittest.TestCase):
    def test_module_owns_exact_two_legacy_identity_symbols(self) -> None:
        self.assertEqual(
            _owned_symbols(MODULE_PATH), EXPECTED_SYMBOLS
        )
        module = importlib.import_module(
            "kaliv_dev_control._tier_a_legacy_toolhost"
        )
        self.assertEqual(module._TIER_A_BUNDLE_FILES, EXPECTED_BUNDLE)

    def test_core_physically_removes_and_reexports_exact_objects(self) -> None:
        self.assertEqual(
            _direct_imports(
                CORE_PATH, "_tier_a_legacy_toolhost"
            ),
            [ "_TIER_A_BUNDLE_FILES", "tier_a_toolhost_sha256" ],
        )
        self.assertFalse(
            set(EXPECTED_SYMBOLS) & set(_owned_symbols(CORE_PATH))
        )
        module = importlib.import_module(
            "kaliv_dev_control._tier_a_legacy_toolhost"
        )
        core = importlib.import_module(
            "kaliv_dev_control._tier_a_execution_core"
        )
        self.assertIs(
            core._TIER_A_BUNDLE_FILES,
            module._TIER_A_BUNDLE_FILES,
        )
        self.assertIs(
            core.tier_a_toolhost_sha256,
            module.tier_a_toolhost_sha256,
        )

    def test_hash_behavior_remains_exact_and_fail_closed(self) -> None:
        module = importlib.import_module(
            "kaliv_dev_control._tier_a_legacy_toolhost"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = hashlib.sha256()
            expected.update(b"kaliv-tier-a-toolhost/v2\0")
            for index, relative in enumerate(EXPECTED_BUNDLE):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                payload = f"{index}:{relative}".encode("utf-8")
                path.write_bytes(payload)
                expected.update(relative.encode("utf-8"))
                expected.update(b"\0")
                expected.update(
                    len(payload).to_bytes(8, "big")
                )
                expected.update(payload)
            self.assertEqual(
                module.tier_a_toolhost_sha256(root),
                expected.hexdigest(),
            )
            missing = root / EXPECTED_BUNDLE[-1]
            missing.unlink()
            with self.assertRaisesRegex(
                module.TierAExecutionError,
                "missing or unsafe",
            ):
                module.tier_a_toolhost_sha256(root)

    def test_authority_bundle_contains_module_once_before_core(self) -> None:
        authority = importlib.import_module(
            "kaliv_dev_control.tier_a_authority"
        )
        module_path = (
            "devcontrol/src/kaliv_dev_control/"
            "_tier_a_legacy_toolhost.py"
        )
        core_path = (
            "devcontrol/src/kaliv_dev_control/"
            "_tier_a_execution_core.py"
        )
        bundle = authority._TIER_A_BUNDLE_FILES
        self.assertEqual(bundle.count(module_path), 1)
        self.assertLess(
            bundle.index(module_path), bundle.index(core_path)
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

    def test_module_boundary_has_no_reverse_or_remote_authority(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(MODULE_PATH))
        absolute: set[str] = set()
        relative: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                absolute.update(
                    alias.name.split(".", 1)[0]
                    for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.module:
                    relative.add(node.module)
                elif (
                    node.module
                    and node.module != "__future__"
                ):
                    absolute.add(
                        node.module.split(".", 1)[0]
                    )
        self.assertEqual(
            absolute, {"hashlib", "pathlib"}
        )
        self.assertEqual(
            relative,
            {"_tier_a_lease", "_tier_a_path_authority"},
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
        for name in (
            "_run_tier_a_launch_plan",
            "run_verified_tier_a_command",
        ):
            self.assertFalse(hasattr(core, name))


if __name__ == "__main__":
    unittest.main()
