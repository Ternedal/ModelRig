from __future__ import annotations

from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: marker count {count}, expected 1\n{old}")
    path.write_text(text.replace(old, new), encoding="utf-8")


workflow = Path(".github/workflows/_tests.yml")
replace_once(
    workflow,
    "      - name: DevControl DC-L01 through DC-L12 tests\n",
    "      - name: DevControl DC-L01 through DC-L13 tests\n",
)
replace_once(
    workflow,
    '''          for future_module in (
              "kaliv_dev_control.local_candidate_materialization",
              "kaliv_dev_control.local_candidate_materialization_h5c",
          ):
              assert importlib.util.find_spec(future_module) is None, future_module
''',
    '''          for landed_module in (
              "kaliv_dev_control.local_candidate_materialization",
              "kaliv_dev_control.local_candidate_materialization_h5c",
          ):
              assert importlib.util.find_spec(landed_module) is not None, landed_module
''',
)
marker = "      - name: DevControl final boundary regressions\n"
step = '''      - name: DevControl DC-L13 local-only candidate materialization boundary
        env:
          PYTHONDONTWRITEBYTECODE: "1"
        shell: bash
        run: |
          set -o pipefail
          PYTHONPATH=devcontrol/src python3 - <<'PY' 2>&1 | tee -a /tmp/modelrig-ci-test.log
          import ast
          import importlib
          import inspect
          import json
          from pathlib import Path

          import kaliv_dev_control

          root = Path.cwd()
          source_root = root / "devcontrol/src/kaliv_dev_control"
          local = importlib.import_module(
              "kaliv_dev_control.local_candidate_materialization"
          )
          asymmetric = importlib.import_module(
              "kaliv_dev_control.local_candidate_materialization_h5c"
          )
          support = importlib.import_module(
              "kaliv_dev_control._local_candidate_materialization_legacy"
          )
          tier_a_facade = importlib.import_module("kaliv_dev_control.tier_a_execution")
          toolhost = importlib.import_module("kaliv_dev_control._tier_a_legacy_toolhost")

          assert callable(local.LocalCandidateMaterializationGate.valid)
          assert callable(local.materialize_local_candidate)
          assert callable(local.verify_local_candidate_materialization)
          assert callable(asymmetric.AsymmetricLocalCandidateMaterializationGate.valid)
          assert callable(asymmetric.materialize_asymmetric_local_candidate)
          assert Path(support.__file__).name == "__init__.py"
          assert not (source_root / "_local_candidate_materialization_legacy.py").exists()
          assert not (source_root / "_compatibility_v1").exists()

          for name in (
              "TrustedLocalGit",
              "materialize_local_candidate",
              "verify_local_candidate_materialization",
              "LocalCandidateMaterializationGate",
          ):
              assert not hasattr(support, name), name

          support_source = inspect.getsource(support)
          local_source = inspect.getsource(local)
          asymmetric_source = inspect.getsource(asymmetric)
          for token in (
              "import subprocess",
              "globals().update",
              "._compatibility_v1",
              "subprocess.run",
              "Popen(",
              "requests.",
              "urllib",
              "http.client",
              "Ed25519PrivateKey",
              ".sign(",
          ):
              assert token not in support_source, token

          combined = local_source + asymmetric_source
          tree = ast.parse(combined)
          strings = {
              node.value
              for node in ast.walk(tree)
              if isinstance(node, ast.Constant) and isinstance(node.value, str)
          }
          assert "fetch" in strings
          assert ".as_uri()" in combined
          for forbidden_command in (
              "push",
              "remote",
              "clone",
              "pull",
              "credential",
              "credential.helper",
              "commit.gpgsign",
              "user.signingkey",
          ):
              assert forbidden_command not in strings, forbidden_command
          for token in (
              "https://",
              "http://",
              "ssh://",
              "git@",
              "requests.",
              "urllib",
              "http.client",
              "socket.",
              "paramiko",
              "Ed25519PrivateKey",
              "private_key",
              ".sign(",
          ):
              assert token not in combined, token

          for name in (
              "LocalCandidateMaterializationReceipt",
              "LocalCandidateMaterializationGate",
              "AsymmetricLocalCandidateMaterializationGate",
              "materialize_local_candidate",
              "materialize_asymmetric_local_candidate",
          ):
              assert not hasattr(kaliv_dev_control, name), name
              assert not hasattr(tier_a_facade, name), name
          assert all(
              "local_candidate_materialization" not in path
              for path in toolhost._TIER_A_BUNDLE_FILES
          )

          for version in ("v1", "v2"):
              schema_path = (
                  root
                  / "devcontrol/schemas"
                  / f"development-local-candidate-materialization-receipt-{version}.schema.json"
              )
              schema = json.loads(schema_path.read_text(encoding="utf-8"))
              properties = schema["properties"]
              assert schema.get("additionalProperties") is False
              assert properties["bare_repository"]["const"] is True
              assert properties["isolated_index"]["const"] is True
              assert properties["local_source_only"]["const"] is True
              assert properties["merge_authority"]["const"] == "human"
              for false_claim in (
                  "remote_configured",
                  "network_write_performed",
                  "remote_push_performed",
                  "pull_request_created",
                  "ready_for_review",
                  "reviewers_requested",
                  "merged",
                  "released",
                  "deployed",
              ):
                  assert properties[false_claim]["const"] is False, (version, false_claim)
              serialized = json.dumps(schema, sort_keys=True)
              for forbidden in (
                  "remote_url",
                  "access_token",
                  "credential_helper",
                  "signing_key",
                  "github_token",
              ):
                  assert forbidden not in serialized, (version, forbidden)
          PY

'''
replace_once(workflow, marker, step + marker)
