"""Default-off production composition for the Agent 4 operator read surface.

This module is imported only after exact opt-in from ``app.entrypoint``. It
composes the narrow canonical read context used by the already-landed operator
API without constructing a lifecycle scheduler, resource admission, queue,
checkpoint/failure services, recovery path or background work.

Composition is deliberately side-effect free: it creates no directory or file,
performs no recovery and starts no thread, timer or polling loop.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import NoReturn

from .domain import CampaignValidationError
from .handoff import (
    CampaignDispatchAcknowledgement,
    CampaignDispatchOutcome,
    CampaignDispatchRequest,
    CampaignSignalAcknowledgement,
    CampaignSignalRequest,
)
from .operator_read_context import (
    Agent4OperatorReadContext,
    compose_agent4_operator_read_context,
)

_AGENT4_OPERATOR_FLAG = "KALIV_AGENT4_OPERATOR_API"
_AGENT4_DATA_ROOT = "KALIV_AGENT4_DATA_ROOT"


class ReadOnlyAgent4HandoffExecutor:
    """Legacy fail-closed handoff guard retained for compatibility tests.

    Production read composition no longer constructs any handoff scheduler or
    executor. Keeping this small guard avoids weakening callers that imported
    it directly while making it non-authoritative for the production context.
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
) -> Agent4OperatorReadContext | None:
    """Compose the canonical dormant read context after exact opt-in.

    Returns ``None`` when the operator surface is off. With exact opt-in, a
    missing or invalid dataroot fails startup closed. The returned context owns
    only read facades; lifecycle, handoff and resource-admission services are
    never constructed for this production mode.
    """

    if os.getenv(_AGENT4_OPERATOR_FLAG, "0") != "1":
        return None

    return compose_agent4_operator_read_context(_configured_root())
