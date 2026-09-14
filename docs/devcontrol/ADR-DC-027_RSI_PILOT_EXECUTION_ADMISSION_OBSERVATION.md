# ADR-DC-027 — Exact-bound execution-admission observation packet before host verification

**Dato 14/09-2026. Status: foreslået til beslutning.**

## Context

ADR-DC-026 fastlåser 21 conjunctive krav, som et senere DC-L16 execution-admission-led skal bevise over ét exact ADR-DC-025 start-consumption receipt. Requirements-manifestet observerer ingen host-state og kan ikke give task execution authority.

Før en host-kontrolleret verifier kan vurdere de 21 krav, skal det konkrete evidence-set bindes til præcis det ADR-DC-026 manifest og den samme start-receipt lineage. Ellers kan evidence fra en anden trial, task, workspace eller consumption blive genbrugt ved rebinding.

## Decision

Vi indfører et inert `kaliv-rsi-dc-l16-pilot-execution-admission-observation-packet/v1`.

Packetet indlejrer hele exact ADR-DC-026 requirements-manifestet og binder:

- `admission_requirements_sha256`;
- `start_receipt_sha256`;
- en explicit observation ID, observer actor og canonical UTC observation time;
- præcis én SHA-256 evidence-reference for hvert af ADR-DC-026's 21 admission-krav.

De 21 evidence-slots er:

1. canonical host-ledger revalidation;
2. fresh upstream ADR-023/024 authority re-verification;
3. live consumption receipt at admission;
4. allowlisted task registry;
5. exact selected task;
6. canonical workspace revalidation;
7. feature flag enabled observation;
8. native Windows isolation;
9. trusted-Git closure;
10. kill switch armed;
11. revoke not asserted;
12. restart recovery proof;
13. network writes blocked;
14. credentials absent;
15. unattended cadence forbidden;
16. general shell forbidden;
17. model-defined commands forbidden;
18. exact source/base/head binding;
19. exact toolchain binding;
20. execution-receipt capability/evidence;
21. manual operator invocation.

Observation time må ikke ligge før ADR-DC-025 consumption time.

## Evidence is not verification

`observation_set_complete=true` betyder kun, at alle 21 digest-slots er til stede og exact-bound til samme ADR-DC-026 requirements manifest.

Denne slice:

- læser ingen host-state;
- åbner ingen ledger;
- verificerer ingen feature flag/runtime/isolation/toolchain evidence;
- registrerer ingen task;
- udfører ingen command;
- skaber ingen execution receipt;
- giver ingen workspace- eller Git-mutation.

Derfor er `evidence_verified=false` obligatorisk.

## Authority stop

Et gyldigt packet holder altid:

- `execution_admission_observed=false`;
- `task_execution_authorized=false`;
- `integration_ready=false`;
- `product_pilot_started=false`;
- `local_commit_authorized=false`;
- remote write/push/PR mutation/merge/release/deploy=false;
- `production_activation_authorized=false`.

Authority er kun `dc-l16-pilot-execution-admission-observation-packet-only`.

Ingen deserialisering eller canonical roundtrip må løfte disse felter.

## Exact binding / replay semantics

Packetet accepterer kun et exact `PilotExecutionAdmissionRequirements` object, som selv består canonical replay-validering. Requirements SHA og nested `start_receipt_sha256` skal matche de indlejrede bytes.

Et komplet evidence-set med manglende eller ekstra digest-key afvises. Alle evidence-referencer skal være lowercase 64-hex SHA-256. Packetet kan deserialiseres som audit-evidence, men det genvinder hverken ADR-DC-025 live transaction provenance eller senere host-verification authority.

## Next boundary

Næste separate boundary skal være en host-kontrolleret verification/attestation over exact ADR-DC-027 packet. Den skal revalidere den relevante live host-state og må kun derefter afgøre, om execution admission faktisk er observeret/satisfied.

Selv en fremtidig green host-verification er ikke automatisk task execution, medmindre en særskilt execution-admission/executor boundary eksplicit autoriserer exact selected task under den signerede scope.

## Consequences

Kæden bliver:

`ADR-025 consumed start receipt → ADR-026 requirements → ADR-027 exact evidence packet → future host verification → future explicit execution admission`.

Ingen merge, release, deploy eller production activation følger af ADR-DC-027.
