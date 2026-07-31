"""D7 trin 1: WebResearchFetchers produktionskaldested -- som ToolGate-vaerktoej.

Beslutning 30/07-2026 (Anders): kaldestedet er et vaerktoej i REGISTRY, ikke et
nyt endpoint og ikke en RAG-sidevej. Tools-sporet baerer allerede fase-signalet
(`tool_run`), bekraeftelseskortet og den todelte adgangsmodel; en offentlig
hentning er `network="public"` per definition, saa kortet foelger af de akser
der allerede findes (requires_confirmation: write/desktop ELLER public), og
D4-graensen kan pinnes strukturelt i stedet for at bevogtes med disciplin.

Vaerktoejet OPFINDER ikke sin egen deklaration. `web_research_capability.py`
landede kontrakten foer featuren (dvalende, `run=None`, nul kaldere), og
registreringen her arver den med `dataclasses.replace` -- eksekvering paa, og
adgang til sit eget flag i et isoleret barn. Kontrakten bliver liggende
dvalende: den er stadig kilden til hvad vaerktoejet ER, saa der er eet sted at
rette, ikke to naesten ens.

Kompositionen er henterens egen konvolut med produktionsklasserne paa samme
niveau -- IKKE valideringsscriptets evidenslag. Den asymmetri er pinnet i
tests/workflow_web_research_parity.py del C+D og flippes bevidst ved trin 2,
ikke her ved et uheld.

Gaten er den EKSISTERENDE flade-gate, ikke et nyt flag:
`KALIV_WEB_RESEARCH_ENABLED` (kun praecis "1" taender; se
web_research_mount.web_research_enabled, som ejer semantikken). Eet navn for
een beslutning -- ruten og vaerktoejet er samme flade, og to naesten ens flag
er en forvekslingsfaelde. `os.getenv` staar literalt HER, fordi
scripts/activation_readiness.py laeser switches fra kildekoden med et
regex-krav om literal streng; mount-modulet bruger en konstant, saa dette
kaldested er det, der goer flaget synligt paa readiness-siden.

Ovenpaa gaelder ToolGates almindelige lag: `KALIV_TOOLS_ENABLED` skal vaere
sat, og kortet kraeves per kald. Et timeout er et nej.

D4 holdes strukturelt: run() modtager KUN `url` og `purpose` og afviser alt
andet foer noget som helst konstrueres. Der findes ingen parameter,
RAG-kontekst kan rejse i, og tests/worker_web_research_tool.py pinner det
behavioralt.

D7 nr. 5 gaelder ogsaa i scheduler-sporet: eet ja raekker til eet kald.
Kontrakten er ikke schedulable, og `requires_confirmation` giver kortet per
kald -- ingen "husk mit valg".
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
    _outcome_for,  # bevidst: D7 nr. 3-skelnen har EEN kilde, og det er den
)

TOOL_NAME = WEB_RESEARCH_CAPABILITY_ID

#: Samme navn som fladens rute-gate. Konstanten bruges til `env_allow`; selve
#: opslaget nedenfor staar literalt af hensyn til activation_readiness.
WEB_RESEARCH_FLAG = "KALIV_WEB_RESEARCH_ENABLED"

#: Saa meget af kroppen der foelger med tilbage som tekst. Loftet er for
#: samtalen, ikke for transporten -- intent.plan.max_bytes ejer selve
#: hentningens graense. Svaret skal kunne laeses og citeres, ikke genudgives.
MAX_BODY_TEXT_CHARS = 20_000

_ALLOWED_ARGS = frozenset({"url", "purpose"})


def _enabled() -> bool:
    """Samme semantik som web_research_mount.web_research_enabled: kun "1".

    Duplikeret i to linjer frem for importeret, fordi mount-modulet skal kunne
    importere DETTE modul uden en cyklus -- og fordi netop dette kald skal
    staa med literal flagstreng af hensyn til activation_readiness' scanning.
    """
    return os.getenv("KALIV_WEB_RESEARCH_ENABLED", "").strip() == "1"


def _resolve(host: str, port: int) -> tuple[str, ...]:
    """Produktionsresolver: getaddrinfo, dedupleret, raekkefoelgen bevaret.

    Ingen filtrering her. is_global-vagten bor i binding-laget, og en resolver
    der ogsaa filtrerede ville skjule praecis de afvisninger auditten skal se.
    """
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return tuple(dict.fromkeys(str(info[4][0]) for info in infos))


def build_production_fetcher() -> WebResearchFetcher:
    """Een hentnings komposition, samlet af produktionsklasserne.

    Frisk ledger per kald: leases deles ikke paa tvaers af hentninger, og et
    vaeltet kald efterlader ingen tilstand som det naeste skal arve.
    """
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
    body_text = result.body.decode("utf-8", errors="replace")
    clipped = len(body_text) > MAX_BODY_TEXT_CHARS
    if clipped:
        body_text = body_text[:MAX_BODY_TEXT_CHARS]
    return json.dumps(
        {
            "url": result.url,
            "status": result.status,
            "bytes_received": result.bytes_received,
            "binding_id": result.binding_id,
            "selected_address": result.selected_address,
            "body_text": body_text,
            "body_clipped": clipped,
        },
        ensure_ascii=False,
    )


def _run_web_research(args: dict, *, fetcher_factory=None) -> str:
    """Een hentning. Argumenterne valideres FOER noget konstrueres.

    Fejl oversaettes efter D7 nr. 3 med fetch-modulets egen tabel: vores nej
    (`blocked`) bliver ToolDenied, modpartens eller nettets fejl (`failed`)
    bliver ToolError. Skelnen genopfindes ikke her.
    """
    from . import tools as _tools

    if not isinstance(args, dict):
        raise _tools.ToolDenied("web_research: args skal vaere et objekt")
    unknown = set(args) - _ALLOWED_ARGS
    if unknown:
        # D4 strukturelt: der findes ingen loedig kanal for ekstra kontekst,
        # saa en ekstra noegle er ikke "ignoreret" -- den er afvist.
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
    """Registrer vaerktoejet -- hvis og kun hvis fladen er taendt.

    Vaerktoejet ARVER `WEB_RESEARCH_CAPABILITY`-kontrakten og tilfoejer praecis
    to ting: eksekveringen, og adgang til sit eget flag inde i et isoleret
    barn. Kontrakten landede foer featuren og bliver liggende dvalende med
    `run=None` -- den er stadig kilden til hvad vaerktoejet ER, og der er
    dermed kun eet sted at rette hvis fx destinationen aendrer sig. En anden,
    naesten ens deklaration her ville vaere den fjerde udgave af samme
    sandhed (HANDOFF lektie 29).

    Funktionen gentager sit eget gatetjek, saa den forbliver fail-closed fra
    enhver import-sti -- ogsaa fra `tool_child`, der bootstrapper den i en
    frisk proces -- og naegter at overtage et navn en anden komponent har.
    """
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
        # Barnet ser kun det vaerktoejet navngiver (toolhost.child_env). Uden
        # flaget her ville et isoleret kald starte i en proces hvor fladen er
        # slukket, og svare "unknown tool" paa noget forael deren netop har
        # faaet et ja til. Flaget er en kontakt, ikke en hemmelighed.
        env_allow=(WEB_RESEARCH_FLAG,),
    )
    return True
