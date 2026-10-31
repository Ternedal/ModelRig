"""Explicit offline handoff projection adapter for the existing GitHub client.

No scheduler, ToolGate registration, network activation or autonomous polling.
The caller must supply a trusted, already configured GitHubReadClient and
obtain any required user confirmation before invoking this adapter.
"""
from __future__ import annotations

from .github_connector_client import GitHubReadClient
from .github_connector_contract import GitHubConnectorGrantStore, normalize_repository
from .github_handoff_projection import Handoff, HandoffProjection


class GitHubHandoffAdapter:
    """Bind source receipt to the same read call, not to untrusted issue text."""

    def __init__(
        self,
        *,
        client: GitHubReadClient,
        grants: GitHubConnectorGrantStore,
        projection: HandoffProjection,
    ) -> None:
        if not isinstance(client, GitHubReadClient):
            raise TypeError("trusted GitHubReadClient required")
        if not isinstance(grants, GitHubConnectorGrantStore):
            raise TypeError("durable GitHub grant store required")
        if not isinstance(projection, HandoffProjection):
            raise TypeError("handoff projection required")
        # Do not let caller pair a client authorized by one grant store with
        # another grant store when deriving an ingestion receipt.
        if client._grants is not grants:
            raise ValueError("client and projection must share grant authority")
        self._client = client
        self._grants = grants
        self._projection = projection

    def ingest_one(
        self,
        grant_id: str,
        *,
        repository: str,
        source_type: str,
        source_id: int,
        now: int,
    ) -> bool:
        if source_type not in ("issue", "pull_request"):
            raise ValueError("only issue and pull request handoffs supported")
        if type(source_id) is not int or source_id <= 0:
            raise ValueError("positive numeric source id required")
        repository = normalize_repository(repository)
        # The read client performs grant validation, pinned-origin transport
        # and GitHub object identity validation. The receipt is taken only
        # from this result; no caller-provided receipt or status is accepted.
        result = self._client.read(
            grant_id, repository=repository, operation=source_type,
            object_id=source_id, now=now,
        )
        path = "issues" if source_type == "issue" else "pull"
        handoff = Handoff(
            repository=repository,
            source_type=source_type,
            source_id=source_id,
            revision=result.source.revision,
            source_url=f"https://github.com/{repository}/{path}/{source_id}",
        )
        return self._projection.ingest(
            handoff, receipt=result.source, grants=self._grants,
        )
