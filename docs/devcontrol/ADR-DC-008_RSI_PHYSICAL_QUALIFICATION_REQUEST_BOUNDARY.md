# ADR-DC-008 — Human-signed RSI request før DC-L15 fysisk qualification

**Dato: 12/09-2026. Status: foreslået til beslutning.**

## Kontekst

ADR-DC-007 etablerer et pre-physical qualification packet, der kan bevise en komplet software-RSI chain-of-custody uden at erklære GO. Den eksisterende DC-L15-kontrakt kræver derefter fresh fysisk I0b-evidens på exact frozen `main`, elleve native probes, uafhængig collector/approver og en senere menneskelig pilotbeslutning.

Der mangler et authority-artifact mellem qualification-pakken og en fremtidig fysisk runner: et menneske skal eksplicit kunne anmode om én konkret DC-L15-validation uden at denne signatur i sig selv starter noget eller bliver til pilot-/activation-authority.

## Beslutning 1 — Requesten er human-signed request-only

Det unsigned payload bruger schema `kaliv-rsi-physical-qualification-request/v1` og skal signeres af en separat Ed25519-authority med issuer system `kaliv-rsi-dc-l15-request-authority-v1`.

Requesten har altid:

- `authority = human-signed-request-only`;
- `scope = dc-l15-physical-validation-request-only`;
- `automatic_start = false`;
- `pilot_authority = false`;
- `activation_authority = false`;
- `remote_publication_authority = false`;
- `exact_frozen_main_confirmed = false`;
- `physical_evidence_present = false`.

En signatur betyder derfor kun: **en identificeret menneskelig authority har anmodet om denne bounded validation**.

## Beslutning 2 — Requested frozen-main SHA er ikke freeze-bevis

Requesten navngiver `requested_frozen_main_sha`, men må ikke attestere, at SHA'en faktisk er current/frozen `main`.

Exact frozen-main confirmation forbliver en separat fremtidig authority/evidence-boundary. Request-verifikation skal derfor fortsat returnere `exact_frozen_main_confirmed = false`.

## Beslutning 3 — DC-L15's fysiske kontrakt bindes før execution

Requesten skal kræve præcis den eksisterende DC-L04/DC-L15 fysiske kontrakt:

- report schema `kaliv-windows-isolation-physical-report/v1`;
- boundary `os_isolated`;
- network mode `deny`;
- alle elleve `REQUIRED_PROBES` i canonical rækkefølge;
- forskellige `collector_actor_id` og `approver_actor_id`.

Requestlaget må ikke opfinde et alternativt probe-univers eller svække fysisk isolation.

## Beslutning 4 — Requesten er kortlivet

`expires_at_utc` skal ligge efter `requested_at_utc` og højst 24 timer senere. En request må ikke verificeres efter udløb.

En senere physical execution-boundary skal desuden kontrollere freshness mod exact frozen-main og faktisk runtime/evidence; denne ADR gør ikke requesten til fysisk evidens.

## Beslutning 5 — Verifikation giver stadig ikke start-authority

Verificeret request-evidens bruger schema `kaliv-rsi-physical-qualification-request-verification/v1` og har altid:

- `human_request_verified = true`;
- `replay_guard_required = true`;
- `request_consumed = false`;
- `exact_frozen_main_confirmed = false`;
- `physical_campaign_completed = false`;
- `campaign_start_authorized = false`;
- `pilot_go_authorized = false`;
- `activation_authorized = false`;
- `remote_publication_authorized = false`;
- `authority = verified-request-evidence-only`.

Det er med vilje umuligt for dette slice at forbruge requesten eller starte campaignen. Replay/consume og actual start skal ligge i en separat boundary.

## Beslutning 6 — Private keys må ikke lande i runtime eller repository

DevControl genbruger ADR-DC-001/DC-L10 asymmetric authority-modellen: runtime modtager kun pinned public verification identities, keyring epoch og revocation state.

Der tilføjes ingen private-key loader, signer, credential mechanism eller remote transport. Test-fixtures må skabe ephemeral private keys in-process, men produktionskoden er verification-only.

## Beslutning 7 — Ingen unattended fysisk recursion

Denne slice må ikke:

- starte DC-L15-processer eller probes;
- bekræfte frozen `main`;
- forbruge/replay-locke requesten;
- starte candidate runtime eller evals;
- oprette background/recurring cadence;
- foretage remote Git/GitHub write;
- merge, release, deploye eller aktivere;
- autorisere DC-L16-pilot.

En senere slice kan indføre exact-main confirmation + one-time replay/consume gate og derefter en separat, operator-invoked fysisk runner-adapter. Hver af disse boundaries skal fortsat være fail-closed.

## Konsekvens

RSI-kæden får et eksplicit menneskeligt håndtryk før fysisk validation uden at blande **request**, **freeze-bevis**, **execution**, **fysisk evidens** og **pilotbeslutning** sammen. Det gør det muligt at automatisere chain-of-custody samtidig med, at selve starten fortsat kræver en særskilt authority-boundary.

## Forhold til tidligere ADR'er

- ADR-DC-001 bevarer human terminal authority.
- ADR-DC-007 bevarer pre-physical no-GO stopreglen.
- DC-L04's eksisterende physical isolation report forbliver source-of-truth for probe-set, OS isolation, network deny, reboot proof og collector/approver independence.
- DC-L15/DC-L16 forbliver separate fremtidige fysiske/pilotmæssige skridt.
