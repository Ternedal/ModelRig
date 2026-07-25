"""D4: automatisk routing må ALDRIG sende RAG-kontekst til en cloud-model.

Besluttet af Anders 25/07-2026. Reglen gælder en feature der ikke findes endnu —
automatisk lokal/cloud-routing — og det er præcis derfor den skal stå som en
test frem for kun i ROADMAP. En regel der kun findes i prosa er en regel der
driver, og den her drifter i den retning ingen opdager: mod "det var vel også
i orden".

Begrundelsen, kort: produktet bæres af invarianten *"lyd forlader aldrig
huset"*, og dens søster er *"dine dokumenter forlader ikke huset uden at du
siger ja"*. En automatisk router er per definition et sted hvor du ikke sagde
ja — det er hele pointen med den. Et samtykke givet i én kontekst må derfor
ikke kunne bæres over på en beslutning software træffer i en anden.

Hvad denne fil håndhæver:

  1.  Samtykke kan KUN komme fra to steder: et eksplicit `allow_rag_cloud` på
      requesten, eller operatørens `KALIV_ALLOW_RAG_CLOUD`. Vokser der en
      tredje kilde — en router-flag, en "husk mit valg", en heuristik — fejler
      denne test, og den der tilføjede den skal forholde sig til D4.
  2.  Default er sikker. Intet samtykke = intet send.
  3.  Gaten fyrer kun når der FAKTISK er dokumentmatch og modellen FAKTISK er i
      cloud — så den ikke blokerer noget den ikke behøver.

Kør: PYTHONPATH=worker python3 tests/worker_d4_auto_routing.py
"""
from __future__ import annotations

import inspect
import os
import sys
import tempfile

os.environ["KALIV_TOOLS_ENABLED"] = "1"
os.environ["KALIV_WORKER_ALLOW_LAN"] = "1"
_tmp = tempfile.mkdtemp(prefix="kaliv-d4-")
os.environ["KALIV_TOOLS_DIR"] = os.path.join(_tmp, "notes")
os.environ["KALIV_AUDIT_DB"] = os.path.join(_tmp, "audit.db")
os.environ.pop("KALIV_ALLOW_RAG_CLOUD", None)

from app import main  # noqa: E402

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


class Req:
    """Minimal stand-in: the guard only reads allow_rag_cloud."""

    def __init__(self, allow=False):
        self.allow_rag_cloud = allow


# --- 1. default er sikker --------------------------------------------------
check(main._rag_cloud_allowed(Req(allow=False)) is False,
      "uden samtykke sendes RAG-indhold IKKE til cloud (sikker default)")

# --- 2. de to tilladte samtykkekilder -------------------------------------
check(main._rag_cloud_allowed(Req(allow=True)) is True,
      "eksplicit allow_rag_cloud paa requesten giver samtykke")

os.environ["KALIV_ALLOW_RAG_CLOUD"] = "1"
check(main._rag_cloud_allowed(Req(allow=False)) is True,
      "operatoerens KALIV_ALLOW_RAG_CLOUD giver samtykke")

for falsy in ("", "0", "false", "False", "no", "off"):
    os.environ["KALIV_ALLOW_RAG_CLOUD"] = falsy
    if main._rag_cloud_allowed(Req(allow=False)) is not False:
        check(False, f"KALIV_ALLOW_RAG_CLOUD={falsy!r} maa IKKE taelle som samtykke")
        break
else:
    check(True, "alle falsy-former af flaget afvises som samtykke")
os.environ.pop("KALIV_ALLOW_RAG_CLOUD", None)


# --- 3. INGEN TREDJE KILDE -- kernen i D4 ---------------------------------
# Reglen kan ikke haandhaeves ved at afproeve fremtidige flag, for de findes ikke
# endnu. Den haandhaeves ved at pinne at funktionen kun LAESER to ting. Vokser
# der en tredje, fejler den her, og den der tilfoejede den maa forholde sig til
# beslutningen frem for at glide udenom den.
src = inspect.getsource(main._rag_cloud_allowed)
reads_request_attrs = {
    line.split("req.")[1].split()[0].strip("():,")
    for line in src.splitlines() if "req." in line
}
check(reads_request_attrs == {"allow_rag_cloud"},
      f"gaten laeser KUN allow_rag_cloud fra requesten (fandt: "
      f"{sorted(reads_request_attrs)})")

env_reads = [ln for ln in src.splitlines() if "getenv" in ln or "environ" in ln]
check(len(env_reads) == 1 and "KALIV_ALLOW_RAG_CLOUD" in env_reads[0],
      "gaten laeser praecis ét miljoeflag, og det er KALIV_ALLOW_RAG_CLOUD")

# Kun den EKSEKVERBARE del: docstringen forklarer netop reglen og naevner derfor
# routing med vilje. Det var proben der var for grov -- fanget af den selv, da
# pejlemaerket blev skrevet ind.
body = src.split('"""')[-1] if src.count('"""') >= 2 else src
check("auto" not in body.lower() and "router" not in body.lower()
      and "fallback" not in body.lower(),
      "ingen routing-, auto- eller fallback-begreber er sivet ind i selve "
      "samtykke-LOGIKKEN -- D4's hele pointe")


# --- 4. gaten fyrer kun naar den skal -------------------------------------
# Den maa ikke blokere en lokal model, og ikke en cloud-tur uden dokumentmatch.
loop_src = inspect.getsource(main)
i = loop_src.find("_rag_cloud_allowed(req)")
window = loop_src[max(0, i - 400):i + 120]
check("matches and req.cloud_key" in window,
      "403'en kraever BAADE dokumentmatch OG en cloud-model -- den blokerer "
      "ikke lokale ture og ikke cloud-ture uden RAG")

print(f"\n===== D4 AUTO-ROUTING: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)
