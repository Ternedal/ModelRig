#!/usr/bin/env python3
"""Hvilke dele af træet hvert fysisk bevis faktisk afhænger af.

Indtil nu bandt hvert bevis til kandidatens VERSIONSSTRENG. Det betød at et
rent versionsbump — hvor ikke én linje produktkode ændrer sig — ugyldiggjorde
alle beviser, også de manuelle. 2.0.9 → 2.0.10 ændrede præcis tre linjer, alle
versionsstrenge, og ville have kostet en fuld ny fysisk runde inklusive den
håndindtastede Pixel-matrix.

Evidens skal binde til **det der blev testet**, ikke til navnet på det.

Derfor: hvert bevis erklærer sine stier her, og et bevis taget på en anden
commit bæres videre HVIS OG KUN HVIS de stier er byte-identiske mellem de to
commits. Ændres én linje i et bevis' scope, falder netop det bevis — og kun
det.

DET ER STRAMMERE END FØR, IKKE LØSERE. Den gamle regel accepterede et bevis
alene fordi etiketten passede; den sagde intet om hvorvidt koden bag beviset
var den samme. Den nye regel spørger om koden.

Stierne er bevidst brede. Er man i tvivl om noget hører med, skal det med:
et bevis der bæres videre for langt er en fejl af den alvorlige slags, mens et
bevis der køres om for tit kun koster tid.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

#: Bevisnavn -> de stier beviset afhænger af.
#:
#: Fælles for alle: workerens og backendens kerne, fordi hvert bevis går
#: gennem den kæde. Version-filer og scripts er UDE — de ændrer ikke hvad
#: hardwaren gør, og det er netop dem der ellers ugyldiggør alt.
#
# FOERSTE UDGAVE VAR FOR GROV: den indeholdt hele "worker/app", saa EN
# aendring hvor som helst i workeren faeldede alle syv beviser. Da Sol landede
# en TTS-provider i voice_tts.py 19/8, invaliderede den RAG-benchmark og
# planner-eval — som ikke har noget med tekst-til-tale at goere.
#
# Det er den samme grovhed som versionsbindingen, bare et niveau ned. Faelles
# er nu KUN den kaede hvert bevis faktisk gaar igennem: HTTP-fladen, lageret,
# konfigurationen og de binaerer der betjener dem. Modulspecifikke filer
# hoerer til i det enkelte bevis' egen liste.
_FAELLES = (
    "worker/app/main.py",
    "worker/app/main_impl.py",
    "worker/app/entrypoint.py",
    "worker/app/store.py",
    "backend/internal",
    "backend/cmd",
)

# Kampagne-gates er med vilje bredere end de enkelte baselines. De er
# sammensatte releasebeviser, og deres reuse er kun en tidsoptimering. Et scope
# der er lidt for bredt koster en genkoersel; et scope der er for smalt kan
# fremstille en falsk groen kampagne. Harness-filerne er derfor med her, fordi
# en aendret maaler ogsaa aendrer hvad receiptet betyder.
_CAMPAIGN_RUNTIME = (
    "worker/app",
    "backend/internal",
    "backend/cmd",
)

PROOF_SCOPES: dict[str, tuple[str, ...]] = {
    # Rig-parathed: hele kæden, fordi den måler den.
    "preflight": _FAELLES,
    # Agent 3-evidens gennem Bearer-gatewayen.
    "agent3": _FAELLES + ("worker/app/agent3",),
    # Planner-eval kører mod modellen gennem workerens agent3-vej.
    "model_eval": _FAELLES + ("worker/app/agent3",),
    # Voice-baseline: pipeline, ASR og TTS.
    "voice": _FAELLES + ("worker/app/voice_pipeline.py", "worker/app/voice_asr.py",
                         "worker/app/voice_tts.py"),
    # Den MANUELLE Pixel-matrix bedømmer APPEN. Derfor android-kilden, og
    # derfor IKKE build.gradle.kts, som kun bærer versionsnavnet.
    # Den MANUELLE Pixel-matrix bedoemmer om lyden STOPPEDE og om gammel lyd
    # ikke kom igen. Det er TTS-output, direkte -- det er den lyd mennesket
    # lytter efter. Foerste udgave havde kun android/app/src og faeldede derfor
    # ikke da Sol landede en ny TTS-provider 19/8. En ny stemme aendrer praecis
    # det, matricen bedoemmer.
    "voice_manual": ("android/app/src", "worker/app/voice_tts.py",
                     "worker/app/voice_pipeline.py") + _FAELLES,
    "rag": _FAELLES + ("worker/app/rag_pdf.py", "worker/app/rag_docx.py",
                       "worker/app/rag_pptx.py", "worker/app/rag_html.py"),
    "scheduler_pilot": _FAELLES + ("worker/app/agent3",),

    # run-proof-campaign.ps1 gate-reuse.  Disse fem navne er de navne receipt-
    # adapteren bruger; ukendt navn giver None og maa aldrig tolkes som reuse.
    "stage_a": _CAMPAIGN_RUNTIME + (
        "android/app/src",
        "scripts/proof_stage_a_current.py",
        "scripts/stage_a_one_click.py",
        "scripts/stage_a_one_click.retained",
        "scripts/run-stage-a-physical-validation.ps1",
        "scripts/physical_validation_candidate_campaign.py",
        "scripts/physical_validation_candidate_gate.py",
    ),
    "forced_recovery": _FAELLES + (
        "worker/app/jobs.py",
        "worker/app/scheduler.py",
        "worker/app/schedule_runner.py",
        "worker/app/tools.py",
        "scripts/forced_recovery_test.py",
    ),
    "workflows": _CAMPAIGN_RUNTIME + (
        "eval",
        "scripts/workflow_baseline_one_click.py",
        "scripts/run-proof-campaign.ps1",
    ),
    "t023": _CAMPAIGN_RUNTIME + (
        "android/app/src",
        "scripts/proof_t023_current.py",
        "scripts/agent3_termination_ui_physical_one_click.py",
        "scripts/agent3_termination_ui_physical_report.py",
        "scripts/agent3_termination_ui_physical_gate.py",
    ),
    "t033": _CAMPAIGN_RUNTIME + (
        "scripts/proof_t033_current.py",
        "scripts/agent3_memory_protected_backup_physical.py",
        "scripts/agent3_memory_protected_backup_physical_gate.py",
    ),
}


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True
    ).stdout.strip()


#: De fire sites version_tool.py vedligeholder maskinelt. En aendring HER der
#: kun roerer versionskonstanten er per definition ikke adfaerd -- det er
#: bogholderi. Alt ANDET i de samme filer taeller fuldt ud.
_VERSIONSSITES = {
    "worker/app/main.py",
    "backend/internal/config/config.go",
    "android/app/build.gradle.kts",
    "desktop/composeApp/build.gradle.kts",
}

#: Linjer i de filer der kun baerer versionen.
_VERSIONSLINJE = re.compile(
    r'^[+-]\s*(const\s+|val\s+|var\s+)?'
    r'(APP_VERSION|VERSION|Version|version|versionName|versionCode|packageVersion)'
    r'\s*[:=]'
)


def _kun_versionsbogholderi(root: Path, fil: str, a: str, b: str) -> bool:
    """Er aendringen i ``fil`` udelukkende versionskonstanten?"""
    if fil not in _VERSIONSSITES:
        return False
    diff = _git(root, "diff", "--unified=0", f"{a}..{b}", "--", fil)
    for linje in diff.splitlines():
        if not linje.startswith(("+", "-")):
            continue
        if linje.startswith(("+++", "---")):
            continue
        if not _VERSIONSLINJE.match(linje):
            return False  # noget andet end versionen aendrede sig
    return True


def scope_unchanged(root: Path, name: str, taken_on_sha: str, head_sha: str) -> bool | None:
    """Er beviset ``name``'s stier identiske mellem de to commits?

    Returnerer None når spørgsmålet ikke kan besvares — ukendt bevisnavn, en
    sha der ikke findes lokalt, eller git der ikke svarer. **None betyder
    ALDRIG "ja".** Kalderen skal behandle den som "kør beviset om"; et bevis
    må aldrig bæres videre på et ubesvaret spørgsmål.
    """
    stier = PROOF_SCOPES.get(name)
    if not stier or not taken_on_sha or not head_sha:
        return None
    if taken_on_sha == head_sha:
        return True
    for sha in (taken_on_sha, head_sha):
        if not _git(root, "cat-file", "-t", sha).strip() == "commit":
            return None
    aendrede = [l for l in _git(
        root, "diff", "--name-only", f"{taken_on_sha}..{head_sha}", "--", *stier
    ).splitlines() if l]
    reelle = [f for f in aendrede
              if not _kun_versionsbogholderi(root, f, taken_on_sha, head_sha)]
    return not reelle


def changed_paths(root: Path, name: str, taken_on_sha: str, head_sha: str) -> list[str]:
    """De filer i beviset scope der ER ændret. Til en brugbar fejlbesked."""
    stier = PROOF_SCOPES.get(name)
    if not stier:
        return []
    aendrede = [l for l in _git(
        root, "diff", "--name-only", f"{taken_on_sha}..{head_sha}", "--", *stier
    ).splitlines() if l]
    return [f for f in aendrede
            if not _kun_versionsbogholderi(root, f, taken_on_sha, head_sha)]
