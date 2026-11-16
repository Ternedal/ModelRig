# ADR-SYS-002: Evidens og freeze bundet til et release-fingerprint, ikke til den eksakte SHA

**Status:** VEDTAGET af Anders 16-11-2026 kl. 14:14 CET ("Kør" på udkastets anbefalinger til Q1–Q3, efter ChatGPTs review af rev. 1). Landing på `main` afventer 2.0.20-freezen; indtil da er dokumentet kun på sin gren. Anders disponerer dokumentet og dets PR alene og kan rette ethvert valg i afsnit 7 med én kommentar.
**Udkast:** rev. 1 skrevet af Claude 16-11-2026 efter Anders' "Kør" på fem procesforbedringer (#2275, kommentar 6915273202); rev. 2 samme dag indarbejder ChatGPTs fund (#2410) og Anders' valg; rev. 3 (samme aften) præciserer D3–D5 ud fra implementeringen (#2411, slice 2) uden at ændre beslutningerne; rev. 4 (17/11) indsnævrer dokumentationsklassen og udvider fingerprintets identitet efter den uafhængige efterprøvning af #2411/#2412.
**Serie:** andet dokument i SYS-serien (efter ADR-SYS-001).
**Stopreglen (A4-005):** dokumentet lander først; kontrakttestene i afsnit 5 skrives røde derefter. Implementering forberedes på egen gren bag denne PR og lander ikke før den.

---

## 1. Kontekst

Al fysisk evidens i ModelRig er bundet til en eksakt commit-SHA, og en freeze på `main` er bundet til, at `main` ikke flytter sig. Tre steder i koden gør det:

1. **`scripts/candidate_freeze_check.py`.** Kvitteringen gemmer `candidate.git_sha`, `candidate.code_sha256` (workerens fingerprint — kun `worker/app/**` og `bodyrig/**`) og `main_anchor.git_sha`. `verify_receipt()` afviser, hvis `origin/main` har flyttet sig fra ankeret ("origin/main moved from frozen anchor … rerun candidate freeze"), og kræver at kandidaten indeholder det aktuelle `main`. Hele det trackede træ (`tree.paths` + `tree.sha256`) skal være uændret — dokumentation inklusive.
2. **`scripts/kaliv_system_release_gate.py`** og de ModelRig-bundne qualifiers (`recovery_soak`, `consciousness_live_lifecycle`, `end_to_end_latency`, `bodyrig_android_live_body`). Evidensens SHA skal være pin-SHA'en eller en forfader med **eksakt samme Git-træ** (`rev-parse <sha>^{tree}`). Reglen findes for at en ren merge-commit ikke ugyldiggør evidens; enhver indholdsændring, også i en `.md`, fælder den.
3. **Release-flowet (HANDOFF §4):** RC-SHA = `main` med fuld CI; tagget sættes på `main`s head.

Konsekvensen er målt, ikke antaget: `main` flytter 150–350 commits om ugen, og hver kandidat siden august (2.0.9, 2.0.10, 2.0.19, 2.0.20) har krævet en freeze på `main`, som så presser PR-køen, til freezen løftes før kampagnen er kørt. 12/11 blev freezen på 2.0.19 løftet uden Stage A; 15/11 blev `main` frosset på 2.0.20 med 16 åbne PR'er og tre aktive sessioner bag sig. Under freezen kan ikke engang HANDOFF, en ADR eller en rettet runbook-sti lande, selv om ingen af dem ændrer én byte af det, riggen kører.

**Det egentlige spørgsmål er:**

> Hvad er det, evidensen beviser noget om — commit-SHA'en, eller koden?

Svaret er koden. SHA'en er en bekvem, men for grov, nøgle til den.

## 2. Beslutninger

**D1. Et repo-bredt release-fingerprint.** `scripts/release_fingerprint.py` beregner SHA-256 over alle trackede stier i en commit **undtagen dokumentationsklassen** (D2), som `(sti, blob-sha256)` i kanonisk rækkefølge, læst fra Git-objekterne (`git ls-tree -r <sha>`), ikke fra arbejdstræet. Fingerprintet er en funktion af commit'en alene og kan beregnes for enhver SHA uden checkout. Workerens eksisterende `code_sha256` bevares uændret som sin egen, snævrere identitet.

**D2. Dokumentationsklassen er en tracket liste, ikke en heuristik — og beskyttede dokumenter kan ikke udelukkes.** `release_fingerprint_exclusions.txt` i repo-roden, én glob pr. linje. Startindhold:

```
*.md
docs/**/*.png  docs/**/*.jpg  docs/**/*.jpeg  docs/**/*.gif  docs/**/*.svg
.github/ISSUE_TEMPLATE/**
LICENSE
```

*Præcisering i rev. 4 (fra reviewet af #2411/#2412):* klassen er markdown overalt plus billeder under `docs/`, ikke `docs/**` som helhed — skemaer og fixtures under `docs/`, som tests og kontrakter læser, er ikke dokumentation i denne forstand og indgår i fingerprintet. Beskyttede suffikser sammenlignes uafhængigt af store/små bogstaver (Windows kører `run.PS1`) og omfatter `.cmd`, `.ps1`, `.psm1`, `.bat` og `.py`. Fingerprintet dækker også filmode og gitlinks (`mode\0sti\0objekt`), så et sat exec-bit, et symlink i stedet for en fil eller en flyttet submodule-pointer ændrer det — D3's `docs_only` så dem allerede, nu ser D4 dem også.

To ting kan **aldrig** udelukkes, uanset listens indhold, og `release_fingerprint.py` afviser en liste der prøver (kontrakttest 4):

- *Beskyttede præfikser* — alt riggen kører eller rigdagen afprøver: `worker/`, `backend/`, `android/`, `desktop/`, `vr/`, `renderers/`, `bodyrig/`, `scripts/`, `tests/`, `deploy/`, `tools/`, `contracts/`, `.github/workflows/`, `VERSION`, `*.cmd`, `*.ps1`. Operatører og tests er kode i denne forstand.
- *Beskyttede dokumenter* — de `.md`-filer, der **er** proceduren eller tilstanden, ikke beskrivelsen af den: de tre runbooks operatøren følger under en kampagne (`RIGDAG_SIMPEL.md`, `STAGED_PHYSICAL_PROMOTION.md`, `STAGE_B_UPDATER_EVIDENCE.md`) og de tre generatorudgange, som operatører og gates læser (`CURRENT_STATE.md`, `ACTIVATION_READINESS.md`, `ROUTE_INVENTORY.md`). En ændring i dem indgår i fingerprintet, selv om de matcher `*.md`. Listen står som en konstant i `release_fingerprint.py` og pinnes ordret af en test; en runbook, der senere får en operatør-læsende rolle, føjes til listen i samme PR.

`HANDOFF.md` er bevidst **ikke** beskyttet. Den beskriver autoritet og status; håndhævelsen af autoriteten ligger i `scripts/` og `tests/`, som er beskyttede præfikser. En ændring, der kun rører HANDOFF-tekst, ændrer intet af det riggen kører eller gaterne måler; en ændring, der flytter en autoritetsgrænse i praksis, rører pr. definition en beskyttet sti. At beskytte HANDOFF ville genindføre freeze-presset for statuslinjer, som er præcis det problem dokumentet løser.

**D3. En freeze overlever docs-only landinger på `main`.** `verify_receipt()` ændres fra "`origin/main` == frosset anker" til: `origin/main` er ankeret **eller** en efterkommer af ankeret, hvor (a) ankeret er i `main`s historie, (b) `git diff --name-only <anker>..<main>` udelukkende rammer stier i dokumentationsklassen, og (c) `release_fingerprint(anker) == release_fingerprint(main)` — samme udsagn målt to veje. Kravet om at kandidaten indeholder **ankeret** bevares (det var invariant fra freeze-tidspunktet og beskytter mod en forfalsket kvittering); kravet om at kandidaten indeholder det *aktuelle* `main` bortfalder, for det er præcis det, en docs-only landing bryder. Kandidatens eget træ-rollup (`tree.sha256`) bevares som i dag — kandidatgrenen flytter sig ikke. *Præcisering i rev. 3:* rev. 2 skrev "fingerprint(kandidat) == fingerprint(main)"; det ville fælde en kandidat, der ved freeze lovligt var foran `main` med kode. Den implementerede regel binder til ankeret og er strengere på det punkt, der tæller (hvad `main`s kode var ved freeze er stadig `main`s kode).

**D4. Evidens er gyldig for enhver commit med samme fingerprint i samme linje.** Systemgatens regel "pin-SHA eller forfader med eksakt samme træ" bliver "pin-SHA eller forfader med samme release-fingerprint". Retningen bevares (evidens på en forfader af pinnen, aldrig omvendt). Reglen bor ét sted, `release_fingerprint.equivalent(evidence_sha, pinned_sha)`, og kaldes fra `kaliv_system_release_gate._modelrig_evidence_matches_pin`, som er det ene sted de fire ModelRig-bundne gates (`recovery_soak`, `consciousness_live_lifecycle`, `end_to_end_latency`, `bodyrig_android_live_body`) sammenlignes med pinnen. *Præcisering i rev. 3:* qualifier-scripterne selv sammenligner kun deres egen evidens med den kandidat-SHA, de blev givet (intern konsistens), ikke med pinnen; de ændres derfor ikke. Ukendte commits er ikke-ækvivalent evidens (fail-closed uden autoritetsfejl); en ubrugelig eksklusionsliste eller manglende git **er** en autoritetsfejl.

**D5. Tagget peger på den frosne kandidat, ikke på `main`s head.** Når `main` er foran kandidaten med docs-only commits, sættes `vX.Y.Z` på kandidat-SHA'en. Så er de publicerede artefakter bygget af præcis den commit, Stage A kørte på — inklusive `commit_identity`-stemplet (`scripts/stamp_build_identity.py`), som ellers ville afvige. `main` indeholder tagget (kandidaten er forfader), så invarianten "tagget er på `main`" holder. *Præcisering i rev. 3:* `freeze_check.py` accepterer allerede en kandidat, der er `identical` eller `behind` i forhold til `main` (API-sammenligning i gitless tilstand, `merge-base --is-ancestor` i git-tilstand) og kræver HEAD == den publicerede tags commit; `candidate_freeze_check._version_tag_owner` accepterer et tag på kandidaten som post-promotion. D5 kræver derfor **ingen kodeændring**, kun at runbooks og HANDOFF §4 siger, hvor tagget sættes.

**D6. Stage B og updater-evidens er uændret.** De binder til publicerede bytes (`SHA256SUMS.txt`) og til den kørende appliance, ikke til en SHA på `main`. D5 gør, at de bytes er kandidatens.

**D7. Fingerprintet står i kvittering og verdikt.** `candidate.release_fingerprint` tilføjes i freeze-kvitteringen; `pinned_release_fingerprints` tilføjes i systemgatens verdikt ved siden af `pinned_repositories`. Et manifest kan derved læses uden Git.

**D8. Dokumentet aktiverer ingenting.** Ingen runtime-flag, ingen default, ingen release, ingen ændring af `production_activation` følger af vedtagelsen. Den fysiske vej (Stage A → kampagne → Stage B) er uændret; kun hvilke `main`-bevægelser der ugyldiggør den, ændres.

## 3. Fravalgte alternativer

- **Behold eksakt SHA.** Ærligt og enkelt, men det er den direkte årsag til freeze-presset, og det har kostet mindst fire kandidater siden august. Prisen betales i Anders' rigtid.
- **Udeluk også `tests/**` og `scripts/**`.** Ville lade flere PR'er lande under freeze, men operatørerne og gaterne er præcis det, rigdagen afprøver; en ændret operatør er en anden rigdag. Afvist.
- **Flyt dokumentationen til et andet repo.** Løser problemet ved at fjerne dokumentationen fra det sted, koden læses. HANDOFF, ADR'er og runbooks hører til ved koden.
- **Kun lempe systemgatens træ-regel, ikke freezen.** Så kan evidens overleve, men `main` er stadig frosset for docs; halvdelen af gevinsten.
- **Tag på `main`s head som i dag og acceptér stempel-afvigelsen.** Artefakterne ville så ikke være byte-identiske med dem, Stage A kørte på (commit-stemplet afviger). D5 undgår spørgsmålet helt.

## 4. Konsekvenser

- En freeze blokerer kun det, der ændrer det riggen kører. HANDOFF-status, ADR'er, runbook-stirettelser (jf. Blok 0-fejlen 15/11) og issue-skabeloner kan lande under en kampagne.
- `main` kan være foran et release-tag med docs-only commits. Det er allerede tilstanden efter enhver promovering (HANDOFF 27/8: "main er foran, hvilket er korrekt").
- Et nyt artefakt at vedligeholde: eksklusionslisten. Den er lille, tracket, og beskyttet af kontrakttest 4.
- En docs-only PR kan ikke ændre en procedure, operatøren følger midt i en kampagne: de tre kampagne-runbooks er beskyttede dokumenter (D2), så en sådan ændring flytter fingerprintet og kræver re-anchor. Prisen er, at en ren stirettelse i `RIGDAG_SIMPEL.md` (som 15/11's) også kræver re-anchor; det er valgt med vilje — proceduren og evidensen følges ad. En glob-liste kan ikke se semantik; derfor er beskyttelsen en navngiven denylist og ikke en konvention.
- Qualifiers, der i dag sammenligner `^{tree}`, får én fælles funktion; mutationstest skal vise, at hver af de fire faktisk kalder den (AST-sporbarhed beviser navne, ikke semantik — HANDOFF §8).

## 5. Kontrakttests (røde før implementeringen, grønne efter)

1. `release_fingerprint(sha)` er uændret af en commit, der kun rører stier i dokumentationsklassen, og ændret af en ét-bytes ændring i hver af: `worker/`, `backend/`, `android/`, `desktop/`, `scripts/`, `tests/`, `deploy/`, `.github/workflows/`, `VERSION`, en rod-`.cmd` — og af en omdøbning af en kodefil. *(`tests/workflow_release_fingerprint.py`, #2411)*
2. `verify_receipt()` accepterer, at `origin/main` er flyttet fra ankeret med docs-only commits (D3), og afviser (a) en flytning, der rører en ikke-udelukket sti, navngivet, (b) en flytning, der rører et beskyttet dokument, (c) et omskrevet `main`, hvis historie ikke holder ankeret, (d) en kandidat, der ikke længere indeholder ankeret, (e) en kvittering uden eller med forfalsket fingerprint. *(`tests/workflow_candidate_freeze.py`, slice 2)*
3. Systemgaten accepterer evidens på en forfader med samme fingerprint og **forskelligt** træ, og afviser evidens på en forfader med forskelligt fingerprint; ukendt commit = ikke-ækvivalent; ubrugelig eksklusionsliste = autoritetsfejl. *(`tests/support/kaliv_system_release_gate_contract.py` via `workflow_candidate_gate.py`, slice 2)*
4. En eksklusionsliste, der nævner et beskyttet præfiks (D2), afvises ved indlæsning; et beskyttet dokument indgår i fingerprintet, selv om `*.md` står på listen (en ét-bytes ændring i `RIGDAG_SIMPEL.md` ændrer fingerprintet, en ét-bytes ændring i `HANDOFF.md` gør ikke); præfikser og beskyttede dokumenter pinnes ordret. *(#2411)*
5. `freeze_check.py` accepterer et tag, der peger på den frosne kandidat, mens `main` er foran (`behind`-status / ancestor) — *dækket af den eksisterende `tests/workflow_freeze_check.py`, jf. D5-præciseringen.*
6. Fingerprintet beregnes fra Git-objekterne: et snavset arbejdstræ ændrer ikke resultatet for en given SHA (D1). *(#2411)*
7. Mutation: fjernes fingerprint-sammenligningen i D3 eller D4 i kilden, bliver mindst én test rød. *Målt i slice 1 og 2: 10/10 i biblioteket, 6/6 i `candidate_freeze_check`, 2/2 i gaten — sweepene står i PR-beskrivelserne, ikke i CI.*

## 6. Implementering (efter vedtagelse)

1. Land dette dokument alene (#2410).
2. Slice 1 (#2411): `scripts/release_fingerprint.py` + `release_fingerprint_exclusions.txt` + kontrakttest 1, 4, 6, D4 (D1, D2, D7-bibliotek).
3. Slice 2 (stacked på #2411): `candidate_freeze_check.py` (D3, D7 i kvitteringen), `kaliv_system_release_gate.py` (D4, D7 i verdiktet), kontrakttest 2 og 3, runbook-noter i `RIGDAG_SIMPEL.md`, `STAGED_PHYSICAL_PROMOTION.md` og HANDOFF §9.
4. Første anvendelse: 2.0.21-æraen. 2.0.20-kampagnen kører færdig under den nuværende regel; en kvittering fra før slice 2 afvises med besked om re-freeze, så ingen gammel kvittering læses under den nye regel uden at nogen opdager det.

## 7. Valg truffet ved vedtagelsen

Anders fik tre spørgsmål 16/11 og vedtog udkastet med dets anbefalinger ("Kør", kl. 14:14 CET), efter at ChatGPT i sit review af rev. 1 havde gjort Q1 til en forudsætning for vedtagelse.

- **Q1 — Runbooks, operatøren læser under en kampagne.** `RIGDAG_SIMPEL.md`, `STAGED_PHYSICAL_PROMOTION.md` og `STAGE_B_UPDATER_EVIDENCE.md` er **beskyttede dokumenter** (D2): de indgår i fingerprintet, og en procedureændring kræver ny freeze. Beskyttelsen er en denylist i koden, ikke en konvention — ChatGPTs krav.
- **Q2 — Generatorernes output.** `CURRENT_STATE.md`, `ACTIVATION_READINESS.md` og `ROUTE_INVENTORY.md` er ligeledes beskyttede dokumenter. Udkastets anbefaling var at lade dem blive i dokumentationsklassen; ved vedtagelsen er de taget med, fordi operatører (`T-023`, readiness-regenerering) læser dem, og fordi det ikke koster noget: de kan kun ændre sig sammen med kode.
- **Q3 — Første anvendelse.** 2.0.21-æraen. 2.0.20-kampagnen kører færdig under den nuværende regel.
- **HANDOFF.md** forbliver i dokumentationsklassen med begrundelsen i D2. ChatGPT bad om enten beskyttelse eller en eksplicit begrundelse; dette er begrundelsen.

## 8. Hvad dokumentet bevidst ikke gør

- Det ændrer ikke, hvad Stage A, kampagnen eller Stage B kræver af evidens.
- Det ændrer ikke ADR-SYS-001's gates eller release-scopes.
- Det tager ikke stilling til merge queue/rulesets (eget spor, efter V1-tagget) eller til CI-tiering.
- Det ændrer ingen kode. Scripts, gate og runbooks følger i egne PR'er efter afsnit 6.
