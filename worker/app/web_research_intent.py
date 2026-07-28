"""Fra en URL til en ResearchSharingIntent (T-034, trin 3a).

Ren logik, ingen netvaerk. Det er her de sikkerhedsvalg ligger som en hentefunktion
senere ikke skal traeffe -- og som er lettest at faa forkert, fordi de alle ser
ud som detaljer:

* **https kun.** En http-hentning kan aendres undervejs, og en kvittering paa
  noget en mellemmand har skrevet er ikke evidens.
* **Praecis vaert, aldrig wildcard.** En hentning af ``example.com/a`` maa ikke
  autorisere ``login.example.com``. ResearchSharingIntent binder domaenescopets
  digest ind i destinationen netop for at en tilladelse ikke kan afspilles med
  en bredere allowlist; her holdes scopet saa smalt som muligt fra starten.
* **Digest af den kanoniske URL.** To stier paa samme vaert giver forskellige
  digests, altsaa forskellige requests, altsaa hver sin godkendelse. Ellers
  ville "ja til forsiden" vaere "ja til hele sitet".
* **Byte-loft under skemaets.** Skemaet tillader 10 MB; en webside behoever
  ikke det, og et loft man aldrig rammer er ikke et loft.

IP-literaler, ``localhost``, ``.local``, ``.internal`` og ``.home.arpa`` afvises
allerede af ``normalize_domain_rule``. Testene navngiver dem alligevel: en
beskyttelse ingen test naevner er en beskyttelse man kan komme til at fjerne.
"""
from __future__ import annotations

import hashlib
from urllib.parse import urlsplit, urlunsplit

from .research_data_sharing import ResearchSharingIntent
from .research_egress import EgressPlan

#: Under skemaets 10 MB. En almindelig side er langt under; rammer noget loftet,
#: er det et signal, ikke normal drift.
MAX_RESPONSE_BYTES = 2_000_000

#: Kort identifikator, ikke en URL. Skal matche _DESTINATION_RE i research_egress.
DESTINATION = "public-web"


class WebResearchIntentError(ValueError):
    """URL'en kan ikke blive til en lovlig intent. Altid en afvisning."""


def canonical_url(raw: str) -> str:
    """Normalisér, og afvis alt der ikke er en simpel offentlig https-URL."""
    if not isinstance(raw, str) or not raw.strip():
        raise WebResearchIntentError("url mangler")
    parts = urlsplit(raw.strip())
    if parts.scheme != "https":
        raise WebResearchIntentError(
            f"kun https er tilladt (fik {parts.scheme or 'ingen scheme'!r})"
        )
    if parts.username or parts.password:
        raise WebResearchIntentError("credentials i url er ikke tilladt i v1")
    if parts.fragment:
        # Fragmentet sendes aldrig til serveren. At beholde det ville betyde at
        # to identiske requests fik forskellige digests -- altsaa to godkendelser
        # for een handling.
        parts = parts._replace(fragment="")
    if not parts.hostname:
        raise WebResearchIntentError("url mangler en vaert")
    if parts.port not in (None, 443):
        raise WebResearchIntentError("kun standardporten er tilladt i v1")
    path = parts.path or "/"
    return urlunsplit(("https", parts.hostname.lower(), path, parts.query, ""))


def build_intent(
    url: str,
    *,
    purpose: str,
    max_bytes: int = MAX_RESPONSE_BYTES,
) -> ResearchSharingIntent:
    """Byg den praecise intent for een hentning. Fejler lukket."""
    target = canonical_url(url)
    host = urlsplit(target).hostname or ""
    if not purpose or not purpose.strip():
        raise WebResearchIntentError("purpose mangler -- en godkendelse uden "
                                     "formaal kan ikke vurderes")
    if not 1 <= int(max_bytes) <= MAX_RESPONSE_BYTES:
        raise WebResearchIntentError(
            f"max_bytes skal vaere mellem 1 og {MAX_RESPONSE_BYTES}"
        )
    plan = EgressPlan(
        destination=DESTINATION,
        purpose=purpose.strip(),
        payload_sha256=hashlib.sha256(target.encode("utf-8")).hexdigest(),
        sensitivity="public",
        allowed_domains=(host,),          # praecis vaert, aldrig "*."
        max_bytes=int(max_bytes),
    )
    return ResearchSharingIntent(
        plan=plan,
        summary=f"Hent {target} ({max_bytes} bytes maks)",
        purpose_code="web_research",
    )
