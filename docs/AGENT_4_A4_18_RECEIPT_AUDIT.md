# Agent 4 A4-18 — receipt-audit

Denne audit er den sidste maskinelle gate efter den fysiske Windows/Pixel-kampagne.
En menneskelig `GO` i receipt-filen er ikke tilstrækkelig alene.

Kør fra repository-roden efter `FINALIZE_AGENT4_PHYSICAL_READ_TEST.cmd GO`:

```cmd
AUDIT_AGENT4_PHYSICAL_READ_RECEIPT.cmd
```

Rapporten skrives credential-frit til:

```text
%USERPROFILE%\ModelRig-Validation\A4-18-receipt-audit\receipt-audit-latest.json
```

Auditoren kræver blandt andet:

- receipt-schema v2, exact local/remote SHA og korrekt A4-18-branch;
- frosset `main` på `218019fd47ea90b046a334253ab5fd84485f772a`;
- integrationsbase `503d4a61b7d7742a34282eb35a1373f0ccacf023` som ancestor;
- kun `validation/`-ændringer efter den fysiske kørsel;
- bit-for-bit gyldig hovedreceipt-digest;
- alle 21 checkpoints med forventede HTTP-statusser og hashes;
- præcis de 21 autoriserede checkpointnavne uden ukendte ekstra felter;
- fixture-counts over pagegrænserne og begge snapshot-mutationer;
- bit-for-bit gyldig digest for hver af de to mutation receipts;
- fysisk Pixel/app-build og et numerisk Android SDK-felt;
- artifact-hashes og fuld cleanup;
- ingen credential-felter eller credential-lignende værdier;
- `credential_data_included=false`, `public_network=false` og
  `production_activation=false`.

Launcheren kører først hovedauditoren. Kun ved exit `0` køres det separate,
read-only hardeninglag. En fejl i et af lagene er NO-GO.

Exit codes:

- `0`: `PASS`; rapporten kan indgå i review af #421.
- `2`: `FAIL`; #421 må ikke lukkes.
- `3`: auditoren kunne ikke gennemføre; det er også NO-GO.

Rapportens `audit_sha256` er content-addressing, ikke en digital signatur.
Auditorens egen basistest kan køres uden hardware:

```powershell
powershell.exe -NoProfile -File .\scripts\agent4-physical-read-audit.ps1 -SelfTest
```
