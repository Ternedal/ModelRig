"""Flag-vagten for web-research-fladen (T-034, trin 2 af 3).

Samme form som `mount_agent3`: mount-funktionen **selvvagter**, og entrypoint
kalder ubetinget. Vagten bor sammen med det den vogter, saa en launcher ikke kan
komme til at montere fladen ved at glemme et hvis.

Rækkefølgen er bevidst. Handleren -- den der faktisk henter -- lander i naeste
trin, INDE i en vagt der allerede er bevist. Man skriver ikke det der sender
data udad og tilfoejer vagten bagefter. Indtil da svarer ruten 501: den findes
kun naar flaget er sat, og den goer intet.

Default er off. `KALIV_WEB_RESEARCH_ENABLED` skal saettes eksplicit -- og at
saette den er stadig en beslutning, ikke en konsekvens af D6. D6 fastlagde
POLITIKKEN for hvornaar noget maa sendes udad; hvilken flade der aabnes er et
separat valg, og det staar i ROADMAP.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, FastAPI

WEB_RESEARCH_FLAG = "KALIV_WEB_RESEARCH_ENABLED"
_STATE_ATTR = "web_research_mounted"


def web_research_enabled() -> bool:
    """True kun ved eksplicit opt-in. Alt andet end '1' er slukket."""
    return os.getenv(WEB_RESEARCH_FLAG, "").strip() == "1"


def build_web_research_router() -> APIRouter:
    """Ruten findes -- men henter intet foer trin 3."""
    router = APIRouter(prefix="/research", tags=["research"])

    @router.post("/fetch", status_code=501)
    def fetch() -> dict:
        # Bevidst ikke implementeret endnu. En rute der svarer 501 er aerligere
        # end en rute der ikke findes: den fortaeller at fladen er aabnet, og at
        # handleren mangler -- frem for at ligne en stavefejl i URL'en.
        return {
            "error": "not_implemented",
            "detail": (
                "Web-research-fladen er aabnet, men henteren er ikke landet "
                "endnu (T-034 trin 3). Ingen udgaaende trafik sker herfra."
            ),
        }

    return router


def mount_web_research(app: FastAPI) -> bool:
    """Montér fladen praecis een gang, og kun efter eksplicit opt-in."""
    if not web_research_enabled():
        return False
    if getattr(app.state, _STATE_ATTR, False):
        return True
    app.include_router(build_web_research_router())
    setattr(app.state, _STATE_ATTR, True)
    return True
