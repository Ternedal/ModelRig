# ADR-SYS-002: Evidens og freeze bundet til et release-fingerprint, ikke til den eksakte SHA

**Status:** FORESLÅET — udkast. Ikke vedtaget. Anders disponerer dokumentet og dets PR alene.
**Udkast:** skrevet af Claude 16-11-2026 efter Anders' "Kør" på fem procesforbedringer (#2275, kommentar 6915273202).
**Serie:** andet dokument i SYS-serien (efter ADR-SYS-001).
**Stopreglen (A4-005):** ingen kode før vedtagelse. Dette dokument lander først; kontrakttestene i afsnit 5 skrives røde derefter.

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

**D2. Dokumentationsklassen er en tracket liste, ikke en heuristik.** `release_fingerprint_exclusions.txt` i repo-roden, én glob pr. linje. Startindhold:

```
docs/**
*.md
.github/*.md
.github/ISSUE_TEMPLATE/**
LICENSE
```

Følgende præfikser kan **aldrig** udelukkes, og kontrakttest 4 håndhæver det: `worker/`, `backend/`, `android/`, `desktop/`, `vr/`, `renderers/`, `bodyrig/`, `scripts/`, `tests/`, `deploy/`, `tools/`, `contracts/`, `.github/workflows/`, `VERSION`, `*.cmd`, `*.ps1`. Operatører og tests er det, rigdagen afprøver; de er kode i denne forstand.

**D3. En freeze overlever docs-only landinger på `main`.** `verify_receipt()` ændres fra "`origin/main` == frosset anker" til: `origin/main` er ankeret **eller** en efterkommer af ankeret, hvor `git diff --name-only <anker>..<main>` udelukkende rammer stier i dokumentationsklassen. Kravet om at kandidaten indeholder ankeret bevares; kravet om at kandidaten indeholder det *aktuelle* `main` erstattes af fingerprint-lighed: `release_fingerprint(kandidat) == release_fingerprint(main)`. Kandidatens eget træ-rollup (`tree.sha256`) bevares som i dag — kandidatgrenen flytter sig ikke.

**D4. Evidens er gyldig for enhver commit med samme fingerprint i samme linje.** Systemgatens og qualifiers' regel "pin-SHA eller forfader med eksakt samme træ" bliver "pin-SHA eller forfader med samme release-fingerprint". Retningen bevares (evidens på en forfader af pinnen, aldrig omvendt). Reglen samles ét sted (`release_fingerprint.equivalent(evidence_sha, pinned_sha)`) og kaldes fra de fire qualifiers og gaten, så den ikke drifter.

**D5. Tagget peger på den frosne kandidat, ikke på `main`s head.** Når `main` er foran kandidaten med docs-only commits, sættes `vX.Y.Z` på kandidat-SHA'en. Så er de publicerede artefakter bygget af præcis den commit, Stage A kørte på — inklusive `commit_identity`-stemplet (`scripts/stamp_build_identity.py`), som ellers ville afvige. `main` indeholder tagget (kandidaten er forfader), så invarianten "tagget er på `main`" holder. `candidate_freeze_check._version_tag_owner` og `freeze_check.py` accepterer et tag på kandidaten som post-promotion, som i dag.

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
- En docs-only PR, der ændrer en **procedure**, en operatør følger (fx `RIGDAG_SIMPEL.md`), kan lande midt i en kampagne. Det er en reel risiko, som D2's liste ikke løser; se spørgsmål Q1.
- Qualifiers, der i dag sammenligner `^{tree}`, får én fælles funktion; mutationstest skal vise, at hver af de fire faktisk kalder den (AST-sporbarhed beviser navne, ikke semantik — HANDOFF §8).

## 5. Kontrakttests (røde før implementeringen, grønne efter)

1. `release_fingerprint(sha)` er uændret af en commit, der kun rører stier i dokumentationsklassen, og ændret af en ét-bytes ændring i hver af: `worker/`, `backend/`, `android/`, `desktop/`, `scripts/`, `tests/`, `deploy/`, `.github/workflows/`, `VERSION`, en rod-`.cmd`.
2. `verify_receipt()` accepterer, at `origin/main` er flyttet fra ankeret med docs-only commits (D3), og afviser både (a) en flytning, der rører en ikke-udelukket sti, og (b) en kandidat, der ikke længere indeholder ankeret.
3. Systemgaten accepterer evidens på en forfader med samme fingerprint og **forskelligt** træ, og afviser evidens på en forfader med forskelligt fingerprint, selv når kun én byte i `worker/` adskiller dem (D4). Samme for hver af de fire qualifiers.
4. En eksklusionsliste, der nævner et beskyttet præfiks (D2), afvises af `release_fingerprint.py` ved indlæsning, og en test, der lister præfikserne ordret, bliver rød, hvis listen i kilden forkortes.
5. `freeze_check.py` accepterer et tag, der peger på den frosne kandidat, mens `main` er foran med docs-only commits (D5), og afviser et tag på en commit, der ikke er kandidaten.
6. Fingerprintet beregnes fra Git-objekterne: et snavset arbejdstræ ændrer ikke resultatet for en given SHA (D1).
7. Mutation: fjernes fingerprint-sammenligningen i D3 eller D4 i kilden, bliver mindst én test rød; fjernes kaldet i én af de fire qualifiers, bliver dens test rød.

## 6. Implementering (efter vedtagelse)

1. Land dette dokument alene.
2. Kontrakttests 1–7 som røde tests (`tests/workflow_release_fingerprint.py`).
3. `scripts/release_fingerprint.py` + `release_fingerprint_exclusions.txt` (D1, D2, D7).
4. `candidate_freeze_check.py` og `freeze_check.py` (D3, D5).
5. `kaliv_system_release_gate.py` og de fire qualifiers (D4) gennem den fælles funktion.
6. `RIGDAG_SIMPEL.md` Blok 0, `STAGED_PHYSICAL_PROMOTION.md`, HANDOFF §4 og §9: freeze-reglen og tag-placeringen (D3, D5). `tests/workflow_staged_promotion_runbook.py` opdateres til den nye kontrakt.
7. Første anvendelse: tidligst 2.0.21-æraen. 2.0.20-kampagnen kører færdig under den nuværende regel.

## 7. Spørgsmål til vedtagelsen

- **Q1 — Runbooks, operatørerne læser under en kampagne.** `RIGDAG_SIMPEL.md`, `STAGED_PHYSICAL_PROMOTION.md` og `STAGE_B_UPDATER_EVIDENCE.md` er `.md` og falder i dokumentationsklassen. Anbefaling: **tag dem ud af klassen** (negativ glob i listen, `!RIGDAG_SIMPEL.md` osv.), så en procedureændring stadig kræver ny freeze. Prisen er, at en stirettelse som 15/11's kræver en re-anchor; gevinsten er, at proceduren og evidensen følges ad.
- **Q2 — Generatorernes output.** `CURRENT_STATE.md`, `ACTIVATION_READINESS.md` og `ROUTE_INVENTORY.md` er `.md`, men genereres fra kode og kan kun ændre sig sammen med den. Anbefaling: lad dem være i klassen; en ændring i dem uden kodeændring fælder allerede `workflow_current_state.py`.
- **Q3 — Første anvendelse.** 2.0.21 (anbefalet) eller først efter V1-tagget. 2.0.21 er den første æra, hvor gevinsten tæller; risikoen er, at D3–D5 landes i samme æra som V1-kampagnen.

## 8. Hvad dokumentet bevidst ikke gør

- Det ændrer ikke, hvad Stage A, kampagnen eller Stage B kræver af evidens.
- Det ændrer ikke ADR-SYS-001's gates eller release-scopes.
- Det tager ikke stilling til merge queue/rulesets (eget spor, efter V1-tagget) eller til CI-tiering.
- Det ændrer ingen kode. Scripts, gate og runbooks følger i egne PR'er efter afsnit 6.
