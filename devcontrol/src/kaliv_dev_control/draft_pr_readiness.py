"""Authenticated draft-PR readiness evidence without GitHub write authority."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .contract import DevelopmentTask, MergeAuthority
from .durable_publication import DurablePublicationError, create_once_file
from .semantic_review import (
    CriterionOutcome,
    SemanticReviewDecision,
    SemanticReviewError,
    SemanticReviewRequest,
    SemanticReviewVerifier,
    SignedSemanticReviewVerdict,
)

DRAFT_PR_READINESS_SCHEMA = (
    "kaliv-development-authenticated-draft-pr-readiness-proposal/v1"
)
_DRAFT_PR_READINESS_POLICY_DOMAIN = b"kaliv-draft-pr-readiness-policy/v1\0"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_BRANCH = re.compile(r"^(?![./])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_MAX_BODY_BYTES = 100_000
_MAX_ARTIFACT_BYTES = 56 * 1024 * 1024

DRAFT_PR_READINESS_POLICY = (
    "Accept only one canonical development task, one exact semantic-review request and one reviewer-authenticated approval verdict.",
    "Bind the exact staged patch, Tier-A command receipt, semantic review, reviewer identity, execution authority and review policy.",
    "Generate the proposed repository, base branch, head branch, title and body deterministically; callers may not provide presentation fields.",
    "Represent a draft pull-request proposal only; merge authority remains human and no repository or network write is performed.",
    "Treat any mismatch, uncertainty, finding, signature failure, authority drift or noncanonical artifact as not ready.",
)


class DraftPrReadinessError(ValueError):
    """Draft-PR readiness evidence is malformed, unauthenticated or mismatched."""


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hex(value: Any, *, name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise DraftPrReadinessError(f"{name} is invalid")
    return value


def _clean_text(value: Any, *, name: str, maximum: int, one_line: bool = False) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\x00" in value
        or len(value.encode("utf-8")) > maximum
        or (one_line and ("\n" in value or "\r" in value))
    ):
        raise DraftPrReadinessError(f"{name} is invalid")
    return value


def _branch(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or value.strip() != value
        or _BRANCH.fullmatch(value) is None
        or value.endswith(("/", ".", ".lock"))
        or "@{" in value
        or "\\" in value
    ):
        raise DraftPrReadinessError(f"{name} is not a canonical branch name")
    return value


def _strict(value: Any, *, name: str, fields: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise DraftPrReadinessError(f"{name} fields mismatch")
    return value


def _has_linkish_component(path: Path) -> bool:
    current = path.absolute()
    while True:
        if current.is_symlink():
            return True
        is_junction = getattr(current, "is_junction", None)
        if is_junction is not None and is_junction():
            return True
        if current.parent == current:
            return False
        current = current.parent


def draft_pr_readiness_policy_sha256() -> str:
    payload = json.dumps(
        list(DRAFT_PR_READINESS_POLICY),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(_DRAFT_PR_READINESS_POLICY_DOMAIN + payload)


def _task_sha256(task: DevelopmentTask) -> str:
    return _sha256_bytes(task.canonical_json().encode("utf-8"))


def _expected_head_branch(task: DevelopmentTask, request: SemanticReviewRequest) -> str:
    suffix = task.task_id.lower().replace("_", "-")
    return _branch(
        f"kaliv-draft/{suffix}-{task.base_sha[:12]}-{request.staged_patch_sha256[:12]}",
        name="proposed head branch",
    )


def _expected_title(task: DevelopmentTask) -> str:
    goal = " ".join(task.goal.split())
    title = f"draft(devcontrol): {goal}"
    if len(title.encode("utf-8")) > 240:
        title = f"draft(devcontrol): {task.task_id}"
    return _clean_text(title, name="proposal title", maximum=240, one_line=True)


def _expected_body(
    *,
    task: DevelopmentTask,
    request: SemanticReviewRequest,
    signed_verdict: SignedSemanticReviewVerdict,
    base_branch: str,
    head_branch: str,
) -> str:
    verdict = signed_verdict.verdict
    criteria = "\n".join(f"- [x] {item}" for item in task.acceptance_criteria)
    body = (
        "## Development task\n\n"
        f"- Task: `{task.task_id}`\n"
        f"- Repository: `{task.repository}`\n"
        f"- Exact base: `{task.base_sha}`\n"
        f"- Risk: `{task.risk.value}`\n"
        "- Merge authority: **human only**\n\n"
        "## Acceptance criteria\n\n"
        f"{criteria}\n\n"
        "## Proposed draft pull request\n\n"
        f"- Base branch: `{base_branch}`\n"
        f"- Proposed head branch: `{head_branch}`\n"
        "- Draft: `true`\n\n"
        "## Immutable candidate evidence\n\n"
        f"- Staged patch: `{request.staged_patch_sha256}` "
        f"({request.staged_patch_bytes} bytes)\n"
        f"- Tier-A command receipt: `{request.receipt_sha256}`\n"
        f"- Command: `{request.command_id}`\n"
        f"- Execution authority: `{request.execution_authority_sha256}`\n"
        f"- Semantic-review policy: `{request.review_policy_sha256}`\n"
        f"- Semantic-review request: `{request.sha256}`\n"
        f"- Signed semantic verdict: `{signed_verdict.sha256}`\n"
        f"- Independent reviewer: `{verdict.reviewer_actor_id}`\n"
        f"- Reviewer system: `{verdict.reviewer_system_id}`\n"
        f"- Reviewer key: `{signed_verdict.key_id}`\n\n"
        "## Authority boundary\n\n"
        "> This canonical artifact is evidence for a **draft pull-request proposal only**. "
        "It does not push a branch, create or update a pull request, request reviewers, "
        "merge, release, change settings, deploy or activate runtime authority. A human "
        "retains all merge authority."
    )
    return _clean_text(body, name="proposal body", maximum=_MAX_BODY_BYTES)


def _translate_semantic_error(exc: SemanticReviewError) -> DraftPrReadinessError:
    return DraftPrReadinessError(f"semantic approval verification failed: {exc}")


@dataclass(frozen=True, slots=True)
class AuthenticatedDraftPrReadinessProposal:
    task: DevelopmentTask
    task_sha256: str
    repository: str
    base_branch: str
    base_sha: str
    head_branch: str
    title: str
    body: str
    staged_patch_sha256: str
    staged_patch_bytes: int
    receipt_sha256: str
    semantic_review_request: SemanticReviewRequest
    semantic_review_request_sha256: str
    signed_semantic_review_verdict: SignedSemanticReviewVerdict
    signed_semantic_review_verdict_sha256: str
    reviewer_actor_id: str
    reviewer_key_id: str
    execution_authority_sha256: str
    review_policy_sha256: str
    proposal_policy_sha256: str
    draft: bool = True
    merge_authority: str = "human"
    schema: str = DRAFT_PR_READINESS_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != DRAFT_PR_READINESS_SCHEMA:
            raise DraftPrReadinessError("unsupported draft-PR readiness schema")
        if not isinstance(self.task, DevelopmentTask):
            raise DraftPrReadinessError("draft-PR readiness task is invalid")
        if self.task.merge_authority is not MergeAuthority.HUMAN:
            raise DraftPrReadinessError("merge authority must remain human")
        _hex(self.task_sha256, name="task hash", pattern=_HEX64)
        _hex(self.base_sha, name="base SHA", pattern=_HEX40)
        _hex(self.staged_patch_sha256, name="staged patch hash", pattern=_HEX64)
        _hex(self.receipt_sha256, name="Tier-A receipt hash", pattern=_HEX64)
        _hex(
            self.semantic_review_request_sha256,
            name="semantic review request hash",
            pattern=_HEX64,
        )
        _hex(
            self.signed_semantic_review_verdict_sha256,
            name="signed semantic review verdict hash",
            pattern=_HEX64,
        )
        _hex(
            self.execution_authority_sha256,
            name="execution authority hash",
            pattern=_HEX64,
        )
        _hex(self.review_policy_sha256, name="review policy hash", pattern=_HEX64)
        _hex(
            self.proposal_policy_sha256,
            name="proposal policy hash",
            pattern=_HEX64,
        )
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
        ):
            raise DraftPrReadinessError("repository is invalid")
        base_branch = _branch(self.base_branch, name="base branch")
        head_branch = _branch(self.head_branch, name="proposed head branch")
        if base_branch == head_branch:
            raise DraftPrReadinessError("base and proposed head branch must differ")
        _clean_text(self.title, name="proposal title", maximum=240, one_line=True)
        _clean_text(self.body, name="proposal body", maximum=_MAX_BODY_BYTES)
        if (
            isinstance(self.staged_patch_bytes, bool)
            or not isinstance(self.staged_patch_bytes, int)
            or self.staged_patch_bytes <= 0
        ):
            raise DraftPrReadinessError("staged patch byte count is invalid")
        if self.draft is not True or self.merge_authority != "human":
            raise DraftPrReadinessError("draft proposal authority is invalid")
        if self.task_sha256 != _task_sha256(self.task):
            raise DraftPrReadinessError("task hash is inconsistent")
        if (
            self.repository != self.task.repository
            or self.base_sha != self.task.base_sha
        ):
            raise DraftPrReadinessError("proposal identity is not bound to the task")
        if not isinstance(self.semantic_review_request, SemanticReviewRequest):
            raise DraftPrReadinessError("semantic review request is invalid")
        if not isinstance(
            self.signed_semantic_review_verdict,
            SignedSemanticReviewVerdict,
        ):
            raise DraftPrReadinessError("signed semantic review verdict is invalid")
        request = self.semantic_review_request
        signed = self.signed_semantic_review_verdict
        if request.sha256 != self.semantic_review_request_sha256:
            raise DraftPrReadinessError("semantic review request hash is inconsistent")
        if signed.sha256 != self.signed_semantic_review_verdict_sha256:
            raise DraftPrReadinessError(
                "signed semantic review verdict hash is inconsistent"
            )
        try:
            request.verify_task(self.task)
            signed.verdict.verify_request(request)
        except SemanticReviewError as exc:
            raise _translate_semantic_error(exc) from exc
        verdict = signed.verdict
        if (
            verdict.decision is not SemanticReviewDecision.APPROVE
            or verdict.findings
            or any(
                assessment.outcome is not CriterionOutcome.SATISFIED
                for assessment in verdict.criterion_assessments
            )
        ):
            raise DraftPrReadinessError(
                "draft-PR readiness requires one complete semantic approval"
            )
        if (
            self.staged_patch_sha256 != request.staged_patch_sha256
            or self.staged_patch_bytes != request.staged_patch_bytes
            or self.receipt_sha256 != request.receipt_sha256
            or self.execution_authority_sha256
            != request.execution_authority_sha256
            or self.review_policy_sha256 != request.review_policy_sha256
            or self.reviewer_actor_id != verdict.reviewer_actor_id
            or self.reviewer_key_id != signed.key_id
        ):
            raise DraftPrReadinessError(
                "proposal evidence identities are inconsistent"
            )
        if self.proposal_policy_sha256 != draft_pr_readiness_policy_sha256():
            raise DraftPrReadinessError("draft-PR readiness policy is unsupported")
        expected_head = _expected_head_branch(self.task, request)
        expected_title = _expected_title(self.task)
        expected_body = _expected_body(
            task=self.task,
            request=request,
            signed_verdict=signed,
            base_branch=base_branch,
            head_branch=expected_head,
        )
        if self.head_branch != expected_head:
            raise DraftPrReadinessError(
                "proposed head branch is not deterministic"
            )
        if self.title != expected_title or self.body != expected_body:
            raise DraftPrReadinessError(
                "draft pull-request presentation is not deterministic"
            )

    @classmethod
    def from_evidence(
        cls,
        *,
        task: DevelopmentTask,
        request: SemanticReviewRequest,
        signed_verdict: SignedSemanticReviewVerdict,
        verifier: SemanticReviewVerifier,
        control_plane_root: Path,
        base_branch: str = "main",
    ) -> "AuthenticatedDraftPrReadinessProposal":
        if not isinstance(task, DevelopmentTask):
            raise DraftPrReadinessError(
                "draft-PR readiness requires a validated task"
            )
        if task.merge_authority is not MergeAuthority.HUMAN:
            raise DraftPrReadinessError("merge authority must remain human")
        if not isinstance(verifier, SemanticReviewVerifier):
            raise DraftPrReadinessError(
                "draft-PR readiness requires a semantic review verifier"
            )
        try:
            verdict = verifier.verify(
                task=task,
                request=request,
                signed_verdict=signed_verdict,
                control_plane_root=Path(control_plane_root),
            )
        except SemanticReviewError as exc:
            raise _translate_semantic_error(exc) from exc
        if verdict.decision is not SemanticReviewDecision.APPROVE:
            raise DraftPrReadinessError(
                "semantic review did not approve the exact candidate"
            )
        base = _branch(base_branch, name="base branch")
        head = _expected_head_branch(task, request)
        title = _expected_title(task)
        body = _expected_body(
            task=task,
            request=request,
            signed_verdict=signed_verdict,
            base_branch=base,
            head_branch=head,
        )
        return cls(
            task=task,
            task_sha256=_task_sha256(task),
            repository=task.repository,
            base_branch=base,
            base_sha=task.base_sha,
            head_branch=head,
            title=title,
            body=body,
            staged_patch_sha256=request.staged_patch_sha256,
            staged_patch_bytes=request.staged_patch_bytes,
            receipt_sha256=request.receipt_sha256,
            semantic_review_request=request,
            semantic_review_request_sha256=request.sha256,
            signed_semantic_review_verdict=signed_verdict,
            signed_semantic_review_verdict_sha256=signed_verdict.sha256,
            reviewer_actor_id=verdict.reviewer_actor_id,
            reviewer_key_id=signed_verdict.key_id,
            execution_authority_sha256=request.execution_authority_sha256,
            review_policy_sha256=request.review_policy_sha256,
            proposal_policy_sha256=draft_pr_readiness_policy_sha256(),
        )

    @classmethod
    def from_mapping(
        cls,
        value: Any,
    ) -> "AuthenticatedDraftPrReadinessProposal":
        fields = {
            "schema",
            "task",
            "task_sha256",
            "repository",
            "base_branch",
            "base_sha",
            "head_branch",
            "title",
            "body",
            "staged_patch_sha256",
            "staged_patch_bytes",
            "receipt_sha256",
            "semantic_review_request",
            "semantic_review_request_sha256",
            "signed_semantic_review_verdict",
            "signed_semantic_review_verdict_sha256",
            "reviewer_actor_id",
            "reviewer_key_id",
            "execution_authority_sha256",
            "review_policy_sha256",
            "proposal_policy_sha256",
            "draft",
            "merge_authority",
        }
        data = _strict(
            value,
            name="authenticated draft-PR readiness proposal",
            fields=fields,
        )
        return cls(
            schema=data["schema"],
            task=DevelopmentTask.from_mapping(data["task"]),
            task_sha256=data["task_sha256"],
            repository=data["repository"],
            base_branch=data["base_branch"],
            base_sha=data["base_sha"],
            head_branch=data["head_branch"],
            title=data["title"],
            body=data["body"],
            staged_patch_sha256=data["staged_patch_sha256"],
            staged_patch_bytes=data["staged_patch_bytes"],
            receipt_sha256=data["receipt_sha256"],
            semantic_review_request=SemanticReviewRequest.from_mapping(
                data["semantic_review_request"]
            ),
            semantic_review_request_sha256=data[
                "semantic_review_request_sha256"
            ],
            signed_semantic_review_verdict=SignedSemanticReviewVerdict.from_mapping(
                data["signed_semantic_review_verdict"]
            ),
            signed_semantic_review_verdict_sha256=data[
                "signed_semantic_review_verdict_sha256"
            ],
            reviewer_actor_id=data["reviewer_actor_id"],
            reviewer_key_id=data["reviewer_key_id"],
            execution_authority_sha256=data["execution_authority_sha256"],
            review_policy_sha256=data["review_policy_sha256"],
            proposal_policy_sha256=data["proposal_policy_sha256"],
            draft=data["draft"],
            merge_authority=data["merge_authority"],
        )

    def verify(
        self,
        *,
        task: DevelopmentTask,
        verifier: SemanticReviewVerifier,
        control_plane_root: Path,
    ) -> None:
        if not isinstance(task, DevelopmentTask):
            raise DraftPrReadinessError(
                "draft-PR readiness verification requires a validated task"
            )
        if task.canonical_json() != self.task.canonical_json():
            raise DraftPrReadinessError(
                "draft-PR readiness proposal is bound to another task"
            )
        if not isinstance(verifier, SemanticReviewVerifier):
            raise DraftPrReadinessError(
                "draft-PR readiness verification requires a semantic verifier"
            )
        try:
            verdict = verifier.verify(
                task=task,
                request=self.semantic_review_request,
                signed_verdict=self.signed_semantic_review_verdict,
                control_plane_root=Path(control_plane_root),
            )
        except SemanticReviewError as exc:
            raise _translate_semantic_error(exc) from exc
        if verdict.decision is not SemanticReviewDecision.APPROVE:
            raise DraftPrReadinessError(
                "draft-PR readiness no longer has semantic approval"
            )
        if self.proposal_policy_sha256 != draft_pr_readiness_policy_sha256():
            raise DraftPrReadinessError(
                "draft-PR readiness policy no longer matches"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "task": self.task.to_dict(),
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_branch": self.base_branch,
            "base_sha": self.base_sha,
            "head_branch": self.head_branch,
            "title": self.title,
            "body": self.body,
            "staged_patch_sha256": self.staged_patch_sha256,
            "staged_patch_bytes": self.staged_patch_bytes,
            "receipt_sha256": self.receipt_sha256,
            "semantic_review_request": self.semantic_review_request.to_dict(),
            "semantic_review_request_sha256": self.semantic_review_request_sha256,
            "signed_semantic_review_verdict": (
                self.signed_semantic_review_verdict.to_dict()
            ),
            "signed_semantic_review_verdict_sha256": (
                self.signed_semantic_review_verdict_sha256
            ),
            "reviewer_actor_id": self.reviewer_actor_id,
            "reviewer_key_id": self.reviewer_key_id,
            "execution_authority_sha256": self.execution_authority_sha256,
            "review_policy_sha256": self.review_policy_sha256,
            "proposal_policy_sha256": self.proposal_policy_sha256,
            "draft": self.draft,
            "merge_authority": self.merge_authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_bytes(self.canonical_json().encode("utf-8"))


class DraftPrReadinessGate:
    """Return readiness only for one fully verified authenticated proposal."""

    @staticmethod
    def ready(
        *,
        proposal: AuthenticatedDraftPrReadinessProposal,
        task: DevelopmentTask,
        verifier: SemanticReviewVerifier,
        control_plane_root: Path,
    ) -> bool:
        if not isinstance(proposal, AuthenticatedDraftPrReadinessProposal):
            return False
        try:
            proposal.verify(
                task=task,
                verifier=verifier,
                control_plane_root=control_plane_root,
            )
        except DraftPrReadinessError:
            return False
        return True


def load_authenticated_draft_pr_readiness_proposal(
    path: Path,
) -> AuthenticatedDraftPrReadinessProposal:
    raw_path = Path(path)
    if (
        not raw_path.is_absolute()
        or _has_linkish_component(raw_path)
        or not raw_path.is_file()
    ):
        raise DraftPrReadinessError(
            "draft-PR readiness proposal must be an absolute regular file"
        )
    raw = raw_path.read_bytes()
    if not 2 <= len(raw) <= _MAX_ARTIFACT_BYTES:
        raise DraftPrReadinessError(
            "draft-PR readiness proposal size is invalid"
        )
    try:
        value = AuthenticatedDraftPrReadinessProposal.from_mapping(
            json.loads(raw.decode("utf-8"))
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DraftPrReadinessError(
            "draft-PR readiness proposal JSON is invalid"
        ) from exc
    if raw != value.canonical_json().encode("utf-8"):
        raise DraftPrReadinessError(
            "draft-PR readiness proposal is not canonical JSON"
        )
    return value


def write_authenticated_draft_pr_readiness_proposal(
    path: Path,
    proposal: AuthenticatedDraftPrReadinessProposal,
) -> str:
    if not isinstance(proposal, AuthenticatedDraftPrReadinessProposal):
        raise DraftPrReadinessError(
            "draft-PR readiness proposal output is invalid"
        )
    output = Path(path)
    if (
        not output.is_absolute()
        or output.exists()
        or output.is_symlink()
        or _has_linkish_component(output.parent)
        or not output.parent.is_dir()
    ):
        raise DraftPrReadinessError(
            "draft-PR readiness output path is unsafe or already exists"
        )
    payload = proposal.canonical_json().encode("utf-8")
    if len(payload) > _MAX_ARTIFACT_BYTES:
        raise DraftPrReadinessError(
            "draft-PR readiness proposal exceeds its byte bound"
        )
    try:
        create_once_file(output, payload)
    except (FileExistsError, DurablePublicationError) as exc:
        raise DraftPrReadinessError(
            "draft-PR readiness proposal could not be durably published"
        ) from exc
    return _sha256_bytes(payload)