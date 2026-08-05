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


def _loop_string_values(tree: ast.Module) -> dict[str, set[str]]:
    values: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.For) or not isinstance(node.target, ast.Name):
            continue
        if not isinstance(node.iter, (ast.Tuple, ast.List, ast.Set)):
            continue
        items = {item.value for item in node.iter.elts if isinstance(item, ast.Constant) and isinstance(item.value, str)}
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
                module_aliases.update(alias.asname or alias.name for alias in node.names if alias.name == "_tier_a_execution_core")
        elif isinstance(node, ast.Import):
            module_aliases.update(alias.asname or alias.name for alias in node.names if alias.name.endswith("._tier_a_execution_core"))
    if not imported_names and not module_aliases:
        return None
    if imported_names and module_aliases:
        raise AssertionError(f"mixed core import styles are not supported: {path}")
    if imported_names:
        return {"import_style":"direct","module_alias":None,"imported_names":sorted(imported_names),"attribute_references":[],"dynamic_removals":[]}
    if len(module_aliases) != 1:
        raise AssertionError(f"core module alias is ambiguous: {path}")
    alias_name = next(iter(module_aliases))
    attributes = sorted({node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == alias_name})
    loop_values = _loop_string_values(tree)
    removals: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "delattr" or len(node.args) != 2 or not isinstance(node.args[0], ast.Name) or node.args[0].id != alias_name:
            continue
        value=node.args[1]
        if isinstance(value, ast.Constant) and isinstance(value.value,str): removals.add(value.value)
        elif isinstance(value, ast.Name): removals.update(loop_values.get(value.id,set()))
    return {"import_style":"module_alias","module_alias":alias_name,"imported_names":[],"attribute_references":attributes,"dynamic_removals":sorted(removals)}


def _git_blob_sha1(payload: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload).hexdigest()


def _resolve(reference: str):
    module_name, symbol = reference.rsplit(".", 1)
    module = importlib.import_module(f"kaliv_dev_control.{module_name}" if module_name != "kaliv_dev_control" else module_name)
    return getattr(module, symbol)


class TierAExecutionCoreSplitContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract=json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.source_path=ROOT/cls.contract["source"]
        cls.source_bytes=cls.source_path.read_bytes()
        cls.source_tree=ast.parse(cls.source_bytes.decode("utf-8"),filename=str(cls.source_path))

    def test_source_and_remaining_symbol_mapping_are_exact(self):
        self.assertEqual(self.contract["schema"],"kaliv-tier-a-execution-core-split-contract/v2")
        self.assertEqual(_git_blob_sha1(self.source_bytes),self.contract["source_git_blob_sha1"])
        expected=_owned_symbols(self.source_tree)
        actual=[(item["name"],item["kind"]) for item in self.contract["symbols"]]
        self.assertEqual(actual,expected)
        self.assertEqual(len(actual),len(set(actual)))
        destinations=set(self.contract["proposed_modules"])
        self.assertEqual({item["destination"] for item in self.contract["symbols"]},destinations)
        self.assertTrue(self.contract["constraints"]["h10k_moves_environment_policy"])
        self.assertTrue(self.contract["constraints"]["earlier_physical_evidence_is_stale"])

    def test_h10k_extraction_is_exact_and_identity_preserving(self):
        extraction=self.contract["completed_extractions"]
        self.assertEqual(len(extraction),1)
        extraction=extraction[0]
        self.assertEqual(extraction["slice"],"H10K")
        path=ROOT/extraction["destination"]
        payload=path.read_bytes()
        self.assertEqual(_git_blob_sha1(payload),extraction["destination_git_blob_sha1"])
        tree=ast.parse(payload.decode("utf-8"),filename=str(path))
        self.assertEqual(_owned_symbols(tree),[(item["name"],item["kind"]) for item in extraction["symbols"]])
        core=importlib.import_module("kaliv_dev_control._tier_a_execution_core")
        environment=importlib.import_module("kaliv_dev_control._tier_a_environment")
        for item in extraction["symbols"]:
            self.assertIs(getattr(core,item["name"]),getattr(environment,item["name"]))

    def test_external_core_consumers_are_complete(self):
        target=self.source_path.resolve(); actual={}
        for path in PACKAGE_ROOT.rglob("*.py"):
            if path.resolve()==target: continue
            details=_core_consumer_details(path)
            if details is not None: actual[path.relative_to(ROOT).as_posix()]=details
        declared=self.contract["external_core_consumers"]
        self.assertEqual([item["path"] for item in declared],sorted(item["path"] for item in declared))
        expected={item["path"]:{key:item[key] for key in ("import_style","module_alias","imported_names","attribute_references","dynamic_removals")} for item in declared}
        self.assertEqual(actual,expected)

    def test_identity_chains_are_preserved_today(self):
        for collection in ("public_identity_chains","private_identity_chains"):
            declared=self.contract[collection]
            self.assertEqual([item["symbol"] for item in declared],sorted(item["symbol"] for item in declared))
            for item in declared:
                identities=[_resolve(reference) for reference in item["chain"]]
                for identity in identities[1:]: self.assertIs(identity,identities[0])
        facade=importlib.import_module("kaliv_dev_control.tier_a_execution")
        package=importlib.import_module("kaliv_dev_control")
        for item in self.contract["public_identity_chains"]:
            self.assertIn(item["symbol"],facade.__all__)
            self.assertIn(item["symbol"],package.__all__)
        core=importlib.import_module("kaliv_dev_control._tier_a_execution_core")
        removals={symbol for consumer in self.contract["external_core_consumers"] for symbol in consumer["dynamic_removals"]}
        self.assertEqual(removals,{"_run_tier_a_launch_plan","run_verified_tier_a_command"})
        for symbol in removals: self.assertFalse(hasattr(core,symbol))

    def test_markdown_review_table_has_no_loss_or_duplication(self):
        markdown=REPORT_PATH.read_text(encoding="utf-8")
        table_symbols=re.findall(r"^\| `([^`]+)` \|",markdown,re.MULTILINE)
        expected=[item["name"] for item in self.contract["symbols"]]
        self.assertEqual(table_symbols,expected)
        self.assertEqual(len(table_symbols),len(set(table_symbols)))
        for extraction in self.contract["completed_extractions"]: self.assertIn(f"`{extraction['destination']}`",markdown)
        for consumer in self.contract["external_core_consumers"]: self.assertIn(f"`{consumer['path']}`",markdown)


if __name__ == "__main__": unittest.main()
