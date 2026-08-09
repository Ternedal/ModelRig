"""Default-off production composition for the Agent 4 operator read surface.

This module is imported only after exact opt-in from ``app.entrypoint``. It
composes the canonical A4-09 object graph around a fail-closed executor so the
already-landed operator API can read persisted campaigns, timeline and evidence
without gaining dispatch, signal, recovery or background-work authority.

Composition is deliberately side-effect free: it creates no directory or file,
performs no recovery and starts no thread, timer or polling loop.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import NoReturn

from .composition import Agent4RuntimeContext, compose_agent4_runtime
from .domain import CampaignValidationError
from .handoff import (
    CampaignDispatchAcknowledgement,
    CampaignDispatchOutcome,
    CampaignDispatchRequest,
    CampaignSignalAcknowledgement,
    CampaignSignalRequest,
)

_AGENT4_OPERATOR_FLAG = "KALIV_AGENT4_OPERATOR_API"
_AGENT4_DATA_ROOT = "KALIV_AGENT4_DATA_ROOT"
_READ_ONLY_RESOURCE = "operator-read"


class ReadOnlyAgent4HandoffExecutor:
    """Fail-closed executor used by the production read-only host mode.

    The operator API never calls this boundary. Keeping a concrete executor in
    the canonical runtime context avoids a parallel read model while making any
    accidental lifecycle call fail before an external side effect can occur.
    """

    @staticmethod
    def _reject(operation: str) -> NoReturn:
        raise CampaignValidationError(
            f"Agent 4 read-only production context forbids {operation}"
        )

    def dispatch(
        self,
        request: CampaignDispatchRequest,
    ) -> CampaignDispatchAcknowledgement:
        del request
        self._reject("dispatch")

    def signal(
        self,
        request: CampaignSignalRequest,
    ) -> CampaignSignalAcknowledgement:
        del request
        self._reject("signal")

    def query_outcome(self, dispatch_id: str) -> CampaignDispatchOutcome:
        del dispatch_id
        self._reject("outcome lookup")


def _configured_root() -> Path:
    raw = os.getenv(_AGENT4_DATA_ROOT, "").strip()
    if not raw:
        raise CampaignValidationError(
            f"{_AGENT4_DATA_ROOT} is required when {_AGENT4_OPERATOR_FLAG}=1"
        )

    root = Path(os.path.expandvars(raw)).expanduser()
    if not root.is_absolute():
        raise CampaignValidationError(
            f"{_AGENT4_DATA_ROOT} must be an absolute filesystem path"
        )
    if root.exists() and not root.is_dir():
        raise CampaignValidationError(
            f"{_AGENT4_DATA_ROOT} must identify a directory path"
        )
    return root


def compose_agent4_operator_context_from_environment(
) -> Agent4RuntimeContext | None:
    """Compose the canonical dormant read context after exact opt-in.

    Returns ``None`` when the operator surface is off. With exact opt-in, a
    missing or invalid dataroot fails startup closed. The returned context owns
    the normal canonical stores but has no executable handoff authority.
    """

    if os.getenv(_AGENT4_OPERATOR_FLAG, "0") != "1":
        return None

    # The canonical runtime requires a non-empty resource vector. This isolated
    # synthetic capacity satisfies that structural invariant only; the executor
    # above still rejects every handoff before an external side effect can occur.
    return compose_agent4_runtime(
        _configured_root(),
        executor=ReadOnlyAgent4HandoffExecutor(),
        resource_capacities={_READ_ONLY_RESOURCE: 1},
        resource_resolver=lambda _spec: {_READ_ONLY_RESOURCE: 1},
    )
