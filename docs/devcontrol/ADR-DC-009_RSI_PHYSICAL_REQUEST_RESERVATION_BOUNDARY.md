# ADR-DC-009 — Exact-main observation og one-time reservation før DC-L15

**Dato:** 12/09-2026  
**Status:** foreslået til beslutning  
**Område:** DevControl / RSI / fysisk qualification

## Kontekst

ADR-DC-008 indfører et kortlivet, human-signeret request-artifact før DC-L15. En gyldig signatur beviser imidlertid kun, at en identificeret human authority bad om én bounded fysisk qualification mod en bestemt ønsket `main`-SHA. Den beviser ikke, at den lokalt observerede `main` faktisk matcher den ønskede SHA, og den forbruger ikke requesten.

Før en fysisk campaign overhovedet kan overvejes, mangler derfor to uafhængige egenskaber:

1. en trusted, lokal og read-only observation af `refs/heads/main`, og
2. en crash-durable one-time reservation, så samme request ikke kan genbruges.

Disse egenskaber må ikke forveksles med en vedvarende freeze eller campaign-start authority.

## Beslutning

Der foreslås et separat evidence-only reservation-led mellem den signerede request og en senere fysisk runner:

`verified human request → trusted local main observation → exact SHA match → durable one-time consume`

### 1. Trusted lokal main-observation

Observationen skal:

- læse præcis `refs/heads/main^{commit}` gennem den staged `TrustedGitRuntime`,
- være lokal og read-only,
- udføre ingen network-operation,
- mutere intet repository,
- binde repository-identiteten `Ternedal/ModelRig`,
- binde SHA-256 af den konkrete resolved lokale repository-path,
- binde Trusted Git runtime-manifest og executable digest,
- have canonical UTC timestamp,
- være højst fem minutter gammel ved reservation.

Observationen er `evidence-only`.

### 2. Exact-main match

Reservation må kun konstrueres, hvis den observerede lokale `main`-SHA er byte-for-byte identisk med `requested_frozen_main_sha` i den human-signerede request.

Navnet `requested_frozen_main_sha` er fortsat et mål fra request-kontrakten. Én observation må **ikke** fortolkes som bevis for, at `main` forbliver frozen over tid.

Et gyldigt reservation-receipt må derfor sige:

- `main_head_match_confirmed=true`
- `request_consumed=true`
- `replay_safe=true`

men skal stadig sige:

- `frozen_main_confirmed=false`
- `physical_campaign_completed=false`
- `campaign_start_authorized=false`
- `pilot_go_authorized=false`
- `activation_authorized=false`
- `remote_publication_authorized=false`

### 3. Re-verifikation af human request

Request-signaturen og qualification-bindingen re-verificeres på consumption-tidspunktet. Reservationen kan ikke bygges ud fra et gammelt verification receipt alene.

Det betyder blandt andet, at requestens expiry stadig håndhæves ved reservation.

### 4. Crash-durable one-time consume

Der anvendes en dedikeret create-once ledger keyed af requestens canonical SHA-256.

Consumption følger fail-closed rækkefølgen:

1. create-once lock/reservation marker,
2. create-once pending artifact,
3. create-once final canonical reservation,
4. read-back og canonical verifikation,
5. cleanup af pending/lock.

Hvis processen crasher eller cleanup fejler efter reservationen er begyndt, må requesten **ikke** blive genbrugelig. Presence af final, pending eller lock betyder consumed eller explicit recovery-required. Der findes ingen implicit rollback til reusable state.

Denne ADR tilføjer ikke en recovery-procedure; usikker state forbliver fail-closed.

### 5. Ingen fysisk execution authority

Reservation-leddet må ikke:

- starte de 11 DC-L15 probes,
- oprette background cadence,
- erklære vedvarende `main` freeze,
- generere fysisk isolation-evidens,
- erklære DC-L15 completed,
- autorisere pilot-GO,
- autorisere merge, push, release, deploy eller remote publication,
- aktivere DC-L16.

En senere fysisk runner skal have sin egen kontrakt og skal re-verificere relevant main/freeze-evidens omkring selve campaignen.

## Artefakter

- `kaliv-rsi-local-main-head-observation/v1`
- `kaliv-rsi-physical-qualification-reservation/v1`
- `PhysicalQualificationRequestLedger`

Reservationens authority er fast `consumed-request-evidence-only`.

## Fail-closed krav

Implementationen skal mindst afvise:

1. forkert eller malformed `main` SHA,
2. observation af anden ref/repository,
3. stale eller future-dated observation,
4. observation hvis SHA ikke matcher den signerede request,
5. expired eller ugyldig human request ved consumption,
6. duplicate consumption af samme request,
7. enhver eksisterende pending/lock-state som genbrugelig request,
8. tampering med canonical final reservation,
9. receipt-forsøg på at flippe freeze/campaign/pilot/publication/activation authority til `true`.

## Konsekvenser

Efter denne boundary kan DevControl bevise, at en specifik human-signeret request blev re-verificeret, matchede den lokalt observerede `main`-head på reservationstidspunktet og blev irreversibelt taget ud af replay-puljen.

Det er stadig **ikke** bevis for en vedvarende frozen-main campaign og stadig **ikke** tilladelse til at starte fysisk execution.
