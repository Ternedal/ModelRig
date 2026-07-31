# RIGDAG_SIMPEL.md — hele rig-testen, kortest mulige vej

**Én dag. Fire blokke. Ét klik starter hver blok — resten er kun de handlinger,
et menneske sandfærdigt kan udføre.** Detaljerne bor i `RIGDAG.md` og
`STAGED_PHYSICAL_PROMOTION.md`; dette dokument er rækkefølgen.

**Kandidaten er `1.58.147`** på branchen `agent/unified-candidate-1.58.147`.
Wizard'en finder selv den eksakte SHA og nægter at gætte den.

## Testlederen: Claude i desktop-appen

Åbn Claude Desktop på riggen → **Code-fanen** → vælg repomappen
`C:\Users\Anders\Desktop\ModelRig` → permission mode **Manual** (Claude spørger
før hver kommando). Giv den denne prompt ordret:

> Du er testleder for rig-dagen. Læs RIGDAG_SIMPEL.md og følg blokkene i
> rækkefølge. Du kører kommandoerne efter min godkendelse, overvåger output og
> stopper ved første afvigelse. Bed mig KUN om de fem menneskelige handlinger
> i blok 1 og de fysiske valg i blok 3 og 4. Alle artefakter samles i
> `rig-evidence\<dato>\`, og du fører `EVIDENCE.md` løbende: pr. blok — hvad
> blev kørt, eksakt artefakt-sti, resultat. Du må ikke merge, pushe, tagge,
> release eller aktivere noget, og du sætter ingen `KALIV_*`-flag permanent —
> kun i den enkelte session.

Cowork-sessionen i samme app kan tage rapport- og dokumentarbejdet, og hele
sessionen kan følges og besvares **fra mobilen**, så du kan gå fra maskinen
mellem de fysiske handlinger. Vigtig sondring: Cowork kører i en sandkasse-VM
med adgang kun til tilkoblede mapper — blokke, der rører riggens processer og
vinduer, hører hjemme i **Code-fanen**.

## Blok 0 — fem minutter, én gang

```powershell
cd C:\Users\Anders\Desktop\ModelRig
git fetch origin
git switch agent/unified-candidate-1.58.147
git pull --ff-only origin agent/unified-candidate-1.58.147
mkdir rig-evidence\<dato>
```

## Blok 1 — Stage A: de syv beviser

Dobbeltklik **`START_STAGE_A_TEST.cmd`**. Wizard'en gør alt andet og kan
genoptages med samme dobbeltklik.

**Din liste er fem punkter:** optag de 20 voice-fraser · gennemfør fem
Pixel-trials · godkend den kanoniske write-plan i appen · tim schedulerens
pause/crash · bekræft det ene offentlige browserkald.

Stopper noget: den manuelle vej står i `STAGED_PHYSICAL_PROMOTION.md`.

## Blok 2 — D7 form (c): henteren rører internettet, beviset fryses

Rækkefølgen er pointen: **først** bruger blok 1 scriptet uændret (det syvende
bevis), **derefter** fryses det:

1. Testlederen omdøber `scripts\browser_peer_public_validation.py` til
   `.retained` efter præcedensen fra `agent3_readonly_pilot_one_click.retained`,
   opdaterer operatørens reference i samme commit og kører den fulde suite
   lokalt, før der committes. Kan præcedensen ikke følges 1:1, udskydes
   frysningen til en lille PR — dagen beviser stadig produktionskaldet.
2. Ét produktionskald ad den rigtige vej: start workeren med
   `KALIV_WEB_RESEARCH_ENABLED=1` **kun i den session**, åbn Kaliv-desktoppen
   og bed om én hentning af en offentlig HTTPS-side via `web_research`.
3. Testlederen verificerer: svaret kom, og audit-loggen har præcis én ny
   linje. Begge kopieres til `rig-evidence\`.

## Blok 3 — Computer Use I3/I4: første capture + én engangsplan

Med `KALIV_COMPUTER_USE=1` kun i sessionen og Notepad åbent som det
allowlistede vindue kører testlederen prøven mod worker-modulerne
(`desktop_capture`/`desktop_screenshot_tool` → HMAC-kontrakten i
`desktop_contract` → én plan via `desktop_action_plan` → én konsumption):

- capture af **præcis ét** forgrundsvindue, signatur verificeret;
- én plan genereret og konsumeret **én gang**;
- **forsøg nr. 2 på samme plan SKAL afvises** — afvisningen er en del af
  beviset;
- ingen input-eksekvering: I5 er ikke bygget, og det skal blive ved med at
  kunne ses.

Screenshot, kontrakt, plan og afvisning → `rig-evidence\`.

## Blok 4 — Paletten: ét visuelt valg

Begge apps åbne side om side (desktop + Android). Vælg med øjnene:
Androids mørkere `#5A4831` (AAA) eller tokenets `#6F665C` (AA).

**Dagens leverance er valget**, skrevet i `EVIDENCE.md`. Implementeringen —
flip af tokenet *eller* tilpasning af Android-temaet — kan testlederen lave
som udkast samme dag; de fire gates skal være grønne før commit:
`workflow_design_tokens`, `workflow_design_token_contrast`,
`workflow_android_palette_divergence`, `workflow_brand_no_token_duplicates`.

## Dagens slutning

Testlederen færdiggør `EVIDENCE.md` og foreslår commit-tekst; **du** committer
og pusher evidensen. Promovering — fast-forward, tag, release, aktivering —
er en separat, eksplicit beslutning og sker **ikke** i dag
(`STAGED_PHYSICAL_PROMOTION.md`).

## Hvis noget stopper

Første afvigelse: testlederen stopper og skriver afvigelsen i `EVIDENCE.md`
med log-sti. `RIGDAG.md` er den detaljerede kørebog — dette dokument erstatter
den ikke; det ordner rækkefølgen og fjerner valgene.
