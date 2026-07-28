"""Een hentning, med livscyklussen lukket paa alle stier (T-034, D7).

**Dvalende.** Intet kalder dette modul; `/research/fetch` svarer stadig 501, og
`web_research` er ikke i REGISTRY. Aktivering er D7 nr. 1 og en beslutning for
sig.

Modulet opfinder ingen sikkerhed. Det saetter graenser der allerede findes i
raekkefoelge, og sikrer at afslutningen sker uanset hvordan turen ender:

    intent   = build_intent(url, purpose)
    lease    = boundary.prepare(intent)
    evidence = boundary.claim(lease, intent)
    auth     = bridge.prepare(evidence, lease, intent, url)
    binding  = peer.issue(auth, evidence, lease, intent, url)
    pin      = transport.pin(binding, ...)
    prepared = transport.prepare(pin, url, "GET", (), max_response_bytes)
    response = transport.execute(pin, prepared, timeout)
    ...
    boundary.complete(lease, intent, outcome=..., bytes_sent=...)

`complete()` staar i en ``finally``, og udfaldet foeres i en variabel der starter
paa ``failed``. En fremtidig ``return`` eller ``raise`` et vilkaarligt sted kan
derfor ikke slippe uden om afslutningen, og glemmer nogen at saette udfaldet,
bliver det registreret som en fejl -- ikke som en succes. Det er strukturelt
frem for disciplinaert, fordi disciplin ikke overlever en refaktorering.

D7 nr. 3: vores egne graenser giver ``blocked``, modpartens fejl giver
``failed``. Uden den skelnen kan en kvittering ikke svare paa om VI naegtede
eller om DET gik i stykker, og det er netop den forskel der goer en audit
brugbar bagefter.

D7 nr. 5: eet ja raekker til eet kald. Der er ingen genforsoeg her. Et
genforsoeg efter en timeout er et nyt udgaaende kald og skal have sit eget ja.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .browser_peer_fulfillment import BrowserPinnedTransportError
from .research_data_sharing import ResearchSharingIntent
from .web_research_intent import WebResearchIntentError, build_intent

#: Et loft, ikke en forventning. Rammer en offentlig side det, er noget galt.
DEFAULT_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class WebResearchResult:
    """Hvad kalderen faar. Bindingens id er med, saa svaret kan spores."""

    url: str
    status: int
    body: bytes
    bytes_received: int
    binding_id: str
    selected_address: str


def _outcome_for(exc: BaseException) -> tuple[str, str]:
    """Oversaet en undtagelse til (outcome, error_code) efter D7 nr. 3.

    Vores egne moduler kaster ``*Denied`` og ``*ContractError``: det er os der
    naegter, og det er ``blocked``. ``BrowserPinnedTransportError`` og OS-fejl
    kommer fra modparten eller nettet og er ``failed``.
    """
    name = type(exc).__name__
    # VORES egne foerst, og paa NAVN -- ikke paa type. BrowserPeerAdapterDenied
    # arver fra PermissionError og dermed OSError, hvilket er semantisk rigtigt
    # (en afvisning ER en tilladelsesfejl) og fatalt for en naiv
    # isinstance-raekkefoelge: et OSError-tjek foerst ville stemple vores egen
    # SSRF-afvisning som modpartens fejl. Maalt 27/07 -- foerste udkast gjorde
    # praecis det.
    if isinstance(exc, WebResearchIntentError):
        return "blocked", name
    if name.endswith("Denied") or name.endswith("ContractError"):
        return "blocked", name
    if isinstance(exc, (BrowserPinnedTransportError, OSError, TimeoutError)):
        return "failed", name
    # Ukendt: antag at det er OS der gik i stykker, ikke at vi naegtede. At
    # kalde noget ukendt "blocked" ville paastaa en beslutning vi ikke traf.
    return "failed", name


class WebResearchFetcher:
    """Orkestrerer een hentning gennem de graenser der allerede findes."""

    def __init__(
        self,
        *,
        boundary: Any,
        bridge: Any,
        peer_ledger: Any,
        transport: Any,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        id_factory: Callable[[str], str] | None = None,
        receipt_ttl_seconds: int = 120,
        binding_ttl_seconds: int = 30,
    ) -> None:
        self._boundary = boundary
        self._bridge = bridge
        self._peer = peer_ledger
        self._transport = transport
        self._timeout = float(timeout_seconds)
        self._ids = id_factory or (lambda prefix: f"{prefix}-1")
        self._receipt_ttl = int(receipt_ttl_seconds)
        self._binding_ttl = int(binding_ttl_seconds)

    def fetch(
        self,
        url: str,
        *,
        purpose: str,
        max_bytes: int | None = None,
        now: int | None = None,
    ) -> WebResearchResult:
        # Intent'en bygges FOER lease'en. Er URL'en ulovlig, findes der endnu
        # ingen lease at afslutte -- og saa er der heller intet at laekke.
        kwargs = {} if max_bytes is None else {"max_bytes": max_bytes}
        intent: ResearchSharingIntent = build_intent(url, purpose=purpose, **kwargs)
        target = intent.plan.destination_url if hasattr(intent.plan, "destination_url") else None
        target = target or _target_from(intent, url)

        lease = self._boundary.prepare(
            intent, now=now, receipt_ttl_seconds=self._receipt_ttl
        )

        outcome = "failed"
        error_code: str | None = "unfinished"
        bytes_sent = 0
        pin = None
        try:
            evidence = self._boundary.claim(lease, intent, now=now)
            authorization = self._bridge.prepare(evidence, lease, intent, target, now=now)
            binding = self._peer.issue(
                authorization,
                evidence,
                lease,
                intent,
                target,
                now=now,
                ttl_seconds=self._binding_ttl,
            )
            pin = self._transport.pin(
                binding,
                cdp_request_id=self._ids("cdp"),
                network_request_id=self._ids("net"),
            )
            prepared = self._transport.prepare(
                pin,
                url=target,
                method="GET",          # v1 er GET-only; ingen krop ud
                headers=(),
                max_response_bytes=intent.plan.max_bytes,
            )
            response = self._transport.execute(
                pin, prepared, timeout_seconds=self._timeout
            )
            bytes_sent = int(response.bytes_sent)
            outcome, error_code = "completed", None
            return WebResearchResult(
                url=target,
                status=int(response.status),
                body=response.body,
                bytes_received=len(response.body),
                binding_id=binding.binding_id,
                selected_address=binding.selected_address,
            )
        except BaseException as exc:  # noqa: BLE001 - udfaldet skal saettes for ALLE
            outcome, error_code = _outcome_for(exc)
            raise
        finally:
            if pin is not None:
                # Pin'en er engangs. Frigives den ikke, kan naeste hentning ikke
                # pinne -- en laekage der viser sig som en uforklarlig afvisning
                # langt senere, og aldrig som en fejl her.
                try:
                    self._transport.release(pin)
                except Exception:  # noqa: BLE001
                    pass
            self._boundary.complete(
                lease,
                intent,
                outcome=outcome,
                bytes_sent=bytes_sent,
                error_code=error_code,
                now=now,
            )


def _target_from(intent: ResearchSharingIntent, fallback: str) -> str:
    """Den kanoniske URL, laest fra intent'ens summary hvis planen ikke baerer den."""
    summary = getattr(intent, "summary", "") or ""
    for token in summary.split():
        if token.startswith("https://"):
            return token
    return fallback
