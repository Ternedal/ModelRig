# ADR-DC-012 — Human/Ed25519 exact-runner execution binding efter physical evidence

**Dato 13/09-2026. Status: foreslået til beslutning.**

## Kontekst

ADR-DC-011 producerer et host-pinned, verificeret post-campaign evidence snapshot,
men lader med vilje fire gates stå åbne:

1. `exact_runner_execution_binding`
2. `continuous_main_freeze_confirmation`
3. `dc_l14_independent_human_verdict`
4. `human_pilot_go_decision`

Det legacy DC-L04 physical-report kan bevise de 11 isolation-probes, men binder
ikke `campaign_id` eller de exact runner-bytes/SHA fra ADR-DC-010. Snapshot'et
bærer disse identiteter side om side, men det er ikke i sig selv bevis for at den
autoriserede runner faktisk var den runner, den menneskelige operator kørte.

Det næste RSI-led skal derfor lukke **kun** runner-execution-bindingen uden at
overfortolke et menneskeligt udsagn som kernel telemetry, continuous Git freeze,
DC-L15 completion eller pilot-GO.

## Beslutning

Der indføres et separat human/asymmetric execution-binding lag. En fysisk
operator kan signere én canonical claim med en separat Ed25519-nøgle. Production
verificerer signaturen mod en fast host-admin-kontrolleret public-key keyring og
udsteder derefter et non-terminalt execution proof.

### 1. Claim binder hele ADR-DC-011 snapshot'et

Schema:
`kaliv-rsi-physical-campaign-execution-binding/v1`.

Claimen binder mindst:

- exact `evidence_snapshot_sha256`;
- `admission_sha256` og `campaign_id`;
- task/repository/base/requested-main identity;
- exact `runner_relative_path`, `runner_sha256` og `runner_bytes`;
- exact `signed_report_sha256`, `physical_report_sha256` og `report_id`;
- operator og approver;
- report start/completion;
- den menneskeligt observerede runner-execution start/completion;
- post-main observationstidspunktet; og
- claimens eget signeringstidspunkt.

Runner-execution intervallet skal ligge helt inden for reportets fysiske campaign
interval. Claimen skal signeres efter post-main observationen og senest 30
minutter efter denne observation.

### 2. Signeren er den fysiske operator, ikke approveren

`operator_actor_id` skal være identisk med ADR-DC-011 snapshot'ets
`collector_actor_id`. `approver_actor_id` bæres videre og skal fortsat være en
anden aktør.

Den detached Ed25519-signaturs `issuer_actor_id` skal være identisk med
`operator_actor_id`, og `signed_at_utc` skal være identisk med claimens
`binding_created_at_utc`.

Dette er bevidst **ikke** den uafhængige menneskelige DC-L14-verdict. Operatoren
attesterer kun hvad der faktisk blev kørt.

### 3. Production trust-root er verification-only og host-pinned

Production accepterer ikke caller-valgt verifier eller keyring.

Fast keyring:

- Windows:
  `C:\Program Files\ModelRig\DevControl\authority\rsi-physical-campaign-execution-binding-keyring-v1.json`
- POSIX:
  `/etc/modelrig/devcontrol/authority/rsi-physical-campaign-execution-binding-keyring-v1.json`

Keyring schema:
`kaliv-rsi-physical-campaign-execution-binding-keyring/v1`.

Authority-domain:
`rsi-dc-l15-exact-runner-execution-binding`.

Issuer-system:
`kaliv-rsi-dc-l15-execution-binding-authority-v1`.

Runtime loader kun public Ed25519 verification keys og revocation state gennem
den eksisterende asymmetric authority primitive. Ingen private signing keys,
signer-API, credential adapter eller network authority introduceres.

Production verification kræver elevated physical host operator. Caller-supplied
`verifier` er kun en compatibility-shape og fejler før host state konsulteres.
Den injectable verifier/clock findes kun i underscored test-seam.

### 4. Human signature er attestation, ikke kernel telemetry

Et successful proof betyder:

> den host-pinnede menneskelige operator har asymmetrisk signeret, at den exact
> campaign/runner identity blev observeret udført og hører til det exact report,
> som claimen binder.

Det betyder **ikke**, at DevControl selv har process-level kernel telemetry for
spawned runner bytes. Authority-værdien er derfor eksplicit:

`verified-human-exact-runner-execution-binding-only`.

Denne afgrænsning er vigtig: den menneskelige signatur lukker den definerede
human/asymmetric execution-binding gate, men må ikke fremstilles som et
maskinelt process-attestation-system.

### 5. ADR-DC-011 evidence bliver ikke implicit opgraderet

Execution proof'et bærer `evidence_snapshot_sha256` og de exact report-digests,
men det re-verificerer ikke det legacy HMAC report og må ikke gøre en vilkårligt
konstrueret snapshot-instans til ny physical-report authority.

ADR-DC-011 forbliver det separate evidence-verification lag. En senere
completion boundary skal kræve begge artifacts med exact digest-binding, ikke
antage at execution proof'et alene beviser de 11 probes.

### 6. Kun én gate lukkes

Schema:
`kaliv-rsi-physical-campaign-execution-proof/v1`.

Successful proof kræver og sætter:

- `evidence_snapshot_binding_verified=true`
- `human_execution_signature_verified=true`
- `runner_execution_binding_proven=true`

Følgende forbliver obligatorisk `false`:

- `continuous_main_freeze_proven`
- `physical_campaign_completed`
- `dc_l15_complete`
- `pilot_go_authorized`
- `activation_authorized`
- `remote_publication_authorized`

De resterende completion-gates er præcis:

1. `continuous_main_freeze_confirmation`
2. `dc_l14_independent_human_verdict`
3. `human_pilot_go_decision`

Execution-binding laget udfører ingen physical probes, ingen Git-read/write,
ingen GitHub mutation, ingen merge, release, deploy, publication eller
activation.

## Konsekvenser

RSI-kæden kan nu skelne mellem:

- verificeret fysisk report-evidence fra ADR-DC-011; og
- en separat menneskelig/asymmetrisk attestation af exact runner execution.

Det fjerner den konkrete campaign/report/runner-identitetskløft uden at springe
over continuous-main-freeze eller den uafhængige menneskelige verdict.

Næste manglende tekniske led er et **continuous-main-freeze proof**, som ikke må
reduceres til endnu en pre/post punktmåling. Først når det led findes, kan en
senere completion boundary kombinere evidence + execution binding + freeze proof
og stadig holde human DC-L14 verdict og pilot-GO separate.

`production_activation=false`.
