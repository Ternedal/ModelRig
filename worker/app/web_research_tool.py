"""Web research as the single ToolGate production caller (T-034, D7).

Decision 30/07-2026 (Anders): the caller is one REGISTRY tool, not a separate
endpoint or RAG side path. It remains behind the existing
``KALIV_WEB_RESEARCH_ENABLED`` surface gate and ordinary ToolGate confirmation.

D7 step 2 now makes the direct pinned fetch citation-ready: the fetcher returns
a canonical ``SourceReceipt`` produced by the shared deterministic verifier,
and this tool exposes that receipt plus its verified excerpt. Raw undecoded
wire bytes are no longer treated as model-visible citation text. The direct
ToolGate path deliberately does not fake Chromium/CDP commit semantics; it has
its own correct commit point (successful pinned GET + in-memory source
verification), while Browser Use keeps its stricter ``Fetch.fulfillRequest``
commit before evidence becomes citeable.

The tool inherits ``WEB_RESEARCH_SPEC`` with ``dataclasses.replace``. D4 remains
structural: run receives only ``url`` and ``purpose``; unknown keys are rejected
before composition. One confirmation authorizes exactly one outbound GET: no
redirect following and no retry.
"""
from __future__ import annotations

import dataclasses
import json
import os
import socket

from .browser_peer_fulfillment import PinnedBrowserPeerTransport
from .research_claim_evidence import (
    VerifiableDataSharingLedger,
    VerifiableResearchSharingBoundary,
)
from .research_peer_authorization import ResearchPeerAuthorizationBridge
from .research_peer_transfer import ResearchPeerTransferLedger
from .web_research_capability import (
    WEB_RESEARCH_CAPABILITY_ID,
    WEB_RESEARCH_SPEC as WEB_RESEARCH_CAPABILITY,
)
from .web_research_fetch import (
    WebResearchFetcher,
    WebResearchResult,
    _outcome_for,
)

TOOL_NAME = WEB_RESEARCH_CAPABILITY_ID
WEB_RESEARCH_FLAG = "KALIV_WEB_RESEARCH_ENABLED"
_ALLOWED_ARGS = frozenset({"url", "purpose"})


def _enabled() -> bool:
    """Same semantics as the route surface: only exact ``1`` opts in."""
    return os.getenv("KALIV_WEB_RESEARCH_ENABLED", "").strip() == "1"


def _resolve(host: str, port: int) -> tuple[str, ...]:
    """Production DNS lookup; public-address enforcement lives downstream."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return tuple(dict.fromkeys(str(info[4][0]) for info in infos))


def build_production_fetcher() -> WebResearchFetcher:
    """Build one isolated direct-fetch composition for one approved call."""
    ledger = VerifiableDataSharingLedger()
    boundary = VerifiableResearchSharingBoundary(ledger, mode="enforce")
    bridge = ResearchPeerAuthorizationBridge(boundary)
    peer = ResearchPeerTransferLedger(bridge, _resolve)
    transport = PinnedBrowserPeerTransport()
    return WebResearchFetcher(
        boundary=boundary,
        bridge=bridge,
        peer_ledger=peer,
        transport=transport,
    )


def _render(result: WebResearchResult) -> str:
    """Return model-visible text only from the verified source receipt.

    ``SourceReceipt.excerpt`` is bounded by the research contract. The full raw
    response remains internal to the fetch result; callers cannot accidentally
    cite unverified/undecoded wire bytes.
    """
    receipt = result.source_receipt
    return json.dumps(
        {
            "url": receipt.url,
            "status": result.status,
            "bytes_received": result.bytes_received,
            "binding_id": result.binding_id,
            "selected_address": result.selected_address,
            "resolved_addresses": list(result.resolved_addresses),
            "source": receipt.to_dict(),
            # Kept under the historical key for client/model compatibility, but
            # its authority is now explicitly the verified bounded excerpt.
            "body_text": receipt.excerpt,
            "body_clipped": receipt.bytes_read > len(receipt.excerpt.encode("utf-8")),
        },
        ensure_ascii=False,
    )


def _run_web_research(args: dict, *, fetcher_factory=None) -> str:
    """Execute one fetch; validate the entire argument surface first."""
    from . import tools as _tools

    if not isinstance(args, dict):
        raise _tools.ToolDenied("web_research: args skal vaere et objekt")
    unknown = set(args) - _ALLOWED_ARGS
    if unknown:
        raise _tools.ToolDenied(
            "web_research: ukendte argumenter afvises: "
            + ", ".join(sorted(unknown))
        )
    url = args.get("url")
    purpose = args.get("purpose")
    if not isinstance(url, str) or not url.strip():
        raise _tools.ToolDenied("web_research: url mangler")
    if not isinstance(purpose, str) or not purpose.strip():
        raise _tools.ToolDenied("web_research: purpose mangler")

    factory = fetcher_factory or build_production_fetcher
    fetcher = factory()
    try:
        result = fetcher.fetch(url, purpose=purpose)
    except BaseException as exc:
        outcome, code = _outcome_for(exc)
        if outcome == "blocked":
            raise _tools.ToolDenied(f"web_research blocked: {code}") from exc
        raise _tools.ToolError(f"web_research failed: {code}") from exc
    return _render(result)


def register_web_research_tool() -> bool:
    """Register the inherited capability iff the existing surface gate is on."""
    if not _enabled():
        return False
    from . import tools as _tools

    existing = _tools.REGISTRY.get(TOOL_NAME)
    if existing is not None:
        if getattr(existing, "run", None) is _run_web_research:
            return True
        raise RuntimeError(
            f"{TOOL_NAME} is already registered by another component"
        )
    _tools.REGISTRY[TOOL_NAME] = dataclasses.replace(
        WEB_RESEARCH_CAPABILITY,
        run=_run_web_research,
        env_allow=(WEB_RESEARCH_FLAG,),
    )
    return True
