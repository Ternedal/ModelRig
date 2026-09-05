from __future__ import annotations

import ast
import unittest
from pathlib import Path, PurePosixPath

from kaliv_dev_control.tier_a_authority import _TIER_A_BUNDLE_FILES


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_ENTRYPOINTS = (
    "devcontrol/src/kaliv_dev_control/tier_a_execution.py",
)
_LOCAL_PACKAGE_ROOTS = {
    "kaliv_dev_control": _REPOSITORY_ROOT / "devcontrol/src/kaliv_dev_control",
    "app": _REPOSITORY_ROOT / "worker/app",
    "worker.app": _REPOSITORY_ROOT / "worker/app",
}


def _module_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for package, root in _LOCAL_PACKAGE_ROOTS.items():
        for path in root.rglob("*.py"):
            relative = path.relative_to(root)
            parts = list(relative.with_suffix("").parts)
            if parts[-1] == "__init__":
                parts.pop()
            module = ".".join((package, *parts)) if parts else package
            repository_relative = path.relative_to(_REPOSITORY_ROOT).as_posix()
            existing = index.get(module)
            if existing is not None and existing != repository_relative:
                raise AssertionError(f"ambiguous local module {module}: {existing}, {repository_relative}")
            index[module] = repository_relative
    return index


def _package_for_path(repository_relative: str) -> str:
    path = PurePosixPath(repository_relative)
    if path.parts[:3] == ("devcontrol", "src", "kaliv_dev_control"):
        suffix = path.parts[3:-1]
        return ".".join(("kaliv_dev_control", *suffix))
    if path.parts[:2] == ("worker", "app"):
        suffix = path.parts[2:-1]
        return ".".join(("app", *suffix))
    raise AssertionError(f"unsupported authority source path: {repository_relative}")


def _resolve_from_import(
    *,
    node: ast.ImportFrom,
    source_path: str,
    modules: dict[str, str],
) -> set[str]:
    package = _package_for_path(source_path)
    if node.level:
        package_parts = package.split(".")
        if node.level > len(package_parts):
            raise AssertionError(f"relative import escapes local package in {source_path}")
        base_parts = package_parts[: len(package_parts) - node.level + 1]
        if node.module:
            base_parts.extend(node.module.split("."))
        base = ".".join(base_parts)
    else:
        base = node.module or ""

    resolved: set[str] = set()
    if base in modules:
        resolved.add(modules[base])
    for alias in node.names:
        candidate = f"{base}.{alias.name}" if base else alias.name
        if candidate in modules:
            resolved.add(modules[candidate])
    return resolved


def _direct_local_imports(repository_relative: str, modules: dict[str, str]) -> set[str]:
    source = (_REPOSITORY_ROOT / repository_relative).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=repository_relative)
    resolved: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            resolved.update(
                _resolve_from_import(
                    node=node,
                    source_path=repository_relative,
                    modules=modules,
                )
            )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name
                while module:
                    if module in modules:
                        resolved.add(modules[module])
                        break
                    module = module.rpartition(".")[0]
    return resolved


def _authority_import_closure() -> set[str]:
    modules = _module_index()
    pending = list(_ENTRYPOINTS)
    closure: set[str] = set()
    while pending:
        current = pending.pop()
        if current in closure:
            continue
        path = _REPOSITORY_ROOT / current
        if not path.is_file():
            raise AssertionError(f"authority entrypoint/import is missing: {current}")
        closure.add(current)
        pending.extend(sorted(_direct_local_imports(current, modules) - closure))
    return closure


class TierAAuthorityBundleClosureTests(unittest.TestCase):
    def test_every_statically_imported_local_authority_file_is_hashed(self) -> None:
        bundle = set(_TIER_A_BUNDLE_FILES)
        closure = _authority_import_closure()
        missing = sorted(closure - bundle)
        self.assertEqual(
            missing,
            [],
            "Tier-A imports local Python files that are absent from "
            f"_TIER_A_BUNDLE_FILES: {missing}",
        )

    def test_bundle_paths_are_unique_regular_python_files(self) -> None:
        bundle = tuple(_TIER_A_BUNDLE_FILES)
        self.assertEqual(len(bundle), len(set(bundle)))
        for repository_relative in bundle:
            self.assertTrue(repository_relative.endswith(".py"), repository_relative)
            path = _REPOSITORY_ROOT / repository_relative
            self.assertTrue(path.is_file(), repository_relative)
            self.assertFalse(path.is_symlink(), repository_relative)


if __name__ == "__main__":
    unittest.main()
