# ADR-DC-025 — Replay-safe host-local consumption of one DC-L16 pilot-start authorization

**Dato 14/09-2026. Status: foreslået til beslutning.**

## Context

ADR-DC-024 kan verificere en kortlivet, human-signeret authorization til præcis én fremtidig lokal DC-L16 pilot-start. Det verificerede proof er med vilje stadig `start_consumed=false` og `product_pilot_started=false`.

Et serialiserbart ADR-DC-024 proof må ikke i sig selv blive genbrugelig execution authority. Før en senere executor kan starte noget, skal det konkrete start-intent brændes præcis én gang i host-kontrolleret replay-state.

## Decision

Vi indfører en separat consumption-boundary mellem ADR-DC-024 og enhver senere product execution.

Production entrypointet accepterer ikke et caller-supplied `PilotStartAuthorizationProof` som authority. Det accepterer de oprindelige ADR-023/024 artifacts og detached signatures og kalder ADR-DC-024's host-pinnede production verification igen. Dermed re-verificeres også ADR-DC-023-signaturen frisk før consumption.

Efter fresh verification publiceres ét canonical consumption receipt med `durable_publication.create_once_file()` i en fast, pre-provisioned host-admin-kontrolleret ledger:

- POSIX: `/var/lib/modelrig/devcontrol/rsi-pilot-start-ledger-v1`
- Windows: `C:\Program Files\ModelRig\DevControl\state\rsi-pilot-start-ledger-v1`

Production kræver elevated host operator og genbruger den eksisterende ACL/DACL-aware host-control validation. Caller kan ikke vælge ledger-path, clock eller verifier.

Marker-navnet afledes kun af SHA-256 over exact ADR-024 proof identity, authorization identity og `start_nonce_sha256`. Publication er no-overwrite. En eksisterende marker afvises som replay/collision og overskrives aldrig.

Efter publication læses de eksakte bytes tilbage gennem et regular-file descriptor. Hvis readback ikke matcher, fjernes markeren ikke: authorizationen forbliver brændt fail-closed efter en tvetydig post-publication hændelse.

## Receipt semantics

Et gyldigt `kaliv-rsi-dc-l16-pilot-start-consumption-receipt/v1` binder exact:

- ADR-024 proof SHA-256 og authorization SHA-256;
- ADR-023 preflight proof/attestation/packet;
- ADR-021 selection, ADR-020 candidate, requirements og trial scope;
- `start_nonce_sha256`;
- repository/base/requested-main;
- trial, operator surface, selected task og workspace digest;
- local-commit policy fra den signerede scope;
- canonical consumption time.

Receiptet sætter kun:

- `host_replay_guard_committed=true`;
- `start_consumed=true`.

Det holder eksplicit:

- `global_replay_safe=false`;
- `integration_ready=false`;
- `pilot_start_authorized=false` efter consumption;
- `product_pilot_started=false`;
- `local_commit_authorized=false`;
- remote write/push/PR mutation/merge/release/deploy=false;
- `production_activation_authorized=false`.

Authority er kun `consumed-dc-l16-pilot-start-intent-only`.

`global_replay_safe=false` er bevidst: en canonical host-admin ledger beskytter mod replay på den konkrete host, men overclaimer ikke distributed/global one-time semantics eller sikkerhed mod kompromitteret host administrator/root.

## Deliberate absences

Denne ADR registrerer ingen command, vælger ingen executor og udfører ingen pilot-task. Den skaber ingen local commit og ingen remote/network/Git/GitHub publication authority.

En senere separat boundary skal kræve det exact consumption receipt og etablere execution/start receipt semantics, før `product_pilot_started` kan blive true.

## Failure semantics

- stale/expired authorization afvises før publication;
- malformed eller broadened ADR-024 proof afvises;
- eksisterende replay marker afvises uden overwrite;
- unsafe/unprivileged/non-host-controlled production ledger afvises;
- publication/readback ambiguity brænder intentet fail-closed frem for at gøre replay muligt.

## Consequences

ADR-DC-024 bliver ikke længere den sidste replay-grænse før execution. DC-L16-kæden bliver i stedet:

`fresh ADR-023 verification → human ADR-024 verification → ADR-025 durable one-shot consumption → future explicit execution boundary`.

Ingen merge, release, deploy eller production activation følger af ADR-DC-025.
