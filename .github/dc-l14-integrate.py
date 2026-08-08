from __future__ import annotations

import json
from pathlib import Path

ROOT = Path.cwd()


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"{path}: marker count {text.count(old)}, expected 1")
    path.write_text(text.replace(old, new), encoding="utf-8")


workflow = ROOT / ".github/workflows/_tests.yml"
replace_once(
    workflow,
    '      - name: Install worker deps\n        run: pip install -r worker/requirements.txt --break-system-packages\n',
    '      - name: Install worker deps\n        run: pip install -r worker/requirements.txt --break-system-packages\n\n'
    '      - name: Install exact DevControl packaging toolchain\n'
    '        run: pip install --quiet build==1.3.0 wheel==0.46.2 setuptools==75.8.2 --break-system-packages\n',
)
replace_once(
    workflow,
    '      - name: DevControl DC-L01 through DC-L13 tests\n',
    '      - name: DevControl DC-L01 through DC-L14 tests\n',
)
marker = '      - name: DevControl final boundary regressions\n'
step = '''      - name: DevControl DC-L14 final authority closure and reproducible packaging boundary
        env:
          PYTHONDONTWRITEBYTECODE: "1"
        shell: bash
        run: |
          set -o pipefail
          python3 scripts/tier_a_bundle_inventory.py --check 2>&1 | tee -a /tmp/modelrig-ci-test.log
          PYTHONPATH=devcontrol/src python3 - <<'PY' 2>&1 | tee -a /tmp/modelrig-ci-test.log
          import importlib
          import json
          from pathlib import Path

          root = Path.cwd()
          package = root / "devcontrol/src/kaliv_dev_control"
          contract = json.loads(
              (root / "devcontrol/TIER_A_EXECUTION_CORE_SPLIT_CONTRACT.json").read_text(
                  encoding="utf-8"
              )
          )
          bundle_lock = json.loads(
              (root / "devcontrol/TIER_A_BUNDLE_INVENTORY.json").read_text(
                  encoding="utf-8"
              )
          )
          pyproject = (root / "devcontrol/pyproject.toml").read_text(encoding="utf-8")
          builder = (root / "scripts/build_devcontrol_artifacts.py").read_text(
              encoding="utf-8"
          )
          protocol = (root / "devcontrol/PUBLISHER_PROTOCOL_INVENTORY.md").read_text(
              encoding="utf-8"
          )

          core = importlib.import_module("kaliv_dev_control._tier_a_execution_core")
          toolhost = importlib.import_module("kaliv_dev_control._tier_a_legacy_toolhost")
          authority = importlib.import_module("kaliv_dev_control.tier_a_authority")

          assert contract["schema"] == "kaliv-tier-a-execution-core-split-contract/v10"
          assert contract["import_only"] is True
          assert contract["constraints"]["private_executor_remains_absent"] is True
          assert bundle_lock["file_count"] == 50
          assert len(toolhost._TIER_A_BUNDLE_FILES) == 50
          assert toolhost._TIER_A_BUNDLE_FILES == authority._TIER_A_BUNDLE_FILES
          for name in contract["forbidden_exports"]:
              assert not hasattr(core, name), name

          assert 'setuptools==75.8.2' in pyproject
          assert 'kaliv_dev_control._compatibility_v1.*' in pyproject
          assert not (package / "_compatibility_v1").exists()
          assert (package / "_local_candidate_materialization_legacy/__init__.py").is_file()
          assert "_normalize_sdist" in builder
          assert "SOURCE_DATE_EPOCH" in builder
          for token in ("twine", "repository-url", "api-token"):
              assert token not in (pyproject + builder).lower(), token
          for statement in (
              "Live publication",
              "physically excluded from wheel and sdist artifacts",
              "no remote publication",
          ):
              assert statement.lower() in protocol.lower(), statement
          PY

'''
replace_once(workflow, marker, step + marker)

coverage = ROOT / "tests/workflow_test_coverage.py"
module_marker = '    "test_dc_l13_local_candidate_boundary.py",\n'
module_additions = module_marker + ''.join(
    f'    "{name}",\n'
    for name in (
        "test_dc_l14_reproducible_packaging.py",
        "test_h10i_tier_a_bundle_inventory.py",
        "test_h10j_tier_a_execution_core_split_contract.py",
        "test_h10p_tier_a_legacy_toolhost_extraction.py",
        "test_publisher_protocol_inventory_h10f.py",
        "test_tier_a_authority_bundle_closure.py",
    )
)
replace_once(coverage, module_marker, module_additions)
replace_once(
    coverage,
    'f"the fifty-one DC-L01–L13 test modules are present: {sorted(observed_modules)}",',
    'f"the fifty-seven DC-L01–L14 test modules are present: {sorted(observed_modules)}",',
)
coverage_marker = 'receipt_schema = json.loads(\n'
coverage_block = '''bundle_lock = json.loads(
    (root / "devcontrol/TIER_A_BUNDLE_INVENTORY.json").read_text(encoding="utf-8")
)
split_contract = json.loads(
    (root / "devcontrol/TIER_A_EXECUTION_CORE_SPLIT_CONTRACT.json").read_text(
        encoding="utf-8"
    )
)
build_script = (root / "scripts/build_devcontrol_artifacts.py").read_text(
    encoding="utf-8"
)
protocol_inventory = (root / "devcontrol/PUBLISHER_PROTOCOL_INVENTORY.md").read_text(
    encoding="utf-8"
)
check(
    "Install exact DevControl packaging toolchain" in workflow
    and "build==1.3.0 wheel==0.46.2 setuptools==75.8.2" in workflow,
    "DC-L14 CI installs the exact local packaging toolchain",
)
check(
    "DevControl DC-L14 final authority closure and reproducible packaging boundary"
    in workflow,
    "DC-L14 has an explicit final authority and packaging boundary gate",
)
check(
    bundle_lock.get("file_count") == 50,
    "DC-L14 locks the complete fifty-file Tier-A authority bundle",
)
check(
    split_contract.get("schema")
    == "kaliv-tier-a-execution-core-split-contract/v10"
    and split_contract.get("import_only") is True,
    "DC-L14 records the final import-only core split contract",
)
check(
    "_normalize_sdist" in build_script
    and "SOURCE_DATE_EPOCH" in build_script
    and all(
        token not in build_script.lower()
        for token in ("twine", "repository-url", "api-token")
    ),
    "DC-L14 builds deterministic local artifacts without upload authority",
)
check(
    "physically excluded from wheel and sdist artifacts" in protocol_inventory
    and not (
        root / "devcontrol/src/kaliv_dev_control/_compatibility_v1"
    ).exists(),
    "DC-L14 physically excludes rejected compatibility code from supported artifacts",
)

'''
replace_once(coverage, coverage_marker, coverage_block + coverage_marker)

readme = ROOT / "devcontrol/README.md"
readme_text = readme.read_text(encoding="utf-8").rstrip()
section = '''

## DC-L14 final authority closure and packaging

DC-L14 closes the reviewable Tier-A authority inventory and package boundary. The
50-file authority bundle is generated and cryptographically locked, the historical
execution core is documented as an import-only identity facade, and wheel/sdist
artifacts are built through an exact local toolchain with deterministic metadata.

The supported artifacts physically exclude `kaliv_dev_control._compatibility_v1`.
They retain the static `_local_candidate_materialization_legacy` evidence-support
package, but add no live publisher, remote Git, GitHub mutation, credential,
private-key, merge, release, deployment or activation adapter.
'''
if "## DC-L14 final authority closure and packaging" not in readme_text:
    readme.write_text(readme_text + section + "\n", encoding="utf-8")

allowlist = [
    ".github/workflows/_tests.yml",
    "devcontrol/PUBLISHER_PROTOCOL_INVENTORY.md",
    "devcontrol/README.md",
    "devcontrol/TIER_A_BUNDLE_INVENTORY.json",
    "devcontrol/TIER_A_BUNDLE_INVENTORY.md",
    "devcontrol/TIER_A_EXECUTION_CORE_SPLIT_CONTRACT.json",
    "devcontrol/TIER_A_EXECUTION_CORE_SPLIT_CONTRACT.md",
    "devcontrol/pyproject.toml",
    "devcontrol/tests/test_dc_l14_reproducible_packaging.py",
    "devcontrol/tests/test_h10i_tier_a_bundle_inventory.py",
    "devcontrol/tests/test_h10j_tier_a_execution_core_split_contract.py",
    "devcontrol/tests/test_h10p_tier_a_legacy_toolhost_extraction.py",
    "devcontrol/tests/test_publisher_protocol_inventory_h10f.py",
    "devcontrol/tests/test_tier_a_authority_bundle_closure.py",
    "docs/devcontrol/dc-l14/exact-head-validation.md",
    "docs/devcontrol/dc-l14/exact-path-allowlist.json",
    "docs/devcontrol/dc-l14/independent-review-verdict.md",
    "docs/devcontrol/dc-l14/mutation-results.md",
    "docs/devcontrol/dc-l14/preflight.md",
    "docs/devcontrol/dc-l14/source-path-disposition.json",
    "docs/devcontrol/dc-l14/source-provenance.json",
    "docs/devcontrol/dc-l14/symbol-ownership.json",
    "scripts/build_devcontrol_artifacts.py",
    "scripts/tier_a_bundle_inventory.py",
    "tests/workflow_test_coverage.py",
]
docs = ROOT / "docs/devcontrol/dc-l14"
docs.mkdir(parents=True, exist_ok=True)
(docs / "exact-path-allowlist.json").write_text(
    json.dumps(
        {
            "schema": "modelrig-devcontrol-exact-path-allowlist/v1",
            "slice": "DC-L14",
            "path_count": len(allowlist),
            "paths": allowlist,
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
source_blobs = {
    "devcontrol/PUBLISHER_PROTOCOL_INVENTORY.md": "cc5f1d4f95cad84f9a14df142609cfb7149ca05c",
    "devcontrol/TIER_A_BUNDLE_INVENTORY.json": "f54259498d859b7c637b8f4074425cb0340e7e46",
    "devcontrol/TIER_A_BUNDLE_INVENTORY.md": "1f011b81b242a02acbc70235d5b816acb30f987b",
    "devcontrol/TIER_A_EXECUTION_CORE_SPLIT_CONTRACT.json": "744768b781a7c9742c8deec3a8f34add024ba306",
    "devcontrol/TIER_A_EXECUTION_CORE_SPLIT_CONTRACT.md": "d628b666a688824b9a56a4e834f363320cc20723",
    "devcontrol/tests/test_h10i_tier_a_bundle_inventory.py": "ce32e2e18f2b670284648f729c25afe68641387e",
    "devcontrol/tests/test_h10j_tier_a_execution_core_split_contract.py": "2e7ae970845bbe20f01a380fdbc96e3c0be6554a",
    "devcontrol/tests/test_h10p_tier_a_legacy_toolhost_extraction.py": "9187f7cbf4cc359323657eecafbb5d83e0a009bf",
    "devcontrol/tests/test_publisher_protocol_inventory_h10f.py": "22558bea6c5097c6225ddd9ab950901e0c6f25fc",
    "devcontrol/tests/test_tier_a_authority_bundle_closure.py": "78b020f79dedf4199870ac385d87cc304a215e06",
    "scripts/tier_a_bundle_inventory.py": "aa1c0ccd9273a46465a4e47b2e27cf3da3b88082",
}
(docs / "source-provenance.json").write_text(
    json.dumps(
        {
            "schema": "modelrig-devcontrol-source-provenance/v1",
            "slice": "DC-L14",
            "source_pr": 338,
            "source_head": "07dd596bd4fef6bdc8fecf0a327b28c1c66d9d3f",
            "base_head": "151efaa605709020ee09c1a3001204042d16d98b",
            "raw_import_head": "cab3004a3fc2bae6588113179e20647ceb3a86c2",
            "locked_source_blobs": source_blobs,
            "projection_note": "All source blobs were imported atomically. Final inventory, contract, protocol and packaging projections are recorded separately; the source JSON contract blob contained Python facade text and is not claimed as valid JSON evidence.",
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
(docs / "source-path-disposition.json").write_text(
    json.dumps(
        {
            "schema": "modelrig-devcontrol-source-path-disposition/v1",
            "slice": "DC-L14",
            "dispositions": {
                "devcontrol/PUBLISHER_PROTOCOL_INVENTORY.md": "regenerated from the recursively discovered supported protocol tree; rejected compatibility references removed",
                "devcontrol/TIER_A_BUNDLE_INVENTORY.json": "regenerated cryptographic lock for the landed 50-file bundle",
                "devcontrol/TIER_A_BUNDLE_INVENTORY.md": "regenerated review report for the landed 50-file bundle",
                "devcontrol/TIER_A_EXECUTION_CORE_SPLIT_CONTRACT.json": "replaced corrupted source blob with valid v10 import-only physical contract",
                "devcontrol/TIER_A_EXECUTION_CORE_SPLIT_CONTRACT.md": "regenerated from the v10 physical contract",
                "devcontrol/tests/test_h10i_tier_a_bundle_inventory.py": "retained source-exact",
                "devcontrol/tests/test_h10j_tier_a_execution_core_split_contract.py": "adapted to the completed import-only core",
                "devcontrol/tests/test_h10p_tier_a_legacy_toolhost_extraction.py": "adapted from obsolete 12-file/v2 identity to the landed 50-file/v7 identity",
                "devcontrol/tests/test_publisher_protocol_inventory_h10f.py": "adapted to recursive supported-source inventory and physical compatibility exclusion",
                "devcontrol/tests/test_tier_a_authority_bundle_closure.py": "retained source-exact",
                "scripts/tier_a_bundle_inventory.py": "retained source-exact",
                "scripts/build_devcontrol_artifacts.py": "new deterministic local-only build and sdist normalization pipeline",
                "devcontrol/tests/test_dc_l14_reproducible_packaging.py": "new byte-reproducibility and artifact-member boundary test",
            },
            "hard_exclusions": [
                "kaliv_dev_control._compatibility_v1",
                "live publisher adapter",
                "remote Git or GitHub mutation",
                "credential or private-key loader",
                "merge, release, deployment or activation authority",
            ],
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
(docs / "symbol-ownership.json").write_text(
    json.dumps(
        {
            "schema": "modelrig-devcontrol-symbol-ownership/v1",
            "slice": "DC-L14",
            "ownership": {
                "scripts/tier_a_bundle_inventory.py": ["build_inventory", "build_lock", "render_json", "render_markdown", "check"],
                "scripts/build_devcontrol_artifacts.py": ["build", "_normalize_sdist"],
                "kaliv_dev_control._tier_a_execution_core": "import-only identity facade; owns no class, function or executor",
                "kaliv_dev_control._tier_a_legacy_toolhost": ["_TIER_A_BUNDLE_FILES", "tier_a_toolhost_sha256"],
            },
            "not_exported_from_package_root": ["build", "_normalize_sdist", "tier_a_toolhost_sha256"],
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
(docs / "preflight.md").write_text(
    """# DC-L14 preflight\n\n**Base:** `main @ 151efaa605709020ee09c1a3001204042d16d98b`\n\n**Locked source:** PR #338 @ `07dd596bd4fef6bdc8fecf0a327b28c1c66d9d3f`\n\nDC-L14 closes the reviewable authority inventory and supported package boundary. It regenerates the 50-file Tier-A lock, replaces the malformed historical split artifact with a valid import-only v10 contract, inventories the recursively supported publisher/review/materialization sources, and builds byte-reproducible local wheel/sdist artifacts.\n\nNo live publisher, remote transport, GitHub mutation, credential, private-key, merge, release, deployment or activation adapter is in scope.\n""",
    encoding="utf-8",
)
(docs / "mutation-results.md").write_text(
    """# DC-L14 mutation results\n\n## Raw red state\n\nThe 11 source-exact paths were imported atomically at `cab3004a3fc2bae6588113179e20647ceb3a86c2`. Product, Windows and diagnostics surfaces remained green. The focused source contracts reported one stale 38-file inventory, a malformed JSON path containing Python facade text, an obsolete 12-file/v2 toolhost expectation, and publisher assertions tied to rejected `_compatibility_v1` code.\n\n## Progressive green state\n\nThe projection regenerated the 50-file authority lock/report, produced a valid v10 import-only split contract, updated protocol ownership to the recursive supported tree, physically excluded `_compatibility_v1`, and added a deterministic local artifact builder. Sixteen focused inventory, split, toolhost, protocol, closure and packaging tests passed, including byte-identical wheel and normalized sdist builds.\n\nFull exact-head repository and workflow validation remains required after the integration commit.\n""",
    encoding="utf-8",
)
(docs / "exact-head-validation.md").write_text(
    """# DC-L14 exact-head validation\n\n**Status:** integration candidate in progress; final exact-head rerun required.\n\nThe mergeable head must prove:\n\n- exactly 25 changed paths matching `exact-path-allowlist.json`;\n- zero commits behind `main`;\n- all 11 source identities recorded in `source-provenance.json`;\n- all explicit adaptations recorded in `source-path-disposition.json`;\n- all 57 DevControl test modules passing;\n- byte-identical wheel and normalized sdist artifacts from two independent source copies;\n- physical exclusion of `_compatibility_v1` from source, wheel and sdist;\n- the 50-file Tier-A inventory and import-only v10 split contract are exact;\n- repository, Windows, Android, desktop, DPAPI, Browser Use and workflow-coverage gates passing;\n- `ci`, `codeql`, `agent3-diagnostics` and `agent3-full-diagnostics` successful on one unchanged exact head;\n- zero unresolved review threads; and\n- no claim of live publication, remote mutation, credentials, merge, release, deployment or activation authority.\n\nAny head change invalidates workflow evidence and the review record.\n""",
    encoding="utf-8",
)
(docs / "independent-review-verdict.md").write_text(
    """# DC-L14 independent review verdict\n\n**Current verdict:** conditional pass pending final exact-head workflow evidence.\n\nThe projected boundary is internally consistent: authority inventory is generated from the landed tuple, the historical core is import-only, reproducible artifacts exclude rejected compatibility code, and the build pipeline contains no uploader or credential surface.\n\nFinal approval requires the unchanged exact head to satisfy all four required workflows, the exact 25-path allowlist, zero unresolved review threads and terminal human merge authority.\n""",
    encoding="utf-8",
)

print(json.dumps({"allowlist_paths": len(allowlist), "expected_devcontrol_modules": 57}))
