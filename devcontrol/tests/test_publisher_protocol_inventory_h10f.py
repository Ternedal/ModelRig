from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "devcontrol/src/kaliv_dev_control"
REPORT = ROOT / "devcontrol/PUBLISHER_PROTOCOL_INVENTORY.md"
TOKENS = ("publisher", "semantic_review", "draft_pr_readiness", "local_candidate_materialization")
EXTRA = {"durable_publication.py", "streaming_publication.py", "store.py", "trusted_git_runtime_staging.py"}


def _expected_paths() -> set[str]:
    result: set[str] = set()
    for path in PACKAGE.rglob("*.py"):
        relative = path.relative_to(PACKAGE).as_posix()
        if any(token in relative for token in TOKENS) or relative in EXTRA:
            result.add(f"devcontrol/src/kaliv_dev_control/{relative}")
    return result


class PublisherProtocolInventoryH10FTests(unittest.TestCase):
    def test_recursive_supported_inventory_is_exact(self) -> None:
        report = REPORT.read_text(encoding="utf-8")
        actual = set(re.findall(r"^- `(devcontrol/src/kaliv_dev_control/[^`]+\.py)`$", report, re.MULTILINE))
        self.assertEqual(actual, _expected_paths())
        self.assertIn("static validation/evidence support package", report)
        self.assertIn("Live publication", report)

    def test_rejected_compatibility_package_is_physically_absent(self) -> None:
        self.assertFalse((PACKAGE / "_compatibility_v1").exists())
        self.assertTrue(all("_compatibility_v1" not in path for path in _expected_paths()))

    def test_protocol_modules_do_not_import_remote_or_credential_clients(self) -> None:
        forbidden = {"requests", "urllib", "http", "socket", "paramiko", "boto3", "twine"}
        for relative in sorted(_expected_paths()):
            path = ROOT / relative
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".", 1)[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    imported.add(node.module.split(".", 1)[0])
            self.assertFalse(imported & forbidden, (relative, imported & forbidden))

    def test_direct_os_replace_and_named_temporaries_are_confined(self) -> None:
        replace_users: set[str] = set()
        temporary_users: set[str] = set()
        for relative in sorted(_expected_paths()):
            path = ROOT / relative
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                function = node.func
                if isinstance(function, ast.Attribute) and isinstance(function.value, ast.Name):
                    if function.value.id == "os" and function.attr == "replace":
                        replace_users.add(path.relative_to(PACKAGE).as_posix())
                    if function.value.id == "tempfile" and function.attr == "NamedTemporaryFile":
                        temporary_users.add(path.relative_to(PACKAGE).as_posix())
        self.assertTrue(replace_users <= {"durable_publication.py", "store.py", "_local_candidate_materialization_legacy/__init__.py"}, replace_users)
        self.assertTrue(temporary_users <= {"store.py"}, temporary_users)


if __name__ == "__main__":
    unittest.main()
