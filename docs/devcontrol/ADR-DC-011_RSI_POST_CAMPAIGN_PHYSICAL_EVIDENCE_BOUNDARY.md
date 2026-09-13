# ADR-DC-011 — Host-pinned post-campaign physical evidence uden DC-L15 completion authority

**Dato 13/09-2026. Status: foreslået til beslutning.**

## Kontekst

ADR-DC-010 kan autorisere starten på præcis én manuel DC-L15-kampagne ved at
binde en live authenticated reservation til en human-signeret exact runner-pin.
Efter kampagnen findes der allerede et DC-L04 fysisk Windows-reportformat med det
faste 11-probe isolation-univers. Det reportformat kan dokumentere, at de krævede
probes bestod, og det kan bindes til task/base/collector/approver via den
eksisterende isolation-attestation.

Det eksisterende reportformat har imidlertid to afgørende begrænsninger:

1. det binder ikke `campaign_id` eller de exact runner-bytes/SHA, som ADR-DC-010
   autoriserede; og
2. det beviser ikke, at `main` forblev kontinuerligt frosset under hele den
   fysiske kampagne.

Derudover bruger DC-L04-formatet HMAC-SHA256. En verifier med HMAC-secret har
signing-equivalent capability. HMAC-verifikation kan derfor ikke i sig selv være
terminal menneskelig completion-authority for RSI-kæden.

Den tidligere prototype til post-campaign evidence accepterede en caller-valgt
`WindowsPhysicalIsolationVerifier` og snapshot-tede callerens Trusted-Git runtime
til en same-user transaction-copy. Det er ikke længere acceptabelt efter
hardeningerne i ADR-DC-009 og ADR-DC-010.

## Beslutning

Der indføres et separat **evidence-only** lag efter campaign admission. Laget må
verificere eksisterende fysisk evidens og lave en frisk post-campaign observation,
men må ikke erklære DC-L15 færdig.

### 1. Production trust state er host-pinned

Public production collection må ikke acceptere en caller-valgt verifier,
HMAC-keyring, evidence-root, repository-root, operation-root eller clock som
authority-input.

Production resolver i stedet:

- evidence-root:
  - Windows: `C:\Program Files\ModelRig\DevControl\evidence\rsi-physical-campaign-evidence-v1`
  - POSIX: `/var/lib/modelrig/devcontrol/rsi-physical-campaign-evidence-v1`
- verification keyring:
  - Windows: `C:\Program Files\ModelRig\DevControl\authority\rsi-physical-campaign-evidence-hmac-keyring-v1.json`
  - POSIX: `/etc/modelrig/devcontrol/authority/rsi-physical-campaign-evidence-hmac-keyring-v1.json`

Begge skal være host-admin-kontrollerede efter de samme custody-principper som
de tidligere fysiske authority-boundaries. Collection er en elevated physical
host-operator operation, ikke almindelig produkt-runtime.

Keyringen er canonical, size-bounded og domain-bundet til
`rsi-dc-l15-physical-campaign-evidence`. Den indeholder kun de HMAC-secrets, som
den legacy DC-L04-verifier kræver. Ingen ny signing-API introduceres.

### 2. HMAC-verifikation er bevis, ikke completion-authority

Fordi HMAC-verifieren besidder signing-equivalent secret-materiale, kan et
successful verify-resultat højst etablere:

- at ét canonical signed report matcher attestationens evidence-digest;
- at signaturen matcher den host-pinnede keyring;
- at reportet er frisk;
- at alle 11 krævede probes er bestået;
- at task/base/catalog/toolchain og collector/approver-binding matcher
  isolation-attestationen.

Det kan **ikke** alene etablere campaign completion, runner execution eller
menneskelig terminal autoritet.

### 3. Production Git observation genbruger hardened host-runtime boundary

Public evidence collection kræver en exact `TrustedGitRuntime`, som består den
samme host-admin-control validation som ADR-DC-009/010. Runtime-bytes kopieres
ikke til en same-user staging-tree.

Post-campaign `refs/heads/main^{commit}` læses gennem den allerede hardened,
direct no-shell Git-reader. Repository/.git authority re-attesteres omkring
readet, og den attesterede Git executable genvalideres efter execution.

Private underscored tests må fortsat bruge injectable verifier, roots, clock og
transaction-private runtime staging; den sti er ikke production authority.

### 4. Fresh post-campaign main er ikke continuous freeze

Et successful snapshot kræver en frisk post-campaign observation inden for 15
minutter efter physical-report completion, og den observerede SHA skal være
identisk med den `requested_main_sha`, som ADR-DC-010-admissionen bandt.

Det beviser kun **post-campaign equality**. Det beviser ikke, at `main` ikke var
ændret midlertidigt under kampagnen. Derfor forbliver
`continuous_main_freeze_proven=false`.

### 5. Exact runner execution forbliver åben

Snapshot’et bærer admissionens runner path/SHA/byte-count videre, men det legacy
fysiske report har ingen cryptographic binding til disse runner-bytes eller til
`campaign_id`.

Derfor forbliver `runner_execution_binding_proven=false`. Et senere separat,
human/asymmetric completion-binding skal forbinde exact admission + exact runner
med exact verified physical report, hvis DC-L15 nogensinde skal kunne lukkes.

### 6. Authority er eksplicit smal

Output schema:
`kaliv-rsi-physical-campaign-evidence-snapshot/v1`.

Authority-værdi:
`verified-physical-evidence-only`.

Følgende er obligatorisk `false`:

- `runner_execution_binding_proven`
- `continuous_main_freeze_proven`
- `physical_campaign_completed`
- `dc_l15_complete`
- `pilot_go_authorized`
- `activation_authorized`
- `remote_publication_authorized`

Følgende gates skal fortsat stå eksplicit åbne:

1. `exact_runner_execution_binding`
2. `continuous_main_freeze_confirmation`
3. `dc_l14_independent_human_verdict`
4. `human_pilot_go_decision`

Collection kører ikke probes, starter ikke en campaign og udfører ingen GitHub-
write, merge, release, deploy, publication eller activation.

## Konsekvenser

RSI-kæden får nu et verifierbart post-campaign evidence-led uden at springe fra
“11 probes passed” til “DC-L15 complete”. Den vigtigste sikkerhedsegenskab er, at
legacy HMAC-evidence og en frisk `main`-observation ikke overfortolkes som de to
beviser, formatet faktisk mangler: exact runner execution og continuous main
freeze.

En senere ADR skal definere det separate human/asymmetric completion-binding,
hvis kæden skal gå videre fra evidence-only snapshot til egentlig DC-L15
completion. Denne ADR giver ikke den autoritet.

`production_activation=false`.
