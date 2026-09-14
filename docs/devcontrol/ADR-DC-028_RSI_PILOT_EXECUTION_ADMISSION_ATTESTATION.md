# ADR-DC-028 — Host-attested execution-admission verification without task execution authority

**Dato 14/09-2026. Status: foreslået til beslutning.**

## Context

ADR-DC-027 binder 21 evidence-digests til ét exact ADR-DC-026 requirements-manifest og samme ADR-DC-025 start-receipt lineage. Packetet er bevidst inert: det fortæller kun hvilke evidence-artifacts der hører til den konkrete admission-scope, ikke om de faktisk er sande.

Før task execution overhovedet kan overvejes, skal de 21 checks kunne attesteres under en host-kontrolleret trust-root uden at gøre selve attestation-proofet til execution authority.

## Decision

Vi indfører to artifacts:

- `kaliv-rsi-dc-l16-pilot-execution-admission-attestation/v1`;
- `kaliv-rsi-dc-l16-pilot-execution-admission-attestation-proof/v1`.

Attestation-claimet indlejrer hele exact ADR-DC-027 packetet, binder `packet_sha256` og `start_receipt_sha256`, og indeholder præcis ét boolsk resultat for hvert af de 21 requirements.

Claimet er kun externally-signable evidence. Det har altid:

- `host_attestation_verified=false`;
- `execution_admission_observed=false`;
- `execution_admission_satisfied=false`;
- `task_execution_authorized=false`;
- `product_pilot_started=false`;
- alle local/remote publication/activation-authorities false.

## Host-pinned trust

Production-verifikation accepterer ikke en caller-valgt verifier. Den resolver kun en verification-only Ed25519 keyring fra canonical host-controlled authority state:

- Windows: `C:\Program Files\ModelRig\DevControl\authority\rsi-pilot-execution-admission-attestation-keyring-v1.json`;
- POSIX: `/etc/modelrig/devcontrol/authority/rsi-pilot-execution-admission-attestation-keyring-v1.json`.

Verification kræver elevated host operator og genbruger den eksisterende host-control/keyring-hærdning. Private/injectable verifier-seams findes kun til deterministic adversarial tests.

Attestation-signeren skal være packetets `observer_actor_id`; signaturens time skal matche claimets `attested_at_utc`, og claimet må ikke predatere ADR-DC-027 observationen.

## Semantics of a verified proof

En cryptographically valid proof kan kun sætte:

- `host_attestation_verified=true`;
- `execution_admission_observed=true`;
- `execution_admission_satisfied=true` **kun hvis alle 21 signerede resultater er true**.

Et gyldigt signeret failed check bevares som observed men `execution_admission_satisfied=false`.

Selv et fuldt grønt proof holder obligatorisk:

- `task_execution_authorized=false`;
- `integration_ready=false`;
- `product_pilot_started=false`;
- `local_commit_authorized=false`;
- remote write/push/PR mutation/merge/release/deploy=false;
- `production_activation_authorized=false`.

Authority er kun `verified-dc-l16-pilot-execution-admission-attestation-only`.

## Important limitation

ADR-DC-028 er en **host-attestation boundary**, ikke kernel telemetry og ikke en executor. Den cryptographically binder en host-attestors 21 resultater til exact evidence packet. Den giver ikke i sig selv en command registry, workspace mutation eller ret til at køre den valgte task.

Den senere execution-admission boundary skal fortsat fail-closed revalidere den exact proof/scope og må kun autorisere den ene allowlistede task under manual operator invocation. Local commit må aldrig overstige den human-signerede upper bound; remote write, push, PR mutation, merge, release, deploy og production activation forbliver separat authority.

## Replay / rebinding

Claim og proof indlejrer exact packet/attestation og canonical-roundtrip-validerer alle nested artifacts. `packet_sha256` og `start_receipt_sha256` skal matche de indlejrede bytes. Deserialisering kan ikke løfte authority-felter.

## Next boundary

Næste separate led er en explicit execution-admission/executor boundary for præcis den valgte task. Den skal kræve et satisfied ADR-DC-028 proof og må ikke genbruge proofet som remote/publication authority.

Kæden bliver:

`ADR-025 consumed start receipt → ADR-026 requirements → ADR-027 evidence packet → ADR-028 host-attested verification → future exact task execution admission`.

Ingen pilot-task udføres af ADR-DC-028.
