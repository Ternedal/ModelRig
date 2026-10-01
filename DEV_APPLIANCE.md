# Udviklingskanalen — appliancen kører fra checkouten

**Besluttet 02/09/2026:** så længe intet er i produktion, udvikles der så
hurtigt som muligt. Koden på riggen er det, checkouten holder.

## Hvad det er

`START_DEV_APPLIANCE.cmd` stopper release-appliancen, bygger backend fra
HEAD, starter backend og worker med **appliancens egne data og env**
(`ModelRig-appliance\modelrig.env`, parset med kommentar-strip), binder
backend til LAN så telefonen kan nå den, og venter på begge healthz.

Ny kode på riggen er derefter to skridt:

    git pull --ff-only
    START_DEV_APPLIANCE.cmd

## Consciousness Core i dev-kanalen

Dev-appliancen aktiverer nu eksplicit den bruger-drevne cognitive kæde:

- Consciousness Core runtime + supervisor;
- normal chat admission;
- exact-event cognition for det aktuelle user turn;
- bounded same-turn response guidance;
- VisionRig -> inferred WorldEvidence admission;
- den operator-kalibrerede dev-profil i `deploy/consciousness-dev-profile.json`.

Dev-appliancen aktiverer også **lived continuity**: sleep/wake-boundary,
unplanned-restart liveness, policy-baseret SelfState-checkpoint samt den
eksisterende scheduler-bro til bounded autonomous cognition. Den autonome
trigger-policy tillader højst 4 automatiske cognitive trin pr. 5 minutter med
30 sekunders cooldown og afviser `user_turn`, `operator_signal` og
`tool_result` som autonome triggers.

Det er **ikke** autonom action-authority: Agent 3 bliver ikke slået til af denne
profil, og cognition-kæden får ingen execution authority. Den almindelige
ModelRig scheduler er aktiv i dev for at levere cadence; eventuelle allerede
godkendte schedules følger fortsat deres eksisterende ToolGate-regler.
Release-defaults forbliver fail-closed, og `production_activation` forbliver
`false`.

C31-F er nu runtime-koblet i dev: hvert faktisk scheduler-callback komponerer et
`ContinuousLoopSupervisorPlan` ud fra scheduler-evidens og den konkrete C18-plan,
når et supervisor-step finder sted. Status viser kun plan-antal og seneste
disposition; interne refs eksponeres ikke.

C31-B er også runtime-koblet: efter den første gennemførte cognitive cycle findes
en reference-only C31-A lived-continuity-receipt. Den næste cycle får et
`PresentContextProjection` med trusted lokal dagfase og session-elapsed tid.
ThoughtEngine får ingen clock-, identity-, persistence- eller scheduling-authority.

Før worker/backend starter, kører dev-appliancen desuden en idempotent
SelfState-bootstrap. Den må kun bruge den allerede valgte og aktiverede
**godkendte Person Revision**. Mangler den, eller matcher en eksisterende
SelfState ikke den aktive Person Revision, stopper startup med fejl. Bootstrap
opretter aldrig selv en Person, vælger aldrig en Person og aktiverer aldrig en
Person Revision. Efter stacken er startet, kræver launcheren desuden at
`GET /experimental/consciousness/status` rapporterer
`ready_for_user_driven_cognition=true`; ellers stoppes startup som fejlet.

Som standard starter dev-appliancen også et sibling-checkout af
`Ternedal/VisionRig` på port 8110 med
`VISIONRIG_MODELRIG_BRIDGE=1`. Startup bliver først erklæret klar, når
VisionRig `main` annoncerer `PerceptionEvent/v4`, og ModelRig-adapteren accepterer
fortsat både v3 og v4. Dev-appliancens readiness-check kræver nu eksplicit v4,
så integrated startup ikke kan erklæres grøn mod en stale v3 health-kontrakt. Brug `-VisionRigDir <sti>` ved en anden checkout-placering eller
`-SkipVisionRig` når perception bevidst skal køres separat.

`STOP_DEV_APPLIANCE.cmd` (eller `-Stop`) lukker dev-stakken og starter
`KalivBootstrap` igen, så den signerede release kommer tilbage.

## Telefonen: samme loop

`INSTALL_DEV_APK.cmd` henter CI's kandidat-APK for `origin/main`s tip (og
bestiller bygget, hvis det ikke findes), og installerer den over adb med
`-r -d`. Debug- og release-builds signeres med samme `modelrig`-nøgle og
deler pakkenavn, så den installeres **oven på** release-appen, og parringen
bevares. Regn med 5-8 minutters CI-tid, hvis bygget ikke ligger klar.

Ny kode hele vejen rundt er derfor:

    git pull --ff-only
    START_DEV_APPLIANCE.cmd
    INSTALL_DEV_APK.cmd

## UI-ændringer der rammer golden-screenshots

CI verificerer Roborazzi-baselines, og ingen udviklingsmaskine har Android
SDK. Derfor: lav UI-ændringen på en gren, åbn PR'en, og kør workflowet
**record-goldens** på grenen (Actions → record-goldens → Run workflow →
`ref` = grenens navn). Det optager alle baselines og committer de ændrede
PNG'er tilbage til grenen; verify bliver grøn, og billed-diffen reviewes i
PR'en. Workflowet nægter at køre mod `main`.

## Hvad det ikke er

- **Det er ikke bevis.** Intet, dev-appliancen kører, er kandidatbundet, og
  ingen gate læser dens output. Citér aldrig en dev-kørsel som evidens i et
  issue.
- **Det rører ikke `production_activation`.** Hver konstant forbliver
  `False`; flip-værnet fælder ellers CI. Den fysiske vej — Stage A,
  proof-kampagnen, Stage B — er stadig baren den dag, produktion bliver
  virkelig.
- **Det springer ikke updater-kæden over for altid.** Release-appliancen er
  ét `-Stop` væk.

## Fælder, scriptet allerede kender

- Env-filen parses af `scripts/Read-KalivEnvFile.ps1` — ikke af et regex.
  `KEY=value # kommentar` giver `value`, ikke `value # kommentar`. Det kostede
  tre døgn i august.
- Backend bindes til `0.0.0.0` som standard. Mesh-netværk med
  klient-isolation gør alligevel telefonen blind for riggen; brug da
  `adb reverse tcp:8080 tcp:8080` og `http://127.0.0.1:8080` i appen.
- De to konsolvinduer ER stakken. Luk dem ikke; brug `-Stop`.
