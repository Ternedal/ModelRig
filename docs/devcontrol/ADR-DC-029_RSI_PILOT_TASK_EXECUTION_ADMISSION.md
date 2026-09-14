# ADR-DC-029 — Replay-safe one-shot admission for one exact DC-L16 pilot task

**Dato:** 14/09-2026  
**Status:** Foreslået til beslutning

## Kontekst

ADR-DC-028 kan kryptografisk bevise, at alle 21 execution-admission checks for ét
exact ADR-DC-027 packet er host-attesterede og satisfied. Det proof giver med
vilje stadig ikke task-execution authority.

ADR-DC-029 er den næste og smalleste authority-grænse. Den må udstede én live,
host-local admission til præcis den allerede valgte pilot-task, men må ikke
udføre tasken.

## Beslutning

En execution-admission kræver samtidig:

1. ét exact, satisfied `PilotExecutionAdmissionAttestationProof` fra ADR-DC-028;
2. fresh kryptografisk re-verifikation af den detached ADR-DC-028-signatur gennem
   den canonical host-pinned verification-only trust-root;
3. exact stable-proof identity mellem supplied og fresh ADR-DC-028 proof;
4. den oprindelige live ADR-DC-025 start-consumption transaction-provenance;
5. admission inden for højst 300 sekunder fra ADR-DC-028 attestationstidspunktet;
6. en canonical host-admin-kontrolleret create-once admission-ledger.

Production må ikke acceptere caller-valgt ledger, verifier eller clock.

## Stable one-shot identity og exact evidence binding

Replay-keyen skal være stabil på tværs af ny host-attestation af det samme start-
consumption scope. Den binder derfor kun den authority-identitet, der ikke må
kunne fornyes ved re-attestation:

- ADR-DC-025 `start_receipt_sha256`;
- signed `start_nonce_sha256`;
- exact `selected_pilot_task_id`.

ADR-DC-028 `attestation_sha256` må **ikke** indgå i replay-keyen. Ellers ville en
ny gyldig host-attestation over samme ADR-DC-025 consumption og samme task kunne
producere en ny ledger-key og dermed omgå one-shot-grænsen.

Den exact ADR-DC-028 attestation for den konkrete admission forbliver stadig
bundet som evidens i replay-marker og receipt. Receiptet binder desuden:

- exact ADR-DC-028 proof + proof digest;
- exact ADR-DC-028 `attestation_sha256`;
- detached attestation-signaturens digest;
- ADR-DC-027 packet digest;
- exact workspace-root digest;
- det menneskeligt signerede local-commit scope som upper bound;
- canonical admission-ledger identity;
- fresh verification- og admission-timestamps.

Task-, workspace-, nonce-, receipt-, proof- eller attestation-rebinding må ikke
svække evidensbindingen. En ny ADR-DC-028 attestation over samme start-receipt,
nonce og task rammer stadig samme create-once replay-slot og kan derfor ikke
udstede en anden one-shot admission.

## Live authority og reload

Et successful receipt registreres kun som live transaction-authenticated, når den
canonical final receipt og dens permanente replay-marker stadig matcher de bytes,
som blev publiceret i den aktuelle proces.

`transaction_authenticated` serialiseres ikke. Et durable/deserialiseret ADR-029
receipt er derfor historisk evidens, men kan ikke genvinde live execution
authority efter reload, proces-genstart eller fork.

Det samme gælder den nested ADR-DC-025 receipt: production kontrollerer dens live
transaction-provenance før snapshotting. Den serialiserede kopi i ADR-029
receiptet er ikke selv execution authority.

## Authority

Et valid live ADR-DC-029 receipt må sætte:

- `host_replay_guard_committed=true`;
- `one_shot_execution_required=true`;
- `execution_admission_satisfied=true`;
- `task_execution_authorized=true`.

Det skal samtidig holde:

- `global_replay_safe=false`;
- `execution_consumed=false`;
- `integration_ready=false`;
- `product_pilot_started=false`;
- `local_commit_authorized=false`;
- remote write/push/PR mutation/merge/release/deploy=false;
- `production_activation_authorized=false`.

Authority-stringen er kun:

`host-admitted-one-dc-l16-pilot-task-execution-only`

## Ikke en executor

ADR-DC-029 registrerer ingen normal ModelRig-command, starter ingen subprocess,
udfører ingen shell/task, skriver ikke workspace/Git og foretager ingen network-
eller GitHub-mutation.

En senere separat executor-boundary skal kræve det exact live ADR-DC-029 receipt,
consume det one-shot og udstede separat execution evidence. Først det senere led
må udføre den allowlistede task.

## Failure semantics

Replay, re-attestation replay, stale admission, failed ADR-DC-028 check, manglende
live ADR-DC-025 provenance, fresh-proof drift, ledger collision, partial
publication eller post-reservation expiry fejler lukket. En permanent reservation
må ikke slettes for at genåbne authority efter usikker/crashed publication.

## Konsekvens

ADR-DC-029 flytter DC-L16-kæden fra "verified admission conditions" til "one exact
task is live-admitted for one later execution". Det er stadig ikke en product
pilot start eller production activation.

`production_activation=false`.
