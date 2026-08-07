from __future__ import annotations

import ast
import hashlib
import importlib
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH_AUTHORITY_PATH = (
    ROOT / "devcontrol/src/kaliv_dev_control/_tier_a_path_authority.py"
)
CORE_PATH = ROOT / "devcontrol/src/kaliv_dev_control/_tier_a_execution_core.py"
AUTHORITY_PATH = ROOT / "devcontrol/src/kaliv_dev_control/tier_a_authority.py"
PATH_AUTHORITY_REPOSITORY_PATH = (
    "devcontrol/src/kaliv_dev_control/_tier_a_path_authority.py"
)
CORE_REPOSITORY_PATH = (
    "devcontrol/src/kaliv_dev_control/_tier_a_execution_core.py"
)
LEASE_REPOSITORY_PATH = "devcontrol/src/kaliv_dev_control/_tier_a_lease.py"
MOVED = [
    "_has_symlink_component",
    "_canonical_directory",
    "workspace_root_authority_sha256",
    "_regular_file_hash",
]
CORE_IMPORT_ORDER = [
    "_canonical_directory",
    "_has_symlink_component",
    "_regular_file_hash",
    "workspace_root_authority_sha256",
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
    result: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == module:
            result.extend(alias.name for alias in node.names)
    return result


class TierAPathAuthorityExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.path_authority = importlib.import_module(
            "kaliv_dev_control._tier_a_path_authority"
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
        cls.plan = importlib.import_module("kaliv_dev_control.tier_a_plan")
        cls.execution_v3 = importlib.import_module(
            "kaliv_dev_control.tier_a_execution_v3"
        )

    def test_module_owns_exact_cohesive_path_authority(self) -> None:
        self.assertEqual(_owned_names(PATH_AUTHORITY_PATH), MOVED)
        for symbol in MOVED:
            self.assertEqual(
                getattr(self.path_authority, symbol).__module__,
                "kaliv_dev_control._tier_a_path_authority",
            )

    def test_core_physically_owns_none_and_reexports_exact_objects(self) -> None:
        self.assertFalse(set(_owned_names(CORE_PATH)) & set(MOVED))
        self.assertEqual(
            _direct_imports(CORE_PATH, "_tier_a_path_authority"),
            CORE_IMPORT_ORDER,
        )
        for symbol in MOVED:
            self.assertIs(
                getattr(self.core, symbol),
                getattr(self.path_authority, symbol),
            )

    def test_public_and_private_consumer_identity_is_unchanged(self) -> None:
        public_identity = self.path_authority.workspace_root_authority_sha256
        self.assertIs(self.core.workspace_root_authority_sha256, public_identity)
        self.assertIs(self.authority.workspace_root_authority_sha256, public_identity)
        self.assertIs(self.facade.workspace_root_authority_sha256, public_identity)
        self.assertIs(self.package.workspace_root_authority_sha256, public_identity)

        for consumer in (self.authority, self.plan, self.execution_v3):
            self.assertIs(
                consumer._core._canonical_directory,
                self.path_authority._canonical_directory,
            )
        for consumer in (self.plan, self.execution_v3):
            self.assertIs(
                consumer._core._regular_file_hash,
                self.path_authority._regular_file_hash,
            )

    def test_canonical_directory_and_workspace_hash_remain_fail_closed(self) -> None:
        error = self.path_authority.TierAExecutionError
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            canonical = self.path_authority._canonical_directory(
                root, name="workspace root"
            )
            self.assertEqual(canonical, root)
            self.assertEqual(
                self.path_authority.workspace_root_authority_sha256(root),
                hashlib.sha256(
                    b"kaliv-tier-a-workspace/v1\0"
                    + os.path.normcase(os.fspath(root)).encode(
                        "utf-8", "surrogatepass"
                    )
                ).hexdigest(),
            )
            self.assertEqual(
                self.path_authority.workspace_root_authority_sha256(root),
                self.path_authority.workspace_root_authority_sha256(root),
            )

            with self.assertRaises(error):
                self.path_authority._canonical_directory(
                    Path("relative"), name="workspace root"
                )
            with self.assertRaises(error):
                self.path_authority._canonical_directory(
                    root / "missing", name="workspace root"
                )

            symlink = root.parent / (root.name + "-link")
            try:
                symlink.symlink_to(root, target_is_directory=True)
            except (NotImplementedError, OSError):
                symlink = None
            if symlink is not None:
                try:
                    self.assertTrue(
                        self.path_authority._has_symlink_component(symlink)
                    )
                    with self.assertRaises(error):
                        self.path_authority._canonical_directory(
                            symlink, name="workspace root"
                        )
                finally:
                    symlink.unlink(missing_ok=True)

    def test_regular_file_hash_remains_streaming_and_fail_closed(self) -> None:
        error = self.path_authority.TierAExecutionError
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            payload = (b"path-authority\0" * 100_000) + b"tail"
            regular = root / "payload.bin"
            regular.write_bytes(payload)
            self.assertEqual(
                self.path_authority._regular_file_hash(
                    regular, name="Tier-A executable"
                ),
                hashlib.sha256(payload).hexdigest(),
            )
            with self.assertRaises(error):
                self.path_authority._regular_file_hash(
                    Path("relative.bin"), name="Tier-A executable"
                )
            with self.assertRaises(error):
                self.path_authority._regular_file_hash(
                    root / "missing.bin", name="Tier-A executable"
                )
            with self.assertRaises(error):
                self.path_authority._regular_file_hash(
                    root, name="Tier-A executable"
                )

            symlink = root / "payload-link.bin"
            try:
                symlink.symlink_to(regular)
            except (NotImplementedError, OSError):
                symlink = None
            if symlink is not None:
                with self.assertRaises(error):
                    self.path_authority._regular_file_hash(
                        symlink, name="Tier-A executable"
                    )

    def test_bundle_contains_path_module_once_before_core(self) -> None:
        bundle = tuple(self.authority._TIER_A_BUNDLE_FILES)
        for path in (
            LEASE_REPOSITORY_PATH,
            PATH_AUTHORITY_REPOSITORY_PATH,
            CORE_REPOSITORY_PATH,
        ):
            self.assertEqual(bundle.count(path), 1)
        self.assertLess(
            bundle.index(LEASE_REPOSITORY_PATH),
            bundle.index(PATH_AUTHORITY_REPOSITORY_PATH),
        )
        self.assertLess(
            bundle.index(PATH_AUTHORITY_REPOSITORY_PATH),
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

    def test_module_adds_no_execution_network_git_or_publication_authority(self) -> None:
        source = PATH_AUTHORITY_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(PATH_AUTHORITY_PATH))
        imports: set[str] = set()
        relative_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module and node.module != "__future__":
                    imports.add(node.module.split(".", 1)[0])
                elif node.level == 1 and node.module:
                    relative_modules.add(node.module)
        self.assertEqual(imports, {"hashlib", "os", "pathlib"})
        self.assertEqual(relative_modules, {"_tier_a_lease"})
        forbidden = {
            "subprocess",
            "socket",
            "urllib",
            "http",
            "requests",
            "git",
            "github",
            "tempfile",
            "shutil",
        }
        self.assertFalse(imports & forbidden)
        call_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertFalse(
            call_names
            & {
                "exec",
                "eval",
                "compile",
                "create_once_file",
                "publish_stream_once",
            }
        )


if __name__ == "__main__":
    unittest.main()
