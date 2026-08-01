# ADR-A4-008 — External side-effect handoff and unknown outcome

**Truffet af Anders 01/08-2026. Status: besluttet** (issue #321). Supplerer
ADR-A4-003 og ADR-A4-006 og er porten til enhver Agent 4-aktivering samt til
en fremtidig write-udvidelse af ADR-A4-007's operator-API. Udkastet blev
udarbejdet af Claude, grundet i målinger, og godkendt af Anders uden
ændringer. Enhver executor-implementering skal bygges mod denne kontrakt;
aktiveringsbetingelsen (Beslutning 8) står over alle feature-flag.

## Kontekst — målt, ikke antaget

- `service.py::dispatch_ready`: `transition_campaign` → `repository.save(running)`
  (bar RUNNING-state, ingen markør) → `executor.dispatch(...)` → først
  derefter projektion. `resume` følger samme mønster med `signal`.
- `CampaignExecutor`-protokollen har kun `dispatch(spec, state) -> str` og
  `signal(campaign_id, command) -> None` — **ingen dispatch-identitet, ingen
  idempotens, intet outcome-opslag.**
- Tre crash-vinduer er reelle: (A) RUNNING gemt, intet eksternt kald sket —
  recovery kan ikke vide det; (B) crash under det eksterne kald — outcome
  ukendt uden markør; (C) kaldet lykkedes, runtime-referencen aldrig
  persisteret — orphan-run.
- **`recovery.py` har nul forekomster af unknown/outcome:** den kontrakt for
  "ukendt execution outcome", ADR-A4-006 Beslutning 5 henviser til, er
  omtalt men aldrig bygget. Denne ADR ER den kontrakt.
- Der findes **ingen executor-implementering** på main (kun protokollen og
  composition-wiring) — kontrakten kan fastlægges uden migrering. Grønt felt.
- Genbrugsmekanikken findes: `CampaignProjectionIntent` (A4-11) beviser
  envelope-mønsteret "intent gemt atomisk med state, kvitteret efter
  projektion". `state.attempt` findes og valideres (heltal ≥ 0).

## Beslutning 1 — Deterministisk dispatch-identitet

Hvert eksternt dispatch har et deterministisk `dispatch_id` afledt kanonisk
af **campaign identity + attempt + operation ("dispatch") + schema-version**.
Samme attempt kan aldrig give to id'er; et nyt forsøg kræver et nyt attempt.
Signaler (resume/pause/cancel) får tilsvarende deterministisk identitet af
campaign identity + attempt + signaltype + resulterende revision.

## Beslutning 2 — Durable dispatch-intent FØR det eksterne kald

En `DISPATCH_REQUESTED`-intent gemmes **atomisk sammen med RUNNING-staten i
samme repository-envelope** (A4-11-mønsteret), FØR `executor.dispatch`
kaldes. Intenten bærer mindst: dispatch_id, campaign identity, attempt,
resulterende revision, schema-version. Vindue A er dermed afgørligt:
RUNNING uden intent kan ikke forekomme; intent uden bekræftelse betyder
"eksternt kald muligvis afsendt".

## Beslutning 3 — Executor-kontrakten bærer identiteten og deduplikerer

`CampaignExecutor.dispatch` udvides til at modtage dispatch_id (som del af
et request-objekt). **Modtagersiden (Agent 3-adapteren) SKAL deduplikere på
dispatch_id:** samme id er idempotent accept af samme run — aldrig to
runtimes for ét id. `signal` bærer tilsvarende sin signal-identitet og er
idempotent pr. identitet.

## Beslutning 4 — Bekræftelse persisteres

Efter acknowledgement gemmes `DISPATCH_CONFIRMED` med runtime-referencen
(atomisk state-opdatering, intenten kvitteres). Vindue C lukkes: en
bekræftelse uden runtime-reference kan ikke forekomme, og en manglende
bekræftelse betyder præcist "outcome ukendt".

## Beslutning 5 — Outcome-opslag, caller-driven

Executor-kontrakten får `query_outcome(dispatch_id) ->
not_dispatched | unknown | accepted | running | completed | failed` (med
evt. runtime-reference/evidens-pointer). **`not_dispatched` er en negativ
commitment, ikke en observation:** adapteren må kun svare det, hvis
dispatch_id aldrig er accepteret, og svaret **tombstoner samtidig id'et**,
så en forsinket original aldrig kan accepteres bagefter. Et tombstonet id
afvises fremover permanent — dedup-registret er dermed også
tombstone-registret. Recovery bruger opslaget ved
REQUESTED-uden-CONFIRMED — **kun ved eksplicit kald** (startup-recovery,
caller-drevet operation eller operatorhandling). Ingen tråde, timers,
polling, tailere eller subscriptions (ADR-A4-003 gælder uændret).

## Beslutning 6 — Ukendt outcome fejler lukket

Ved `unknown` efter opslag må systemet **ikke** re-dispatche automatisk.
Kampagnen markeres som krævende operatorintervention (eksisterende
fail-closed mønster). Re-dispatch er altid et nyt attempt med nyt
dispatch_id og kræver en eksplicit beslutning gennem recovery-kontrakten —
aldrig et gæt. Audit-reparation og execution-recovery forbliver separate
ansvar (ADR-A4-006).

Ved `not_dispatched` er "aldrig accepteret" bevist og id'et tombstonet:
recovery må markere kampagnen **klar til nyt forsøg** — men igangsættelsen
forbliver caller-driven som al anden lifecycle-operation. Automatisk
redispatch er fortsat forbudt, også ved bevist negativ. Et nyt forsøg er
altid et nyt attempt med nyt dispatch_id; et tombstonet id genafsendes
aldrig.

## Beslutning 7 — Én mekanik, ingen ny journal

Dispatch- og signal-intents genbruger A4-11's envelope- og
projektionsmekanik og projiceres til timelinen som almindelige events med
deterministisk identitet. Der indføres **ingen** ny storage-klasse, ingen
separat dispatch-journal, ingen ny wire-model. Storage-boundary- og
dormant-gates skal forblive grønne.

## Beslutning 8 — Aktiveringsbetingelse

Agent 4 må ikke orkestrere unattended, og operator-API'et må ikke få
write-flader, før denne ADR's kontrakttests er beviste mod en rigtig
Agent 3-adapter (mock-bevis er nødvendigt, men ikke tilstrækkeligt for
aktivering).

## Beslutning 9 — Resource reconciliation efter recovery

A4-03-lease-kernen (`InMemoryResourceLeaseManager`) er bevidst
process-local: et crash sletter alle leases, mens eksterne runtimes kan
leve videre med de fysiske ressourcer. Outcome-viden genopretter derfor
ikke ressourceejerskab.

Markøren **`resource_reconciliation_required`** persisteres på kampagnens
state, når recovery **ikke sikkert kan bevise, at ingen levende runtime
holder ressourcer** — atomisk med recovery-opdateringen, via den
eksisterende envelope-mekanik. Konkret pr. opslagssvar:

- `accepted` eller `running`: markør sættes — runtimen er bevist levende.
- `unknown`: markør sættes — runtimen **kan** være levende og holde
  ressourcer; fravær kan ikke bevises. `unknown` beholder samtidig sin
  uændrede execution-semantik fra Præcisering 1 (fail-closed, ingen
  redispatch, operatorintervention); dette punkt ændrer alene
  ressourcesikkerheden.
- `not_dispatched`: ingen markør — svaret tombstoner samtidig id'et, og
  ingen runtime er nogensinde accepteret.
- `completed` eller `failed`: ingen markør. Et terminalt svar er
  adapterens **autoritative attest** for, at runtimen er afsluttet og
  ikke længere holder ressourcer — samme commitment-semantik som
  tombstonen i Præcisering 1. En adapter, der ikke kan afgive den attest,
  **skal** svare `unknown` i stedet; tvivl bliver dermed altid til en
  markør.

Ingen ny storage-klasse; barrieren afledes af markørerne og er ikke et
separat globalt flag.

Så længe mindst én kampagne bærer markøren, gælder en **global
fail-closed dispatchbarriere** for resource-admission-stien:

- ingen nye resource-admitted dispatches (entydig, fast fejl);
- ingen automatisk lease-reacquire;
- ingen automatisk redispatch eller cancel.

Den almindelige scheduler uden resource admission er uberørt.

Opløsning er altid en **eksplicit caller-/operatorhandling**, der
dokumenterer én af tre grunde — ressourcerne er genetableret; runtimen er
verificeret afsluttet (et terminalt opslagssvar må bruges som bevis);
konflikten er manuelt håndteret — og fjerner markøren durable. Intet
clearer markøren automatisk; heller ikke et terminalt
`query_outcome`-svar i sig selv.

**Fravalgt, med begrundelse:** (i) lease-rekonstruktion fra intent eller
konfiguration — erklærede krav er ikke fysisk bevis for, hvad en levende
runtime faktisk holder; (ii) durable leases med fencing tokens — en reel
arkitekturudvidelse, der kræver sin egen ADR ved målt behov; (iii) en
per-ressource-barriere — den kræver præcis den ejerskabsviden, som gik
tabt med processen. Ingen polling, ingen tråde, ingen ny automatik;
aktiveringsbetingelsen (Beslutning 8) står uændret over alle flag.

## Obligatoriske kontrakttests

1. RUNNING-state og DISPATCH_REQUESTED-intent er atomiske: intet
   crash-vindue kan give det ene uden det andet.
2. Crash i handoff-vinduet: REQUESTED uden CONFIRMED afgøres **kun** via
   `query_outcome` — aldrig fra afsenderens durable state alene. Svarer
   adapteren `not_dispatched`, er "aldrig accepteret" bevist, id'et er
   tombstonet, og recovery markerer klar til nyt attempt — uden gæt og
   uden automatisk redispatch.
3. Dublet-dispatch med samme dispatch_id er idempotent — præcis én runtime.
4. Crash efter kald, før CONFIRMED: recovery bruger query_outcome og
   handler kun på et entydigt svar.
5. `unknown` giver aldrig automatisk re-dispatch; kampagnen fail-closer til
   operatorintervention.
6. Re-dispatch kræver nyt attempt og giver nyt deterministisk dispatch_id.
7. Signal-idempotens: samme signal-identitet leveres højst én gang virksomt.
8. Import, composition og recovery starter ingen tråde, timers eller
   polling; opslag sker kun ved eksplicit kald.
9. Intents projiceres via A4-11-mekanikken — ingen ny storage-flade
   (gate-bevist).
10. Storage-boundary- og dormant-runtime-gates forbliver grønne.
11. Tombstone: efter et `not_dispatched`-svar afviser adapteren en
    forsinket original-dispatch med samme id — permanent.
12. Nyt forsøg efter `not_dispatched` kræver nyt attempt og giver nyt
    deterministisk dispatch_id; et tombstonet id genafsendes aldrig.
13. `not_dispatched` udløser ingen automatisk redispatch — kun en
    caller-driven klar-markering.
14. Recovery persisterer `resource_reconciliation_required` atomisk med
    state-opdateringen ved `accepted`, `running` **og** `unknown` — og
    testen beviser samtidig, at `not_dispatched` (tombstone, ingen
    accepteret runtime) og terminale svar (adapterens attest) **ikke**
    skaber markøren.
15. Med mindst én markør til stede nægter resource-admission-stien alle
    nye dispatches fail-closed med den faste fejl; den almindelige
    scheduler uden resource admission er upåvirket.
16. Ingen kaldevej fra recovery eller barrieren til lease-reacquire,
    redispatch eller cancel (AST-/kaldegraf-bevist).
17. Markøren fjernes kun gennem den eksplicitte opløsningsoperation med
    dokumenteret grund, fjernelsen er durable, og et terminalt
    opslagssvar alene clearer intet.

## Konsekvenser

**Positive:** alle tre crash-vinduer bliver afgørlige; dobbelt-dispatch
bliver umuligt by construction; recovery får en kontrakt i stedet for et
tomrum; executor-grænsefladen fastlægges, mens den er grønt felt; writes og
aktivering får en målbar port.

**Accepterede begrænsninger:** Agent 3-adapteren skal implementere dedup og
outcome-opslag (ny kontraktflade på modtagersiden); state-envelope vokser
med dispatch-intents; `unknown` kan kræve et menneske — det er bevidst;
kontrakten er bevist med mock før rigtig adapter, men aktivering venter på
det fysiske bevis.

## Relaterede beslutninger

ADR-A4-007 (read-fladen) er uafhængig og allerede besluttet. Denne ADR er
porten til ADR-A4-007's fremtidige write-udvidelse og til enhver
production_activation af Agent 4-orkestrering.

## Præcisering 1 — `not_dispatched` som negativ commitment

**Besluttet af Anders 01/08-2026** efter fund under Sols slice-planlægning:
kontrakttest 2's oprindelige formulering var uopfyldelig, fordi et crash
før og et crash under det eksterne kald efterlader identisk durable
tilstand (REQUESTED uden CONFIRMED), og værdisættet havde ingen bevist
negativ. Samtidig indebærer Beslutning 3's dedup-krav, at adapteren
besidder svaret. To retninger blev fremlagt; Anders valgte den stærkere
outcome-kontrakt med tre bindende præciseringer: tombstone-semantikken
(uden den genopstår vinduet på modtagersiden), altid nyt attempt/id efter
negativ, og opslagsbaseret entydighed i test 2. `unknown`-semantikken er
urørt: fail-closed, ingen redispatch, operatorintervention.
Beslutning 5, Beslutning 6 og kontrakttest 2 ovenfor bærer præciseringen;
kontrakttest 11–13 beviser den.

## Præcisering 2 — resource reconciliation efter recovery

**Besluttet af Anders 01/08-2026** efter Sols preflight-fund til
slice-planen: ADR'en afgjorde execution-outcome, men ikke hvordan mistet
ressourceejerskab håndteres efter et process-crash — A4-03-leases er
process-local, så en levende ekstern runtime efterlader et tomt
lease-kammer, og resource admission kunne overbooke riggen med nye
dispatches. Anders skærpede reglen til princippet: markøren sættes, når
recovery **ikke kan bevise** fravær af ressourcehold — dermed også ved
`unknown`, hvis execution-semantik er uændret. Beslutning 9 og
kontrakttest 14–17 ovenfor bærer præciseringen: en afledt, global
fail-closed dispatchbarriere med caller-driven, dokumenteret opløsning —
ingen durable leases, ingen fencing, ingen ny automatik.
`not_dispatched`-semantikken fra Præcisering 1 er urørt.
