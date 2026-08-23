# A4-18R — uafhængig offline receipt-verifikation

## Formål

Denne verifier er det separate, receipt-only bevis for A4-18R. Den erstatter
**ikke** den canonical repository/runtime-audit.

De to beviser har bevidst forskellige authority-grænser:

1. `scripts/agent4_a4_18r_audit.py` kører på den fysiske A4-18R checkout og
   evidence-root. Den genberegner artifact-hashes mod faktiske repository- og
   output-filer, kontrollerer cleanup på evidence-træet og scanner hele den
   lokale runtime-evidence.
2. `scripts/agent4_a4_18r_receipt_verify_offline.py` læser kun én afsluttet
   JSON-receipt plus én eksplicit forventet Git-SHA. Den foretager ingen Git-
   eller repository-lookup, ingen netværksadgang, ingen subprocess-kørsel og
   ingen filskrivning.

En grøn offline-verifikation betyder derfor **ikke**, at artifact-bytes er
uafhængigt genlæst. Rapporten siger eksplicit
`artifact_bytes_verified=false` og `canonical_runtime_audit_still_required=true`.

## Authority

Verifieren må kun anvendes mod den immutable physical target, der står som
**current authority** på issue #421. Gæt eller genbrug aldrig en historisk SHA.

Den forventede SHA gives altid eksplicit:

```text
VERIFY_AGENT4_A4_18R_RECEIPT_OFFLINE.cmd <EXPECTED_PHYSICAL_SHA> <RECEIPT_JSON>
```

Eksempel efter en fysisk A4-18R-kørsel:

```powershell
cd C:\Users\admin\Desktop\ModelRig-git
.\VERIFY_AGENT4_A4_18R_RECEIPT_OFFLINE.cmd `
  $ExpectedSha `
  "$Out\a4-18r-physical-read-receipt.json"
```

Verifier-code har sin **egen** exact-head authority. Issue #421 skal derfor
registrere både:

- physical target SHA, som receiptens `expected_sha` og `observed_head` skal
  matche;
- offline verifier SHA, som er den separat kvalificerede verifier-kode.

## Hvad verifieren kræver

Receipt-only PASS kræver blandt andet:

- schema `modelrig-agent4/a4-18r-physical-read-receipt/v1`;
- `expected_sha == observed_head ==` den eksplicitte forventede SHA;
- gyldig content-bound self-digest på hovedreceipt og begge mutationer;
- præcis de 21 canonical A4-18R trials med korrekte HTTP-resultater;
- krævede payload- og cursor-digests;
- canonical fixture med paging-grænser over 25 elementer;
- præcis campaign-record- og summary-mutation med forventede semantiske deltas;
- fysisk Google Pixel-identitet og isoleret package
  `dk.ternedal.modelrig.a425f`;
- receipts for alle kritiske current-product repository-artifacts og A4-18R
  output-artifacts;
- fuld cleanup, ingen ukendt listener og afinstalleret test-app;
- `human_decision=GO`;
- `credential_data_included=false`;
- `public_network=false`;
- `production_activation=false`.

Credential-scanningen er fail-closed og accepterer digest-formede værdier kun i
schema/path-ejede hash-felter. Raw 64-hex device-token-form, pairing-code,
Bearer/admin-key-aliaser og `sha256:<raw-token>` i fri tekst afvises. Duplicate
JSON keys afvises før semantisk verifikation.

## Krævet final rækkefølge

Efter den faktiske Windows + Pixel-kampagne:

```powershell
# 1. Canonical audit på den fysiske checkout/evidence-root
python .\scripts\agent4_a4_18r_audit.py `
  --output-root $Out `
  --expected-sha $ExpectedSha

# 2. Separat receipt-only verifikation med den kvalificerede verifier-code
.\VERIFY_AGENT4_A4_18R_RECEIPT_OFFLINE.cmd `
  $ExpectedSha `
  "$Out\a4-18r-physical-read-receipt.json"
```

#421 kan først få fysisk GO, når begge beviser er grønne på de identities, der
er registreret på issue'et, og den menneskelige fysiske beslutning er `GO`.
Ingen del af offline-verifieren giver release-, merge-, lifecycle-, write- eller
production-activation-authority.
