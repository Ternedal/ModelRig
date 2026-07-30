"""Capability-kontrakten for web/research (T-034), landet før featuren.

**Dormant. Bevidst IKKE i REGISTRY.** `ToolGate.is_enabled` bruger en deny-liste,
ikke en allow-liste -- et værktøj i registret er live i samme øjeblik
`KALIV_TOOLS_ENABLED=1`. At tilføje web-research dér ville altså åbne fladen som
en bivirkning af en import, ikke som en beslutning. Samme mønster som
`read_scope.py` og `data_sharing.py`: kontrakten først, dvalende, med nul
kaldere.

Hvad D6 betyder her: en offentlig sidehentning bærer ingen lokal information
udad, så dens `data_class` er `public` og politikken siger `automatic`. Det er
ikke fordi bekræftelse er sprunget over -- det er fordi der ikke er noget af
brugerens at bekræfte. Sender en fremtidig variant *brugerens* tekst med
(f.eks. en søgning formuleret ud fra et dokument), er den `private`, og så
kræver samme politik bekræftelse uden at nogen skal huske det.

`schedulable` er **False** og det er et sikkerhedsvalg, ikke en mangel: en
uovervåget udadgående hentning fjerner mennesket fra præcis den beslutning D6
handler om.
"""
from __future__ import annotations

from .tools import Tool

WEB_RESEARCH_CAPABILITY_ID = "web_research"

#: Kontrakten. Bygges som en Tool, så den kan valideres af den samme
#: descriptor-adapter som alle andre værktøjer -- ikke som en parallel form.
WEB_RESEARCH_SPEC = Tool(
    name=WEB_RESEARCH_CAPABILITY_ID,
    risk="read",
    description=(
        "Hent én afgrænset offentlig webside og returnér dens indhold med "
        "kildekvittering. GET-only, ingen credentials, ingen login, ingen "
        "upload eller download."
    ),
    params={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Absolut https-URL"},
            # Maalt 30/07-2026 (D7 trin 1): kontrakten landede FOER henteren, og
            # henteren kraever et formaal -- `build_intent` afviser en tom
            # `purpose`, saa en spec uden feltet kan kun producere blokerede
            # kald. Formaalet er desuden praecis det, mennesket godkender paa
            # kortet: "hent X" og "hent X for at Y" er ikke samme beslutning.
            "purpose": {
                "type": "string",
                "description": "Formålet med hentningen; vises på kortet",
            },
        },
        "required": ["url", "purpose"],
        # Lukket skema: der findes ingen kanal ekstra kontekst kan rejse i
        # (D4). En ukendt noegle er afvist, ikke ignoreret.
        "additionalProperties": False,
    },
    run=None,  # dvalende: ingen eksekvering før aktivering er besluttet
    sensitivity="public",
    isolate=True,
    env_allow=(),
    network="public",
    # Destinationen navngiver en SLAGS modpart, ikke en URL -- samme form som
    # ollama-vaerktoejernes ("ollama",), og samme ord som D6's _DESTINATIONS.
    # Tool-kontrakten naegter "public" uden destination: man kan ikke erklaere
    # "gaar paa det aabne internet" uden at sige hvorhen.
    network_destinations=("public_web",),
    impact="read",
    cancellation="cooperative",
    idempotent=True,
    schedulable=False,
    unschedulable_because=(
        "En uovervaaget udadgaaende hentning fjerner mennesket fra "
        "data-sharing-beslutningen (D6). Web-research koeres kun paa "
        "foranledning."
    ),
)
