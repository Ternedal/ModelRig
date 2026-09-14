# ADR-DC-023 — Host-attested runtime-preflight proof over exact ADR-DC-022 evidence packet

**Dato:** 14/09-2026  
**Status:** foreslået til beslutning  
**production_activation:** `false`

## Kontekst

ADR-DC-022 binder de tolv DC-L16 preflight-krav til hver sin SHA-256 evidence-
reference og til exact ADR-DC-021 human selection + ADR-DC-017 requirements. Det
packet er med vilje ikke et proof: `evidence_verified=false`,
`preflight_observed=false` og `preflight_satisfied=false`.

Det næste authority-hul er at attestere, om de tolv packet-bound evidences faktisk
opfylder deres krav, uden at miste per-check chain-of-custody og uden at forveksle
en grøn preflight med pilot-start authority.

Parallelle eksperimenter, der signerede løse booleans uden at indlejre ADR-DC-022
packetet, er ikke denne beslutning. ADR-DC-023 gør packetet til den canonical
input-boundary.

## Beslutning

Der indføres et separat host-attestation claim/proof-lag oven på exact
`PilotRuntimePreflightObservationPacket` fra ADR-DC-022.

### 1. Hele evidence-packetet ligger i de signerede bytes

Attestation-claimen indlejrer hele ADR-DC-022 packetet og binder dets canonical
SHA-256. Dermed ligger følgende transitivt i den detached Ed25519-signatur:

- exact ADR-DC-021 human-selection proof;
- exact ADR-DC-017 preflight requirements;
- trial scope, base/requested-main, operator surface, task og workspace root;
- local-commit scope;
- alle tolv individuelle evidence SHA-256-digests;
- packetets observer actor og observation time.

Et evidence-digest kan derfor ikke ændres uden at packet-hash og signatur brydes.

### 2. Attestation-resultater er signerede, men claimen giver ingen authority

Claimen indeholder ét boolsk resultat for hvert af de tolv krav:

- feature flag off;
- pilot runtime;
- native Windows isolation;
- trusted Git closure;
- kill switch prearm;
- restart/revoke prearm;
- network write block;
- credentials absent;
- unattended cadence forbidden;
- off-state import block;
- exact source binding;
- receipt binding.

Claim-builderen læser ingen host-state og kan ikke selv verificere disse værdier.
Den producerer kun canonical bytes til ekstern signering. Derfor forbliver i
claimen:

- `host_attestation_verified=false`;
- `preflight_observed=false`;
- `preflight_satisfied=false`;
- alle execution/publication/activation-authorities false.

### 3. Separat host-controlled Ed25519 trust-root

Et claim kan kun blive til proof gennem en detached Ed25519-signatur fra det
separate issuer-system:

`kaliv-rsi-dc-l16-runtime-preflight-attestor-v1`

Signeren skal være samme actor som ADR-DC-022 packetets `observer_actor_id`, og
signature time skal være claimens canonical `attested_at_utc`.

Production-facaden accepterer ikke caller-valgt verifier. Den resolver kun en
verification-only public-key keyring fra canonical host-controlled DevControl
path og kræver elevated host operator. Private signing keys, signer og credential
transport er ikke del af repo/runtime.

### 4. Verified failure bevares som audit-evidence

Et cryptographically valid proof sætter altid:

- `host_attestation_verified=true`;
- `preflight_observed=true`.

`preflight_satisfied=true` er kun tilladt, når alle tolv signerede resultater er
exact `true`. Hvis ét eller flere resultater er false, er proofet fortsat gyldigt
host-attested audit-evidence med `preflight_satisfied=false`.

Replay/deserialisering genberegner denne relation og afviser både falsk positiv
og falsk negativ satisfaction-state.

### 5. Preflight satisfaction er ikke pilot-start authority

Selv et fully green ADR-DC-023 proof holder følgende false:

- `integration_ready`;
- `pilot_start_authorized`;
- `product_pilot_started`;
- `local_commit_authorized`;
- `remote_write_authorized`;
- `push_authorized`;
- `pr_mutation_authorized`;
- `merge_authorized`;
- `release_authorized`;
- `deploy_authorized`;
- `production_activation_authorized`.

Proof-authority er kun:

`verified-dc-l16-runtime-preflight-attestation-only`

Et senere, separat authority-step er fortsat nødvendigt før product integration
kan erklæres ready eller en pilot kan startes.

## Ikke en del af denne ADR

Denne slice:

- opretter ikke et faktisk signed host-attestation artifact;
- læser ikke feature flags eller andre host-signaler selv;
- starter ingen runtime observer, executor eller task registry;
- ændrer ingen backend/Desktop/Android-produktkode;
- registrerer ingen DevControl commands;
- udfører ingen local commit, remote write, push, PR mutation, merge, release,
  deploy eller production activation.

## Falsificerbare kontrakter

ADR-DC-023 skal mindst afvise:

1. caller-selected production verifier;
2. forkert issuer-system eller signer actor;
3. claim der predaterer ADR-DC-022 packetet;
4. ændret per-check evidence digest uden ny signatur;
5. ændret attestation-resultat uden ny signatur;
6. proof med `preflight_satisfied=true`, hvis en signerede check er false;
7. proof med `preflight_satisfied=false`, hvis alle signerede checks er true;
8. enhver local-commit, pilot, remote, publication eller activation escalation ved replay.

Kontrakten skal køre gennem den eksisterende Stage-B support-chain uden at udvide
den låste top-level `tests/*.py` inventory.
