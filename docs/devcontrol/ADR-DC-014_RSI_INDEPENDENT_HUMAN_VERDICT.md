# ADR-DC-014 — Independent human verdict closes DC-L15, not pilot GO

**Dato:** 13/09-2026  
**Status:** foreslået til beslutning  
**Production activation:** `false`

## Beslutning

ADR-DC-014 indfører et verification-only led efter ADR-DC-013. Ledet kan kun
lukke den åbne `dc_l14_independent_human_verdict` gate ved at verificere et
separat Ed25519-signeret menneskeligt verdict over den eksakte fysiske
chain-of-custody.

ModelRig kan bygge de canonical bytes, som et menneske skal gennemgå og signere,
men ModelRig indeholder ingen production signer, privat nøgle eller automatisk
reviewer. Et verdict eksisterer først, når en ekstern menneskelig authority har
signeret claimet.

## Exact binding

Verdictet binder mindst:

- exact ADR-DC-013 `PhysicalCampaignMainFreezeProof` digest;
- exact ADR-DC-012 `PhysicalCampaignExecutionProof` digest;
- exact ADR-DC-011 evidence snapshot digest og admission digest;
- campaign, task, base og requested-main SHA;
- physical operator og approver;
- independent reviewer identity;
- decision, findings og canonical review timestamp.

Main-freeze proof og execution proof skal desuden re-bindes mod hinanden under
verification. Et korrekt signeret verdict over en anden execution/freeze chain
må derfor ikke kunne genbruges.

## Aktørseparation

Tre roller skal være forskellige:

1. physical operator/collector;
2. physical approver;
3. independent human reviewer.

Reviewer-signaturen skal have reviewerens actor ID som issuer. En operator eller
approver kan ikke selv lukke independent-review gaten, heller ikke med en ellers
gyldig nøgle.

## Decision semantics

`approve`, `request_changes` og `reject` er gyldige verdict-værdier, men kun
`approve` kan producerer et completion proof. `request_changes` og `reject`
forbliver signerbar review-evidence og fejler lukket ved forsøg på at konvertere
dem til DC-L15 completion.

Et non-approval verdict skal indeholde mindst ét finding.

## Production trust

Production accepterer ikke caller-valgt verifier. Public verification resolver
kun en fast host-admin-kontrolleret verification-only keyring:

- Windows: `C:\Program Files\ModelRig\DevControl\authority\rsi-physical-campaign-independent-verdict-keyring-v1.json`
- POSIX: `/etc/modelrig/devcontrol/authority/rsi-physical-campaign-independent-verdict-keyring-v1.json`

Keyringen indeholder kun Ed25519 public keys, issuer identity, epoch, validity og
revocation state. Private signing keys er fortsat forbudt i repository, worker,
DevControl runtime, staged closure og genereret evidence.

Verification kræver elevated host operator og arver den eksisterende
host-control keyring boundary. Caller-valgt keyring, private key og signer er ikke
production authority.

## Freshness

Verdictet skal registreres efter ADR-DC-013 freeze-finalization og senest 24 timer
efter. Verification skal ske ved eller efter verdict-tidspunktet og senest 24
timer efter. Grænserne er fail-closed og kan ændres ved en senere ADR, hvis den
operative review-proces kræver et andet vindue.

## Authority efter successful verification

Et verificeret `approve` må sætte:

- `independent_human_verdict_verified=true`;
- `runner_execution_binding_proven=true`;
- `continuous_main_freeze_proven=true`;
- `physical_campaign_completed=true`;
- `dc_l15_complete=true`;
- `dc_l14_independent_human_verdict_required=false`.

Det må **ikke** sætte:

- `pilot_go_authorized=true`;
- `activation_authorized=true`;
- `remote_publication_authorized=true`.

Den eneste resterende completion gate er:

`human_pilot_go_decision`

Proof-authority er derfor bevidst
`verified-independent-human-dc-l15-completion-only`.

## Ikke en pilotbeslutning

DC-L15 completion er evidens for, at den fysiske qualification chain er afsluttet
og uafhængigt menneskeligt vurderet. Det er ikke en beslutning om at tage en
candidate i pilot, merge, release, deploy eller production.

Pilot GO kræver et separat menneskeligt authority-step. ADR-DC-014 indeholder
ingen funktion, der kan træffe den beslutning på menneskets vegne.

## Ikke omfattet

ADR-DC-014 giver ingen Git/GitHub write, merge, tag, release, deploy,
publication, credential loading eller activation authority. Den starter ingen
physical campaign og genkører ingen probes.

`production_activation=false` forbliver invariant.
