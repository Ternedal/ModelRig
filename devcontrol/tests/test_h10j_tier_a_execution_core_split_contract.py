from __future__ import annotations

import ast
import hashlib
import importlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "devcontrol/TIER_A_EXECUTION_CORE_SPLIT_CONTRACT.json"
REPORT_PATH = ROOT / "devcontrol/TIER_A_EXECUTION_CORE_SPLIT_CONTRACT.md"


def _git_blob_sha1(payload: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload).hexdigest()


class TierAExecutionCoreSplitContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.source_path = ROOT / cls.contract["source"]
        cls.payload = cls.source_path.read_bytes()
        cls.tree = ast.parse(cls.payload.decode("utf-8"), filename=str(cls.source_path))

    def test_contract_is_exact_for_current_physical_core(self) -> None:
        self.assertEqual(self.contract["schema"], "kaliv-tier-a-execution-core-split-contract/v10")
        self.assertTrue(self.contract["import_only"])
        self.assertEqual(_git_blob_sha1(self.payload), self.contract["source_git_blob_sha1"])
        actual: dict[str, list[str]] = {}
        for node in self.tree.body:
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
                actual[node.module] = [alias.name for alias in node.names]
        self.assertEqual(actual, self.contract["direct_imports"])
        self.assertFalse(any(isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) for node in self.tree.body))

    def test_reexports_preserve_identity_and_executors_remain_absent(self) -> None:
        core = importlib.import_module("kaliv_dev_control._tier_a_execution_core")
        for module_name, names in self.contract["direct_imports"].items():
            extracted = importlib.import_module(f"kaliv_dev_control.{module_name}")
            for name in names:
                self.assertIs(getattr(core, name), getattr(extracted, name), (module_name, name))
        for name in self.contract["forbidden_exports"]:
            self.assertFalse(hasattr(core, name), name)

    def test_report_is_complete_and_reviewable(self) -> None:
        report = REPORT_PATH.read_text(encoding="utf-8")
        self.assertIn(self.contract["source_git_blob_sha1"], report)
        for module_name in self.contract["direct_imports"]:
            self.assertIn(f"`kaliv_dev_control.{module_name}`", report)
        for name in self.contract["forbidden_exports"]:
            self.assertIn(f"`{name}`", report)


if __name__ == "__main__":
    unittest.main()
