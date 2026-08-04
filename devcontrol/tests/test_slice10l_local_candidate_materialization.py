from __future__ import annotations

import inspect
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from functools import lru_cache
from pathlib import Path
from unittest.mock import patch

import kaliv_dev_control.local_candidate_materialization as materialization_module
from kaliv_dev_control.draft_pr_readiness import AuthenticatedDraftPrReadinessProposal
from kaliv_dev_control.local_candidate_materialization import (
    LocalCandidateMaterializationError,
    LocalCandidateMaterializationGate,
    LocalCandidateMaterializationReceipt,
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
from kaliv_dev_control.trusted_git_runtime import (
    TrustedGitRuntime,
    capture_trusted_git_runtime_manifest,
    stage_trusted_git_runtime,
)
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
        timeout=120,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr.decode("utf-8", errors="replace"))
    return completed.stdout


def _copy_runtime_library(source: Path, destination: Path) -> None:
    target = destination / source.name
    if target.exists():
        if target.read_bytes() != source.read_bytes():
            raise unittest.SkipTest(
                f"runtime library basename collision: {source.name}"
            )
        return
    shutil.copy2(source, target)


def _copy_dynamic_libraries(executable: Path, destination: Path) -> None:
    ldd = shutil.which("ldd")
    if ldd is None:
        return
    dependencies = subprocess.run(
        [ldd, str(executable)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if dependencies.returncode != 0:
        return
    observed: set[Path] = set()
    for line in dependencies.stdout.splitlines():
        text = line.strip()
        candidate = ""
        if "=>" in text:
            candidate = text.split("=>", 1)[1].strip().split(" ", 1)[0]
        elif text.startswith("/"):
            candidate = text.split(" ", 1)[0]
        if candidate.startswith("/"):
            path = Path(candidate).resolve()
            if path.is_file() and path not in observed:
                observed.add(path)
                _copy_runtime_library(path, destination)


@lru_cache(maxsize=1)
def trusted_git() -> TrustedGitRuntime:
    if os.name == "nt":
        raise unittest.SkipTest("portable real-Git closure proof runs on POSIX")
    executable = shutil.which("git")
    if executable is None:
        raise unittest.SkipTest("Git executable is unavailable")
    installed = Path(executable).resolve()
    root = Path(tempfile.mkdtemp(prefix="kaliv-test-git-runtime-"))
    source = root / "source"
    bin_root = source / "bin"
    helper_root = source / "libexec" / "git-core"
    library_root = source / "lib"
    bin_root.mkdir(parents=True)
    helper_root.mkdir(parents=True)
    library_root.mkdir(parents=True)
    shutil.copy2(installed, bin_root / "git")

    exec_path_result = subprocess.run(
        [str(installed), "--exec-path"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if exec_path_result.returncode != 0:
        raise unittest.SkipTest("Git exec-path discovery failed")
    exec_path = Path(exec_path_result.stdout.strip()).resolve()
    upload_pack = exec_path / "git-upload-pack"
    if not upload_pack.is_file():
        raise unittest.SkipTest("Git upload-pack helper is unavailable")
    staged_upload_pack = helper_root / "git-upload-pack"
    shutil.copy2(upload_pack, staged_upload_pack)
    staged_upload_pack.chmod(0o755)

    _copy_dynamic_libraries(installed, library_root)
    _copy_dynamic_libraries(upload_pack.resolve(), library_root)
    manifest = capture_trusted_git_runtime_manifest(
        source.resolve(),
        executable_relative_path="bin/git",
        exec_path_relative_path="libexec/git-core",
        path_relative_directories=("bin", "libexec/git-core", "lib"),
    )
    staging = root / "staging"
    staging.mkdir()
    transaction = stage_trusted_git_runtime(
        manifest,
        source_root=source.resolve(),
        staging_root=staging.resolve(),
    )
    runtime = TrustedGitRuntime(transaction.resolve())
    roles = {item.relative_path: item.role for item in manifest.files}
    if roles.get("libexec/git-core/git-upload-pack") != "helper":
        raise AssertionError("upload-pack is not bound as a runtime helper")
    return runtime


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
    chain = make_chain(root)
    (
        source,
        task,
        staged_patch,
        semantic_verifier,
        publisher_verifier,
        authorization_verifier,
        dry_run,
        preflight,
    ) = chain
    output = root / output_name
    output.mkdir()
    runtime = trusted_git()
    source_before = git(
        source,
        "status",
        "--porcelain=v2",
        "-z",
        "--untracked-files=all",
    )
    receipt = materialize_local_candidate(
        preflight=preflight,
        task=task,
        authorization_verifier=authorization_verifier,
        publisher_verifier=publisher_verifier,
        semantic_verifier=semantic_verifier,
        control_plane_root=ROOT,
        source_repository=source,
        materialization_root=output.resolve(),
        trusted_git=runtime,
        materialized_at_utc=MATERIALIZED,
    )
    source_after = git(
        source,
        "status",
        "--porcelain=v2",
        "-z",
        "--untracked-files=all",
    )
    if source_before != source_after:
        raise AssertionError("source repository changed")
    return (*chain, output.resolve(), runtime, receipt)


class LocalCandidateMaterializationTests(unittest.TestCase):
    def test_exact_commit_runtime_receipt_and_determinism(self):
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
                runtime,
                receipt,
            ) = create_materialization(root)
            transaction = output / receipt.transaction_id
            repository = transaction / receipt.repository_relative_path
            receipt_path = transaction / receipt.receipt_relative_path

            self.assertEqual(
                receipt.schema,
                "kaliv-development-local-candidate-materialization-receipt/v2",
            )
            self.assertEqual(
                receipt.git.runtime.runtime_manifest_sha256,
                runtime.receipt.manifest.sha256,
            )
            self.assertEqual(
                git(
                    output,
                    f"--git-dir={repository}",
                    "rev-parse",
                    "--is-bare-repository",
                ).strip(),
                b"true",
            )
            self.assertEqual(
                git(output, f"--git-dir={repository}", "remote"), b""
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
                receipt.materialization_policy_sha256,
                local_candidate_materialization_policy_sha256(),
            )
            verify_local_candidate_materialization(
                receipt=receipt,
                task=task,
                authorization_verifier=authorization_verifier,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=ROOT,
                source_repository=source,
                materialization_root=output,
                trusted_git=runtime,
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
                    trusted_git=runtime,
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
                trusted_git=runtime,
                materialized_at_utc=MATERIALIZED,
            )
            self.assertEqual(
                second.candidate.commit_sha, receipt.candidate.commit_sha
            )
            self.assertEqual(second.canonical_json(), receipt.canonical_json())

    def test_expiry_wrong_runtime_and_source_fail_closed(self):
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
            output = root / "expired"
            output.mkdir()
            common = dict(
                preflight=preflight,
                task=task,
                authorization_verifier=authorization_verifier,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=ROOT,
                source_repository=source,
                materialization_root=output.resolve(),
                materialized_at_utc=MATERIALIZED,
            )
            with self.assertRaises(LocalCandidateMaterializationError):
                materialize_local_candidate(
                    **(common | {"trusted_git": trusted_git(), "materialized_at_utc": EXPIRES})
                )
            with self.assertRaisesRegex(
                LocalCandidateMaterializationError, "trusted Git runtime"
            ):
                materialize_local_candidate(**(common | {"trusted_git": object()}))

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
                    **(
                        common
                        | {
                            "source_repository": wrong_source.resolve(),
                            "materialization_root": wrong_output.resolve(),
                            "trusted_git": trusted_git(),
                        }
                    )
                )

    def test_tampering_flags_schema_and_retired_legacy_paths(self):
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
                runtime,
                receipt,
            ) = create_materialization(root)
            with self.assertRaisesRegex(
                LocalCandidateMaterializationError, "already exists"
            ):
                materialize_local_candidate(
                    preflight=preflight,
                    task=task,
                    authorization_verifier=authorization_verifier,
                    publisher_verifier=publisher_verifier,
                    semantic_verifier=semantic_verifier,
                    control_plane_root=ROOT,
                    source_repository=source,
                    materialization_root=output,
                    trusted_git=runtime,
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
                        LocalCandidateMaterializationError, "authority boundary"
                    ):
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
                    trusted_git=runtime,
                )
            )

            copy_path = output / "receipt-copy.json"
            self.assertEqual(
                write_local_candidate_materialization_receipt(copy_path, receipt),
                receipt.sha256,
            )
            with self.assertRaisesRegex(
                LocalCandidateMaterializationError, "already exists"
            ):
                write_local_candidate_materialization_receipt(copy_path, receipt)
            schema = json.loads(
                (
                    ROOT
                    / "devcontrol"
                    / "schemas"
                    / "development-local-candidate-materialization-receipt-v2.schema.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(set(schema["required"]), set(receipt.to_dict()))
            self.assertEqual(set(schema["properties"]), set(receipt.to_dict()))
            for definition, payload in (
                ("git", receipt.git.to_dict()),
                ("source", receipt.source.to_dict()),
                ("candidate", receipt.candidate.to_dict()),
            ):
                self.assertEqual(
                    set(schema["$defs"][definition]["required"]), set(payload)
                )
                self.assertEqual(
                    set(schema["$defs"][definition]["properties"]), set(payload)
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
        for retired in (
            "TrustedLocalGit",
            "materialize_local_candidate",
            "verify_local_candidate_materialization",
            "LocalCandidateMaterializationGate",
        ):
            self.assertFalse(hasattr(materialization_module._legacy, retired))
        source_text = inspect.getsource(materialization_module)
        for forbidden in (
            "import subprocess",
            "import requests",
            "import urllib",
            "import socket",
            "api.github.com",
            "github_token",
        ):
            self.assertNotIn(forbidden, source_text)

    def test_authority_drift_fails_gate(self):
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
                runtime,
                receipt,
            ) = create_materialization(Path(directory).resolve())
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
                        materialization_root=output,
                        trusted_git=runtime,
                    )
                )


if __name__ == "__main__":
    unittest.main()
