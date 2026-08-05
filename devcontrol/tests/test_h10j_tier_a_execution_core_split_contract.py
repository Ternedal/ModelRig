from __future__ import annotations

import ast
import hashlib
import importlib
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "devcontrol/TIER_A_EXECUTION_CORE_SPLIT_CONTRACT.json"
REPORT_PATH = ROOT / "devcontrol/TIER_A_EXECUTION_CORE_SPLIT_CONTRACT.md"
PACKAGE_ROOT = ROOT / "devcontrol/src/kaliv_dev_control"


def _owned_symbols(tree: ast.Module) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    result.append((target.id, "constant"))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            result.append((node.target.id, "constant"))
        elif isinstance(node, ast.ClassDef):
            result.append((node.name, "class"))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result.append((node.name, "function"))
    return result


def _imports_core(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "_tier_a_execution_core":
                return True
            if node.module is None and any(
                alias.name == "_tier_a_execution_core" for alias in node.names
            ):
                return True
        elif isinstance(node, ast.Import):
            if any(
                alias.name.endswith("._tier_a_execution_core")
                for alias in node.names
            ):
                return True
    return False


def _core_consumer_details(path: Path, alias_name: str) -> tuple[list[str], list[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    attributes = sorted(
        {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == alias_name
        }
    )
    removals = sorted(
        {
            node.args[1].value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "delattr"
            and len(node.args) == 2
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == alias_name
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        }
    )
    return attributes, removals


class TierAExecutionCoreSplitContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.source_path = ROOT / cls.contract["source"]
        cls.source_bytes = cls.source_path.read_bytes()
        cls.source_tree = ast.parse(
            cls.source_bytes.decode("utf-8"), filename=str(cls.source_path)
        )

    def test_source_and_symbol_mapping_are_exact(self):
        self.assertEqual(
            self.contract["schema"],
            "kaliv-tier-a-execution-core-split-contract/v1",
        )
        git_blob = hashlib.sha1(
            b"blob "
            + str(len(self.source_bytes)).encode("ascii")
            + b"\0"
            + self.source_bytes
        ).hexdigest()
        self.assertEqual(git_blob, self.contract["source_git_blob_sha1"])

        expected = _owned_symbols(self.source_tree)
        actual = [
            (item["name"], item["kind"])
            for item in self.contract["symbols"]
        ]
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), len(set(actual)))

        destinations = set(self.contract["proposed_modules"])
        self.assertTrue(destinations)
        self.assertEqual(
            {item["destination"] for item in self.contract["symbols"]},
            destinations,
        )
        for item in self.contract["symbols"]:
            self.assertIn(item["kind"], {"constant", "class", "function"})
            self.assertTrue(item["responsibility"])
            self.assertTrue(
                Path(item["destination"]).name.startswith("_tier_a_")
            )

        constraints = self.contract["constraints"]
        self.assertFalse(constraints["h10j_moves_production_code"])
        self.assertTrue(
            constraints["preserve_object_identity_during_future_split"]
        )
        self.assertTrue(
            constraints["fresh_physical_evidence_required_after_future_split"]
        )

    def test_external_core_consumer_is_complete(self):
        target = self.source_path.resolve()
        consumers = sorted(
            path.relative_to(ROOT).as_posix()
            for path in PACKAGE_ROOT.rglob("*.py")
            if path.resolve() != target and _imports_core(path)
        )
        expected_consumer = self.contract["external_core_consumer"]
        self.assertEqual(consumers, [expected_consumer["path"]])
        attributes, removals = _core_consumer_details(
            ROOT / expected_consumer["path"],
            expected_consumer["module_alias"],
        )
        self.assertEqual(attributes, expected_consumer["attribute_references"])
        self.assertEqual(removals, expected_consumer["dynamic_removals"])

    def test_public_identity_chains_are_preserved_today(self):
        package = importlib.import_module("kaliv_dev_control")
        facade = importlib.import_module("kaliv_dev_control.tier_a_execution")
        authority = importlib.import_module("kaliv_dev_control.tier_a_authority")
        core = importlib.import_module(
            "kaliv_dev_control._tier_a_execution_core"
        )
        declared = self.contract["public_identity_chains"]
        self.assertEqual(
            [item["symbol"] for item in declared],
            sorted(item["symbol"] for item in declared),
        )
        for item in declared:
            symbol = item["symbol"]
            self.assertEqual(
                item["chain"],
                [
                    f"_tier_a_execution_core.{symbol}",
                    f"tier_a_authority.{symbol}",
                    f"tier_a_execution.{symbol}",
                    f"kaliv_dev_control.{symbol}",
                ],
            )
            identity = getattr(core, symbol)
            self.assertIs(getattr(authority, symbol), identity)
            self.assertIs(getattr(facade, symbol), identity)
            self.assertIs(getattr(package, symbol), identity)
            self.assertIn(symbol, facade.__all__)
            self.assertIn(symbol, package.__all__)

        for symbol in self.contract["external_core_consumer"][
            "dynamic_removals"
        ]:
            self.assertFalse(hasattr(core, symbol))

    def test_markdown_review_table_has_no_loss_or_duplication(self):
        markdown = REPORT_PATH.read_text(encoding="utf-8")
        table_symbols = re.findall(r"^\| `([^`]+)` \|", markdown, re.MULTILINE)
        expected = [item["name"] for item in self.contract["symbols"]]
        self.assertEqual(table_symbols, expected)
        self.assertEqual(len(table_symbols), len(set(table_symbols)))
        for destination in self.contract["proposed_modules"]:
            self.assertIn(f"`{destination}`", markdown)
        for chain in self.contract["public_identity_chains"]:
            self.assertIn(f"`{chain['symbol']}`", markdown)


if __name__ == "__main__":
    unittest.main()
