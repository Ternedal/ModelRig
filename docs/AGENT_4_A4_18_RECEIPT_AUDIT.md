# Agent 4 A4-18 — receipt-audit

Denne audit er den sidste maskinelle gate efter den fysiske Windows/Pixel-kampagne.
En menneskelig `GO` i receipt-filen er ikke tilstrækkelig alene.

Kør fra repository-roden efter `FINALIZE_AGENT4_PHYSICAL_READ_TEST.cmd GO` og brug
præcis den SHA, som den fysiske kampagne blev startet med:

```cmd
AUDIT_AGENT4_PHYSICAL_READ_RECEIPT.cmd <40-tegns-exact-SHA>
```

Launcheren afviser manglende, malformed eller kendte superseded A4-18-heads. Den
angivne SHA skal samtidig matche lokal `HEAD`, receiptens `expected_sha` og
`observed_head`, safety-bindingen samt de remote refs, som basisauditoren
verificerer. Pixel-SDK skal være en numerisk streng.

Rapporten skrives credential-frit til:

```text
%USERPROFILE%\ModelRig-Validation\A4-18-receipt-audit\receipt-audit-latest.json
```

Auditoren kræver blandt andet:

- eksplicit exact-SHA-authority; den udleder ikke acceptance-authority fra det
  checkout, operatoren tilfældigvis står på;
- receipt-schema v2, exact local/remote SHA og korrekt A4-18-branch;
- frosset `main` på `218019fd47ea90b046a334253ab5fd84485f772a`;
- integrationsbase `503d4a61b7d7742a34282eb35a1373f0ccacf023` som ancestor;
- kun `validation/`-ændringer efter den fysiske kørsel;
- bit-for-bit gyldig hovedreceipt-digest og begge mutationsdigests;
- alle og kun de 21 checkpoints med forventede HTTP-statusser og hashes;
- fixture-counts over pagegrænserne og begge snapshot-mutationer;
- fysisk Google Pixel og app-build;
- redigerede tekstobservationer for alle UI-checkpoints;
- ingen screenshots eller andre billedfiler i acceptance-evidensen, fordi synlige
  credentials i pixels ikke kan verificeres sikkert uden OCR;
- eksakt privat RFC1918-backendbinding, loopback-worker, `LocalSubnet`-firewall
  og netværksprofil `Private` eller `DomainAuthenticated`;
- hash- og feltkonsistens mellem receiptens safety-evidence og den faktiske
  `validation/agent4-physical-runtime/safety-binding.json`;
- artifact-hashes og fuld cleanup, inklusive verificeret allerede-stoppet
  pre-stop uden levende eller genbrugte registrerede PID'er;
- scanning af alle `.json`, `.log` og `.txt` runtime-evidensfiler for Bearer-
  værdier, authorization headers, pairing codes, device tokens, admin keys og
  andre credential-lignende felter;
- at `admin-key.txt` er slettet;
- `credential_data_included=false`, `public_network=false` og
  `production_activation=false`.

Hardening-gates er read-only. De ændrer ikke receipt, runtime-evidens, Git refs,
release-state eller produktionsruntime. Et hardening-afslag stopper launcheren
med `FAIL`; basisauditorens credential-frie JSON-rapport er kun autoritativ, når
alle forudgående gates er passeret.

Exit codes:

- `0`: `PASS`; rapporten kan indgå i review af #421.
- `2`: `FAIL`; #421 må ikke lukkes.
- `3`: basisauditoren kunne ikke gennemføre; det er også NO-GO.

Rapportens `audit_sha256` er content-addressing, ikke en digital signatur.
Hardening-lagets egen basistest kan køres uden hardware:

```powershell
python .\scripts\agent4_physical_read_audit_hardening.py --self-test
```

Exact-head- og SDK-gates dækkes desuden af repository-kontrakttestene i
`tests/workflow_agent4_physical_read_audit.py`.
