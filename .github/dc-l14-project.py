from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import textwrap
from pathlib import Path

ROOT = Path.cwd()
PACKAGE = ROOT / "devcontrol/src/kaliv_dev_control"


def write(path: str, value: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(textwrap.dedent(value).lstrip(), encoding="utf-8")


def git_blob_sha1(payload: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload).hexdigest()


# Package metadata: exact backend and physical exclusion of rejected compatibility code.
pyproject = (ROOT / "devcontrol/pyproject.toml").read_text(encoding="utf-8")
pyproject = pyproject.replace(
    'description = "Fail-closed DC-L01–L10 primitives for controlled self-development"',
    'description = "Fail-closed DC-L01–L14 primitives for controlled self-development"',
)
if 'exclude = ["kaliv_dev_control._compatibility_v1"' not in pyproject:
    pyproject = pyproject.replace(
        'where = ["src"]\n',
        'where = ["src"]\nexclude = ["kaliv_dev_control._compatibility_v1", "kaliv_dev_control._compatibility_v1.*"]\n',
    )
(ROOT / "devcontrol/pyproject.toml").write_text(pyproject, encoding="utf-8")

# Regenerate the final 50-file Tier-A bundle lock/report from the landed tuple.
spec = importlib.util.spec_from_file_location(
    "tier_a_bundle_inventory", ROOT / "scripts/tier_a_bundle_inventory.py"
)
assert spec is not None and spec.loader is not None
inventory_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory_module)
inventory = inventory_module.build_inventory(ROOT)
(ROOT / inventory_module.LOCK_PATH).write_text(
    inventory_module.render_json(inventory_module.build_lock(inventory)), encoding="utf-8"
)
(ROOT / inventory_module.MARKDOWN_PATH).write_text(
    inventory_module.render_markdown(inventory), encoding="utf-8"
)

# Replace the corrupted historical artifact with a final import-only split contract.
core_path = PACKAGE / "_tier_a_execution_core.py"
core_payload = core_path.read_bytes()
core_tree = ast.parse(core_payload.decode("utf-8"), filename=str(core_path))
direct_imports: dict[str, list[str]] = {}
for node in core_tree.body:
    if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
        direct_imports[node.module] = [alias.name for alias in node.names]
contract = {
    "schema": "kaliv-tier-a-execution-core-split-contract/v10",
    "source": "devcontrol/src/kaliv_dev_control/_tier_a_execution_core.py",
    "source_git_blob_sha1": git_blob_sha1(core_payload),
    "import_only": True,
    "direct_imports": direct_imports,
    "forbidden_exports": ["_run_tier_a_launch_plan", "run_verified_tier_a_command"],
    "constraints": {
        "all_production_extractions_complete": True,
        "core_owns_no_classes_or_functions": True,
        "reexports_preserve_object_identity": True,
        "private_executor_remains_absent": True,
        "future_physical_change_requires_fresh_contract": True,
    },
}
write(
    "devcontrol/TIER_A_EXECUTION_CORE_SPLIT_CONTRACT.json",
    json.dumps(contract, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
)
rows = [
    "# Tier-A execution core split contract",
    "",
    "Schema: `kaliv-tier-a-execution-core-split-contract/v10`",
    "",
    "The historical core is now an import-only identity facade. It owns no executor,",
    "process launcher, remote transport, credential loader or publication adapter.",
    "",
    f"Source blob: `{contract['source_git_blob_sha1']}`",
    "",
    "| Extracted module | Re-exported identities |",
    "|---|---|",
]
for module, names in direct_imports.items():
    rows.append(f"| `kaliv_dev_control.{module}` | {', '.join(f'`{name}`' for name in names)} |")
rows.extend([
    "",
    "Forbidden executor identities remain absent: `_run_tier_a_launch_plan` and",
    "`run_verified_tier_a_command`.",
    "",
])
write("devcontrol/TIER_A_EXECUTION_CORE_SPLIT_CONTRACT.md", "\n".join(rows))

write(
    "devcontrol/tests/test_h10j_tier_a_execution_core_split_contract.py",
    r'''
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
    ''',
)

write(
    "devcontrol/tests/test_h10p_tier_a_legacy_toolhost_extraction.py",
    r'''
    from __future__ import annotations

    import ast
    import hashlib
    import importlib
    import tempfile
    import unittest
    from pathlib import Path

    ROOT = Path(__file__).resolve().parents[2]
    MODULE_PATH = ROOT / "devcontrol/src/kaliv_dev_control/_tier_a_legacy_toolhost.py"
    CORE_PATH = ROOT / "devcontrol/src/kaliv_dev_control/_tier_a_execution_core.py"


    def _owned_symbols(path: Path) -> list[tuple[str, str]]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        result: list[tuple[str, str]] = []
        for node in tree.body:
            if isinstance(node, ast.Assign):
                result.extend((target.id, "constant") for target in node.targets if isinstance(target, ast.Name))
            elif isinstance(node, ast.FunctionDef):
                result.append((node.name, "function"))
        return result


    class TierALegacyToolhostExtractionTests(unittest.TestCase):
        def test_module_owns_only_bundle_and_hash_function(self) -> None:
            self.assertEqual(_owned_symbols(MODULE_PATH), [("_TIER_A_BUNDLE_FILES", "constant"), ("tier_a_toolhost_sha256", "function")])
            module = importlib.import_module("kaliv_dev_control._tier_a_legacy_toolhost")
            authority = importlib.import_module("kaliv_dev_control.tier_a_authority")
            self.assertEqual(module._TIER_A_BUNDLE_FILES, authority._TIER_A_BUNDLE_FILES)
            self.assertEqual(len(module._TIER_A_BUNDLE_FILES), 50)
            self.assertEqual(len(module._TIER_A_BUNDLE_FILES), len(set(module._TIER_A_BUNDLE_FILES)))

        def test_core_reexports_exact_objects_without_executor(self) -> None:
            module = importlib.import_module("kaliv_dev_control._tier_a_legacy_toolhost")
            core = importlib.import_module("kaliv_dev_control._tier_a_execution_core")
            self.assertIs(core._TIER_A_BUNDLE_FILES, module._TIER_A_BUNDLE_FILES)
            self.assertIs(core.tier_a_toolhost_sha256, module.tier_a_toolhost_sha256)
            for name in ("_run_tier_a_launch_plan", "run_verified_tier_a_command"):
                self.assertFalse(hasattr(core, name), name)

        def test_hash_behavior_is_v7_exact_and_fail_closed(self) -> None:
            module = importlib.import_module("kaliv_dev_control._tier_a_legacy_toolhost")
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                expected = hashlib.sha256()
                expected.update(b"kaliv-tier-a-toolhost/v7\0")
                for index, relative in enumerate(module._TIER_A_BUNDLE_FILES):
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    payload = f"{index}:{relative}".encode("utf-8")
                    path.write_bytes(payload)
                    expected.update(relative.encode("utf-8"))
                    expected.update(b"\0")
                    expected.update(len(payload).to_bytes(8, "big"))
                    expected.update(payload)
                self.assertEqual(module.tier_a_toolhost_sha256(root), expected.hexdigest())
                (root / module._TIER_A_BUNDLE_FILES[-1]).unlink()
                with self.assertRaisesRegex(module.TierAExecutionError, "missing or unsafe"):
                    module.tier_a_toolhost_sha256(root)

        def test_module_import_boundary_has_no_process_or_remote_authority(self) -> None:
            tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"), filename=str(MODULE_PATH))
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
            self.assertEqual(absolute, {"hashlib", "pathlib"})
            self.assertEqual(relative, {"_tier_a_lease", "_tier_a_path_authority"})
            self.assertFalse(absolute & {"subprocess", "socket", "requests", "urllib", "http"})
            self.assertFalse(relative & {"github_read", "durable_publication", "streaming_publication"})


    if __name__ == "__main__":
        unittest.main()
    ''',
)

# Final protocol inventory: recursive supported-source list, no rejected compatibility package.
PROTOCOL_TOKENS = (
    "publisher",
    "semantic_review",
    "draft_pr_readiness",
    "local_candidate_materialization",
)
EXTRA_PROTOCOL_FILES = {
    "durable_publication.py",
    "streaming_publication.py",
    "store.py",
    "trusted_git_runtime_staging.py",
}
protocol_files: list[str] = []
for path in sorted(PACKAGE.rglob("*.py")):
    relative_package = path.relative_to(PACKAGE).as_posix()
    if any(token in relative_package for token in PROTOCOL_TOKENS) or relative_package in EXTRA_PROTOCOL_FILES:
        protocol_files.append(f"devcontrol/src/kaliv_dev_control/{relative_package}")
lines = [
    "# Publisher protocol and durable-publication inventory",
    "",
    "This final DC-L14 inventory is generated from the recursively discovered supported source tree.",
    "It inventories evidence, review, authorization, recovery, dry-run and local-only materialization",
    "surfaces without granting live publisher, remote Git, GitHub mutation, credential or activation authority.",
    "",
    "## Supported protocol source files",
    "",
]
lines.extend(f"- `{path}`" for path in protocol_files)
lines.extend([
    "",
    "## Packaging boundary",
    "",
    "- `kaliv_dev_control._compatibility_v1` is physically excluded from wheel and sdist artifacts.",
    "- `_local_candidate_materialization_legacy` is a static validation/evidence support package, not an executable legacy runner.",
    "- Live publication, push, reviewer mutation, merge, release, deployment and activation remain absent.",
    "",
])
write("devcontrol/PUBLISHER_PROTOCOL_INVENTORY.md", "\n".join(lines))

write(
    "devcontrol/tests/test_publisher_protocol_inventory_h10f.py",
    r'''
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
            for path in _expected_paths():
                self.assertNotIn("_compatibility_v1", path)

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

        def test_direct_replace_and_named_temporaries_are_confined(self) -> None:
            replace_users: set[str] = set()
            temporary_users: set[str] = set()
            for relative in sorted(_expected_paths()):
                path = ROOT / relative
                source = path.read_text(encoding="utf-8")
                if "os.replace(" in source or ".replace(" in source:
                    replace_users.add(path.relative_to(PACKAGE).as_posix())
                if "NamedTemporaryFile(" in source:
                    temporary_users.add(path.relative_to(PACKAGE).as_posix())
            self.assertTrue(replace_users <= {"store.py", "_local_candidate_materialization_legacy/__init__.py"}, replace_users)
            self.assertTrue(temporary_users <= {"store.py"}, temporary_users)


    if __name__ == "__main__":
        unittest.main()
    ''',
)

write(
    "devcontrol/tests/test_dc_l14_reproducible_packaging.py",
    r'''
    from __future__ import annotations

    import hashlib
    import os
    import shutil
    import subprocess
    import sys
    import tarfile
    import tempfile
    import unittest
    import zipfile
    from pathlib import Path

    ROOT = Path(__file__).resolve().parents[2]
    PROJECT = ROOT / "devcontrol"


    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()


    def _copy_project(destination: Path) -> Path:
        target = destination / "devcontrol"
        shutil.copytree(
            PROJECT,
            target,
            ignore=shutil.ignore_patterns("dist", "build", "*.egg-info", "__pycache__", "*.pyc"),
        )
        return target


    def _build(source: Path, output: Path) -> tuple[Path, Path]:
        env = dict(os.environ)
        env.update({"SOURCE_DATE_EPOCH": "1700000000", "PYTHONHASHSEED": "0", "TZ": "UTC"})
        subprocess.run(
            (sys.executable, "-m", "build", "--no-isolation", "--wheel", "--sdist", "--outdir", str(output)),
            cwd=source,
            env=env,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        wheel = next(output.glob("*.whl"))
        sdist = next(output.glob("*.tar.gz"))
        return wheel, sdist


    class ReproduciblePackagingTests(unittest.TestCase):
        def test_wheel_and_sdist_are_reproducible_and_exclude_compatibility(self) -> None:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                first_source = _copy_project(root / "first")
                second_source = _copy_project(root / "second")
                first = _build(first_source, root / "dist-first")
                second = _build(second_source, root / "dist-second")
                self.assertEqual([_sha256(path) for path in first], [_sha256(path) for path in second])

                with zipfile.ZipFile(first[0]) as archive:
                    wheel_members = sorted(archive.namelist())
                with tarfile.open(first[1], "r:gz") as archive:
                    sdist_members = sorted(member.name.split("/", 1)[-1] for member in archive.getmembers() if "/" in member.name)

                self.assertTrue(any(name.endswith("kaliv_dev_control/__init__.py") for name in wheel_members))
                self.assertTrue(any("_local_candidate_materialization_legacy/__init__.py" in name for name in wheel_members))
                for members in (wheel_members, sdist_members):
                    joined = "\n".join(members)
                    self.assertNotIn("_compatibility_v1", joined)
                    self.assertNotIn("__pycache__", joined)
                    self.assertNotIn(".pyc", joined)

        def test_project_has_no_upload_or_publish_tooling(self) -> None:
            pyproject = (PROJECT / "pyproject.toml").read_text(encoding="utf-8")
            for token in ("twine", "upload", "repository-url", "api-token"):
                self.assertNotIn(token, pyproject.lower())
            self.assertIn('setuptools==75.8.2', pyproject)
            self.assertIn('kaliv_dev_control._compatibility_v1.*', pyproject)


    if __name__ == "__main__":
        unittest.main()
    ''',
)

print(json.dumps({"inventory_files": inventory["file_count"], "protocol_files": len(protocol_files)}, sort_keys=True))
