"""Trusted-runtime local candidate materialization (receipt v2).

The public boundary retains the proven Slice 10L object and repository checks,
but every Git invocation now runs through one complete staged
``TrustedGitRuntime``. The former executable-only implementation is retained as
an internal helper core and its write entrypoints are not re-exported.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, TypeVar

from . import _local_candidate_materialization_legacy as _legacy
from .trusted_git_runtime import (
    TrustedGitRunner,
    TrustedGitRuntime,
    TrustedGitRuntimeError,
    TrustedGitRuntimeEvidence,
)

LOCAL_CANDIDATE_MATERIALIZATION_RECEIPT_SCHEMA = (
    "kaliv-development-local-candidate-materialization-receipt/v2"
)
_LOCAL_GIT_EVIDENCE_SCHEMA = "kaliv-development-local-git-evidence/v2"
_MATERIALIZATION_POLICY_DOMAIN = (
    b"kaliv-local-candidate-materialization-policy/v2\0"
)

LocalCandidateMaterializationError = _legacy.LocalCandidateMaterializationError
LocalSourceRepositoryEvidence = _legacy.LocalSourceRepositoryEvidence
LocalCandidateCommitEvidence = _legacy.LocalCandidateCommitEvidence
PublisherPreflightReceipt = _legacy.PublisherPreflightReceipt
PublisherAuthorizationVerifier = _legacy.PublisherAuthorizationVerifier
PublisherRequestVerifier = _legacy.PublisherRequestVerifier
SemanticReviewVerifier = _legacy.SemanticReviewVerifier
DevelopmentTask = _legacy.DevelopmentTask
MergeAuthority = _legacy.MergeAuthority

LOCAL_CANDIDATE_MATERIALIZATION_POLICY = (
    *_legacy.LOCAL_CANDIDATE_MATERIALIZATION_POLICY,
    "Require one complete create-once staged Git runtime manifest, including its executable, helper and library files, and verify it before and after every Git command.",
    "Bind the complete trusted Git runtime evidence into the canonical materialization receipt rather than trusting one executable hash or inherited host PATH.",
)


def local_candidate_materialization_policy_sha256() -> str:
    payload = json.dumps(
        list(LOCAL_CANDIDATE_MATERIALIZATION_POLICY),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return _legacy._sha256_bytes(_MATERIALIZATION_POLICY_DOMAIN + payload)


@dataclass(frozen=True, slots=True)
class LocalGitEvidence:
    executable_sha256: str
    executable_bytes: int
    executable_basename: str
    version: str
    runtime: TrustedGitRuntimeEvidence
    object_format: str = "sha1"
    schema: str = _LOCAL_GIT_EVIDENCE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != _LOCAL_GIT_EVIDENCE_SCHEMA:
            raise LocalCandidateMaterializationError(
                "unsupported local Git evidence schema"
            )
        _legacy._hex(self.executable_sha256, name="local Git executable hash")
        _legacy._integer(
            self.executable_bytes,
            name="local Git executable bytes",
            low=1,
            high=_legacy._MAX_GIT_EXECUTABLE_BYTES,
        )
        _legacy._clean_text(
            self.executable_basename,
            name="local Git executable basename",
            maximum=255,
            one_line=True,
        )
        _legacy._clean_text(
            self.version,
            name="local Git version",
            maximum=512,
            one_line=True,
        )
        if not isinstance(self.runtime, TrustedGitRuntimeEvidence):
            raise LocalCandidateMaterializationError(
                "local Git runtime evidence is invalid"
            )
        if (
            self.runtime.executable_sha256 != self.executable_sha256
            or self.runtime.version != self.version
        ):
            raise LocalCandidateMaterializationError(
                "local Git executable evidence is not bound to its runtime"
            )
        if self.object_format != "sha1":
            raise LocalCandidateMaterializationError(
                "local Git object format must remain sha1"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "LocalGitEvidence":
        data = _legacy._strict(
            value,
            name="local Git evidence",
            fields={
                "schema",
                "executable_sha256",
                "executable_bytes",
                "executable_basename",
                "version",
                "runtime",
                "object_format",
            },
        )
        return cls(
            schema=data["schema"],
            executable_sha256=data["executable_sha256"],
            executable_bytes=data["executable_bytes"],
            executable_basename=data["executable_basename"],
            version=data["version"],
            runtime=TrustedGitRuntimeEvidence.from_mapping(data["runtime"]),
            object_format=data["object_format"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "executable_sha256": self.executable_sha256,
            "executable_bytes": self.executable_bytes,
            "executable_basename": self.executable_basename,
            "version": self.version,
            "runtime": self.runtime.to_dict(),
            "object_format": self.object_format,
        }


_RECEIPT_FIELDS = {
    "schema",
    "preflight",
    "preflight_sha256",
    "lease_sha256",
    "replay_entry_sha256",
    "request_sha256",
    "readiness_sha256",
    "task_sha256",
    "invocation_nonce",
    "materialization_policy_sha256",
    "materialized_at_utc",
    "transaction_id",
    "repository_relative_path",
    "receipt_relative_path",
    "git",
    "source",
    "candidate",
    "bare_repository",
    "isolated_index",
    "local_source_only",
    "remote_configured",
    "network_write_performed",
    "remote_push_performed",
    "pull_request_created",
    "ready_for_review",
    "reviewers_requested",
    "merged",
    "released",
    "deployed",
    "merge_authority",
}


@dataclass(frozen=True, slots=True)
class LocalCandidateMaterializationReceipt:
    preflight: PublisherPreflightReceipt
    preflight_sha256: str
    lease_sha256: str
    replay_entry_sha256: str
    request_sha256: str
    readiness_sha256: str
    task_sha256: str
    invocation_nonce: str
    materialization_policy_sha256: str
    materialized_at_utc: str
    transaction_id: str
    repository_relative_path: str
    receipt_relative_path: str
    git: LocalGitEvidence
    source: LocalSourceRepositoryEvidence
    candidate: LocalCandidateCommitEvidence
    bare_repository: bool = True
    isolated_index: bool = True
    local_source_only: bool = True
    remote_configured: bool = False
    network_write_performed: bool = False
    remote_push_performed: bool = False
    pull_request_created: bool = False
    ready_for_review: bool = False
    reviewers_requested: bool = False
    merged: bool = False
    released: bool = False
    deployed: bool = False
    merge_authority: str = "human"
    schema: str = LOCAL_CANDIDATE_MATERIALIZATION_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != LOCAL_CANDIDATE_MATERIALIZATION_RECEIPT_SCHEMA:
            raise LocalCandidateMaterializationError(
                "unsupported local materialization receipt schema"
            )
        if not isinstance(self.git, LocalGitEvidence):
            raise LocalCandidateMaterializationError(
                "local materialization Git evidence is invalid"
            )
        legacy_git = _legacy.LocalGitEvidence(
            executable_sha256=self.git.executable_sha256,
            executable_bytes=self.git.executable_bytes,
            executable_basename=self.git.executable_basename,
            version=self.git.version,
            object_format=self.git.object_format,
        )
        _legacy.LocalCandidateMaterializationReceipt(
            preflight=self.preflight,
            preflight_sha256=self.preflight_sha256,
            lease_sha256=self.lease_sha256,
            replay_entry_sha256=self.replay_entry_sha256,
            request_sha256=self.request_sha256,
            readiness_sha256=self.readiness_sha256,
            task_sha256=self.task_sha256,
            invocation_nonce=self.invocation_nonce,
            materialization_policy_sha256=(
                _legacy.local_candidate_materialization_policy_sha256()
            ),
            materialized_at_utc=self.materialized_at_utc,
            transaction_id=self.transaction_id,
            repository_relative_path=self.repository_relative_path,
            receipt_relative_path=self.receipt_relative_path,
            git=legacy_git,
            source=self.source,
            candidate=self.candidate,
            bare_repository=self.bare_repository,
            isolated_index=self.isolated_index,
            local_source_only=self.local_source_only,
            remote_configured=self.remote_configured,
            network_write_performed=self.network_write_performed,
            remote_push_performed=self.remote_push_performed,
            pull_request_created=self.pull_request_created,
            ready_for_review=self.ready_for_review,
            reviewers_requested=self.reviewers_requested,
            merged=self.merged,
            released=self.released,
            deployed=self.deployed,
            merge_authority=self.merge_authority,
        )
        if (
            self.materialization_policy_sha256
            != local_candidate_materialization_policy_sha256()
        ):
            raise LocalCandidateMaterializationError(
                "local materialization policy identity is inconsistent"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "LocalCandidateMaterializationReceipt":
        data = _legacy._strict(
            value,
            name="local candidate materialization receipt",
            fields=_RECEIPT_FIELDS,
        )
        return cls(
            schema=data["schema"],
            preflight=PublisherPreflightReceipt.from_mapping(data["preflight"]),
            preflight_sha256=data["preflight_sha256"],
            lease_sha256=data["lease_sha256"],
            replay_entry_sha256=data["replay_entry_sha256"],
            request_sha256=data["request_sha256"],
            readiness_sha256=data["readiness_sha256"],
            task_sha256=data["task_sha256"],
            invocation_nonce=data["invocation_nonce"],
            materialization_policy_sha256=data["materialization_policy_sha256"],
            materialized_at_utc=data["materialized_at_utc"],
            transaction_id=data["transaction_id"],
            repository_relative_path=data["repository_relative_path"],
            receipt_relative_path=data["receipt_relative_path"],
            git=LocalGitEvidence.from_mapping(data["git"]),
            source=LocalSourceRepositoryEvidence.from_mapping(data["source"]),
            candidate=LocalCandidateCommitEvidence.from_mapping(data["candidate"]),
            bare_repository=data["bare_repository"],
            isolated_index=data["isolated_index"],
            local_source_only=data["local_source_only"],
            remote_configured=data["remote_configured"],
            network_write_performed=data["network_write_performed"],
            remote_push_performed=data["remote_push_performed"],
            pull_request_created=data["pull_request_created"],
            ready_for_review=data["ready_for_review"],
            reviewers_requested=data["reviewers_requested"],
            merged=data["merged"],
            released=data["released"],
            deployed=data["deployed"],
            merge_authority=data["merge_authority"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "preflight": self.preflight.to_dict(),
            "preflight_sha256": self.preflight_sha256,
            "lease_sha256": self.lease_sha256,
            "replay_entry_sha256": self.replay_entry_sha256,
            "request_sha256": self.request_sha256,
            "readiness_sha256": self.readiness_sha256,
            "task_sha256": self.task_sha256,
            "invocation_nonce": self.invocation_nonce,
            "materialization_policy_sha256": self.materialization_policy_sha256,
            "materialized_at_utc": self.materialized_at_utc,
            "transaction_id": self.transaction_id,
            "repository_relative_path": self.repository_relative_path,
            "receipt_relative_path": self.receipt_relative_path,
            "git": self.git.to_dict(),
            "source": self.source.to_dict(),
            "candidate": self.candidate.to_dict(),
            "bare_repository": self.bare_repository,
            "isolated_index": self.isolated_index,
            "local_source_only": self.local_source_only,
            "remote_configured": self.remote_configured,
            "network_write_performed": self.network_write_performed,
            "remote_push_performed": self.remote_push_performed,
            "pull_request_created": self.pull_request_created,
            "ready_for_review": self.ready_for_review,
            "reviewers_requested": self.reviewers_requested,
            "merged": self.merged,
            "released": self.released,
            "deployed": self.deployed,
            "merge_authority": self.merge_authority,
        }

    def canonical_json(self) -> str:
        return _legacy._canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _legacy._sha256_bytes(self.canonical_json().encode("utf-8"))


class _MaterializationGitRunner:
    def __init__(
        self,
        *,
        trusted_git: TrustedGitRuntime,
        transaction_root: Path,
    ) -> None:
        if not isinstance(trusted_git, TrustedGitRuntime):
            raise LocalCandidateMaterializationError(
                "local materialization requires a trusted Git runtime"
            )
        try:
            self._delegate = TrustedGitRunner(
                trusted_git,
                operation_root=transaction_root,
            )
        except TrustedGitRuntimeError as exc:
            raise LocalCandidateMaterializationError(
                "trusted Git runtime could not be bound to the transaction"
            ) from exc
        self._transaction_root = self._delegate.operation_root
        self._template = self._delegate._template

    def run(self, args: tuple[str, ...], **kwargs: Any) -> bytes:
        try:
            return self._delegate.run(args, **kwargs)
        except TrustedGitRuntimeError as exc:
            raise LocalCandidateMaterializationError(
                "trusted local Git command failed"
            ) from exc

    def evidence(self) -> LocalGitEvidence:
        try:
            runtime = self._delegate.evidence()
        except TrustedGitRuntimeError as exc:
            raise LocalCandidateMaterializationError(
                "trusted local Git evidence failed"
            ) from exc
        manifest = self._delegate.runtime.receipt.manifest
        executable = next(
            item
            for item in manifest.files
            if item.relative_path == manifest.executable_relative_path
        )
        return LocalGitEvidence(
            executable_sha256=executable.sha256,
            executable_bytes=executable.size_bytes,
            executable_basename=Path(manifest.executable_relative_path).name,
            version=runtime.version,
            runtime=runtime,
        )


def _verify_transaction_layout(transaction: Path) -> None:
    expected = {
        "repository.git",
        "receipt.json",
        "isolated-home",
        "isolated-xdg",
        "disabled-hooks",
        "empty-template",
        "empty-global-config",
        "isolated-temp",
    }
    actual = {item.name for item in transaction.iterdir()}
    if actual != expected:
        raise LocalCandidateMaterializationError(
            "local materialization transaction layout is not exact"
        )
    for name in (
        "isolated-home",
        "isolated-xdg",
        "disabled-hooks",
        "empty-template",
        "isolated-temp",
    ):
        directory = transaction / name
        if (
            not directory.is_dir()
            or _legacy._has_linkish_component(directory)
            or any(directory.iterdir())
        ):
            raise LocalCandidateMaterializationError(
                "local materialization isolation directory is not empty and exact"
            )
    global_config = transaction / "empty-global-config"
    if (
        not global_config.is_file()
        or _legacy._has_linkish_component(global_config)
        or global_config.read_bytes() != b""
    ):
        raise LocalCandidateMaterializationError(
            "local materialization global configuration is not empty and exact"
        )


def materialize_local_candidate(
    *,
    preflight: PublisherPreflightReceipt,
    task: DevelopmentTask,
    authorization_verifier: PublisherAuthorizationVerifier,
    publisher_verifier: PublisherRequestVerifier,
    semantic_verifier: SemanticReviewVerifier,
    control_plane_root: Path,
    source_repository: Path,
    materialization_root: Path,
    trusted_git: TrustedGitRuntime,
    materialized_at_utc: str,
) -> LocalCandidateMaterializationReceipt:
    """Create one exact local candidate using a complete trusted Git runtime."""

    if not isinstance(preflight, PublisherPreflightReceipt):
        raise LocalCandidateMaterializationError(
            "local materialization requires a preflight receipt"
        )
    if not isinstance(task, DevelopmentTask):
        raise LocalCandidateMaterializationError(
            "local materialization requires a validated task"
        )
    if task.merge_authority is not MergeAuthority.HUMAN:
        raise LocalCandidateMaterializationError(
            "merge authority must remain human"
        )
    if not isinstance(authorization_verifier, PublisherAuthorizationVerifier):
        raise LocalCandidateMaterializationError(
            "local materialization requires an authorization verifier"
        )
    if not isinstance(trusted_git, TrustedGitRuntime):
        raise LocalCandidateMaterializationError(
            "local materialization requires a trusted Git runtime"
        )
    try:
        preflight.verify(
            task=task,
            authorization_verifier=authorization_verifier,
            publisher_verifier=publisher_verifier,
            semantic_verifier=semantic_verifier,
            control_plane_root=Path(control_plane_root),
        )
        authorization_verifier.verify(
            lease=preflight.lease,
            task=task,
            publisher_verifier=publisher_verifier,
            semantic_verifier=semantic_verifier,
            control_plane_root=Path(control_plane_root),
            at_utc=materialized_at_utc,
        )
    except _legacy.PublisherAuthorizationError as exc:
        raise LocalCandidateMaterializationError(
            f"publisher preflight verification failed: {exc}"
        ) from exc
    materialized = _legacy._utc(
        materialized_at_utc,
        name="materialization time",
    )
    checked = _legacy._utc(preflight.checked_at_utc, name="preflight check time")
    if materialized < checked:
        raise LocalCandidateMaterializationError(
            "materialization cannot precede preflight"
        )
    root = _legacy._existing_link_free_directory(
        materialization_root,
        name="materialization root",
    )
    transaction_id = _legacy._transaction_id(preflight.sha256)
    final_transaction = root / transaction_id
    if final_transaction.exists():
        raise LocalCandidateMaterializationError(
            "local materialization transaction already exists"
        )
    temporary = Path(tempfile.mkdtemp(prefix=f".{transaction_id}-", dir=root))
    repository = temporary / "repository.git"
    index_path = temporary / "candidate.index"
    receipt_path = temporary / "receipt.json"
    published = False
    try:
        runner = _MaterializationGitRunner(
            trusted_git=trusted_git,
            transaction_root=temporary,
        )
        git_evidence = runner.evidence()
        source, source_evidence = _legacy._inspect_source(
            runner,
            source_repository=source_repository,
            base_sha=task.base_sha,
        )
        runner.run(
            (
                "-c",
                "init.defaultBranch=kaliv-unborn",
                "init",
                "--bare",
                f"--template={os.fspath(runner._template)}",
                os.fspath(repository),
            ),
            cwd=temporary,
            maximum=2_000_000,
        )
        runner.run(
            _legacy._repository_args(
                repository,
                "fetch",
                "--no-tags",
                "--no-write-fetch-head",
                "--no-recurse-submodules",
                "--no-auto-maintenance",
                source.as_uri(),
                task.base_sha,
            ),
            cwd=temporary,
            maximum=_legacy._MAX_GIT_OUTPUT_BYTES,
        )
        request = preflight.lease.signed_request.request
        patch = request.readiness.semantic_review_request.staged_patch
        if (
            len(patch) != request.staged_patch_bytes
            or _legacy._sha256_bytes(patch) != request.staged_patch_sha256
        ):
            raise LocalCandidateMaterializationError(
                "authorized staged patch bytes are inconsistent"
            )
        index_env = {"GIT_INDEX_FILE": os.fspath(index_path)}
        runner.run(
            _legacy._repository_args(repository, "read-tree", task.base_sha),
            cwd=temporary,
            maximum=4096,
            extra_env=index_env,
        )
        runner.run(
            _legacy._repository_args(
                repository,
                "apply",
                "--cached",
                "--binary",
                "--whitespace=nowarn",
                "-",
            ),
            cwd=temporary,
            stdin=patch,
            maximum=_legacy._MAX_GIT_OUTPUT_BYTES,
            extra_env=index_env,
        )
        tree_sha = runner.run(
            _legacy._repository_args(repository, "write-tree"),
            cwd=temporary,
            maximum=4096,
            extra_env=index_env,
        ).decode("ascii", errors="strict").strip()
        _legacy._hex(tree_sha, name="candidate tree SHA", pattern=_legacy._HEX40)
        if tree_sha == source_evidence.base_tree_sha:
            raise LocalCandidateMaterializationError(
                "candidate patch produced no tree change"
            )
        reproduced = runner.run(
            _legacy._repository_args(
                repository,
                "diff",
                "--binary",
                "--full-index",
                "--no-color",
                "--no-ext-diff",
                "--no-textconv",
                "--no-renames",
                task.base_sha,
                tree_sha,
                "--",
            ),
            cwd=temporary,
            maximum=_legacy._MAX_ARTIFACT_BYTES,
        )
        if reproduced != patch:
            raise LocalCandidateMaterializationError(
                "candidate tree does not reproduce the exact authorized patch"
            )
        tree_payload = runner.run(
            _legacy._repository_args(repository, "cat-file", "tree", tree_sha),
            cwd=temporary,
            maximum=_legacy._MAX_OBJECT_BYTES,
        )
        if _legacy._git_object_id("tree", tree_payload) != tree_sha:
            raise LocalCandidateMaterializationError(
                "candidate tree object is inconsistent"
            )
        publisher_actor = request.publisher_actor_id
        name = _legacy._author_name(publisher_actor)
        email = _legacy._actor_email(publisher_actor)
        git_timestamp = _legacy._git_timestamp(preflight.lease.issued_at_utc)
        message = _legacy._commit_message(task)
        commit_env = {
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_AUTHOR_DATE": f"@{git_timestamp}",
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
            "GIT_COMMITTER_DATE": f"@{git_timestamp}",
        }
        commit_sha = runner.run(
            _legacy._repository_args(
                repository,
                "commit-tree",
                tree_sha,
                "-p",
                task.base_sha,
            ),
            cwd=temporary,
            stdin=message.encode("utf-8") + b"\n",
            maximum=4096,
            extra_env=commit_env,
        ).decode("ascii", errors="strict").strip()
        _legacy._hex(commit_sha, name="candidate commit SHA", pattern=_legacy._HEX40)
        commit_payload = runner.run(
            _legacy._repository_args(repository, "cat-file", "commit", commit_sha),
            cwd=temporary,
            maximum=_legacy._MAX_OBJECT_BYTES,
        )
        expected_commit = _legacy._expected_commit_payload(
            tree_sha=tree_sha,
            parent_sha=task.base_sha,
            author_name=name,
            author_email=email,
            author_git_timestamp=git_timestamp,
            committer_name=name,
            committer_email=email,
            committer_git_timestamp=git_timestamp,
            message=message,
        )
        if (
            commit_payload != expected_commit
            or _legacy._git_object_id("commit", commit_payload) != commit_sha
        ):
            raise LocalCandidateMaterializationError(
                "candidate commit metadata is not deterministic"
            )
        branch_ref = f"refs/heads/{request.head_branch}"
        runner.run(("check-ref-format", branch_ref), cwd=temporary, maximum=4096)
        runner.run(
            _legacy._repository_args(
                repository,
                "update-ref",
                branch_ref,
                commit_sha,
                "0" * 40,
            ),
            cwd=temporary,
            maximum=4096,
        )
        runner.run(
            _legacy._repository_args(
                repository,
                "symbolic-ref",
                "HEAD",
                branch_ref,
            ),
            cwd=temporary,
            maximum=4096,
        )
        _legacy._verify_source_unchanged(
            runner,
            source=source,
            evidence=source_evidence,
        )
        try:
            index_path.unlink()
        except FileNotFoundError as exc:
            raise LocalCandidateMaterializationError(
                "isolated candidate index disappeared before publication"
            ) from exc
        candidate = LocalCandidateCommitEvidence(
            parent_sha=task.base_sha,
            staged_patch_sha256=request.staged_patch_sha256,
            staged_patch_bytes=request.staged_patch_bytes,
            tree_sha=tree_sha,
            tree_object_sha256=_legacy._sha256_bytes(tree_payload),
            tree_object_bytes=len(tree_payload),
            commit_sha=commit_sha,
            commit_object_sha256=_legacy._sha256_bytes(commit_payload),
            commit_object_bytes=len(commit_payload),
            commit_message=message,
            commit_message_sha256=_legacy._sha256_bytes(message.encode("utf-8")),
            author_actor_id=publisher_actor,
            author_name=name,
            author_email=email,
            author_git_timestamp=git_timestamp,
            committer_actor_id=publisher_actor,
            committer_name=name,
            committer_email=email,
            committer_git_timestamp=git_timestamp,
            head_branch=request.head_branch,
            branch_ref=branch_ref,
            branch_target_sha=commit_sha,
            head_symbolic_ref=branch_ref,
        )
        receipt = LocalCandidateMaterializationReceipt(
            preflight=preflight,
            preflight_sha256=preflight.sha256,
            lease_sha256=preflight.lease_sha256,
            replay_entry_sha256=preflight.replay_entry_sha256,
            request_sha256=preflight.request_sha256,
            readiness_sha256=preflight.readiness_sha256,
            task_sha256=preflight.task_sha256,
            invocation_nonce=preflight.invocation_nonce,
            materialization_policy_sha256=(
                local_candidate_materialization_policy_sha256()
            ),
            materialized_at_utc=materialized_at_utc,
            transaction_id=transaction_id,
            repository_relative_path="repository.git",
            receipt_relative_path="receipt.json",
            git=git_evidence,
            source=source_evidence,
            candidate=candidate,
        )
        _legacy._inspect_materialized_repository(
            runner,
            repository=repository,
            receipt=receipt,
        )
        receipt_path.write_bytes(receipt.canonical_json().encode("utf-8"))
        if receipt_path.read_bytes() != receipt.canonical_json().encode("utf-8"):
            raise LocalCandidateMaterializationError(
                "local transaction receipt publication is not canonical"
            )
        _verify_transaction_layout(temporary)
        try:
            os.rename(temporary, final_transaction)
        except OSError as exc:
            raise LocalCandidateMaterializationError(
                "local materialization transaction could not be published"
            ) from exc
        published = True
        return receipt
    finally:
        if not published and temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


def verify_local_candidate_materialization(
    *,
    receipt: LocalCandidateMaterializationReceipt,
    task: DevelopmentTask,
    authorization_verifier: PublisherAuthorizationVerifier,
    publisher_verifier: PublisherRequestVerifier,
    semantic_verifier: SemanticReviewVerifier,
    control_plane_root: Path,
    source_repository: Path,
    materialization_root: Path,
    trusted_git: TrustedGitRuntime,
) -> None:
    if not isinstance(receipt, LocalCandidateMaterializationReceipt):
        raise LocalCandidateMaterializationError(
            "local materialization verification requires a receipt"
        )
    if not isinstance(trusted_git, TrustedGitRuntime):
        raise LocalCandidateMaterializationError(
            "local materialization verification requires a trusted Git runtime"
        )
    try:
        receipt.preflight.verify(
            task=task,
            authorization_verifier=authorization_verifier,
            publisher_verifier=publisher_verifier,
            semantic_verifier=semantic_verifier,
            control_plane_root=Path(control_plane_root),
        )
        authorization_verifier.verify(
            lease=receipt.preflight.lease,
            task=task,
            publisher_verifier=publisher_verifier,
            semantic_verifier=semantic_verifier,
            control_plane_root=Path(control_plane_root),
            at_utc=receipt.materialized_at_utc,
        )
    except _legacy.PublisherAuthorizationError as exc:
        raise LocalCandidateMaterializationError(
            f"publisher preflight verification failed: {exc}"
        ) from exc
    root = _legacy._existing_link_free_directory(
        materialization_root,
        name="materialization root",
    )
    transaction = root / receipt.transaction_id
    if (
        not transaction.is_dir()
        or _legacy._has_linkish_component(transaction)
        or transaction.parent != root
    ):
        raise LocalCandidateMaterializationError(
            "local materialization transaction is missing or unsafe"
        )
    _verify_transaction_layout(transaction)
    receipt_path = transaction / receipt.receipt_relative_path
    repository = transaction / receipt.repository_relative_path
    if (
        not receipt_path.is_file()
        or _legacy._has_linkish_component(receipt_path)
        or receipt_path.read_bytes() != receipt.canonical_json().encode("utf-8")
    ):
        raise LocalCandidateMaterializationError(
            "local transaction receipt file is missing or noncanonical"
        )
    runner = _MaterializationGitRunner(
        trusted_git=trusted_git,
        transaction_root=transaction,
    )
    git_evidence = runner.evidence()
    if git_evidence.to_dict() != receipt.git.to_dict():
        raise LocalCandidateMaterializationError(
            "local Git runtime evidence no longer matches"
        )
    source, source_evidence = _legacy._inspect_source(
        runner,
        source_repository=source_repository,
        base_sha=task.base_sha,
    )
    if source_evidence.to_dict() != receipt.source.to_dict():
        raise LocalCandidateMaterializationError(
            "local source repository evidence no longer matches"
        )
    _legacy._verify_source_unchanged(
        runner,
        source=source,
        evidence=receipt.source,
    )
    _legacy._inspect_materialized_repository(
        runner,
        repository=repository,
        receipt=receipt,
    )


class LocalCandidateMaterializationGate:
    @staticmethod
    def valid(
        *,
        receipt: LocalCandidateMaterializationReceipt,
        task: DevelopmentTask,
        authorization_verifier: PublisherAuthorizationVerifier,
        publisher_verifier: PublisherRequestVerifier,
        semantic_verifier: SemanticReviewVerifier,
        control_plane_root: Path,
        source_repository: Path,
        materialization_root: Path,
        trusted_git: TrustedGitRuntime,
    ) -> bool:
        try:
            verify_local_candidate_materialization(
                receipt=receipt,
                task=task,
                authorization_verifier=authorization_verifier,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=Path(control_plane_root),
                source_repository=Path(source_repository),
                materialization_root=Path(materialization_root),
                trusted_git=trusted_git,
            )
        except LocalCandidateMaterializationError:
            return False
        return True


_T = TypeVar("_T")


def load_local_candidate_materialization_receipt(
    path: Path,
) -> LocalCandidateMaterializationReceipt:
    return _legacy._load_canonical(
        path,
        LocalCandidateMaterializationReceipt.from_mapping,
        name="local candidate materialization receipt",
    )


def write_local_candidate_materialization_receipt(
    path: Path,
    receipt: LocalCandidateMaterializationReceipt,
) -> str:
    if not isinstance(receipt, LocalCandidateMaterializationReceipt):
        raise LocalCandidateMaterializationError(
            "local candidate materialization receipt output is invalid"
        )
    return _legacy._write_canonical(
        path,
        receipt,
        name="local candidate materialization receipt",
        prefix=".local-candidate-materialization-v2-",
    )


# Prevent the retained helper core from exposing a second executable boundary
# after this public facade has imported its pure helpers and evidence types.
for _retired_name in (
    "TrustedLocalGit",
    "materialize_local_candidate",
    "verify_local_candidate_materialization",
    "LocalCandidateMaterializationGate",
):
    if hasattr(_legacy, _retired_name):
        delattr(_legacy, _retired_name)
del _retired_name

__all__ = [
    "LOCAL_CANDIDATE_MATERIALIZATION_RECEIPT_SCHEMA",
    "LOCAL_CANDIDATE_MATERIALIZATION_POLICY",
    "LocalCandidateCommitEvidence",
    "LocalCandidateMaterializationError",
    "LocalCandidateMaterializationGate",
    "LocalCandidateMaterializationReceipt",
    "LocalGitEvidence",
    "LocalSourceRepositoryEvidence",
    "load_local_candidate_materialization_receipt",
    "local_candidate_materialization_policy_sha256",
    "materialize_local_candidate",
    "verify_local_candidate_materialization",
    "write_local_candidate_materialization_receipt",
]
