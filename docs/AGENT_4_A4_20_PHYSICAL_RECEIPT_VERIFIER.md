# Agent 4 A4-20 — offline verifiering af fysisk receipt

## Formål

A4-20 verificerer den credential-frie A4-18 receipt efter den fysiske Windows/Pixel-kørsel. Verifieren udfører ingen netværkskald, ændrer ingen filer, lukker ingen GitHub-issue og kan ikke producere et fysisk GO. Den accepterer kun en allerede produceret `modelrig-agent4/physical-read-receipt/v2`.

## Kørsel

Fra repository-roden på den exact head, som den fysiske receipt påstår:

```cmd
VERIFY_AGENT4_PHYSICAL_RECEIPT.cmd
```

Eksplicit receipt og SHA:

```cmd
VERIFY_AGENT4_PHYSICAL_RECEIPT.cmd C:\sti\agent4-physical-read-latest.json ce6cbbbd02003f6e35cf2986c7b24b326add5fee
```

Direkte maskinlæsbar kørsel:

```powershell
python scripts\verify-agent4-physical-read-receipt.py `
  validation\agent4-physical-read-latest.json `
  --expected-sha ce6cbbbd02003f6e35cf2986c7b24b326add5fee `
  --json
```

Exitkoder:

- `0`: receipt passerer alle kontroller;
- `1`: receipt er læsbar, men acceptance eller integritet fejler;
- `2`: input, SHA-format eller JSON-læsning er ugyldig.

## Fail-closed kontroller

Verifieren kræver blandt andet:

- schema `modelrig-agent4/physical-read-receipt/v2`;
- exact 40-tegns SHA, hvor `observed_head == expected_sha`;
- branch `agent/a4-18-physical-read-product`;
- `human_decision=GO` og alle 21 kendte checkpoints, præcis én gang;
- korrekte HTTP-statusser for default-off, no-grant, grant, stale snapshots, revoke, restart og regrant;
- payload/cursor/screenshot/artifact hashes som `sha256:<64 lowercase hex>`;
- fysisk Google Pixel-identitet og ingen emulator/QEMU-markører;
- komplet cleanup, frie porte, fjernet firewall og slettet admin-key;
- `credential_data_included=false`, `public_network=false` og `production_activation=false`;
- ingen credential-lignende nøgler eller værdier nogen steder i receipt;
- receipt-digest genberegnet med samme kompakte JSON-form som PowerShell-finalizeren.

Manglende eller ukendte checkpoints afvises. Ukendte felter er tilladt, men bliver stadig credential-scannet.

## Autoritetsgrænse

Et PASS betyder kun, at den leverede receipt er internt konsistent med A4-18-kontrakten og den angivne exact SHA. Det beviser ikke af sig selv, at en menneskelig observation var sand, og det merger, releaser eller aktiverer intet. Issue #421 må kun lukkes efter separat menneskelig review af receipt, screenshots og fysisk testlog.

`main`, kandidat-PR #412, tags, release og `production_activation` må ikke ændres af A4-20.
