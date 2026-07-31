# RIGDAG_SIMPEL.md — hele rig-testen, kortest mulige vej

**Én dag. Fire blokke plus én 30-sekunders beslutning. Ét klik starter hver
blok — resten er kun de handlinger, et menneske sandfærdigt kan udføre.** Detaljerne bor i `RIGDAG.md` og
`STAGED_PHYSICAL_PROMOTION.md`; dette dokument er rækkefølgen.

**Kandidaten er `1.58.147`** på branchen `agent/unified-candidate-1.58.147`.
Wizard'en finder selv den eksakte SHA og nægter at gætte den.

## SHA-invarianten — dagens hårdeste regel

Stage A binder til kandidatens **eksakte 40-tegns SHA**. Samme SHA bruges til
fast-forward, tag og release, og **enhver ændring af checkouten efter Stage A
ugyldiggør hele dagens fysiske evidens** (`STAGED_PHYSICAL_PROMOTION.md`).
Derfor: fra blok 1 starter, til promoveringen er afgjort, ændres
kandidat-checkouten **ikke** — ingen commits, ingen omdøbninger, ingen
git-operationer ud over læsning. Alt, der skal landes, landes **efter**
dagen som normale PR'er mod `main`. Testlederen håndhæver reglen og afviser
ethvert trin, der ville flytte SHA'en.

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

## Automatikgraden — hvad kører selv

- **Blok 0, 2 og 3 er fuldautomatiske:** testlederen kører alle kommandoer;
  Code-fanen beder om ét ja pr. kommandobatch — sig ja én gang pr. blok.
- **Blok 1 er automatisk undtagen dine fem handlinger.** Wizard'en kører
  selv; testlederen overvåger loggen og siger præcis, hvornår og hvad du
  skal gøre — du rører kun mikrofon, telefon, app-godkendelse og ur.
- **Blok 4:** valget er dit; udkastet laver testlederen i en separat mappe —
  ingen commits på dagen (SHA-invarianten).
- **Rapporten:** Cowork-sessionen kan køre Full Auto i sandkassen på
  `rig-evidence\` og skrive `EVIDENCE.md` løbende, mens Code-fanen kører
  blokkene.
- De hårde grænser gælder uanset mode: intet merges, pushes, tagges,
  releases eller aktiveres, og ingen `KALIV_*`-flag sættes permanent.

## Blok 0 — fem minutter, én gang

```powershell
cd C:\Users\Anders\Desktop\ModelRig
git fetch origin
git switch agent/unified-candidate-1.58.147
git pull --ff-only origin agent/unified-candidate-1.58.147
mkdir rig-evidence\<dato>
```

Kandidatbranchen holdes på main af Claude frem til dagen. `--ff-only`-pullet
fejler højlydt, hvis den alligevel er bagud — sig til, så rykkes den, før
noget andet startes.

## Blok 1 — Stage A: de syv beviser

Dobbeltklik **`START_STAGE_A_TEST.cmd`**. Wizard'en gør alt andet og kan
genoptages med samme dobbeltklik.

**Din liste er fem punkter:** optag de 20 voice-fraser · gennemfør fem
Pixel-trials · godkend den kanoniske write-plan i appen · tim schedulerens
pause/crash · bekræft det ene offentlige browserkald.

Stopper noget: den manuelle vej står i `STAGED_PHYSICAL_PROMOTION.md`.

## Blok 2 — D7 form (c): henteren rører internettet, beviset fryses

Blok 1 har allerede brugt scriptet **uændret** (det syvende bevis) — og der
røres ikke ved det i dag: `.retained`-frysningen sker **efter promoveringen**
som en normal PR (se »Efter dagen«), aldrig mellem Stage A og
exact-SHA-promotion.

1. Ét produktionskald ad den rigtige vej — **fuldautomatisk**: testlederen
   starter workeren med begge flag kun i den session
   (`KALIV_TOOLS_ENABLED=1` og `KALIV_WEB_RESEARCH_ENABLED=1`, begge kræver
   præcis `"1"`), tæller rækkerne i audit-databasen `kaliv-audit.db`, og
   kalder produktionsstien direkte:

   ```powershell
   curl.exe -s -X POST http://127.0.0.1:8099/tools/chat/stream `
     -H "Content-Type: application/json" `
     -d '{"message":"Hent https://example.com med web_research og opsummer den kort"}'
   ```

   (`model`-feltet er valgfrit — workeren bruger sin default.) Det er samme
   endpoint og samme tool-loop, som appen rammer — appen er UX, ikke beviset.
2. Testlederen verificerer automatisk: svaret indeholder en gennemført
   `web_research`-kørsel, og audit-databasen har **præcis én** ny post
   (rækketælling før/efter via `sqlite3`). Svar + audit-udtræk →
   `rig-evidence\`.

## Blok 3 — Computer Use I3/I4: første capture + én engangsplan

Med `KALIV_COMPUTER_USE=1` kun i sessionen starter testlederen selv Notepad
(`Start-Process notepad`) som det allowlistede vindue og kører prøven mod
worker-modulerne
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

**Dagens leverance er valget**, skrevet i `EVIDENCE.md` — intet andet.
Implementeringen — flip af tokenet *eller* tilpasning af Android-temaet —
laver testlederen som udkast i en **separat mappe uden for checkouten** og
lander den **efter dagen** som normal PR med de fire gates grønne:
`workflow_design_tokens`, `workflow_design_token_contrast`,
`workflow_android_palette_divergence`, `workflow_brand_no_token_duplicates`.
Ingen commits på kandidat-checkouten (SHA-invarianten).

## Én beslutning på 30 sekunder — memory-pilotens politik

Protect-first-sporet er landet (DPAPI-format, migration, reader, writer,
leak-gate). Før piloten åbnes, skal politikken bekræftes: **piloten
begrænses til `public`/`operational` — private/secret holdes ude.** Bekræft
eller revidér med én sætning i `EVIDENCE.md`; testlederen skriver den ind.

## Dagens slutning

Testlederen færdiggør `EVIDENCE.md`. Evidensen gemmes med
**`SAVE_STAGE_A_RESULTS.cmd`** og ligger i `rig-evidence\` — **kandidat-
checkouten forlades urørt** (SHA-invarianten). Promovering — fast-forward,
tag, release, aktivering — er en separat, eksplicit beslutning og sker
**ikke** i dag (`STAGED_PHYSICAL_PROMOTION.md`).

## Efter dagen — landinger der bevidst IKKE skete på kandidaten

Claude lander som normale PR'er mod `main`, i denne rækkefølge og først
**efter** at promoveringen er afgjort:

1. `.retained`-frysningen af `scripts\browser_peer_public_validation.py`
   (rename + loader efter præcedensen, operatør-referencen opdateret i samme
   commit, fuld suite grøn).
2. Palettevalgets implementering fra testlederens udkast, med de fire gates
   grønne.
3. Evidens-artefakterne fra `rig-evidence\`, hvis de skal ind i repoet.

## Hvis noget stopper

Første afvigelse: testlederen stopper og skriver afvigelsen i `EVIDENCE.md`
med log-sti. `RIGDAG.md` er den detaljerede kørebog — dette dokument erstatter
den ikke; det ordner rækkefølgen og fjerner valgene.
