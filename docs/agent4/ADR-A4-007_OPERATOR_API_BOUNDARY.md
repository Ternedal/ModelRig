# ADR-A4-007 — Operator-API'ets host-, transport- og auth-grænse efter A4-13

**Truffet af Anders 01/08-2026. Status: besluttet** (issue #308). Supplerer
ADR-A4-005 og ADR-A4-006. Udkastet blev udarbejdet af Claude på Sols
anmodning, grundet i målinger, og godkendt af Anders uden ændringer. A4-14
må implementeres mod denne ADR — worker-mountet efter #291-modellen, backend-
proxy og grant-mekanik som separat slice; intet merges uden Anders' kør.

## Kontekst — målt, ikke antaget

- A4-13 monterer bevidst ingen route; read-fladerne findes som
  `Agent4OperatorReadService` (bounded pages via B-referencens hash-bound
  cursors) og `Agent4OperatorEvidenceReadService` (bounded stable pages via
  hash-bound evidence cursors).
- A4-09's composition er den eneste lovlige objektgraf-ejer: én context pr.
  kanonisk dataroot, second-writer-context afvises i samme proces
  (ADR-A4-006, kontrakttest 6-7). **Der findes ingen cross-process-
  koordination — bevidst.**
- Præcedens for eksponering findes allerede: Agent 3's ruter serveres af den
  loopback-only worker, og backenden er den autentificerede gateway, der
  forwarder (`backend/internal/httpapi/agent3.go`). Workerens
  ikke-loopback-afvisning og backendens "bearer selv på loopback" er
  fastlagte invarianter.
- Mount-præcedens: `production_mount.mount_agent3(app)` bag
  `KALIV_AGENT3_ENABLED`, pinnet af kontrakttest som eneste offentlige ejer.
- **Et scope-/grant-begreb findes ikke i backenden i dag** (0 reelle
  forekomster) — det bliver denne beslutnings eneste nye byggeklods.

## Beslutning 1 — Host-ejer: workerens FastAPI. RigGate afvises.

Operator-API'et hostes af den eksisterende worker-proces. En separat
RigGate-host afvises — ikke kun af konservatisme, men fordi ADR-A4-006 gør
den forkert: campaign-repository, timeline og evidence store ejes af **én
host-composed context pr. kanonisk dataroot, proces-lokalt, uden
cross-process lock/lease/arbitration**. En separat host ville enten skulle
læse storen uden om den kanoniske context (parallel læsevej — forbudt i ånd
og gate) eller genåbne præcis den cross-process-koordination, ADR-A4-006
bevidst ikke indførte. Operator-API'et skal bo i samme proces som contexten.

## Beslutning 2 — Transport: kun backend-proxied. Ingen ny lytteflade.

Klienter når API'et som alt andet: klient → backend (:8080, bearer) →
loopback-worker. Der åbnes **ingen** direkte lokal/Tailscale-flade på
workeren; Tailscale-adgang følger backendens eksisterende model. "Begge
veje" afvises, fordi to indgange giver to autoritative auth-grænser — den
fejlklasse, agent3-gateway-mønsteret netop eliminerede. Én dør, én vagt.

## Beslutning 3 — Autorisering: paired-device Bearer + eksplicit `agent4:read`-grant

Principal er den parrede enhed (eksisterende Bearer). Dertil kræves et
eksplicit **`agent4:read`-grant pr. enhed**: gemt i pairing-recorden,
**fraværende by default for alle enheder** (også allerede parrede),
tildelt/frataget kun ved eksplicit operatorhandling. Backenden håndhæver
grantet før forward; workeren forbliver loopback-only og stoler på gatewayen
(agent3-mønsteret). Bearer alene er ikke nok: pairing beviser "min enhed",
ikke "må læse orkestrator-interne kampagne- og evidensdata".

## Beslutning 4 — Aktivering: `KALIV_AGENT4_OPERATOR_API`, én mount-ejer

- Flag: `KALIV_AGENT4_OPERATOR_API`, default off, kun præcis `"1"` tænder
  (husets konvention).
- Mount-ejer: `worker/app/agent4/production_mount.py::mount_agent4_operator(app, context)`
  efter agent3-præcedensen — eneste offentlige ejer, pinnet af kontrakttest,
  kaldt fra samme sted i `main_impl` som agent3-mountet.
- Mountet er rent additivt: registrerer routes og intet andet. Ingen
  startup-recovery, ingen tråde/timers/polling, ingen implicit
  reconciliation, ingen Agent 3-dispatch. Backendens proxyruter registreres
  ubetinget (som agent3's) og fejler lukket, når workeren ikke har fladen.

## Beslutning 5 — Første scope: kun read

Kun A4-10's og A4-13's read-operationer eksponeres (GET). Udtrykkeligt
udelukket i denne ADR: submit, dispatch, pause, resume, cancel, checkpoint,
retry, intervention — og enhver write-flade i øvrigt. Write-eksponering
kræver en ny ADR og er desuden reelt blokeret af den kommende
side-effect-handoff-beslutning (se "Relateret" nederst).

## Beslutning 6 — Wire-model: de kanoniske cursors og identities, byte-identisk

API'et eksponerer de eksisterende hash-bound cursors og identities **uden
parallel wire-model**: payloads serialiseres af de to eksisterende services,
og proxy/API-laget må ikke re-serialisere på måder, der ændrer hash-input
eller cursor-bytes. Én konvolut (media-type + schema-version) er tilladt
rundt om — aldrig inde i — de kanoniske payloads.

## Beslutning 7 — Én context, injiceret

Operator-API'et modtager den host-composed A4-09-context som argument fra
mount-ejeren. Det komponerer aldrig selv, åbner ingen egen store, kender
ingen dataroot-sti direkte og deler evidence store/dataroot med resten af
contexten. Second-context-afvisningen (ADR-A4-006, test 7) gælder uændret.

## Obligatoriske kontrakttests

1. Flag off ⇒ ingen agent4-operator-route i OpenAPI-/route-inventaret.
2. Mount med flag on skaber ingen tråde, timers, filer eller polling
   (dormant-gate-mønsteret).
3. Verbums-inventar: operator-fladen har kun GET.
4. Backend nægter uden `agent4:read`-grant med den faste fejlbody — også for
   en i øvrigt gyldigt parret enhed.
5. Workerens ikke-loopback-afvisning er uændret (LAN-kald direkte mod
   workeren fejler fortsat).
6. Cursor-/identity-payloads er byte-identiske med servicelagets output
   (round-trip-test gennem proxyen).
7. Anden writer-context mod samme dataroot afvises fortsat (genbrug af
   A4-11's test).
8. Ingen kaldevej fra operator-modulerne til dispatch/signal/lifecycle-
   writes (AST-/kaldegraf-test).
9. Storage-boundary- og dormant-runtime-gates forbliver grønne.

## Konsekvenser

**Positive:** én dør og én vagt; ingen nye lytteflader; ADR-A4-006's
ejerskabsmodel bevares urørt; read-fladen kan bevises dvalende med de
eksisterende gate-mønstre; grant-modellen giver en genbrugelig byggeklods
til fremtidige scopes.

**Accepterede begrænsninger:** ingen fjernadgang uden om backenden; ingen
writes i denne generation; `agent4:read`-grantet er ny mekanik og skal have
sin egen lille kontraktflade i backenden; RigGate er udskudt til et målt
behov, ikke afvist for evigt.

## Relateret kommende beslutning (nummerering fastlægges her)

**ADR-A4-008-kandidat: "External side-effect handoff and unknown outcome."**
Dispatch/resume gemmer i dag bar state uden intent før det eksterne
Agent 3-kald (bekræftet ved læsning af `service.py`), og executor-kontrakten
har hverken dispatch-id, idempotency eller outcome-lookup. Det blokerer
**aktivering**, ikke denne read-flade — men det skal besluttes, før Agent 4
nogensinde orkestrerer unattended, og før nogen write-eksponering i
operator-API'et.