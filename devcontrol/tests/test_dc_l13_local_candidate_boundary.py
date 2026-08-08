from __future__ import annotations

import ast
import importlib
import inspect
import json
import unittest
from pathlib import Path

import kaliv_dev_control
import kaliv_dev_control._tier_a_legacy_toolhost as toolhost
from kaliv_dev_control.local_candidate_materialization import (
    LocalCandidateMaterializationGate,
)
from kaliv_dev_control.local_candidate_materialization_h5c import (
    AsymmetricLocalCandidateMaterializationGate,
)


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "devcontrol/src/kaliv_dev_control"


class DcL13LocalCandidateBoundaryTests(unittest.TestCase):
    def test_modern_surface_is_local_and_not_exported_from_broader_facades(self) -> None:
        local = importlib.import_module(
            "kaliv_dev_control.local_candidate_materialization"
        )
        asymmetric = importlib.import_module(
            "kaliv_dev_control.local_candidate_materialization_h5c"
        )
        support = importlib.import_module(
            "kaliv_dev_control._local_candidate_materialization_legacy"
        )
        tier_a = importlib.import_module("kaliv_dev_control.tier_a_execution")

        self.assertTrue(callable(local.materialize_local_candidate))
        self.assertTrue(callable(local.verify_local_candidate_materialization))
        self.assertTrue(callable(asymmetric.materialize_asymmetric_local_candidate))
        self.assertEqual(Path(support.__file__).name, "__init__.py")
        self.assertFalse((SOURCE_ROOT / "_local_candidate_materialization_legacy.py").exists())
        self.assertFalse((SOURCE_ROOT / "_compatibility_v1").exists())

        for name in (
            "LocalCandidateMaterializationReceipt",
            "LocalCandidateMaterializationGate",
            "AsymmetricLocalCandidateMaterializationGate",
            "materialize_local_candidate",
            "materialize_asymmetric_local_candidate",
        ):
            self.assertFalse(hasattr(kaliv_dev_control, name), name)
            self.assertFalse(hasattr(tier_a, name), name)

        self.assertTrue(
            all(
                "local_candidate_materialization" not in path
                for path in toolhost._TIER_A_BUNDLE_FILES
            )
        )

    def test_static_support_contains_no_legacy_execution_or_compatibility_proxy(self) -> None:
        support = importlib.import_module(
            "kaliv_dev_control._local_candidate_materialization_legacy"
        )
        source = inspect.getsource(support)
        for name in (
            "TrustedLocalGit",
            "materialize_local_candidate",
            "verify_local_candidate_materialization",
            "LocalCandidateMaterializationGate",
        ):
            self.assertFalse(hasattr(support, name), name)
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
            self.assertNotIn(token, source, token)

    def test_modern_modules_encode_no_remote_git_or_credential_command(self) -> None:
        sources = [
            (SOURCE_ROOT / "local_candidate_materialization.py").read_text(
                encoding="utf-8"
            ),
            (SOURCE_ROOT / "local_candidate_materialization_h5c.py").read_text(
                encoding="utf-8"
            ),
        ]
        tree = ast.parse("\n".join(sources))
        strings = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        for command in (
            "push",
            "remote",
            "clone",
            "pull",
            "credential",
            "credential.helper",
            "commit.gpgsign",
            "user.signingkey",
        ):
            self.assertNotIn(command, strings, command)
        combined = "\n".join(sources)
        self.assertIn("fetch", strings)
        self.assertIn(".as_uri()", combined)
        for forbidden_url in ("https://", "http://", "ssh://", "git@"):
            self.assertNotIn(forbidden_url, combined, forbidden_url)
        for token in (
            "requests.",
            "urllib",
            "http.client",
            "socket.",
            "paramiko",
            "Ed25519PrivateKey",
            "private_key",
            ".sign(",
        ):
            self.assertNotIn(token, combined, token)

    def test_invalid_receipt_types_fail_closed_before_local_mutation(self) -> None:
        common = {
            "receipt": object(),
            "task": object(),
            "authorization_verifier": object(),
            "publisher_verifier": object(),
            "semantic_verifier": object(),
            "control_plane_root": ROOT,
            "source_repository": ROOT,
            "materialization_root": ROOT,
            "trusted_git": object(),
        }
        self.assertFalse(LocalCandidateMaterializationGate.valid(**common))
        self.assertFalse(AsymmetricLocalCandidateMaterializationGate.valid(**common))

    def test_receipt_schemas_remain_closed_and_local_only(self) -> None:
        for version in ("v1", "v2"):
            path = (
                ROOT
                / "devcontrol/schemas"
                / f"development-local-candidate-materialization-receipt-{version}.schema.json"
            )
            schema = json.loads(path.read_text(encoding="utf-8"))
            properties = schema.get("properties", {})
            self.assertFalse(schema.get("additionalProperties", True), version)
            self.assertIs(properties["bare_repository"]["const"], True)
            self.assertIs(properties["isolated_index"]["const"], True)
            self.assertIs(properties["local_source_only"]["const"], True)
            self.assertEqual(properties["merge_authority"]["const"], "human")
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
                self.assertIs(properties[false_claim]["const"], False, (version, false_claim))
            text = json.dumps(schema, sort_keys=True)
            for forbidden in (
                "remote_url",
                "access_token",
                "credential_helper",
                "signing_key",
                "github_token",
            ):
                self.assertNotIn(forbidden, text, (version, forbidden))


if __name__ == "__main__":
    unittest.main()
