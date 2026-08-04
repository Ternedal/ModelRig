from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path
import unittest


_PACKAGE = Path(__file__).resolve().parents[1] / "src" / "kaliv_dev_control"

_SHARED_FILE_PUBLISHERS = Counter(
    {
        ("draft_pr_readiness.py", "write_authenticated_draft_pr_readiness_proposal", "create_once_file"): 1,
        ("physical_isolation.py", "write_signed_report", "create_once_file"): 1,
        ("publisher_authorization_chain_v2.py", "consume_once", "create_once_file"): 3,
        ("publisher_authorization_chain_v2.py", "recover", "create_once_file"): 3,
        ("publisher_authorization_chain_v2.py", "_write_v2", "create_once_file"): 1,
        ("publisher_dry_run.py", "_write_canonical", "create_once_file"): 1,
        ("publisher_recovery_authorization.py", "recover_authenticated", "create_once_file"): 1,
        (
            "publisher_recovery_authorization.py",
            "write_publisher_replay_recovery_authorization_v1",
            "create_once_file",
        ): 1,
        ("publisher_recovery_primary.py", "recover_authenticated", "create_once_file"): 1,
        (
            "publisher_recovery_receipt_v3.py",
            "write_publisher_replay_recovery_receipt_v3",
            "create_once_file",
        ): 1,
        ("publisher_replay_h4.py", "consume_once", "create_once_file"): 3,
        ("publisher_replay_h4.py", "recover", "create_once_file"): 3,
        ("semantic_review.py", "_write_canonical_file", "create_once_file"): 1,
        (
            "trusted_git_runtime_staging.py",
            "stage_trusted_git_runtime",
            "create_once_file",
        ): 1,
    }
)

_SHARED_DIRECTORY_PUBLISHERS = Counter(
    {
        (
            "trusted_git_runtime_staging.py",
            "stage_trusted_git_runtime",
            "rename_directory_no_replace",
        ): 1,
        (
            "trusted_git_runtime_staging.py",
            "recover_trusted_git_runtime_transaction",
            "rename_directory_no_replace",
        ): 1,
    }
)


_SHARED_STREAMING_PUBLISHERS = Counter(
    {
        (
            "_runtime_closure_common.py",
            "_closure_publish_exact_file",
            "publish_stream_once",
        ): 1,
    }
)

_LOW_LEVEL_PROTOCOLS = Counter(
    {
        (
            "_compatibility_v1/local_candidate_materialization.py",
            "_write_canonical",
            "tempfile.mkstemp",
        ): 1,
        (
            "_compatibility_v1/local_candidate_materialization.py",
            "_write_canonical",
            "os.replace",
        ): 1,
        (
            "_compatibility_v1/publisher_authorization.py",
            "_write_canonical",
            "tempfile.mkstemp",
        ): 1,
        (
            "_compatibility_v1/publisher_authorization.py",
            "_write_canonical",
            "os.replace",
        ): 1,
        ("durable_publication.py", "create_once_file", "tempfile.mkstemp"): 1,
        ("durable_publication.py", "create_once_file", "os.link"): 1,
        (
            "streaming_publication.py",
            "publish_stream_once",
            "tempfile.mkstemp",
        ): 1,
        (
            "streaming_publication.py",
            "publish_stream_once",
            "os.link",
        ): 1,
        ("runtime_staging.py", "stage", "tempfile.mkstemp"): 1,
        ("runtime_staging.py", "stage", "os.link"): 1,
        ("patch.py", "apply", "tempfile.NamedTemporaryFile"): 1,
        ("store.py", "save", "tempfile.NamedTemporaryFile"): 1,
        ("store.py", "save", "temporary.replace"): 1,
    }
)

_INTERESTING = {
    "create_once_file",
    "rename_directory_no_replace",
    "publish_stream_once",
    "tempfile.mkstemp",
    "tempfile.NamedTemporaryFile",
    "os.link",
    "os.replace",
    "temporary.replace",
}


class _CallInventory(ast.NodeVisitor):
    def __init__(self, relative: str) -> None:
        self.relative = relative
        self.functions: list[str] = []
        self.calls: Counter[tuple[str, str, str]] = Counter()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions.append(node.name)
        self.generic_visit(node)
        self.functions.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        name = self._name(node.func)
        if name in _INTERESTING:
            self.calls[(
                self.relative,
                self.functions[-1] if self.functions else "<module>",
                name,
            )] += 1
        self.generic_visit(node)

    @staticmethod
    def _name(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            prefix = _CallInventory._name(node.value)
            return f"{prefix}.{node.attr}" if prefix else node.attr
        return ""


def _inventory() -> Counter[tuple[str, str, str]]:
    observed: Counter[tuple[str, str, str]] = Counter()
    for path in sorted(_PACKAGE.rglob("*.py")):
        relative = path.relative_to(_PACKAGE).as_posix()
        visitor = _CallInventory(relative)
        visitor.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        observed.update(visitor.calls)
    return observed


class PublisherProtocolInventoryH10FTests(unittest.TestCase):
    def test_complete_publisher_protocol_inventory_is_exact(self) -> None:
        self.assertEqual(
            _inventory(),
            _SHARED_FILE_PUBLISHERS
            + _SHARED_DIRECTORY_PUBLISHERS
            + _SHARED_STREAMING_PUBLISHERS
            + _LOW_LEVEL_PROTOCOLS,
        )

    def test_supported_immutable_artifacts_use_shared_durable_primitives(self) -> None:
        observed = _inventory()
        self.assertEqual(
            Counter(
                {
                    key: count
                    for key, count in observed.items()
                    if key[2] == "create_once_file"
                }
            ),
            _SHARED_FILE_PUBLISHERS,
        )
        self.assertEqual(
            Counter(
                {
                    key: count
                    for key, count in observed.items()
                    if key[2] == "rename_directory_no_replace"
                }
            ),
            _SHARED_DIRECTORY_PUBLISHERS,
        )

    def test_replace_publication_is_confined_to_retained_v1_and_mutable_cas(self) -> None:
        observed = _inventory()
        replace_calls = Counter(
            {
                key: count
                for key, count in observed.items()
                if key[2] in {"os.replace", "temporary.replace"}
            }
        )
        self.assertEqual(
            replace_calls,
            Counter(
                {
                    (
                        "_compatibility_v1/local_candidate_materialization.py",
                        "_write_canonical",
                        "os.replace",
                    ): 1,
                    (
                        "_compatibility_v1/publisher_authorization.py",
                        "_write_canonical",
                        "os.replace",
                    ): 1,
                    ("store.py", "save", "temporary.replace"): 1,
                }
            ),
        )

    def test_h10g_a_migrates_closure_to_the_shared_streaming_primitive(self) -> None:
        observed = _inventory()
        self.assertEqual(
            Counter(
                {
                    key: count
                    for key, count in observed.items()
                    if key[2] == "publish_stream_once"
                }
            ),
            _SHARED_STREAMING_PUBLISHERS,
        )
        self.assertEqual(
            observed[
                (
                    "streaming_publication.py",
                    "publish_stream_once",
                    "tempfile.mkstemp",
                )
            ],
            1,
        )
        self.assertEqual(
            observed[
                (
                    "streaming_publication.py",
                    "publish_stream_once",
                    "os.link",
                )
            ],
            1,
        )
        closure = (_PACKAGE / "_runtime_closure_common.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("publish_stream_once", closure)
        self.assertNotIn("tempfile.mkstemp", closure)
        self.assertNotIn("os.link(", closure)
        self.assertNotIn("os.replace", closure)

    def test_runtime_staging_remains_explicitly_classified_for_h10g_b(self) -> None:
        observed = _inventory()
        self.assertEqual(
            observed[("runtime_staging.py", "stage", "tempfile.mkstemp")],
            1,
        )
        self.assertEqual(
            observed[("runtime_staging.py", "stage", "os.link")],
            1,
        )
        source = (_PACKAGE / "runtime_staging.py").read_text(encoding="utf-8")
        self.assertNotIn("os.replace", source)

    def test_named_temporaries_are_only_ephemeral_patch_input_or_mutable_state(self) -> None:
        observed = _inventory()
        named = Counter(
            {
                key: count
                for key, count in observed.items()
                if key[2] == "tempfile.NamedTemporaryFile"
            }
        )
        self.assertEqual(
            named,
            Counter(
                {
                    ("patch.py", "apply", "tempfile.NamedTemporaryFile"): 1,
                    ("store.py", "save", "tempfile.NamedTemporaryFile"): 1,
                }
            ),
        )


if __name__ == "__main__":
    unittest.main()
