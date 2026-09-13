# ADR-DC-010 — One-shot RSI physical campaign admission før DC-L15 execution

**Dato:** 13/09-2026  
**Status:** foreslået til beslutning  
**Beslutningsejer:** Anders  
**Afhænger af:** ADR-DC-001, ADR-DC-007, ADR-DC-008 og ADR-DC-009

## Problem

ADR-DC-009 kan bevise, at én human-signeret DC-L15-request blev forbrugt på et
tidspunkt, hvor den lokale `refs/heads/main` matchede den SHA, mennesket havde
anmodet om. Den reservation giver med vilje **ingen** campaign-start authority.

Det efterlader et nødvendigt authority-led før fysisk execution:

```text
consumed human request
  -> frisk pre-start main-observation
  -> præcis én manuel DC-L15 campaign-admission
  -> fysisk runner (uden for denne slice)
```

Uden dette led ville en runner enten skulle acceptere den ikke-autoriserende
reservation direkte eller selv opfinde regler for freshness, repo-identitet,
collector/approver og det eksisterende I0b-report-univers.

## Beslutning

Der indføres `kaliv-rsi-physical-campaign-admission/v1` og en create-once lokal
admission-ledger.

En admission må kun udstedes når alle følgende bindinger holder:

1. input er en gyldig `PhysicalQualificationReservation` fra ADR-DC-009;
2. den originale `QualificationPacket` hasher præcis til reservationens
   `qualification_packet_sha256`;
3. den originale reservation-observation hasher præcis til
   `main_observation_sha256` i reservationen;
4. en ny trusted, read-only pre-start observation måler samme
   `refs/heads/main` SHA som requestens `requested_main_sha`;
5. pre-start observationen kommer fra samme lokale repository-root og samme
   staged Trusted-Git runtime/executable som reservation-observationen;
6. pre-start observationen er højst ét minut gammel ved admission;
7. reservationen er højst 15 minutter gammel ved admission;
8. campaign-operatoren er præcis den collector, som den human-signerede request
   navngav;
9. collector og approver forbliver forskellige personer;
10. admissionen kræver det allerede eksisterende
    `kaliv-windows-isolation-physical-report/v1`, `os_isolated`, `network=deny`
    og hele det eksakte 11-probe `REQUIRED_PROBES`-univers;
11. admissionen bindes til qualification-pakkens `proposal_id`, `task_id`,
    `task_sha256`, repository og `base_sha`.

## Authority

En admission er det første artifact i denne RSI-kæde, der må sætte
`campaign_start_authorized=true`, men authority er bevidst meget smal:

```text
authority = single-physical-campaign-start-only
manual_operator_required = true
single_campaign_only = true
automatic_start = false
campaign_start_authorized = true
physical_campaign_completed = false
post_campaign_main_observation_required = true
frozen_main_confirmed = false
pilot_go_authorized = false
activation_authorized = false
remote_publication_authorized = false
merge_authority = human
```

Admissionen **starter ikke** processen. Den må kun være et input til en separat,
operator-invoked physical runner.

## One-shot-egenskab

`PhysicalCampaignAdmissionLedger` navngiver det durable artifact efter den
forbrugte reservations SHA-256 og bruger create-once publication. Dermed kan
samme reservation højst udstede én campaign-admission.

Det er ikke det samme som at påstå, at en fremtidig runner allerede håndhæver
single-use af selve admission-artifactet. Runner-integration skal eksplicit
forbruge/binde admissionen og det navngivne `campaign_id`; denne ADR må ikke
skjule den resterende execution-replay-grænse.

## Ingen falsk frozen-main påstand

To punktobservationer kan ikke bevise, at en Git-ref aldrig flyttede sig mellem
dem. Derfor forbliver `frozen_main_confirmed=false` også efter pre-start
admission.

Admissionen kræver i stedet `post_campaign_main_observation_required=true`.
En senere completion-boundary skal mindst:

- binde det signerede 11-probe physical report til admissionens `campaign_id`,
  `task_id`, `task_sha256`, repository, `base_sha`, collector og approver;
- kræve en ny post-campaign trusted main-observation;
- fejle hvis main ikke matcher request-SHA ved campaign boundary;
- fortsat undlade at kalde dette et kontinuerligt freeze-bevis, medmindre en
  separat mekanisme faktisk gør refs immutable gennem hele kampagnen.

## Eksisterende physical-isolation kontrakt genbruges

ADR'en introducerer ikke et nyt probe-format eller en parallel Tier-A runner.
Den refererer direkte til eksisterende `physical_isolation.py`:

- `REPORT_SCHEMA`;
- `IsolationBoundary.OS_ISOLATED`;
- `NetworkMode.DENY`;
- `REQUIRED_PROBES` med alle elleve probes.

Det eksisterende `WindowsPhysicalIsolationVerifier` forbliver den komponent, der
senere verificerer et faktisk signeret physical report. Synthetic CI-evidence er
ikke fysisk I0b-evidence.

## Fail-closed regler

Admission fejler blandt andet ved:

- andet qualification packet;
- forkert eller manipuleret reservation-observation;
- forkert `main` SHA;
- andet lokalt repository-root;
- ændret trusted-Git runtime/executable;
- stale/future timestamp-rækkefølge;
- reservation ældre end 15 minutter;
- operator som ikke er requestens collector;
- ændret/manglende 11-probe-univers;
- forsøg på automatic start, completed campaign, frozen-main, pilot,
  publication eller activation authority;
- andet merge-authority end human;
- forsøg på at udstede endnu en admission fra samme reservation.

## Bevidste ikke-mål

Denne ADR og slice må ikke:

- køre én eneste fysisk probe;
- kalde Tier-A executor eller ToolHost;
- skabe en always-on agent eller cadence;
- fetch/push/publish til remote Git/GitHub;
- merge, release eller deploye;
- erklære DC-L15 completed;
- udstede DC-L16 pilot-GO;
- aktivere ModelRig/DevControl;
- erstatte den uafhængige collector/approver-gate.

## Næste nødvendige led

Efter denne slice mangler stadig en fysisk completion-boundary, der binder det
faktiske signerede I0b-report tilbage til admissionen og en frisk post-campaign
main-observation. Først derefter kan en separat menneskelig pilotbeslutning
vurderes. Ingen af disse senere led er implícit godkendt af denne foreslåede ADR.
