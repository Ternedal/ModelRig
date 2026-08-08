from __future__ import annotations

from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: marker count {count}, expected 1\n{old}")
    path.write_text(text.replace(old, new), encoding="utf-8")


coverage = Path("tests/workflow_test_coverage.py")
replace_once(
    coverage,
    '    "test_slice10k_publisher_authorization.py",\n',
    '    "test_dc_l13_local_candidate_boundary.py",\n'
    '    "test_slice10k_publisher_authorization.py",\n'
    '    "test_slice10l_local_candidate_materialization.py",\n',
)
replace_once(
    coverage,
    'f"the forty-nine DC-L01–L12 test modules are present: {sorted(observed_modules)}",',
    'f"the fifty-one DC-L01–L13 test modules are present: {sorted(observed_modules)}",',
)
replace_once(
    coverage,
    '''check(
    all(
        importlib.util.find_spec(module) is None
        for module in (
            "kaliv_dev_control.local_candidate_materialization",
            "kaliv_dev_control.local_candidate_materialization_h5c",
        )
    ),
    "DC-L13 local candidate materialization remains absent",
)
''',
    '''local_materialization = importlib.import_module(
    "kaliv_dev_control.local_candidate_materialization"
)
asymmetric_local_materialization = importlib.import_module(
    "kaliv_dev_control.local_candidate_materialization_h5c"
)
local_support = importlib.import_module(
    "kaliv_dev_control._local_candidate_materialization_legacy"
)
check(
    callable(local_materialization.materialize_local_candidate)
    and callable(local_materialization.verify_local_candidate_materialization)
    and callable(
        asymmetric_local_materialization.materialize_asymmetric_local_candidate
    ),
    "DC-L13 exposes verified local-only candidate materialization",
)
check(
    Path(local_support.__file__).name == "__init__.py"
    and not (
        root
        / "devcontrol/src/kaliv_dev_control/_local_candidate_materialization_legacy.py"
    ).exists()
    and not (
        root / "devcontrol/src/kaliv_dev_control/_compatibility_v1"
    ).exists(),
    "DC-L13 distributes static support without rejected compatibility files",
)
local_support_source = Path(local_support.__file__).read_text(encoding="utf-8")
local_source = (
    root / "devcontrol/src/kaliv_dev_control/local_candidate_materialization.py"
).read_text(encoding="utf-8")
local_h5c_source = (
    root / "devcontrol/src/kaliv_dev_control/local_candidate_materialization_h5c.py"
).read_text(encoding="utf-8")
check(
    all(
        token not in local_support_source
        for token in (
            "import subprocess",
            "globals().update",
            "._compatibility_v1",
            "TrustedLocalGit",
            "subprocess.run",
            "Popen(",
        )
    ),
    "DC-L13 support contains no legacy executable runner or dynamic proxy",
)
check(
    all(
        token not in local_source + local_h5c_source
        for token in (
            "requests.",
            "urllib",
            "http.client",
            "socket.",
            "paramiko",
            "Ed25519PrivateKey",
            "private_key",
            ".sign(",
            "credential.helper",
            "git push",
        )
    ),
    "DC-L13 contains no network, credential, signer or remote-push adapter",
)
''',
)

foundation = Path("devcontrol/tests/test_foundation.py")
replace_once(
    foundation,
    '            "publisher_replay_h4.py",\n        }',
    '            "publisher_replay_h4.py",\n'
    '            "local_candidate_materialization.py",\n'
    '            "local_candidate_materialization_h5c.py",\n'
    '        }',
)
replace_once(
    foundation,
    '''        future = (
            "local_candidate_materialization",
            "local_candidate_materialization_h5c",
        )
''',
    '''        future: tuple[str, ...] = ()
''',
)

readme = Path("devcontrol/README.md")
readme_text = readme.read_text(encoding="utf-8")
section = '''

## DC-L13 local-only candidate materialization

The landed DC-L13 boundary consumes one exact verified DC-L12 preflight chain
and may create only a deterministic candidate commit plus proposed branch inside
a new isolated local bare repository. Every Git command is executed through a
complete staged `TrustedGitRuntime`, and source, tree, commit, ref and receipt
bytes are re-verified before evidence is accepted.

The boundary configures no remote and provides no network fetch, push,
credential helper, signer, GitHub mutation, reviewer request, ready conversion,
merge, release, deployment or activation authority. The historical dynamic
legacy proxy and `_compatibility_v1` package are not distributed; the modern
facade uses a static internal validation/evidence support package only.
'''
if "## DC-L13 local-only candidate materialization" not in readme_text:
    readme.write_text(readme_text.rstrip() + section + "\n", encoding="utf-8")

boundary_test = Path("devcontrol/tests/test_dc_l13_local_candidate_boundary.py")
boundary_test.write_text(
    '''from __future__ import annotations

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
        self.assertIn("file://", combined)
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
            text = json.dumps(schema, sort_keys=True)
            self.assertFalse(schema.get("additionalProperties", True), version)
            for forbidden in (
                "remote_url",
                "access_token",
                "credential_helper",
                "pushed",
                "pull_request_created",
                "merged",
                "released",
                "deployed",
            ):
                self.assertNotIn(forbidden, text, (version, forbidden))


if __name__ == "__main__":
    unittest.main()
''',
    encoding="utf-8",
)
