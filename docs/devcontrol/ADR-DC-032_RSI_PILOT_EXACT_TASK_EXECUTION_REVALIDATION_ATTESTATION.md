# ADR-DC-032 — Host-attested exact-task revalidation without execution admission authority

**Dato:** 14/09-2026  
**Status:** foreslået til beslutning  
**Production activation:** false

## Kontekst

ADR-DC-031 binder de 25 fresh-revalidation evidence-referencer, som ADR-DC-029 kræver før en senere exact-task execution admission, til ét exact ADR-DC-030 human task-execution authorization proof. Packetet beviser imidlertid kun binding og completeness; det verificerer ikke host-state eller de konkrete artifacts bag evidence-digests.

Et ADR-DC-031 packet må derfor ikke konverteres direkte til execution admission eller `task_execution_authorized=true`.

## Beslutning

Der indføres en separat host-attesteret Ed25519 verification boundary over ét exact ADR-DC-031 packet.

Attestationens signerede bytes indlejrer hele packetet og binder eksplicit:

- packet SHA-256;
- exact ADR-DC-030 authorization-proof SHA-256;
- ADR-DC-030 detached human-signature SHA-256;
- exact ADR-DC-028 admission-attestation proof SHA-256;
- ADR-DC-028 detached host-signature SHA-256;
- signerede execution nonce;
- samtlige 25 ADR-DC-031 evidence-referencer;
- packetets repository/base/main/trial/operator/task/workspace lineage transitivt gennem det indlejrede proof.

Attestation kan ikke ligge før ADR-DC-031 observationen eller efter ADR-DC-030 human authorization expiry.

## 25 signerede resultater

Attestationen indeholder præcis ét boolsk resultat for hvert ADR-DC-029/031 krav:

1. fresh host-attestation reverified;
2. fresh live consumption revalidated;
3. fresh human task-execution authorization verified;
4. one-shot execution nonce verified;
5. host-local execution-admission ledger verified;
6. exact allowlisted task-registry entry verified;
7. exact selected task verified;
8. canonical workspace revalidated;
9. exact source/base/head binding verified;
10. exact toolchain binding verified;
11. feature flag enabled reobserved;
12. native Windows isolation revalidated;
13. trusted-Git closure revalidated;
14. kill-switch armed revalidated;
15. revoke not asserted revalidated;
16. restart recovery revalidated;
17. network writes blocked revalidated;
18. credentials absent revalidated;
19. general shell forbidden verified;
20. model-defined commands forbidden verified;
21. unattended cadence forbidden verified;
22. exact fixed command plan verified;
23. bounded execution budget verified;
24. manual operator invocation verified;
25. post-execution receipt capability verified.

Et cryptographically valid proof sætter altid `host_attestation_verified=true` og `execution_revalidation_observed=true`. `execution_revalidation_satisfied=true` må kun forekomme, når **alle 25** signerede resultater er exact `true`.

Et gyldigt signeret failed check bevares som audit-evidence med `execution_revalidation_observed=true` og `execution_revalidation_satisfied=false`.

## Attestationens evidensgrænse

ADR-DC-032 er en kryptografisk host-attestation af attestorens 25 signerede resultater. Modulet genindlæser eller måler ikke selv de 25 host-artifacts, operativsystemets kernel-state eller de konkrete evidence-kilder bag ADR-DC-031-digests.

`execution_revalidation_satisfied=true` betyder derfor præcist, at en betroet host-signer har attesteret alle 25 checks som `true` for det exact-bound packet, og at signaturen samt upstream provenance er verificeret. Det er ikke et selvstændigt kernel-telemetry- eller artifact-collection proof.

## Fresh upstream provenance

Production må ikke stole på indlejrede/deserialiserede ADR-DC-028 eller ADR-DC-030 proofs som selv-autentificerende.

Før ADR-DC-032's egen detached signatur accepteres, skal production på samme aktuelle verification-tid:

1. kræve den detached ADR-DC-028 host-attestation signatur;
2. re-verificere ADR-DC-028 mod dens canonical host-controlled verification-only keyring;
3. kræve den detached ADR-DC-030 human execution-authorization signatur;
4. re-verificere ADR-DC-030 mod dens separate canonical host-controlled human-authority keyring;
5. kræve at den fresh ADR-DC-030 verification reproducerer alle stabile proof-semantikker fra det exact proof, som ADR-DC-031 packetet binder.

Caller-valgte verifiers er ikke production authority.

## ADR-DC-032 trust root

ADR-DC-032 bruger en separat host-admin-kontrolleret verification-only Ed25519 keyring:

- POSIX: `/etc/modelrig/devcontrol/authority/rsi-pilot-exact-task-execution-revalidation-attestation-keyring-v1.json`
- Windows: `C:\Program Files\ModelRig\DevControl\authority\rsi-pilot-exact-task-execution-revalidation-attestation-keyring-v1.json`

Production verification kræver elevated host operator. Private signing keys, signer og credential transport er ikke en del af ModelRig runtime eller keyring.

## Authority boundary

Selv et fully satisfied ADR-DC-032 proof holder obligatorisk:

- `task_execution_admission_observed=false`;
- `task_execution_authorized=false`;
- `task_execution_started=false`;
- `integration_ready=false`;
- `product_pilot_started=false`;
- `local_commit_authorized=false`;
- remote write/push/PR mutation/merge/release/deploy=false;
- production activation=false.

Authority er kun:

`verified-dc-l16-exact-task-execution-revalidation-attestation-only`

ADR-DC-032 verifierer den signerede revalidation-attestation og dens exact provenance; den consumer ikke execution authorization/noncen, udsteder ikke execution admission og kalder ingen executor.

## Næste boundary

En senere separat host-local replay-safe boundary kan bruge et fully satisfied exact ADR-DC-032 proof som én nødvendig input til at consume den signerede execution authorization/nonce og udstede en one-shot execution-admission capability.

Den senere admission må fortsat være adskilt fra selve executor-transaktionen. Ingen task bør køre som sideeffekt af verification eller admission, og durable/reloaded admission-evidence må ikke alene kunne genvinde live execution authority.

## Ikke omfattet

Denne ADR:

- opretter ingen rigtig human eller host signatur;
- consumer ingen authorization eller nonce;
- opretter ingen execution-admission ledger marker;
- registrerer ingen command eller task-registry entry;
- kalder ingen subprocess/executor;
- muterer ikke workspace eller Git/GitHub;
- giver ingen local commit-, remote publication- eller production authority;
- starter ikke product pilot eller task execution.

`production_activation=false`.
