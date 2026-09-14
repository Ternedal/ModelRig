# ADR-DC-024 — Fresh human one-shot pilot-start authorization after satisfied host-attested preflight

**Dato:** 14/09-2026  
**Status:** foreslået til beslutning  
**production_activation:** `false`

## Kontekst

ADR-DC-022 binder det komplette 12-check preflight evidence-set til exact human
product-integration selection og exact preflight requirements. ADR-DC-023 gør
hele dette packet til input for en host-controlled Ed25519-attestation og kan
bevise `preflight_observed=true` samt, når alle signerede checks er grønne,
`preflight_satisfied=true`.

ADR-DC-023 stopper med vilje før pilot-start: et strukturelt gyldigt eller
host-attesteret proof må ikke alene kunne ophøje sig selv til execution
authority. Den tidligere menneskelige GO-beslutning og product-selection ligger
transitivt i chain-of-custody, men starttidspunkt, freshness og one-shot intent
skal være en ny, separat menneskelig beslutning efter den grønne preflight.

Et serialiseret ADR-DC-023 proof er desuden ikke selv-autentificerende. Proofet
indeholder signaturmetadata og signaturhash, men den detached Ed25519-signatur er
separat. ADR-DC-024 må derfor ikke opgradere caller-leveret "proof-shaped data"
til start-authority uden frisk host-side re-verifikation af ADR-DC-023-signaturen.

## Beslutning

ADR-DC-024 indfører en kortlivet, separat Ed25519-signeret human authorization
til præcis én fremtidig lokal pilot-start.

### 1. Exact canonical ADR-DC-023 proof er eneste signerede preflight-input

Authorizationen indlejrer hele exact `PilotRuntimePreflightAttestationProof` og
binder separat dets canonical SHA-256 samt:

- ADR-DC-023 attestation SHA-256;
- ADR-DC-022 packet SHA-256;
- ADR-DC-021 selection-proof SHA-256;
- ADR-DC-020 candidate-proof SHA-256;
- ADR-DC-017 requirements SHA-256;
- ADR-DC-016 trial-scope SHA-256;
- repository, base SHA og requested-main SHA;
- trial ID, operator surface og selected pilot task;
- workspace-root digest og local-commit scope;
- preflight observer actor og observer host.

Kun et exact proof med `host_attestation_verified=true`,
`preflight_observed=true` og `preflight_satisfied=true` accepteres. Et gyldigt
host-attesteret failed preflight er audit-evidence, men kan ikke bruges til en
start-authorization.

### 2. Fresh human authority efter preflight

Start-authorizeren skal være den samme menneskelige actor, som signerede den
exact ADR-DC-021 product-integration selection. Start-authorizeren skal samtidig
være forskellig fra både packetets preflight-observer og ADR-DC-023
host-attestoren.

Dette er en bevidst fail-closed rollemodel. Eventuel senere delegation eller
rolle-adskillelse kræver en separat ADR; den må ikke opfindes implicit af
runtime- eller produktlaget.

### 3. Kortlivet og one-shot

Authorizationen indeholder:

- canonical `authorized_at_utc`;
- canonical `expires_at_utc`;
- maksimum 15 minutters gyldighed;
- separat ikke-placeholder `start_nonce_sha256`;
- intent `authorize-one-local-pilot-start`;
- `one_shot_start_required=true`.

Authorizationstidspunktet må ikke ligge før verification-tidspunktet på exact
ADR-DC-023 proof.

Selve claimen er kun signable bytes og holder derfor:

- `pilot_start_authorized=false`;
- `start_consumed=false`;
- `product_pilot_started=false`;
- `integration_ready=false`;
- `local_commit_authorized=false`;
- alle remote/publication/activation-authorities false.

### 4. Fresh host-side ADR-DC-023 provenance før human start-authority

Public ADR-DC-024-verifikation skal modtage både det human-signerede start-artifact
og den detached ADR-DC-023-signatur, som hører til det indlejrede preflight proof.
Et proof-objekt eller en JSON-roundtrip er ikke i sig selv host-attestation.

Før human start-signaturen verificeres skal production:

1. resolve den canonical host-controlled ADR-DC-023 verification-only keyring;
2. re-verificere den detached ADR-DC-023-signatur over exact indlejrede
   attestation-bytes ved den aktuelle verification time;
3. kræve at detached-signaturens SHA-256 matcher `signature_sha256` i det
   caller-leverede preflight proof;
4. kræve at fresh re-verifikation reproducerer exact attestation hash, key ID,
   issuer actor/system, packet hash og alle preflight-/authority-semantikker i
   det proof, som den menneskelige start-authorization binder.

`verified_at_utc` fra den historiske ADR-DC-023 proof-identitet må gerne afvige
fra tidspunktet for den friske re-verifikation; cryptographic payload identity,
signer identity og authority-semantik må ikke afvige.

Missing detached signature, revoked/stale/untrusted ADR-DC-023 key, invalid
signature, payload drift eller proof/signature metadata drift fejler lukket før
ADR-DC-024 human authority vurderes.

### 5. Separat host-pinned human verification trust-root

Detached ADR-DC-024-signaturen bruger issuer-systemet:

`kaliv-rsi-dc-l16-pilot-start-human-authority-v1`

Production-facaden accepterer ikke caller-valgt verifier. Den resolver kun en
separat verification-only public-key keyring fra canonical host-controlled
DevControl path og kræver elevated host operator. Private/signing keys og signer-
transport er ikke del af repo/runtime.

Signaturens actor skal være exact `start_authorizer_actor_id`, og signature time
skal være exact `authorized_at_utc`. Verification skal ske inden for det signerede
gyldighedsvindue.

### 6. Successful verification autoriserer kun et fremtidigt start-consume

Et cryptographically valid ADR-DC-024 proof må sætte præcis:

- `pilot_start_authorized=true`.

Det bevarer:

- `one_shot_start_required=true`;
- `start_consumed=false`;
- `integration_ready=false`;
- `product_pilot_started=false`;
- `local_commit_authorized=false`;
- `remote_write_authorized=false`;
- `push_authorized=false`;
- `pr_mutation_authorized=false`;
- `merge_authorized=false`;
- `release_authorized=false`;
- `deploy_authorized=false`;
- `production_activation_authorized=false`.

Proof-authority er kun:

`verified-human-dc-l16-pilot-start-authorization-only`

Dette proof er derfor **ikke** et start receipt og er ikke execution evidence.

## Replay/consumption boundary

ADR-DC-024 opretter ingen replay-ledger og consumer ikke start-noncen. En senere,
separat boundary skal atomisk og replay-safe consume exact authorization proof,
revalidere freshness og preflight binding og først derefter kunne etablere en
start receipt.

Den boundary må ikke antage, at `pilot_start_authorized=true` betyder
`product_pilot_started=true`.

## Ikke en del af denne ADR

Denne slice:

- opretter ikke et faktisk menneskeligt signeret start-artifact;
- consumer ikke authorization eller nonce;
- registrerer ingen DevControl command;
- starter ingen task registry eller executor;
- ændrer ingen backend/Desktop/Android-produktkode;
- udfører ingen local commit;
- udfører ingen remote write, push, PR mutation, merge, release eller deploy;
- giver ingen production activation authority.

## Falsificerbare kontrakter

ADR-DC-024 skal mindst afvise:

1. ADR-DC-023 proof med failed preflight;
2. rebound/tampered nested preflight proof;
3. caller-konstrueret ADR-DC-023 proof med forged signature-hash/key metadata;
4. missing detached ADR-DC-023 signature;
5. invalid/revoked/untrusted detached ADR-DC-023 signature ved fresh host verification;
6. human authorizer som ikke matcher exact ADR-DC-021 selection maker;
7. human authorizer som er preflight-observer eller host-attestor;
8. placeholder start nonce;
9. authorization før preflight verification;
10. authorization window over 15 minutter;
11. verification efter expiry;
12. wrong human signer actor eller issuer domain;
13. nonce rebinding uden ny human signatur;
14. caller-selected production verifier;
15. replay der sætter consumed/product-start/local-commit/remote/publication/activation authority true.

Kontrakten skal køre gennem den eksisterende Stage-B support-chain uden at
udvide den låste top-level `tests/*.py` inventory.

## Næste authority-led

En senere ADR kan definere replay-safe consumption/start-receipt boundary. Den
skal kræve exact ADR-DC-024 proof og må fortsat holde remote publication,
release, deploy og production activation separat.
