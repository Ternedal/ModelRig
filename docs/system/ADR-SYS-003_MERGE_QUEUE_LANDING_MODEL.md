# ADR-SYS-003: Landing gennem merge queue — det testede er det landede

**Status:** UDKAST rev. 1, skrevet af Claude 18-11-2026 kl. 21:30 CET efter Anders' "Kør" på anbefalingerne i #2415 (1 script, 2 ADR, 3 Stage B i køen, 4 ChatGPT-status senere). Anders disponerer dokumentet og dets PR alene og kan rette ethvert valg i afsnit 7 med én kommentar. **Ingen ændring af `main`s beskyttelse før V1-tagget**; workflow-siden (afsnit 6, trin 1) må lande før, fordi den er inert uden en kø.
**Serie:** tredje dokument i SYS-serien (efter ADR-SYS-001 og ADR-SYS-002).
**Stopreglen (A4-005):** dokumentet lander først; kontrakttestene i afsnit 5 skrives røde derefter. Ruleset-migrationen (trin 2–3) kører først den dag V1 er tagget og gate 10 er målt på den nuværende model.

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

**D1 — Landingsmodellen for `main` er merge queue på en ruleset.** Klassisk branch protection afløses af én aktiv branch-ruleset på `main` med reglerne `pull_request` (review-tråde løst), `required_status_checks` (samme 14 navne, bundet til Actions-app-id `15368`), `merge_queue`, `non_fast_forward`, `deletion`, og **ingen bypass-actors**. Rulesetet er versioneret som JSON i repoet (`deploy/repository-authority/main-ruleset.json`) og anvendes af et script, aldrig håndskrevet i UI'et.

**D2 — Up-to-date-kravet erstattes af køen, og gate 10 ved det.** `strict_required_status_checks_policy` sættes til `false`. `scripts/repository_authority.py` ændres, så en aktiv `merge_queue`-regel på `main` opfylder det, *strict* i dag opfylder: advarslen "required status checks do not require an up-to-date branch" udgår, når `merge_queue` er til stede, og **fejler**, når hverken *strict* eller `merge_queue` er til stede. Uden `merge_queue` er evaluatoren uændret, så gate 10's dom på den nuværende model ikke flytter sig før migrationen.

**D3 — Stage B kører i køen, ikke efter landingen.** `exact-head-qualification.yml` får `merge_group:`-triggeren, og Stage B-kæden kører på merge-group-commit'en med `github.sha` som exact head. Docs-only-reglen (ADR-SYS-002 D1 via `release-class`, #2422) gælder også dér: en kø-commit, hvis merge-base..head er dokumentationsklassen, springer Stage B over. Udkast-reglen (#2413) er irrelevant i køen; kun ikke-drafts kan stå i den.

**D4 — Exact head i kø-kontekst er `github.sha`, aldrig `pull_request.head.sha`.** Alle workflows, der i dag læser `github.event.pull_request.head.sha`, får en fælles udledning: `HEAD_SHA = github.event.pull_request.head.sha || github.sha`, og *base* = `github.event.merge_group.base_sha` henholdsvis `github.event.pull_request.base.sha`. Evidens, freeze-kvitteringer og `release-class` følger den regel. Det er *den* ændring, der bærer hele ADR'en; afsnit 5 tester den.

**D5 — Køen har én kandidat ad gangen under en kampagne.** `merge_method: merge` (aldrig squash: det testede commit skal stå i historikken), `max_entries_to_build: 1`, `min_entries_to_merge: 1`, `grouping_strategy: ALLGREEN`. Hastighed er ikke målet; at det testede lander, er.

**D6 — ChatGPT-ACCEPT bliver en required status i et senere trin, ikke nu.** Indtil da gælder HANDOFF's regel: ingen PR sættes i køen uden SHA-scoped ACCEPT i tråden, og det er Anders (eller den session, han har givet landing til), der sætter den i køen. Kommentar-parsing i et landingsscript udgår; `gh pr merge --auto` (eller UI'ets "Merge when ready") er landingshandlingen.

**D7 — Freeze-vinduet omdefineres.** En freeze under en kampagne betyder: *intet uden for dokumentationsklassen i køen*, håndhævet af `release-class` + en `KALIV_FREEZE`-markør, som køens kvalifikation læser (afsnit 6, trin 3). `main` behøver ikke stå stille; evidensen overlever docs-flytninger (ADR-SYS-002 D3).

## 3. Fravalgte alternativer

- **Beholde klassisk protection og bare slå *strict* fra.** Så lander en merge-commit, ingen CI har set, mod en `main` der kan have flyttet sig siden PR'en blev testet. Det er præcis det hul, exact-head-disciplinen findes for at lukke.
- **Et eget landingsscript, der serialiserer (lås i #2275 + rebase + vent + merge).** Det er det, der er kørt manuelt 17–18/11, og det kræver den menneskelige timing, køen fjerner. Scriptet skal også have skrive-token til `main`, hvilket sessionerne bevidst ikke har.
- **Squash i køen.** Giver pænere historik, men det landede commit er så aldrig det testede, og `release_fingerprint equivalent` bliver den eneste bro. Merge-commit holder det testede head i historikken, og ADR-SYS-002 gør merge-committen ækvivalent.
- **`merge_group:` kun på de billige workflows, Stage B kun på `main`-push.** Billigere, men så opdages en rød Stage B *efter* landingen, og `main` er rød, til nogen reverter. Det er den model, projektet kom fra.

## 4. Konsekvenser

- **Positivt:** ingen rekvalifikation fordi en anden landede; det testede commit er det landede; landing uden menneskelig timing; CodeQL-retarget-fælden forsvinder (køen tager kun PR'er mod `main`); freeze bliver et indholdskrav, ikke et stilstandskrav.
- **Pris:** hver kø-kandidat koster sin egen fulde kvalifikation (~1,5 t required, ~3,5 t med Stage B for kode) — serielt. Med 3–6 kode-landinger om dagen er køen flaskehalsen; det er *villet* under en kampagne (D5) og kan løsnes (`max_entries_to_build`) efter V1.
- **Gate 10 ændrer definition** (D2). Det kræver, at ADR'en er vedtaget og evaluatoren ændret *før* rulesetet aktiveres, ellers er gate 10 rød i mellemtiden.
- **Alle sessioner skal kunne skelne `pull_request`- og `merge_group`-kontekst** i workflows (D4). Det er en engangsomkostning med test (afsnit 5).
- **`verify-repository-authority.ps1` på søsterrepoerne** ændres ikke; de bliver på klassisk model, til de får egen beslutning.

## 5. Kontrakttests (røde før implementeringen, grønne efter)

1. `tests/workflow_repository_authority.py`: ruleset-fixture med `merge_queue` og `strict=false` → PASS uden advarsel; fixture med hverken *strict* eller `merge_queue` → FAIL (ikke advarsel); fixture med `merge_queue` men `bypass_actors` → FAIL; klassisk fixture uændret → samme dom som i dag (regression).
2. `tests/workflow_exact_head_concurrency.py`: `exact-head-qualification.yml` har `merge_group:`; ingen `github.event.pull_request.head.sha` uden `|| github.sha`-fallback; concurrency-gruppen skelner `merge_group` fra `pull_request`, så en kø-kørsel ikke cancellerer en PR-kørsel på samme SHA og omvendt.
3. `tests/workflow_test_coverage.py`: hver workflow, der producerer et navn i `REQUIRED_STATUS_CHECKS`, har `merge_group:` (ellers står køen stille — fail-closed i den forkerte retning).
4. `tests/workflow_release_fingerprint.py`: `release_class.sh` tager base fra `merge_group.base_sha`, når den findes; fixture-test med en kø-lignende merge-commit (to forældre) klassificerer merge-base..head korrekt.
5. `deploy/repository-authority/main-ruleset.json` valideres af `repository_authority.py` offline → PASS; en mutation, der fjerner `deletion`-reglen → FAIL.
6. Mutationssweep på 1–5 dokumenteres i PR'en (HANDOFF §8-standard).

## 6. Implementering (efter vedtagelse)

**Trin 1 — workflow-siden (må lande før V1-tag; inert uden kø):** `merge_group:` på `ci.yml`, `exact-head-qualification.yml`, `codeql.yml`, `agent3-diagnostics.yml`, `agent3-full-diagnostics.yml`, `agent3-memory-*-windows.yml`, `agent4-*-harness.yml` (for `offline-harness`/android-varianter), `bodyrig-*` (hvis de producerer required navne), `_tests.yml` (via `workflow_call` arver den kalderen). Fælles `HEAD_SHA`/`BASE_SHA`-udledning (D4). `release_class.sh` læser `MERGE_GROUP_BASE_SHA`. Kontrakttest 2–4.

**Trin 2 — gate 10 (må lande før V1-tag; dom uændret uden `merge_queue`):** `repository_authority.py` D2 + kontrakttest 1 og 5. `configure-repository-authority-ruleset.ps1` (anvender JSON'en via REST, nægter hvis klassisk protection stadig findes, printer diff mod live). Dry-run i Windows-CI.

**Trin 3 — migration (den dag V1 er tagget; Anders, ~1 time):** (a) `verify-repository-authority.ps1` → PASS på klassisk model og gem rapporten; (b) `configure-repository-authority-ruleset.ps1 -Apply`; (c) fjern klassisk protection (UI eller script); (d) `verify` → PASS i ruleset-tilstand uden advarsler; (e) første kø-landing er en docs-only PR (billig, beviser kæden); (f) HANDOFF §3/§4/§9 omskrives: landingsscriptet udgår, "Kør merge <sha>" bliver "sæt i kø", freeze = D7.

**Trin 4 (senere):** ChatGPT-ACCEPT som check-run (D6).

## 7. Valg truffet ved vedtagelsen

| # | Spørgsmål | Valg | Hvem |
|---|---|---|---|
| Q1 | Migrationsvej | Script + versioneret JSON | Claude-anbefaling; Anders' "Kør" 18/11 21:24 |
| Q2 | *strict* under køen | Evaluatoren ændres (D2), ikke bare advarsel accepteret | samme |
| Q3 | Stage B i køen | Ja (D3) | samme |
| Q4 | ChatGPT-ACCEPT som status | Senere trin (D6) | samme |
| Q5 | Kø-parametre | merge-commit, 1 ad gangen, ALLGREEN (D5) | Claude-forslag; kan rettes |
| Q6 | Hvornår trin 3 må køre | Den dag V1 er tagget — ikke før | fastholdt fra #2415 |

## 8. Hvad dokumentet bevidst ikke gør

- Det ændrer ikke, *hvad* der kvalificerer en release (gates 1–10, ADR-SYS-001) eller hvad evidens binder til (ADR-SYS-002). Det ændrer kun, hvordan et kvalificeret commit bliver `main`.
- Det rører ikke søsterrepoernes beskyttelse.
- Det lover ikke kortere Stage B. Kæden er stadig ~3,5 t for kode; køen sørger bare for, at den betales én gang pr. landing.
- Det fjerner ikke menneskelig accept: ACCEPT i tråden er stadig kravet for at sætte en PR i køen (D6), og kun Anders eller den session, han har givet landing til, gør det.
