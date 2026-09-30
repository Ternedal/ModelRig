"""Capability-kontrakten for web/research (T-034).

**Import-inert.** Selve spec'en har `run=None` og registreres aldrig som en
eksekverbar capability ved import. `web_research_tool.py` kan først registrere
en execution-bound kopi i ToolGate, når den eksakte opt-in
`KALIV_WEB_RESEARCH_ENABLED=1` er aktiv via `mount_web_research`. Dermed kan
`KALIV_TOOLS_ENABLED=1` alene ikke åbne web-research-fladen, og der findes
ingen parallel `/research/fetch`-surface.

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
    run=None,  # spec er inert; runtime-tool binder callable kun bag exact opt-in
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
