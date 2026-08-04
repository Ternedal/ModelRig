"""Hash-bound draft pull-request proposals without GitHub write authority."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .campaign import CampaignState, DevelopmentCampaign
from .contract import DevelopmentTask, MergeAuthority
from .review import DraftPrGate, ReviewRequest, ReviewVerdict

PROPOSAL_SCHEMA = "kaliv-development-draft-pr-proposal/v1"
_BRANCH = re.compile(r"^(?![./])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")


class ProposalError(ValueError):
    """A draft proposal is not bound to reviewed campaign evidence."""


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _branch(value: str, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or value.strip() != value
        or _BRANCH.fullmatch(value) is None
        or value.endswith(("/", ".", ".lock"))
        or "@{" in value
        or "\\" in value
    ):
        raise ProposalError(f"{name} is not a canonical branch name")
    return value


@dataclass(frozen=True, slots=True)
class DraftPullRequestProposal:
    repository: str
    base_branch: str
    base_sha: str
    head_branch: str
    title: str
    body: str
    task_sha256: str
    campaign_head_sha256: str
    review_request_sha256: str
    review_verdict_sha256: str
    draft: bool = True
    merge_authority: str = "human"
    schema: str = PROPOSAL_SCHEMA

    @classmethod
    def from_mapping(cls, value: Any) -> "DraftPullRequestProposal":
        allowed = {
            "schema",
            "repository",
            "base_branch",
            "base_sha",
            "head_branch",
            "title",
            "body",
            "task_sha256",
            "campaign_head_sha256",
            "review_request_sha256",
            "review_verdict_sha256",
            "draft",
            "merge_authority",
        }
        if not isinstance(value, Mapping) or set(value) != allowed:
            raise ProposalError("proposal fields mismatch")
        if value["schema"] != PROPOSAL_SCHEMA:
            raise ProposalError("proposal schema is unsupported")
        if not isinstance(value["repository"], str) or _REPOSITORY.fullmatch(
            value["repository"]
        ) is None:
            raise ProposalError("proposal repository is invalid")
        if not isinstance(value["base_sha"], str) or _SHA40.fullmatch(
            value["base_sha"]
        ) is None:
            raise ProposalError("proposal base SHA is invalid")
        for name in (
            "task_sha256",
            "campaign_head_sha256",
            "review_request_sha256",
            "review_verdict_sha256",
        ):
            if not isinstance(value[name], str) or _SHA64.fullmatch(value[name]) is None:
                raise ProposalError(f"proposal {name} is invalid")
        title = value["title"]
        body = value["body"]
        if (
            not isinstance(title, str)
            or not title
            or title.strip() != title
            or "\x00" in title
            or "\n" in title
            or len(title.encode("utf-8")) > 240
        ):
            raise ProposalError("proposal title is invalid")
        if (
            not isinstance(body, str)
            or not body
            or "\x00" in body
            or len(body.encode("utf-8")) > 50_000
        ):
            raise ProposalError("proposal body is invalid")
        if value["draft"] is not True or value["merge_authority"] != "human":
            raise ProposalError("proposal authority is invalid")
        return cls(
            repository=value["repository"],
            base_branch=_branch(value["base_branch"], name="base branch"),
            base_sha=value["base_sha"],
            head_branch=_branch(value["head_branch"], name="head branch"),
            title=title,
            body=body,
            task_sha256=value["task_sha256"],
            campaign_head_sha256=value["campaign_head_sha256"],
            review_request_sha256=value["review_request_sha256"],
            review_verdict_sha256=value["review_verdict_sha256"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "repository": self.repository,
            "base_branch": self.base_branch,
            "base_sha": self.base_sha,
            "head_branch": self.head_branch,
            "title": self.title,
            "body": self.body,
            "task_sha256": self.task_sha256,
            "campaign_head_sha256": self.campaign_head_sha256,
            "review_request_sha256": self.review_request_sha256,
            "review_verdict_sha256": self.review_verdict_sha256,
            "draft": self.draft,
            "merge_authority": self.merge_authority,
        }

    def canonical_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )

    @property
    def proposal_sha256(self) -> str:
        return _sha256(self.canonical_json())


class DraftProposalBuilder:
    """Create a deterministic proposal; perform no repository or network write."""

    @staticmethod
    def build(
        *,
        task: DevelopmentTask,
        campaign: DevelopmentCampaign,
        request: ReviewRequest,
        verdict: ReviewVerdict,
        base_branch: str = "main",
    ) -> DraftPullRequestProposal:
        if task.merge_authority is not MergeAuthority.HUMAN:
            raise ProposalError("merge authority must remain human")
        campaign.verify()
        if campaign.state is not CampaignState.REVIEWED:
            raise ProposalError("campaign must be reviewed before proposing a draft PR")
        task_hash = _sha256(task.canonical_json())
        if (
            campaign.task_id != task.task_id
            or campaign.task_sha256 != task_hash
            or campaign.base_sha != task.base_sha
        ):
            raise ProposalError("campaign is not bound to the task")
        if not DraftPrGate.ready(task, request, verdict):
            raise ProposalError("structural draft-PR gate did not pass")

        base = _branch(base_branch, name="base branch")
        suffix = task.task_id.lower().replace("_", "-")
        head = _branch(
            f"kaliv-dev/{suffix}-{task.base_sha[:12]}", name="head branch"
        )
        goal_title = " ".join(task.goal.split())
        title = f"draft(devcontrol): {goal_title}"
        if len(title.encode("utf-8")) > 240:
            title = f"draft(devcontrol): {task.task_id}"
        criteria = "\n".join(f"- [ ] {item}" for item in task.acceptance_criteria)
        commands = "\n".join(
            f"- `{item.command_id}`: {'passed' if item.passed else 'failed'} "
            f"(`{item.receipt_sha256}`)"
            for item in request.command_evidence
        )
        body = (
            "## Development task\n\n"
            f"- Task: `{task.task_id}`\n"
            f"- Exact base: `{task.base_sha}`\n"
            f"- Risk: `{task.risk.value}`\n"
            "- Merge authority: **human only**\n\n"
            "## Acceptance criteria\n\n"
            f"{criteria}\n\n"
            "## Structural evidence\n\n"
            f"- Staged diff: `{request.index_diff_sha256}`\n"
            f"- Review request: `{_sha256(request.canonical_json())}`\n"
            f"- Review verdict: `{_sha256(verdict.canonical_json())}`\n"
            f"- Independent reviewer: `{verdict.reviewer_actor_id}`\n\n"
            "## Required commands\n\n"
            f"{commands}\n\n"
            "> This is a proposal for a **draft** pull request. It grants no merge, "
            "release or production authority. Semantic human review is still required.\n"
        )
        if len(body.encode("utf-8")) > 50_000:
            raise ProposalError("generated proposal body exceeds 50000 UTF-8 bytes")
        return DraftPullRequestProposal(
            repository=task.repository,
            base_branch=base,
            base_sha=task.base_sha,
            head_branch=head,
            title=title,
            body=body,
            task_sha256=task_hash,
            campaign_head_sha256=campaign.events[-1].event_sha256,
            review_request_sha256=_sha256(request.canonical_json()),
            review_verdict_sha256=_sha256(verdict.canonical_json()),
        )
