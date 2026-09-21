# ADR-DC-015 — Human-signed pilot decision without starting DC-L16

**Dato:** 13/09-2026  
**Status:** foreslået til beslutning  
**Production activation:** `false`

## Beslutning

ADR-DC-015 definerer den sidste menneskelige beslutningsgrænse mellem en
verificeret, afsluttet DC-L15 qualification chain og en senere kontrolleret
DC-L16 product-pilot.

ModelRig må bygge canonical bytes for en eksplicit `GO`, `NO-GO` eller
`GO WITH CONDITIONS` beslutning og verificere en separat Ed25519-signatur fra
den navngivne human decision maker. ModelRig må ikke selv træffe beslutningen,
indeholder ingen production signer/private key og starter ingen pilot som følge
af verification.

## Forudsætning

Input skal være exact
`PhysicalCampaignIndependentHumanVerdictProof` fra ADR-DC-014 med:

- independent human verdict verified;
- runner execution binding proven;
- continuous main freeze proven;
- physical campaign completed;
- `dc_l15_complete=true`;
- `human_pilot_go_required=true`;
- `pilot_go_authorized=false`;
- activation/publication false;
- remaining completion gate præcis `human_pilot_go_decision`.

Et andet eller over-autoriserende completion proof fejler lukket.

## Pilot-scope ligger i den signerede beslutning

Den menneskelige beslutning binder exact:

- completion-proof digest;
- campaign/task/base/requested-main identity;
- decision maker actor;
- decision ID og decision;
- operator surface;
- én til otte sorterede, unikke allowlisted task IDs;
- canonical workspace-root path digest;
- eksplicit valg af om lokale commits er tilladt;
- beslutningsnoter/conditions;
- decision timestamp.

Derved findes der ikke et generisk `GO`. Et positivt verdict gælder kun den
scope, der faktisk blev gennemgået og signeret.

## Invarianter i enhver signerbar scope

Alle beslutninger — også et menneskeligt `GO` — skal fastholde:

- feature flag default-off;
- local-only scope;
- kill switch required;
- restart/revoke required;
- ingen unattended cadence;
- ingen remote write;
- ingen push;
- ingen PR mutation;
- ingen merge;
- ingen release;
- ingen deploy;
- ingen production activation.

Disse felter er konstante authority-invarianter, ikke forslag.

## Decision semantics

Tre beslutninger understøttes:

- `go`: pilot-scope er godkendt uden betingelser;
- `go_with_conditions`: pilot-scope er godkendt med mindst én eksplicit note;
- `no_go`: pilot-scope er afvist og kræver mindst én eksplicit note.

Et verificeret `go` eller `go_with_conditions` må sætte
`pilot_go_authorized=true`. Et verificeret `no_go` sætter det false.

Alle tre producerer kun et decision proof; de starter ikke en pilot.

## Production trust

Production accepterer ikke caller-valgt verifier. Den resolver en fast,
host-admin-kontrolleret verification-only Ed25519 public-key keyring:

- Windows: `C:\Program Files\ModelRig\DevControl\authority\rsi-human-pilot-decision-keyring-v1.json`
- POSIX: `/etc/modelrig/devcontrol/authority/rsi-human-pilot-decision-keyring-v1.json`

Verification kræver elevated host operator. Private signing keys, signer,
credential loader og remote mutation adapter er ikke del af denne slice.

## Authority efter verification

Et proof må registrere:

- `human_pilot_decision_recorded=true`;
- `pilot_go_authorized=true` kun for `go`/`go_with_conditions`.

Følgende forbliver altid false:

- `product_pilot_started`;
- `remote_write_authorized`;
- `merge_authorized`;
- `release_authorized`;
- `deploy_authorized`;
- `production_activation_authorized`.

Proof-authority er
`verified-human-dc-l16-pilot-decision-only`.

## Relation til DC-L16 / issue #423

Et positivt decision proof er kun en prerequisite til DC-L16. Den senere
product-pilot skal fortsat implementere og fysisk bevise den konkrete
operatorflade, feature flag, allowlisted registry, workspace scope, kill switch,
revoke/restart og ingen remote mutation.

ADR-DC-015 tilføjer derfor ingen Kaliv/ModelRig product import af DevControl,
ingen normal operator-entrypoint og ingen aktiveret task-registry.

## Governance

Denne ADR må ikke fortolkes som Anders' faktiske GO-beslutning. Et GO eksisterer
først, når den eksterne human decision authority signerer exact claim bytes med
den relevante nøgle. Repository-kode eller CI kan ikke syntetisere den signatur.

Ingen physical campaign, pilot execution, Git/GitHub mutation, merge,
publication, release, deploy eller activation udføres af denne grænse.

`production_activation=false` forbliver invariant.
