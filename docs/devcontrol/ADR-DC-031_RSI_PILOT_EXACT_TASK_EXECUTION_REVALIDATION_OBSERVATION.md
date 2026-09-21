# ADR-DC-031 — Exact-task execution revalidation observation before host verification

**Dato:** 14/09-2026  
**Status:** foreslået til beslutning  
**Production activation:** false

## Kontekst

ADR-DC-029 fastlåser 25 conjunctive krav, som skal være opfyldt umiddelbart før en senere one-shot task-execution admission. ADR-DC-030 tilføjer et separat, kortlivet human-signed exact-task execution authorization proof, men verificerer ikke de øvrige runtime-, ledger-, isolation-, task-registry- eller toolchain-gates på ny.

Det er derfor ikke sikkert at konvertere et ADR-DC-030 proof direkte til `task_execution_authorized=true`. Et sådant spring ville kunne genbruge ældre ADR-DC-028 evidence og omgå ADR-DC-029's krav om fresh revalidation.

## Beslutning

Der indføres et separat, **ikke-autoriserende observation packet** for exact-task execution revalidation.

Packetet indlejrer ét exact, replay-validt ADR-DC-030 `PilotExactTaskExecutionAuthorizationProof` og binder dets:

- proof- og detached-signatur SHA-256;
- ADR-DC-029 requirements SHA-256;
- ADR-DC-028 proof- og detached-signatur SHA-256;
- ADR-DC-025 start-receipt SHA-256;
- signerede execution nonce;
- repository/base/main;
- trial og operator surface;
- exact selected task;
- workspace-root digest;
- human-signed local-commit upper bound.

Observationen skal ligge efter ADR-DC-030 verification og senest ved den signerede authorization expiry. Et udløbet human execution authorization kan derfor ikke få et nyt observation packet.

## 25 exact evidence slots

Packetet kræver præcis én non-placeholder SHA-256 reference for hvert ADR-DC-029 krav:

1. fresh host-attestation re-verification;
2. fresh live ADR-DC-025 consumption revalidation;
3. fresh human task-execution authorization;
4. one-shot execution nonce;
5. canonical host-local execution-admission ledger;
6. exact allowlisted task-registry entry;
7. exact selected task;
8. canonical workspace revalidation;
9. exact source/base/head binding;
10. exact toolchain binding;
11. enabled feature-flag re-observation;
12. native Windows isolation revalidation;
13. trusted-Git closure revalidation;
14. kill-switch armed revalidation;
15. revoke-not-asserted revalidation;
16. restart-recovery revalidation;
17. network-write blocked revalidation;
18. credentials-absent revalidation;
19. general shell forbidden;
20. model-defined commands forbidden;
21. unattended cadence forbidden;
22. exact fixed command plan;
23. bounded execution budget;
24. manual operator invocation;
25. post-execution receipt capability/evidence.

To slots er stærkere end en fri evidence-reference:

- `fresh_human_task_execution_authorization_evidence_sha256` skal være **exact ADR-DC-030 proof SHA-256**;
- `one_shot_execution_nonce_evidence_sha256` skal være **exact signerede execution nonce**.

Dermed kan packetet ikke rebinde den menneskelige authorization eller one-shot identiteten til andre bytes.

## Authority boundary

`observation_set_complete=true` betyder kun, at alle 25 slots er til stede og exact-bound. `human_authorization_proof_bound=true` betyder kun, at exact ADR-DC-030 proofet er indlejret og digest-bundet.

Packetet udfører ingen host-I/O og verificerer ingen referenced evidence. Følgende er derfor obligatorisk false:

- `evidence_verified`;
- `task_execution_admission_observed`;
- `task_execution_authorized`;
- `task_execution_started`;
- `integration_ready`;
- `product_pilot_started`;
- `local_commit_authorized`;
- remote write/push/PR mutation/merge/release/deploy;
- production activation.

Authority er kun:

`dc-l16-exact-task-execution-revalidation-observation-packet-only`

## Næste boundary

En senere separat host-controlled attestation boundary skal fresh verificere:

- ADR-DC-030 human signature;
- ADR-DC-028 host-attestation signature;
- live ADR-DC-025 transaction/ledger state;
- de konkrete artifacts bag alle 25 evidence-digests.

Selv et grønt attestation proof bør ikke i sig selv køre tasken. Replay-safe one-shot consumption/admission og actual executor transaction forbliver separate senere boundaries.

## Ikke omfattet

Denne ADR:

- opretter ingen rigtig human signatur;
- læser ingen feature flags, workspace, Git state, credentials eller host state;
- registrerer ingen command;
- opretter ingen task registry entry;
- kalder ingen subprocess/executor;
- muterer ikke workspace eller Git/GitHub;
- giver ingen local commit-, remote publication- eller production authority;
- starter ikke product pilot eller task execution.

`production_activation=false`.
