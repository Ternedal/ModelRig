# ADR-DC-029 — Requirements before one exact task-execution admission

**Dato 14/09-2026. Status: foreslået til beslutning.**

## Context

ADR-DC-028 kan verificere en host-attesteret, fully satisfied execution-admission observation over exact ADR-DC-027 evidence. Det proof er med vilje ikke task-execution authority: `task_execution_authorized=false`.

At alle 21 host-checks er grønne er derfor stadig kun en nødvendig forudsætning. Den næste authority-grænse er stærkere: den skal kunne autorisere præcis én senere task execution uden at forveksle et audit-proof med et menneskeligt execution-GO.

Brugerens generelle ønske om at fortsætte udviklingsarbejdet er ikke i sig selv et kryptografisk eller one-shot execution-artifact. Derfor fastlåser denne ADR kun requirements og giver ingen task execution authority.

## Decision

Vi indfører et inert `kaliv-rsi-dc-l16-exact-task-execution-admission-requirements/v1` afledt af ét exact, fully satisfied `PilotExecutionAdmissionAttestationProof` fra ADR-DC-028.

Manifestet binder hele proofet og dets canonical SHA-256 samt:

- attestation SHA-256 og detached signature SHA-256;
- ADR-DC-027 packet SHA-256;
- ADR-DC-025 start-receipt SHA-256;
- repository, base SHA og requested main SHA;
- trial ID og operator surface;
- exact selected pilot task ID;
- workspace-root digest;
- det menneskeligt signerede local-commit scope som upper bound.

Et ADR-DC-028 proof med `execution_admission_satisfied=false` kan ikke bruges.

## Mandatory later gates

En senere exact task-execution admission skal conjunctively bevise alle følgende:

1. fresh host-verification af ADR-DC-028 attestation/provenance;
2. fresh live revalidation af ADR-DC-025 consumption lineage;
3. en **separat, fresh human task-execution authorization**;
4. en separat one-shot execution nonce;
5. canonical host-local execution-admission replay ledger;
6. exact allowlisted task-registry entry;
7. exact selected task identity;
8. canonical workspace revalidation;
9. exact source/base/head binding;
10. exact toolchain binding;
11. feature flag enabled re-observation;
12. native Windows isolation revalidation;
13. trusted-Git closure revalidation;
14. kill switch armed revalidation;
15. revoke-not-asserted revalidation;
16. restart-recovery revalidation;
17. network writes blocked revalidation;
18. credentials absent revalidation;
19. general shell forbidden;
20. model-defined commands forbidden;
21. unattended cadence forbidden;
22. exact fixed command plan;
23. bounded execution budget;
24. manual operator invocation;
25. post-execution receipt.

Ingen af disse krav må degraderes til optional mode.

## Human terminal authority

`fresh_human_task_execution_authorization_required=true` er bevidst separat fra både ADR-DC-024 pilot-start authorization og ADR-DC-028 host-attestation.

Den senere human authorization skal være exact-bound til ADR-DC-028 proofet, exact selected task, workspace, command plan, execution nonce, source/toolchain og den signerede local-commit upper bound. Den må ikke udvide remote/publication/activation scope.

Denne ADR opretter ingen sådan signatur og antager ikke, at en chatbesked alene er det durable authority-artifact.

## Authority stop

Et gyldigt ADR-DC-029 requirements-manifest holder obligatorisk:

- `task_execution_admission_observed=false`;
- `task_execution_authorized=false`;
- `task_execution_started=false`;
- `integration_ready=false`;
- `product_pilot_started=false`;
- `local_commit_authorized=false`;
- remote write/push/PR mutation/merge/release/deploy=false;
- `production_activation_authorized=false`.

Authority er kun `dc-l16-exact-task-execution-admission-requirements-only`.

Manifestet registrerer ingen command, starter ingen executor, ændrer ingen workspace-bytes og skriver ikke til Git/GitHub.

## Replay and narrowing

Nested ADR-DC-028 proof replay-valideres canonical. Alle proof-, packet-, receipt-, task- og workspace-bindinger revalideres ved deserialization.

`local_commits_allowed_by_human_scope` er kun en arvet upper bound. ADR-DC-029 giver ikke local-commit authority; en senere execution/admission boundary skal fortsat narrowe dette eksplicit og kan aldrig løfte remote writes, push, PR mutation, merge, release, deploy eller activation.

## Next boundary

Næste sikre boundary er en separat human-signed exact-task execution authorization claim/proof, stadig uden at udføre tasken. Først derefter kan en host-local one-shot consumption/admission boundary overvejes.

Selve executor-kaldet skal forblive endnu en separat transaktion, så authorization, consumption/admission og execution ikke kollapser til samme step.

`production_activation=false`.
