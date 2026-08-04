from __future__ import annotations

import hashlib
import inspect
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import kaliv_dev_control.local_candidate_materialization as materialization_module
from kaliv_dev_control.draft_pr_readiness import AuthenticatedDraftPrReadinessProposal
from kaliv_dev_control.local_candidate_materialization import (
    LocalCandidateMaterializationError,
    LocalCandidateMaterializationGate,
    LocalCandidateMaterializationReceipt,
    TrustedLocalGit,
    load_local_candidate_materialization_receipt,
    local_candidate_materialization_policy_sha256,
    materialize_local_candidate,
    verify_local_candidate_materialization,
    write_local_candidate_materialization_receipt,
)
from kaliv_dev_control.publisher_authorization import (
    HmacPublisherAuthorizationIssuer,
    PublisherAuthorizationVerifier,
    PublisherPreflightReceipt,
    PublisherReplayLedger,
    RemoteRepositoryIdentity,
    TrustedAuthorizationIssuerKey,
)
from kaliv_dev_control.publisher_dry_run import (
    HmacPublisherRequestSigner,
    PublisherDryRunReceipt,
    PublisherRequest,
    PublisherRequestVerifier,
    TrustedPublisherKey,
)
from kaliv_dev_control.semantic_review import SemanticReviewRequest
from test_slice10g_command_receipt import make_task
from test_slice10h_semantic_review import DEVELOPER, ROOT, approve, make_receipt
from test_slice10j_publisher_dry_run import (
    NONCE,
    PUBLISHER,
    PUBLISHER_KEY_ID,
    PUBLISHER_SECRET,
    PUBLISHER_SYSTEM,
)
from test_slice10k_publisher_authorization import (
    CHECKED,
    CONSUMED,
    EXPIRES,
    ISSUED,
    ISSUER,
    ISSUER_KEY_ID,
    ISSUER_SECRET,
    ISSUER_SYSTEM,
    LEDGER_ID,
    REPOSITORY_ID,
)

MATERIALIZED = "2026-08-04T06:48:00Z"


def git(root: Path, *args: str, stdin: bytes | None = None) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr.decode("utf-8", errors="replace"))
    return completed.stdout


def trusted_git() -> TrustedLocalGit:
    executable = shutil.which("git")
    if executable is None:
        raise unittest.SkipTest("Git executable is unavailable")
    path = Path(executable).resolve()
    return TrustedLocalGit(
        executable_path=path,
        expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def make_chain(root: Path):
    source = root / "source"
    source.mkdir()
    git(source, "init", "-q")
    git(source, "config", "user.name", "Slice 10L")
    git(source, "config", "user.email", "slice10l@example.invalid")
    (source / "tracked.txt").write_text("base\n", encoding="utf-8")
    git(source, "add", "tracked.txt")
    git(source, "commit", "-q", "-m", "base")
    base_sha = git(source, "rev-parse", "HEAD").decode("ascii").strip()
    (source / "tracked.txt").write_text("staged\n", encoding="utf-8")
    git(source, "add", "tracked.txt")
    staged_patch = git(
        source,
        "diff",
        "--cached",
        "--binary",
        "--full-index",
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--",
    )

    task = make_task(base_sha)
    tier_a_receipt = make_receipt(task, staged_patch)
    review_request = SemanticReviewRequest.from_evidence(
        task=task,
        developer_actor_id=DEVELOPER,
        staged_patch=staged_patch,
        receipt=tier_a_receipt,
        control_plane_root=ROOT,
    )
    _, signed_verdict, semantic_verifier = approve(review_request)
    readiness = AuthenticatedDraftPrReadinessProposal.from_evidence(
        task=task,
        request=review_request,
        signed_verdict=signed_verdict,
        verifier=semantic_verifier,
        control_plane_root=ROOT,
        base_branch="main",
    )
    publisher_request = PublisherRequest.from_readiness(
        readiness=readiness,
        task=task,
        semantic_verifier=semantic_verifier,
        control_plane_root=ROOT,
        publisher_actor_id=PUBLISHER,
        publisher_system_id=PUBLISHER_SYSTEM,
        invocation_nonce=NONCE,
    )
    signed_request = HmacPublisherRequestSigner(
        key_id=PUBLISHER_KEY_ID,
        publisher_actor_id=PUBLISHER,
        secret=PUBLISHER_SECRET,
    ).sign(publisher_request)
    publisher_verifier = PublisherRequestVerifier(
        {
            PUBLISHER_KEY_ID: TrustedPublisherKey(
                publisher_actor_id=PUBLISHER,
                secret=PUBLISHER_SECRET,
            )
        }
    )
    dry_run = PublisherDryRunReceipt.from_signed_request(
        signed_request=signed_request,
        task=task,
        publisher_verifier=publisher_verifier,
        semantic_verifier=semantic_verifier,
        control_plane_root=ROOT,
    )
    remote = RemoteRepositoryIdentity.github(
        repository=publisher_request.repository,
        repository_id=REPOSITORY_ID,
    )
    lease = HmacPublisherAuthorizationIssuer(
        key_id=ISSUER_KEY_ID,
        issuer_actor_id=ISSUER,
        issuer_system_id=ISSUER_SYSTEM,
        secret=ISSUER_SECRET,
    ).issue(
        signed_request=signed_request,
        task=task,
        publisher_verifier=publisher_verifier,
        semantic_verifier=semantic_verifier,
        control_plane_root=ROOT,
        remote_repository=remote,
        issued_at_utc=ISSUED,
        expires_at_utc=EXPIRES,
    )
    authorization_verifier = PublisherAuthorizationVerifier(
        {
            ISSUER_KEY_ID: TrustedAuthorizationIssuerKey(
                issuer_actor_id=ISSUER,
                secret=ISSUER_SECRET,
            )
        }
    )
    ledger_root = root / "replay-ledger"
    ledger_root.mkdir()
    replay_entry = PublisherReplayLedger(
        root=ledger_root.resolve(),
        ledger_id=LEDGER_ID,
    ).consume_once(
        lease=lease,
        task=task,
        authorization_verifier=authorization_verifier,
        publisher_verifier=publisher_verifier,
        semantic_verifier=semantic_verifier,
        control_plane_root=ROOT,
        consumed_at_utc=CONSUMED,
    )
    preflight = PublisherPreflightReceipt.from_consumed_lease(
        lease=lease,
        replay_entry=replay_entry,
        task=task,
        authorization_verifier=authorization_verifier,
        publisher_verifier=publisher_verifier,
        semantic_verifier=semantic_verifier,
        control_plane_root=ROOT,
        checked_at_utc=CHECKED,
    )
    return (
        source.resolve(),
        task,
        staged_patch,
        semantic_verifier,
        publisher_verifier,
        authorization_verifier,
        dry_run,
        preflight,
    )


def create_materialization(root: Path, *, output_name: str = "materialized"):
    (
        source,
        task,
        staged_patch,
        semantic_verifier,
        publisher_verifier,
        authorization_verifier,
        dry_run,
        preflight,
    ) = make_chain(root)
    output = root / output_name
    output.mkdir()
    tool = trusted_git()
    source_before = git(source, "status", "--porcelain=v2", "-z", "--untracked-files=all")
    receipt = materialize_local_candidate(
        preflight=preflight,
        task=task,
        authorization_verifier=authorization_verifier,
        publisher_verifier=publisher_verifier,
        semantic_verifier=semantic_verifier,
        control_plane_root=ROOT,
        source_repository=source,
        materialization_root=output.resolve(),
        trusted_git=tool,
        materialized_at_utc=MATERIALIZED,
    )
    source_after = git(source, "status", "--porcelain=v2", "-z", "--untracked-files=all")
    if source_before != source_after:
        raise AssertionError("source repository changed")
    return (
        source,
        task,
        staged_patch,
        semantic_verifier,
        publisher_verifier,
        authorization_verifier,
        dry_run,
        preflight,
        output.resolve(),
        tool,
        receipt,
    )


class LocalCandidateMaterializationTests(unittest.TestCase):
    def test_exact_local_commit_branch_receipt_and_determinism(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (
                source,
                task,
                staged_patch,
                semantic_verifier,
                publisher_verifier,
                authorization_verifier,
                dry_run,
                preflight,
                output,
                tool,
                receipt,
            ) = create_materialization(root)
            transaction = output / receipt.transaction_id
            repository = transaction / receipt.repository_relative_path
            receipt_path = transaction / receipt.receipt_relative_path

            self.assertEqual(
                git(output, f"--git-dir={repository}", "rev-parse", "--is-bare-repository")
                .decode("ascii")
                .strip(),
                "true",
            )
            self.assertEqual(
                git(output, f"--git-dir={repository}", "symbolic-ref", "HEAD")
                .decode("utf-8")
                .strip(),
                receipt.candidate.branch_ref,
            )
            self.assertEqual(
                git(output, f"--git-dir={repository}", "remote"),
                b"",
            )
            reproduced = git(
                output,
                f"--git-dir={repository}",
                "diff",
                "--binary",
                "--full-index",
                "--no-color",
                "--no-ext-diff",
                "--no-textconv",
                "--no-renames",
                task.base_sha,
                receipt.candidate.commit_sha,
                "--",
            )
            self.assertEqual(reproduced, staged_patch)
            self.assertEqual(
                load_local_candidate_materialization_receipt(receipt_path).sha256,
                receipt.sha256,
            )
            commit_parameters = {
                item.name: item.value for item in dry_run.operations[1].parameters
            }
            self.assertEqual(
                receipt.candidate.commit_message,
                commit_parameters["commit_message"],
            )
            self.assertEqual(
                receipt.candidate.author_actor_id,
                commit_parameters["author_actor_id"],
            )
            self.assertEqual(
                receipt.materialization_policy_sha256,
                local_candidate_materialization_policy_sha256(),
            )
            self.assertFalse(receipt.remote_configured)
            self.assertFalse(receipt.network_write_performed)
            self.assertFalse(receipt.remote_push_performed)
            self.assertFalse(receipt.pull_request_created)

            verify_local_candidate_materialization(
                receipt=receipt,
                task=task,
                authorization_verifier=authorization_verifier,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=ROOT,
                source_repository=source,
                materialization_root=output,
                trusted_git=tool,
            )
            self.assertTrue(
                LocalCandidateMaterializationGate.valid(
                    receipt=receipt,
                    task=task,
                    authorization_verifier=authorization_verifier,
                    publisher_verifier=publisher_verifier,
                    semantic_verifier=semantic_verifier,
                    control_plane_root=ROOT,
                    source_repository=source,
                    materialization_root=output,
                    trusted_git=tool,
                )
            )

            second_root = root / "second-root"
            second_root.mkdir()
            second = materialize_local_candidate(
                preflight=preflight,
                task=task,
                authorization_verifier=authorization_verifier,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=ROOT,
                source_repository=source,
                materialization_root=second_root.resolve(),
                trusted_git=tool,
                materialized_at_utc=MATERIALIZED,
            )
            self.assertEqual(second.candidate.commit_sha, receipt.candidate.commit_sha)
            self.assertEqual(second.candidate.tree_sha, receipt.candidate.tree_sha)
            self.assertEqual(second.canonical_json(), receipt.canonical_json())

    def test_expiry_wrong_task_authority_source_and_git_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (
                source,
                task,
                _,
                semantic_verifier,
                publisher_verifier,
                authorization_verifier,
                _,
                preflight,
            ) = make_chain(root)
            expired = root / "expired"
            expired.mkdir()
            with self.assertRaises(LocalCandidateMaterializationError):
                materialize_local_candidate(
                    preflight=preflight,
                    task=task,
                    authorization_verifier=authorization_verifier,
                    publisher_verifier=publisher_verifier,
                    semantic_verifier=semantic_verifier,
                    control_plane_root=ROOT,
                    source_repository=source,
                    materialization_root=expired.resolve(),
                    trusted_git=trusted_git(),
                    materialized_at_utc=EXPIRES,
                )

            executable = Path(shutil.which("git") or "").resolve()
            with self.assertRaisesRegex(LocalCandidateMaterializationError, "expected hash"):
                TrustedLocalGit(executable_path=executable, expected_sha256="0" * 64)

            wrong_source = root / "wrong-source"
            wrong_source.mkdir()
            git(wrong_source, "init", "-q")
            git(wrong_source, "config", "user.name", "Wrong")
            git(wrong_source, "config", "user.email", "wrong@example.invalid")
            (wrong_source / "wrong.txt").write_text("wrong\n", encoding="utf-8")
            git(wrong_source, "add", "wrong.txt")
            git(wrong_source, "commit", "-q", "-m", "wrong")
            wrong_output = root / "wrong-output"
            wrong_output.mkdir()
            with self.assertRaises(LocalCandidateMaterializationError):
                materialize_local_candidate(
                    preflight=preflight,
                    task=task,
                    authorization_verifier=authorization_verifier,
                    publisher_verifier=publisher_verifier,
                    semantic_verifier=semantic_verifier,
                    control_plane_root=ROOT,
                    source_repository=wrong_source.resolve(),
                    materialization_root=wrong_output.resolve(),
                    trusted_git=trusted_git(),
                    materialized_at_utc=MATERIALIZED,
                )

            good = root / "good"
            good.mkdir()
            receipt = materialize_local_candidate(
                preflight=preflight,
                task=task,
                authorization_verifier=authorization_verifier,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=ROOT,
                source_repository=source,
                materialization_root=good.resolve(),
                trusted_git=trusted_git(),
                materialized_at_utc=MATERIALIZED,
            )
            other_task = make_task("2" * 40)
            self.assertFalse(
                LocalCandidateMaterializationGate.valid(
                    receipt=receipt,
                    task=other_task,
                    authorization_verifier=authorization_verifier,
                    publisher_verifier=publisher_verifier,
                    semantic_verifier=semantic_verifier,
                    control_plane_root=ROOT,
                    source_repository=source,
                    materialization_root=good,
                    trusted_git=trusted_git(),
                )
            )
            with patch(
                "kaliv_dev_control.semantic_review.tier_a_toolhost_sha256",
                return_value="0" * 64,
            ):
                self.assertFalse(
                    LocalCandidateMaterializationGate.valid(
                        receipt=receipt,
                        task=task,
                        authorization_verifier=authorization_verifier,
                        publisher_verifier=publisher_verifier,
                        semantic_verifier=semantic_verifier,
                        control_plane_root=ROOT,
                        source_repository=source,
                        materialization_root=good,
                        trusted_git=trusted_git(),
                    )
                )

    def test_existing_transaction_receipt_and_disk_tampering_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (
                source,
                task,
                _,
                semantic_verifier,
                publisher_verifier,
                authorization_verifier,
                _,
                preflight,
                output,
                tool,
                receipt,
            ) = create_materialization(root)

            with self.assertRaisesRegex(LocalCandidateMaterializationError, "already exists"):
                materialize_local_candidate(
                    preflight=preflight,
                    task=task,
                    authorization_verifier=authorization_verifier,
                    publisher_verifier=publisher_verifier,
                    semantic_verifier=semantic_verifier,
                    control_plane_root=ROOT,
                    source_repository=source,
                    materialization_root=output,
                    trusted_git=tool,
                    materialized_at_utc=MATERIALIZED,
                )

            for field in (
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
                payload = receipt.to_dict()
                payload[field] = True
                with self.subTest(field=field):
                    with self.assertRaisesRegex(
                        LocalCandidateMaterializationError,
                        "authority boundary",
                    ):
                        LocalCandidateMaterializationReceipt.from_mapping(payload)

            payload = receipt.to_dict()
            payload["candidate"]["branch_target_sha"] = "0" * 40
            with self.assertRaisesRegex(LocalCandidateMaterializationError, "branch or patch"):
                LocalCandidateMaterializationReceipt.from_mapping(payload)
            payload = receipt.to_dict()
            payload["source"]["source_mutated"] = True
            with self.assertRaisesRegex(LocalCandidateMaterializationError, "claims mutation"):
                LocalCandidateMaterializationReceipt.from_mapping(payload)

            transaction = output / receipt.transaction_id
            repository = transaction / receipt.repository_relative_path
            git(
                output,
                f"--git-dir={repository}",
                "remote",
                "add",
                "origin",
                "https://example.invalid/repo.git",
            )
            self.assertFalse(
                LocalCandidateMaterializationGate.valid(
                    receipt=receipt,
                    task=task,
                    authorization_verifier=authorization_verifier,
                    publisher_verifier=publisher_verifier,
                    semantic_verifier=semantic_verifier,
                    control_plane_root=ROOT,
                    source_repository=source,
                    materialization_root=output,
                    trusted_git=tool,
                )
            )

    def test_canonical_storage_schema_and_api_surface(self):
        with tempfile.TemporaryDirectory() as directory:
            (
                source,
                task,
                _,
                semantic_verifier,
                publisher_verifier,
                authorization_verifier,
                _,
                _,
                output,
                tool,
                receipt,
            ) = create_materialization(Path(directory).resolve())
            copy_path = output / "receipt-copy.json"
            self.assertEqual(
                write_local_candidate_materialization_receipt(copy_path, receipt),
                receipt.sha256,
            )
            with self.assertRaisesRegex(LocalCandidateMaterializationError, "already exists"):
                write_local_candidate_materialization_receipt(copy_path, receipt)
            noncanonical = output / "noncanonical.json"
            noncanonical.write_bytes(receipt.canonical_json().encode("utf-8") + b"\n")
            with self.assertRaisesRegex(LocalCandidateMaterializationError, "canonical"):
                load_local_candidate_materialization_receipt(noncanonical)

            schema = json.loads(
                (
                    ROOT
                    / "devcontrol/schemas"
                    / "development-local-candidate-materialization-receipt-v1.schema.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(set(schema["required"]), set(receipt.to_dict()))
            self.assertEqual(set(schema["properties"]), set(receipt.to_dict()))
            for definition, payload in (
                ("git", receipt.git.to_dict()),
                ("source", receipt.source.to_dict()),
                ("candidate", receipt.candidate.to_dict()),
            ):
                self.assertEqual(set(schema["$defs"][definition]["required"]), set(payload))
                self.assertEqual(set(schema["$defs"][definition]["properties"]), set(payload))

            transaction = output / receipt.transaction_id
            (transaction / "unexpected.txt").write_text("unexpected", encoding="utf-8")
            self.assertFalse(
                LocalCandidateMaterializationGate.valid(
                    receipt=receipt,
                    task=task,
                    authorization_verifier=authorization_verifier,
                    publisher_verifier=publisher_verifier,
                    semantic_verifier=semantic_verifier,
                    control_plane_root=ROOT,
                    source_repository=source,
                    materialization_root=output,
                    trusted_git=tool,
                )
            )

        parameters = set(inspect.signature(materialize_local_candidate).parameters)
        for forbidden in (
            "remote",
            "remote_url",
            "github",
            "token",
            "credential",
            "push",
            "pull_request",
            "reviewers",
            "ready",
            "merge",
            "release",
            "deploy",
            "branch",
            "commit_message",
            "author",
            "argv",
            "environment",
            "source_env",
        ):
            self.assertNotIn(forbidden, parameters)
        for forbidden in (
            "push_branch",
            "create_pull_request",
            "update_pull_request",
            "request_reviewers",
            "mark_ready_for_review",
            "merge_pull_request",
            "release",
            "deploy",
        ):
            self.assertNotIn(forbidden, set(dir(materialization_module)))
        source_text = inspect.getsource(materialization_module)
        self.assertNotIn("import requests", source_text)
        self.assertNotIn("import urllib", source_text)
        self.assertNotIn("import socket", source_text)
        self.assertNotIn("api.github.com", source_text)
        self.assertNotIn("Authorization:", source_text)
        self.assertNotIn("github_token", source_text)


if __name__ == "__main__":
    unittest.main()
