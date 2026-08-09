# Agent 4 A4-20 — fysisk receipt-validator

## Formål

Denne slice validerer den maskinlæsbare A4-18-receipt efter den fysiske Windows/Pixel-kørsel. Den accepterer ikke en kampagne alene fordi `human_decision` er `GO`.

Validatoren er read-only og ændrer ingen runtime, grant, firewall, branch, tag eller release.

## Kommando

Fra repository-roden på den samme exact head som den fysiske kampagne:

```cmd
VALIDATE_AGENT4_PHYSICAL_READ_RECEIPT.cmd
```

En anden receipt kan angives som første argument:

```cmd
VALIDATE_AGENT4_PHYSICAL_READ_RECEIPT.cmd C:\sti\receipt.json
```

Launcheren binder automatisk valideringen til `git rev-parse HEAD` og verificerer artefakter mod det aktuelle repository.

Direkte Python-brug:

```powershell
python scripts\validate-agent4-physical-read-receipt.py `
  validation\agent4-physical-read-latest.json `
  --expected-sha ce6cbbbd02003f6e35cf2986c7b24b326add5fee `
  --repo-root .
```

## Hårde gates

Receipt accepteres kun når:

- schema er præcis `modelrig-agent4/physical-read-receipt/v2`;
- `observed_head`, `expected_sha` og den eksplicit forventede SHA er identiske;
- alle præcis 21 checkpoints findes og har `status=pass`;
- de sikkerhedskritiske checkpoints har de forventede 200/403/404/422-statusser;
- beslutningen er `GO` og `all_required_observations_passed=true`;
- Pixel-identiteten er til stede, SDK er numerisk, og installeret app-version kan aflæses;
- backend, worker, firewall, porte og admin-key-cleanup er grønne;
- `credential_data_included=false`, `public_network=false` og `production_activation=false`;
- ingen credential-formede nøgler findes i receipt-strukturen;
- receiptens eget SHA-256 matcher den kanoniske JSON uden digestfeltet;
- alle artefaktpaths er relative, unikke og inden for repoet;
- alle artefaktstørrelser og SHA-256-hashes matcher de faktiske filer.

## Exit codes

- `0`: receipt er gyldig;
- `2`: receipt, digest, checkpoint, cleanup, SHA eller artefakt er ugyldig.

Et validator-resultat er stadig ikke en merge- eller releaseautorisation. A4-18 og A4-20 forbliver post-release-forberedelse, og den frosne 1.58.151-kandidat må ikke flyttes af denne workflow.
