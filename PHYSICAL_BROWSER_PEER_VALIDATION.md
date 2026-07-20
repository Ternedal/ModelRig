# T-032 — fysisk browser-peer-validering på ModelRig

Denne gate er det fysiske Windows-bevis for den claim-bound browsertransport.
Den hosted GitHub-receipt viser, at den offentlige transportvej virker, men den
kan **ikke** bruges som ModelRig-bevis. Den fysiske gate kræver samme rene
candidate-checkout som resten af kampagnen, et interaktivt Windows-terminalvindue
og en eksplicit indtastet engangsgodkendelse.

## Sikkerhedsgrænse

Operator-runneren:

- afviser Linux/macOS, GitHub Actions, generisk CI og ikke-interaktive sessioner;
- udfører først den offline `prepare`-fase uden DNS eller socket;
- viser kun hostname, URL-hash, candidate-SHA og udløbstid;
- viser aldrig challenge eller candidate-bound approval-værdi;
- kræver, at operatøren skriver `EXECUTE ONE PUBLIC GET` præcist;
- udfører derefter ét GET med den samme ti-minutters engangsplan;
- skriver den redigerede transport-receipt og en separat fysisk Windows-attestation;
- aktiverer ingen BrowserHost, ToolGate, API-route eller produktionsfunktion.

## 1. Frys den rigtige candidate

Kør fra repositoryets rod på ModelRig:

```powershell
git fetch origin
git switch agent/t032-physical-operator-gate
git pull --ff-only origin agent/t032-physical-operator-gate

git status --short
git rev-parse HEAD
python scripts\version_tool.py check
```

`git status --short` skal være tom. Skift ikke branch, pull ikke nye commits og
redigér ikke tracked filer mellem browser-gaten og den samlede kampagneverify.

## 2. Udfør den fysiske browser-peer-gate

Brug en lille, stabil HTTPS-side, som du udtrykkeligt accepterer at kontakte.
Den standards-reserverede side er velegnet til denne ene GET:

```powershell
powershell -ExecutionPolicy Bypass -File `
  .\scripts\run-browser-peer-public-validation.ps1 `
  -Url "https://example.com/"
```

Efter den offline prepare-fase vises target-host, URL-SHA-256, candidate-SHA og
udløbstid. Netværket er endnu ikke kontaktet. Skriv derefter præcist:

```text
EXECUTE ONE PUBLIC GET
```

Ved succes oprettes:

```text
validation/browser-peer-public-validation-latest.json
validation/browser-peer-public-validation-physical-latest.json
```

Den første fil er transport-receipt’en. Den anden binder receipt-hash, Windows-
host, interaktiv bekræftelse og candidate-identitet sammen. Begge rolling-filer
er ignorerede og må ikke committes direkte.

## 3. Kontrollér receipt’en

```powershell
$receipt = Get-Content `
  validation\browser-peer-public-validation-latest.json `
  -Raw | ConvertFrom-Json

$physical = Get-Content `
  validation\browser-peer-public-validation-physical-latest.json `
  -Raw | ConvertFrom-Json

$receipt.passed
$receipt.public_network_contacted
$receipt.transport
$receipt.citation
$physical.host
$physical.gate
```

Kravene er blandt andet:

- `passed=true` og `public_network_contacted=true`;
- selected DNS-peer er den samme som connected peer;
- HTTPS-port 443 og succesfuld status;
- outbound- og response-bytes er inden for de faste lofter;
- response-, evidence- og citation-hash er identiske;
- planen ligger som en consumed engangsfil;
- fysisk attestation siger Windows, interaktiv operatør og ikke-CI;
- `production_activation=false` hele vejen.

## 4. Kør den eksisterende seks-bevis-kampagne

Følg `PHYSICAL_VALIDATION_CAMPAIGN.md`. Når de seks eksisterende beviser er grønne:

```powershell
python scripts\physical_validation_campaign.py `
  --mode verify `
  --max-age-hours 168 `
  --min-model-exact 1.0 `
  --report validation\physical-validation-campaign-latest.json
```

## 5. Kør den afsluttende syv-bevis-gate

```powershell
python scripts\physical_validation_final_gate.py `
  --campaign-report validation\physical-validation-campaign-latest.json `
  --browser-attestation validation\browser-peer-public-validation-physical-latest.json `
  --max-age-hours 168 `
  --report validation\physical-validation-final-latest.json
```

Exit codes:

| Exit | Betydning |
|---:|---|
| `0` | Alle seks kampagnebeviser plus fysisk T-032 er friske, candidate-bound og grønne. |
| `1` | Evidens er rød, stale, mismatched, hosted/CI-baseret eller ufuldstændig. |
| `2` | Final-gaten kunne ikke bestemme candidate eller læse/skrive troværdigt. |

Kun følgende kombination betyder, at hele den fysiske kampagne er færdig:

```text
gate.passed=true
gate.physical_campaign_complete=true
gate.browser_peer_physical_complete=true
gate.all_physical_evidence_complete=true
gate.production_activation=false
```

## Permanent evidens

Når final-gaten er grøn og begge underliggende receipts er manuelt reviewet:

```powershell
Copy-Item `
  validation\physical-validation-final-latest.json `
  validation\physical-validation-final-2026-07-XX.json
```

Commit kun den daterede, manuelt reviewede final-receipt. Rolling-filer,
engangsplaner og host-specifikke arbejdsfiler forbliver lokale.
