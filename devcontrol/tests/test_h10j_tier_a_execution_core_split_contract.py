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


def _git_blob_sha1(payload: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
    ).hexdigest()


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


def _loop_string_values(tree: ast.Module) -> dict[str, set[str]]:
    values: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.For) or not isinstance(node.target, ast.Name):
            continue
        if not isinstance(node.iter, (ast.Tuple, ast.List, ast.Set)):
            continue
        items = {
            item.value
            for item in node.iter.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        }
        if len(items) == len(node.iter.elts):
            values[node.target.id] = items
    return values


def _core_consumer_details(path: Path) -> dict[str, object] | None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported_names: set[str] = set()
    module_aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "_tier_a_execution_core":
                imported_names.update(alias.name for alias in node.names)
            elif node.module is None:
                module_aliases.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name == "_tier_a_execution_core"
                )
        elif isinstance(node, ast.Import):
            module_aliases.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name.endswith("._tier_a_execution_core")
            )
    if not imported_names and not module_aliases:
        return None
    if imported_names and module_aliases:
        raise AssertionError(f"mixed core import styles are not supported: {path}")
    if imported_names:
        return {
            "import_style": "direct",
            "module_alias": None,
            "imported_names": sorted(imported_names),
            "attribute_references": [],
            "dynamic_removals": [],
        }
    if len(module_aliases) != 1:
        raise AssertionError(f"core module alias is ambiguous: {path}")
    alias_name = next(iter(module_aliases))
    attributes = sorted(
        {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == alias_name
        }
    )
    loop_values = _loop_string_values(tree)
    removals: set[str] = set()
    for node in ast.walk(tree):
        if (
            not isinstance(node, ast.Call)
            or not isinstance(node.func, ast.Name)
            or node.func.id != "delattr"
            or len(node.args) != 2
            or not isinstance(node.args[0], ast.Name)
            or node.args[0].id != alias_name
        ):
            continue
        value = node.args[1]
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            removals.add(value.value)
        elif isinstance(value, ast.Name):
            removals.update(loop_values.get(value.id, set()))
    return {
        "import_style": "module_alias",
        "module_alias": alias_name,
        "imported_names": [],
        "attribute_references": attributes,
        "dynamic_removals": sorted(removals),
    }


def _direct_imports(tree: ast.Module, module: str) -> list[str]:
    result: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == module:
            result.extend(alias.name for alias in node.names)
    return result


class TierAExecutionCoreSplitContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.source_path = ROOT / cls.contract["source"]
        cls.source_bytes = cls.source_path.read_bytes()
        cls.source_tree = ast.parse(
            cls.source_bytes.decode("utf-8"), filename=str(cls.source_path)
        )

    def test_source_remaining_symbols_and_destinations_are_exact(self):
        self.assertEqual(
            self.contract["schema"],
            "kaliv-tier-a-execution-core-split-contract/v6",
        )
        self.assertEqual(
            _git_blob_sha1(self.source_bytes),
            self.contract["source_git_blob_sha1"],
        )

        expected = _owned_symbols(self.source_tree)
        actual = [
            (item["name"], item["kind"])
            for item in self.contract["symbols"]
        ]
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), len(set(actual)))

        remaining_destinations = {
            item["destination"] for item in self.contract["symbols"]
        }
        extracted_destinations = {
            extraction["path"]
            for extraction in self.contract["completed_extractions"]
        }
        self.assertEqual(
            remaining_destinations | extracted_destinations,
            set(self.contract["proposed_modules"]),
        )
        self.assertTrue(
            extracted_destinations <= set(self.contract["proposed_modules"])
        )
        for item in self.contract["symbols"]:
            self.assertIn(item["kind"], {"constant", "class", "function"})
            self.assertTrue(item["responsibility"])
            self.assertTrue(
                Path(item["destination"]).name.startswith("_tier_a_")
            )

        constraints = self.contract["constraints"]
        self.assertFalse(constraints["h10j_moves_production_code"])
        self.assertTrue(constraints["h10k_completed_first_production_extraction"])
        self.assertTrue(constraints["h10k_changes_authority_digest"])
        self.assertTrue(constraints["h10l_extracted_error_identity"])
        self.assertTrue(constraints["h10l_eliminates_lazy_reverse_dependency"])
        self.assertTrue(constraints["h10m_extracted_cohesive_lease_model"])
        self.assertTrue(constraints["h10m_changes_authority_digest"])
        self.assertTrue(constraints["h10n_extracted_path_authority"])
        self.assertTrue(constraints["h10n_changes_authority_digest"])
        self.assertTrue(
            constraints["h10o_extracted_materialization_services"]
        )
        self.assertTrue(constraints["h10o_changes_authority_digest"])
        self.assertTrue(constraints["earlier_physical_evidence_is_stale"])
        self.assertTrue(
            constraints["preserve_object_identity_during_future_split"]
        )
        self.assertTrue(
            constraints["fresh_physical_evidence_required_after_future_split"]
        )

    def test_completed_extractions_are_exact_and_reexported_by_identity(self):
        extractions = self.contract["completed_extractions"]
        self.assertEqual(
            [item["path"] for item in extractions],
            [
                "devcontrol/src/kaliv_dev_control/_tier_a_environment.py",
                "devcontrol/src/kaliv_dev_control/_tier_a_lease.py",
                "devcontrol/src/kaliv_dev_control/_tier_a_path_authority.py",
                "devcontrol/src/kaliv_dev_control/_tier_a_materialization.py",
            ],
        )
        core = importlib.import_module("kaliv_dev_control._tier_a_execution_core")
        for extraction in extractions:
            path = ROOT / extraction["path"]
            payload = path.read_bytes()
            self.assertEqual(_git_blob_sha1(payload), extraction["git_blob_sha1"])
            tree = ast.parse(payload.decode("utf-8"), filename=str(path))
            expected = [
                (item["name"], item["kind"])
                for item in extraction["symbols"]
            ]
            self.assertEqual(_owned_symbols(tree), expected)
            self.assertEqual(
                _direct_imports(self.source_tree, extraction["core_import_module"]),
                extraction["legacy_core_reexports"],
            )
            extracted_module = importlib.import_module(
                "kaliv_dev_control." + Path(extraction["path"]).stem
            )
            for symbol in extraction["legacy_core_reexports"]:
                self.assertIs(getattr(core, symbol), getattr(extracted_module, symbol))

        environment, lease, path_authority, materialization = extractions
        self.assertEqual(environment["completed_slices"], ["H10K"])
        self.assertEqual(
            environment["resolved_dependencies"],
            {"TierAExecutionError": "_tier_a_lease"},
        )
        self.assertEqual(lease["completed_slices"], ["H10L", "H10M"])
        self.assertEqual(
            lease["direct_consumers"],
            ["_tier_a_environment", "_tier_a_execution_core"],
        )
        self.assertEqual(path_authority["completed_slices"], ["H10N"])
        self.assertEqual(
            path_authority["direct_consumers"],
            ["_tier_a_execution_core"],
        )
        self.assertEqual(
            path_authority["resolved_dependencies"],
            {
                "TierAExecutionError": "_tier_a_lease",
                "_sha256": "_tier_a_lease",
            },
        )
        self.assertEqual(
            materialization["completed_slices"], ["H10O"]
        )
        self.assertEqual(
            materialization["direct_consumers"],
            ["_tier_a_execution_core"],
        )
        self.assertEqual(
            materialization["resolved_dependencies"],
            {
                "TierAExecutionError": "_tier_a_lease",
                "TierAExecutionLease": "_tier_a_lease",
                "_task_sha": "_tier_a_lease",
                "CatalogMaterializer": "catalog",
                "ExecutableVerifier": "catalog",
                "IsolationAttestation": "catalog",
                "ModelRigCommandCatalog": "catalog",
                "Toolchain": "catalog",
                "CommandRegistry": "commands",
                "CommandTemplate": "commands",
                "DevelopmentTask": "contract",
                "WindowsPhysicalIsolationVerifier": "physical_isolation",
            },
        )
        self.assertEqual(
            [item["slice"] for item in self.contract["migration_history"]],
            ["H10K", "H10L", "H10M", "H10N", "H10O"],
        )

    def test_external_core_consumers_are_complete(self):
        target = self.source_path.resolve()
        actual: dict[str, dict[str, object]] = {}
        for path in PACKAGE_ROOT.rglob("*.py"):
            if path.resolve() == target:
                continue
            details = _core_consumer_details(path)
            if details is not None:
                actual[path.relative_to(ROOT).as_posix()] = details
        declared = self.contract["external_core_consumers"]
        self.assertEqual(
            [item["path"] for item in declared],
            sorted(item["path"] for item in declared),
        )
        expected = {
            item["path"]: {
                key: item[key]
                for key in (
                    "import_style",
                    "module_alias",
                    "imported_names",
                    "attribute_references",
                    "dynamic_removals",
                )
            }
            for item in declared
        }
        self.assertEqual(actual, expected)

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

        removals = {
            symbol
            for consumer in self.contract["external_core_consumers"]
            for symbol in consumer["dynamic_removals"]
        }
        self.assertEqual(
            removals,
            {"_run_tier_a_launch_plan", "run_verified_tier_a_command"},
        )
        for symbol in removals:
            self.assertFalse(hasattr(core, symbol))

    def test_markdown_review_tables_have_no_loss_or_duplication(self):
        markdown = REPORT_PATH.read_text(encoding="utf-8")
        table_symbols = re.findall(r"^\| `([^`]+)` \|", markdown, re.MULTILINE)
        expected = [item["name"] for item in self.contract["symbols"]]
        expected.extend(
            item["name"]
            for extraction in self.contract["completed_extractions"]
            for item in extraction["symbols"]
        )
        self.assertCountEqual(table_symbols, expected)
        self.assertEqual(len(table_symbols), len(set(table_symbols)))
        for destination in self.contract["proposed_modules"]:
            self.assertIn(f"`{destination}`", markdown)
        for consumer in self.contract["external_core_consumers"]:
            self.assertIn(f"`{consumer['path']}`", markdown)
        for chain in self.contract["public_identity_chains"]:
            self.assertIn(f"`{chain['symbol']}`", markdown)


if __name__ == "__main__":
    unittest.main()
