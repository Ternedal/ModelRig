# ADR-SYS-003: Landing gennem merge queue — det testede er det landede

**Status:** UDKAST rev. 3, 19-11-2026 kl. 00:10 CET. Rev. 3 indarbejder Codex' to fund på rev. 2: D3 gør Stage B-fuldførelse til et *required* kø-check (`stage-b-verdict`), og trin 3's migrationsrækkefølge stemmer nu med scriptets faktiske adfærd (rulesetet skrives og verificeres, *før* klassisk protection fjernes). Rev. 2, 18-11 kl. 23:15: Rev. 1 skrevet af Claude kl. 21:30 efter Anders' "Kør" på anbefalingerne i #2415 (1 script, 2 ADR, 3 Stage B i køen, 4 ChatGPT-status senere); rev. 2 indarbejder ChatGPTs beslutningsreview (betinget ACCEPT af D1–D6, HOLD på D7): D7 er nu eksplicit en *definition* uden håndhævelse i denne ADR, og stopreglen siger entydigt, at kun trin 3 venter på V1-tagget. Anders disponerer dokumentet og dets PR alene og kan rette ethvert valg i afsnit 7 med én kommentar.
**Serie:** tredje dokument i SYS-serien (efter ADR-SYS-001 og ADR-SYS-002).
**Stopreglen (A4-005):** dokumentet lander først; kontrakttestene i afsnit 5 skrives røde derefter. **Trin 1 og 2 (afsnit 6) må lande før V1-tagget** — de er inerte uden en kø, og gate 10's dom på den klassiske model er uændret af dem. **Kun trin 3 (aktivering af rulesetet og fjernelse af klassisk protection) venter på V1-tagget**, fordi gate 10 skal være målt på den nuværende model, før modellen skiftes.

---

## 1. Kontekst

`main` lander i dag PR for PR mod en klassisk branch protection: PR påkrævet, alle review-tråde løst, 14 required checks (`scripts/repository_authority.py`, `REQUIRED_STATUS_CHECKS`), *strict* (PR'en skal indeholde `main`s tip), ingen admin-bypass. Gate 10 (`repository_authority`) består på den model og accepterer allerede en ækvivalent ruleset-model, hvor manglende *strict* kun er en advarsel.

Det, der er målt 17–18/11 under landingen af ADR-SYS-002-kæden og de to efterfølgende PR'er:

1. **Strict mode gør hver landing til en rekvalifikation af alle andre.** #2422 blev `behind` tre gange på én dag (efter #2420, #2425, #2421/#2426) og kørte sin Stage B-kæde (~3,5 t) fire gange for samme indhold. #2421 to gange. Prisen er runner-timer og — værre — at det *testede* head og det *landede* head skilles ad hver gang nogen lander før én.
2. **`main` kan ikke fast-forwardes**, heller ikke af admin (GH006). Det landede er derfor altid en merge-commit, GitHub bygger i det øjeblik der trykkes merge — en commit ingen CI har set. Træet er identisk med PR-headet, når PR'en indeholder `main`s tip (strict), og det er netop derfor *strict* ikke bare kan slås fra i den klassiske model.
3. **Landingen kræver en menneskelig finger på knappen i præcis det vindue, hvor alt er grønt.** Med tre sessioner og ~3,5 t kvalifikation er det vindue ofte lukket igen, før nogen når det. 18/11 landede én PR med Stage B-slices stadig i gang, fordi vinduet ellers var væk.
4. CodeQL's to checks findes kun på PR'er med base `main`, så en stakket PR kan ikke blive `clean` uden retarget — endnu et manuelt trin med en fælde (Merge-knappen på en stakket PR merger ind i base-*branchen*).

Merge queue er GitHub's svar på 1–3: køen serialiserer kandidaterne, bygger selv merge-commit'en mod den *aktuelle* `main`, kører de required checks på præcis den commit (`merge_group`-eventet), og lander den uden menneskelig timing. Det er en stærkere exact-head-garanti end i dag: **det testede er det landede**, byte for byte, og ingen anden landing kan skille dem ad.

Køen kræver en ruleset (ikke klassisk protection), og den rapporterer kun checks fra workflows med en `merge_group:`-trigger. Ingen workflow i repoet har den i dag.

## 2. Beslutninger

**D1 — Landingsmodellen for `main` er merge queue på en ruleset.** Klassisk branch protection afløses af én aktiv branch-ruleset på `main` med reglerne `pull_request` (review-tråde løst), `required_status_checks` (de 14 klassiske navne **plus `stage-b-verdict`**, D3; alle bundet til Actions-app-id `15368`), `merge_queue`, `non_fast_forward`, `deletion`, og **ingen bypass-actors**. Rulesetet er versioneret som JSON i repoet (`deploy/repository-authority/main-ruleset.json`) og anvendes af et script, aldrig håndskrevet i UI'et.

**D2 — Up-to-date-kravet erstattes af køen, og gate 10 ved det.** `strict_required_status_checks_policy` sættes til `false`. `scripts/repository_authority.py` ændres, så en aktiv `merge_queue`-regel på `main` opfylder det, *strict* i dag opfylder: advarslen "required status checks do not require an up-to-date branch" udgår, når `merge_queue` er til stede, og **fejler**, når hverken *strict* eller `merge_queue` er til stede. Uden `merge_queue` er evaluatoren uændret, så gate 10's dom på den nuværende model ikke flytter sig før migrationen.

**D3 — Stage B kører i køen, og køen venter på den.** `exact-head-qualification.yml` får `merge_group:`-triggeren, og Stage B-kæden kører på merge-group-commit'en med `github.sha` som exact head. Docs-only-reglen (ADR-SYS-002 D1 via `release-class`, #2422) gælder også dér: en kø-commit, hvis merge-base..head er dokumentationsklassen, springer Stage B over. Udkast-reglen (#2413) er irrelevant i køen; kun ikke-drafts kan stå i den. **Fordi de enkelte Stage B-jobs ikke er required checks (navnene varierer pr. shard), indføres ét aggregat-check, `stage-b-verdict`,** der afhænger af `release-class` og `stage-b-slices` og kun består, når Stage B bestod, eller blev sprunget over af en grund politikken tillader (docs-only; draft-PR). Enhver anden overspringelse, fejl eller annullering fælder det. I kø-tilstand er det required (`QUEUE_REQUIRED_STATUS_CHECKS` = de klassiske 14 + `stage-b-verdict` i `scripts/repository_authority.py`); den klassiske model i dag lister det ikke, så gate 10's nuværende dom er uændret. (Codex P1 på rev. 2: uden dette ville køen kunne lande, mens Stage B stadig kørte eller var fejlet.)

**D4 — Exact head i kø-kontekst er `github.sha`, aldrig `pull_request.head.sha`.** Alle workflows, der i dag læser `github.event.pull_request.head.sha`, får en fælles udledning: `HEAD_SHA = github.event.pull_request.head.sha || github.sha`, og *base* = `github.event.merge_group.base_sha` henholdsvis `github.event.pull_request.base.sha`. Evidens, freeze-kvitteringer og `release-class` følger den regel. Det er *den* ændring, der bærer hele ADR'en; afsnit 5 tester den.

**D5 — Køen har én kandidat ad gangen under en kampagne.** `merge_method: merge` (aldrig squash: det testede commit skal stå i historikken), `max_entries_to_build: 1`, `min_entries_to_merge: 1`, `grouping_strategy: ALLGREEN`. Hastighed er ikke målet; at det testede lander, er.

**D6 — ChatGPT-ACCEPT bliver en required status i et senere trin, ikke nu.** Indtil da gælder HANDOFF's regel: ingen PR sættes i køen uden SHA-scoped ACCEPT i tråden, og det er Anders (eller den session, han har givet landing til), der sætter den i køen. Kommentar-parsing i et landingsscript udgår; `gh pr merge --auto` (eller UI'ets "Merge when ready") er landingshandlingen.

**D7 — Freeze-vinduet omdefineres.** *(Håndhævelsen er foreslået som trin 4 i #2436 — status opdateres her, når den lander: repository-variablen `KALIV_FREEZE` = `1`, ejer Anders, håndhævet af `.github/workflows/freeze-guard.yml`, der i rulesetet er required workflow pinnet til `main` og dømmer fra **basens** checkout med basens `scripts/freeze_guard.sh` og classifier — kandidaten kan ikke redigere sin egen dommer (ChatGPT P1 på #2436). Kontrakttest 7 i `tests/workflow_freeze_guard.py` inkl. en kandidat, der skriver classifier og guard om til `exit 0` og alligevel afvises. Gate 10 kræver i kø-tilstand, at rulesetet pinner den workflow. Teksten herunder er rev. 3's og beskriver kravene.)* En freeze under en kampagne *betyder* fra nu af: intet uden for dokumentationsklassen (ADR-SYS-002 D1) sættes i køen. `main` behøver ikke stå stille; evidensen overlever docs-flytninger (ADR-SYS-002 D3). **Indtil en separat implementerings-PR lander, håndhæves D7 som i dag:** ved aftale på #2275, ved at ingen PR sættes i køen uden SHA-scoped ACCEPT (D6), og ved at `release-class` allerede rapporterer `docs_only` på hver kandidat, så et brud er synligt i kørslen. Den PR skal levere: en freeze-markør med én ejer (Anders) og ét sted (en fil i repoet eller en repository-variabel — valget er PR'ens, ikke denne ADR's), et `release-class`-trin der fejler en kø-kandidat med `docs_only=false`, når markøren er sat, negative tests for begge veje (markør sat + kode → fejl; markør sat + docs → kør; markør ikke sat → uændret) og en HANDOFF-opdatering. Denne ADR lover ikke den garanti, før den PR er landet.

## 3. Fravalgte alternativer

- **Beholde klassisk protection og bare slå *strict* fra.** Så lander en merge-commit, ingen CI har set, mod en `main` der kan have flyttet sig siden PR'en blev testet. Det er præcis det hul, exact-head-disciplinen findes for at lukke.
- **Et eget landingsscript, der serialiserer (lås i #2275 + rebase + vent + merge).** Det er det, der er kørt manuelt 17–18/11, og det kræver den menneskelige timing, køen fjerner. Scriptet skal også have skrive-token til `main`, hvilket sessionerne bevidst ikke har.
- **Squash i køen.** Giver pænere historik, men det landede commit er så aldrig det testede, og `release_fingerprint equivalent` bliver den eneste bro. Merge-commit holder det testede head i historikken, og ADR-SYS-002 gør merge-committen ækvivalent.
- **`merge_group:` kun på de billige workflows, Stage B kun på `main`-push.** Billigere, men så opdages en rød Stage B *efter* landingen, og `main` er rød, til nogen reverter. Det er den model, projektet kom fra.

## 4. Konsekvenser

- **Positivt:** ingen rekvalifikation fordi en anden landede; det testede commit er det landede; landing uden menneskelig timing; CodeQL-retarget-fælden forsvinder (køen tager kun PR'er mod `main`); freeze bliver et indholdskrav, ikke et stilstandskrav (D7 — defineret her, håndhævet af en senere PR).
- **Pris:** hver kø-kandidat koster sin egen fulde kvalifikation (~1,5 t required, ~3,5 t med Stage B for kode) — serielt. Med 3–6 kode-landinger om dagen er køen flaskehalsen; det er *villet* under en kampagne (D5) og kan løsnes (`max_entries_to_build`) efter V1.
- **Gate 10 ændrer definition** (D2). Det kræver, at ADR'en er vedtaget og evaluatoren ændret *før* rulesetet aktiveres, ellers er gate 10 rød i mellemtiden.
- **Alle sessioner skal kunne skelne `pull_request`- og `merge_group`-kontekst** i workflows (D4). Det er en engangsomkostning med test (afsnit 5).
- **`verify-repository-authority.ps1` på søsterrepoerne** ændres ikke; de bliver på klassisk model, til de får egen beslutning.

## 5. Kontrakttests (røde før implementeringen, grønne efter)

1. `tests/workflow_repository_authority.py`: ruleset-fixture med `merge_queue` og `strict=false` → PASS uden advarsel; fixture med hverken *strict* eller `merge_queue` → FAIL (ikke advarsel); fixture med `merge_queue` men `bypass_actors` → FAIL; **fixture med `merge_queue` uden `stage-b-verdict` → FAIL med navnet**; klassisk fixture uændret → samme dom som i dag (regression).
2. `tests/workflow_exact_head_concurrency.py`: `exact-head-qualification.yml` har `merge_group:`; ingen `github.event.pull_request.head.sha` uden `|| github.sha`-fallback; concurrency-gruppen skelner `merge_group` fra `pull_request`, så en kø-kørsel ikke cancellerer en PR-kørsel på samme SHA og omvendt; **`stage-b-verdict` afhænger af `release-class` og `stage-b-slices`, bruger `!cancelled()`, tillader kun docs-only- og draft-skips og fælder alt andet.**
3. `tests/workflow_test_coverage.py`: hver workflow, der producerer et navn i `REQUIRED_STATUS_CHECKS`, har `merge_group:` (ellers står køen stille — fail-closed i den forkerte retning).
4. `tests/workflow_release_fingerprint.py`: `release_class.sh` tager base fra `merge_group.base_sha`, når den findes; fixture-test med en kø-lignende merge-commit (to forældre) klassificerer merge-base..head korrekt.
5. `deploy/repository-authority/main-ruleset.json` valideres af `repository_authority.py` offline → PASS; en mutation, der fjerner `deletion`-reglen → FAIL.
6. Mutationssweep på 1–5 dokumenteres i PR'en (HANDOFF §8-standard).
7. *(D7, separat PR — ikke en forudsætning for trin 1–3):* markør sat + kode-kandidat → kø-kvalifikationen fejler; markør sat + docs-only → kører; markør ikke sat → uændret adfærd.

## 6. Implementering (efter vedtagelse)

**Trin 1 — workflow-siden (må lande før V1-tag; inert uden kø):** `merge_group:` på `ci.yml`, `exact-head-qualification.yml`, `codeql.yml`, `agent3-diagnostics.yml`, `agent3-full-diagnostics.yml`, `agent3-memory-*-windows.yml`, `agent4-*-harness.yml` (for `offline-harness`/android-varianter), `bodyrig-*` (hvis de producerer required navne), `_tests.yml` (via `workflow_call` arver den kalderen). Fælles `HEAD_SHA`/`BASE_SHA`-udledning (D4). `release_class.sh` læser `MERGE_GROUP_BASE_SHA`. Kontrakttest 2–4.

**Trin 2 — gate 10 (må lande før V1-tag; dom uændret uden `merge_queue`):** `repository_authority.py` D2 + D3's `QUEUE_REQUIRED_STATUS_CHECKS`, `stage-b-verdict`-jobbet, kontrakttest 1, 2 og 5. `configure-repository-authority-ruleset.ps1`: evaluerer JSON'en offline med checkout'ets evaluator og sender intet, der ikke ville bestå gate 10; nægter, hvis *andre* aktive branch-rulesets findes; **tillader at klassisk protection stadig findes**, og fjerner den kun med `-RemoveClassicProtection` og kun *efter* at rulesetet er skrevet — et vindue med begge er sikkert, et vindue med ingen er det ikke. Dry-run som standard.

**Trin 3 — migration (den dag V1 er tagget; Anders, ~1 time):** (a) `verify-repository-authority.ps1` → PASS på klassisk model og gem rapporten; (b) `configure-repository-authority-ruleset.ps1` (dry-run) → læs payload; (c) `configure-repository-authority-ruleset.ps1 -Apply` → rulesetet skrives, klassisk protection består stadig, verifieren kører (PASS i ruleset-tilstand med `strict` fra den klassiske model stadig aktiv); (d) `configure-repository-authority-ruleset.ps1 -Apply -RemoveClassicProtection` → klassisk protection fjernes, verifieren kører igen → PASS i ruleset-tilstand uden advarsler; (e) første kø-landing er en docs-only PR (billig, beviser kæden incl. `stage-b-verdict`'s docs-only-gren); (f) første kode-landing i køen beviser, at alle 15 required contexts materialiserer på merge-group-SHA'en (ChatGPT's residual på #2428); (g) HANDOFF §3/§4/§9 omskrives: landingsscriptet udgår, "Kør merge <sha>" bliver "sæt i kø", freeze = D7. (Codex P2 på rev. 2: rev. 2's trin 2 sagde "nægter hvis klassisk protection findes", hvilket ville have stoppet migrationen før (c); scriptet gør det modsatte, og teksten følger nu scriptet.)

**Trin 4 (senere, hver sin PR):** D7's freeze-markør og kø-guard med kontrakttest 7; ChatGPT-ACCEPT som check-run (D6).

## 7. Valg truffet ved vedtagelsen

| # | Spørgsmål | Valg | Hvem |
|---|---|---|---|
| Q1 | Migrationsvej | Script + versioneret JSON | Claude-anbefaling; Anders' "Kør" 18/11 21:24 |
| Q2 | *strict* under køen | Evaluatoren ændres (D2), ikke bare advarsel accepteret | samme |
| Q3 | Stage B i køen | Ja (D3) | samme |
| Q4 | ChatGPT-ACCEPT som status | Senere trin (D6) | samme |
| Q5 | Kø-parametre | merge-commit, 1 ad gangen, ALLGREEN (D5) | Claude-forslag; kan rettes |
| Q6 | Hvornår trin 3 må køre | Den dag V1 er tagget — ikke før; trin 1–2 må lande før | fastholdt fra #2415, præciseret i rev. 2 |
| Q8 | Venter køen på Stage B? | Ja: `stage-b-verdict` er required i kø-tilstand (D3) | Codex P1 på rev. 2; Claude rev. 3 |
| Q7 | D7's håndhævelse | Defineret her, leveret i en separat PR (trin 4) med egen ejer og negative tests; indtil da gælder dagens aftale-baserede freeze | ChatGPT-review 18/11; Claude rev. 2 |

## 8. Hvad dokumentet bevidst ikke gør

- Det ændrer ikke, *hvad* der kvalificerer en release (gates 1–10, ADR-SYS-001) eller hvad evidens binder til (ADR-SYS-002). Det ændrer kun, hvordan et kvalificeret commit bliver `main`.
- Det rører ikke søsterrepoernes beskyttelse.
- Det lover ikke, at en freeze er maskinelt håndhævet i køen, før D7's implementerings-PR er landet (Q7).
- Det lover ikke kortere Stage B. Kæden er stadig ~3,5 t for kode; køen sørger bare for, at den betales én gang pr. landing.
- Det fjerner ikke menneskelig accept: ACCEPT i tråden er stadig kravet for at sætte en PR i køen (D6), og kun Anders eller den session, han har givet landing til, gør det.
