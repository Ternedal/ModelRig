# ADR-DC-001 — DevControl som isoleret, dvalende autoritetskæde for kontrolleret selvudvikling

**Truffet af Anders 05/08-2026. Status: besluttet.** Første ADR i DC-serien. Udarbejdet af Claude, grundet i målinger mod `main @ 11dcd7b0` og branchen `agent/devcontrol-foundation-v1 @ bad88eb1` (PR #338, draft, 412 commits, 215 filer), og godkendt uden ændringer.

---

## Den ubehagelige forudsætning, der skal siges først

Denne ADR skrives **efter** koden, ikke før. Det er en inversion af ADR-A4-005's stopregel, som er projektets hårdeste governance-invariant: arkitektur besluttes gennem en ADR, derefter bygges den — aldrig omvendt. DevControl er ~14.360 linjer fordelt på 194 filer i ti implementerede slices, uden et beslutningsdokument.

Det er ikke en anklage; det er en tilstand, der skal håndteres eksplicit, fordi alternativet er, at en fremtidig læser tror, stopreglen blev fulgt. To ærlige veje:

1. **Retro-ADR med eksplicit mærkat.** ADR'en vedtages som den beslutning, arbejdet *skulle* have haft, og bærer et dateret afsnit om, at den blev skrevet efter implementeringen. Prisen er, at ADR'en beskriver frem for at styre — dens beslutninger er allerede truffet i kode.
2. **ADR først, derefter genvurdering af koden mod den.** ADR'en vedtages på sine egne præmisser, og PR #338 efterprøves derefter *mod* ADR'en som en hvilken som helst anden implementering. Afvigelser bliver fund, ikke fakta.

**Anders valgte vej 2 den 05/08-2026.** ADR'en vedtages på sine egne præmisser og landes på `main` FØR koden, netop så efterprøvningen af PR #338 bliver reel frem for ceremoniel: afvigelser mellem branchen og denne ADR er fund, ikke fakta. Stopreglens betydning bevares dermed, selv om implementeringen tidsmæssigt kom først.

## Kontekst — målt, ikke antaget

- DevControl bor i `devcontrol/` med egen `pyproject.toml`, egen pakke `kaliv_dev_control`, egne tests (52 filer) og egne schemas (48 filer). Det er en **selvstændig enhed**, ikke en udvidelse af workeren.
- **Ingen kobling til produktet:** hverken `worker/`, `backend/`, `desktop/` eller `android/` importerer `kaliv_dev_control`. Det eneste berøringspunkt er `scripts/tier_a_bundle_inventory.py` — et inventarværktøj, ikke en runtime-sti.
- Formålet, som DevControls egen README erklærer: en **dvalende, fail-closed grundvold for kontrolleret selvudvikling** — en kæde, hvor præcis én opgave kan passere gennem reviewet kommandoautoritet, frisk signeret fysisk Windows-evidens, native Tier-A-indeslutning, deterministisk runtime-lukning, git-bevidst eksekveringsevidens, uafhængig semantisk godkendelse, autentificeret draft-PR-parathed, signeret publisher-intent, en tidsbegrænset engangsautorisation og til sidst **lokal** oprettelse af et kandidat-commit i et isoleret bart Git-repo.
- Kæden indeholder i dag **ingen** GitHub-credential, ingen netværks-skriveadapter, intet branch-push, ingen PR-skrivning, ingen reviewer-request, ingen ready-for-review, ingen merge, release, settings eller deployment-autoritet.

## Beslutning 1 — DevControl er en isoleret enhed, ikke en produktkomponent

DevControl leveres som selvstændig pakke under `devcontrol/` med egen dependency-grænse. Produktkoden (`worker/`, `backend/`, klienter) må **ikke** importere `kaliv_dev_control`, og DevControl må ikke importere produktets runtime-moduler ud over det, en eksplicit, versioneret kontrakt tillader. Grænsen håndhæves af en gate, ikke af konvention.

## Beslutning 2 — Menneskelig autoritet er terminal og kan ikke delegeres

Merge, push, release, PR-skrivning og aktivering forbliver **udelukkende** menneskelige handlinger. DevControl må producere forslag — kandidat-commits, patches, draft-PR-data — men ingen kæde, ingen autorisation og ingen fremtidig slice må give processen skriveadgang til det offentlige repo. Denne beslutning kan kun omgøres af en ny ADR, ikke af en slice.

## Beslutning 3 — Fail-closed på hvert autoritetslag

Hvert lag skal afvise ved tvivl frem for at fortsætte: fejlede probes forbliver repræsenterbare men kan ikke autorisere eksekvering; en lease udstedes kun mod gyldig, frisk, signeret evidens; hver offentlig kørsel kræver en frisk kvittering; timeout dræber hele Job Object'et og returnerer ikke-bestående evidens. Ingen sti må have en "fortsæt alligevel"-gren.

## Beslutning 4 — Fysisk evidens er en forudsætning, ikke en rapport

Eksekveringsautoritet kræver frisk, HMAC-SHA256-signeret fysisk Windows-evidens bundet til præcis opgave, katalog, toolchain, rig, workspace og autorisationskode, med adskilte collector- og approver-identiteter. Evidens fra en anden SHA, en anden rig eller en tidligere kørsel autoriserer intet. Det er samme princip som Stage A's SHA-binding, anvendt på selvudvikling.

## Beslutning 5 — Indeslutning er operativsystemets ansvar, ikke procesdisciplinens

Eksekvering sker i en deterministisk zero-capability AppContainer uden netværkskapabilitet, med positivliste-miljø, i et kill-on-close Job Object med proces- og hukommelsesgrænser, oprettet suspenderet og først derefter resumeret. Sikkerheden må ikke afhænge af, at den kørende kode opfører sig ordentligt.

## Beslutning 6 — Dvale er default og bevises

DevControl er dvalende: ingen mount, ingen route, intet flag tændt, ingen baggrundstråde, timers eller polling, og ingen import fra produktets runtime. Dvalen skal bevises af en gate på samme måde som Agent 4's dormant-gate — ikke hævdes i en README.

## Beslutning 7 — Aktiveringsport

Enhver udvidelse, der giver DevControl faktisk publikationsevne — netværks-skriveadapter, GitHub-credential, push, PR-skrivning — kræver **sin egen ADR** og en separat, eksplicit beslutning fra Anders. Grøn CI, bestået fysisk I0b og en komplet autoritetskæde er nødvendige, men aldrig tilstrækkelige.

## Beslutning 8 — Egen ADR-serie

DevControl er ikke Agent 4 og må ikke nummereres ind i A4-serien. Beslutninger føres som **ADR-DC-NNN** med samme indeksmodel: et komplet indeks i `devcontrol/DEVCONTROL_ARCHITECTURE_DECISIONS.md`, fuldtekster i `docs/devcontrol/`. ADR'er beskriver beslutninger, aldrig merge-status.

## Obligatoriske kontrakttests

1. Ingen produktmodul importerer `kaliv_dev_control` (AST-/importgraf-bevist).
2. Import af DevControl starter ingen tråde, timers, filer eller polling.
3. Autoritetskæden indeholder ingen netværks-skrivesti (kaldegraf-bevist mod en negativliste).
4. Evidens fra en anden SHA, rig eller tidsstempel autoriserer ikke eksekvering.
5. En fejlet probe kan repræsenteres men kan ikke udstede en lease.
6. Publikationsstien ender lokalt: intet kald når et offentligt remote.
7. Produktets eksisterende storage- og dormant-gates forbliver grønne.

## Konsekvenser

**Positive:** selvudvikling får en eksplicit, gated grænse i stedet for en implicit; menneskelig terminal autoritet står skrevet, ikke underforstået; isolationen gør DevControl fjernbar uden at røre produktet; og aktiveringsporten gør det umuligt at glide fra "forslag" til "publikation" uden en beslutning.

**Accepterede begrænsninger:** DevControl kan intet udgive selv — hver kandidat kræver en menneskelig handling; kæden er dyr at udvide, fordi hvert lag kræver evidens; og Windows-bindingen (Job Objects, AppContainer) gør indeslutningen platformspecifik. Sidstnævnte bør stå eksplicit som en kendt begrænsning frem for at blive opdaget senere.

## Afgjort sammen med denne ADR

- **PR #338 landes ikke i ét stykke.** 412 commits og 215 filer kan ikke reviewes meningsfuldt. Branchen opdeles i afgrænsede slices mod denne ADR, efter samme model som bar ADR-A4-008 igennem: preflight før kode, rapport før merge, exact-head-review med mutationstest, og Anders' kør pr. landing. Autoritetslagene er allerede nummererede slices i koden, så opdelingen findes — den skal blot respekteres i landingen.
- **Platformbindingen accepteres som kendt begrænsning.** Indeslutningen er Windows-specifik (Job Objects, AppContainer). Det er bevidst og noteres her frem for at blive opdaget senere. Genbesøges kun ved et målt behov for en anden platform, og da gennem en ny ADR.

## Ejerskab — afgjort

**Sol ejer `devcontrol/`.** Besluttet af Anders 05/08-2026, umiddelbart efter at
denne ADR blev landet. Sol driver dermed opdelingen af PR #338 i slices mod
ADR'en og ejer træet, herunder `devcontrol/src/kaliv_dev_control/**`,
`devcontrol/tests/**` og `devcontrol/schemas/**`.

Claude efterprøver som hidtil: exact-head-review med mutationstest, verdikt før
landing, ingen merge uden Anders' kør. Selve ejerskabsteksten står i
`SOL-CLAUDE-SAMARBEJDE.md`; denne ADR gengiver den kun for kontekst.
