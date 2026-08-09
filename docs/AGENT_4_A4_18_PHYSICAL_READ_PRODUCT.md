# Agent 4 A4-18 — fysisk read-product validation

## Status og formål

Denne runbook validerer den komplette, dormant Agent 4 read-produktvej på den
fysiske ModelRig-Windows-maskine og én fysisk Pixel:

```text
Kaliv Android
  → paired-device Bearer
  → ModelRig backend på LAN:8080
  → eksplicit agent4:read grant
  → loopback worker på 127.0.0.1:8099
  → canonical campaign/timeline/evidence stores
```

Harnesset aktiverer ingen Agent 4-orchestration, scheduler, recovery-loop eller
produktionsruntime. Det bruger en isoleret fixture, en isoleret pairing-store og
midlertidige processer, som operatoren selv ejer og rydder op. Resultatet er
altid `production_activation=false`.

Denne validering er post-release-forberedelse. Den må ikke flytte `main`, den
frosne 1.58.151-kandidat, tags eller releases.

## Hårde forudsætninger

- Windows PowerShell 5.1 kørt som administrator.
- Repository checkout på den præcise A4-18 validation-head.
- Ren working tree.
- `git`, `python`, `go`, `adb`, Java 17 og Android SDK/Gradle-wrapper tilgængelige.
- Præcis én autoriseret Pixel i `adb devices`.
- Pixel og rig på samme betroede lokale netværk.
- Port 8080 og 8099 ledige.
- Ingen credentials må indsættes i noter eller receipts.
- Screenshots og andre billedfiler må ikke bruges som acceptance-evidens, fordi
  synlige credentials i pixels ikke kan credential-verificeres maskinelt.

Operatoren stopper, hvis SHA, working tree, procesidentitet, portejerskab,
faseorden eller checkpointbevis ikke passer.

## 1. Freeze den fysiske validation-head

Fra repository-roden:

```powershell
cd C:\Users\admin\Desktop\ModelRig
git fetch origin
git switch agent/a4-18-physical-read-product
git pull --ff-only origin agent/a4-18-physical-read-product

$ExpectedSha = (git rev-parse HEAD).Trim()
if ($ExpectedSha -notmatch '^[0-9a-f]{40}$') {
    throw "Ugyldig validation-SHA: $ExpectedSha"
}
if (git status --porcelain) {
    throw "Working tree er ikke ren"
}
$ExpectedSha
```

Gem SHA'en sammen med den fysiske testlog. Hvis branch-headen flytter sig,
skal hele valideringen starte forfra på den nye exact SHA.

## 2. PrepareOff — byg, installer og start default-off

```powershell
.\START_AGENT4_PHYSICAL_READ_TEST.cmd $ExpectedSha
```

Launcheren:

- bygger en isoleret canonical fixture med mere end 25 campaigns, timeline-events
  og evidence-records;
- bygger backend og den lokale grant-CLI;
- bygger og installerer den signerede debug-APK på den ene Pixel;
- starter worker på `127.0.0.1:8099` med Agent 4 API slået fra;
- starter backend på riggens LAN-adresse, kun tilladt fra `LocalSubnet`;
- opretter en isoleret pairing-store og en kortlivet pairing-kode;
- skriver ingen admin-nøgle i command-filer eller receipt.

Par Pixel med den viste server-URL og kode. Åbn Agent 4-fladen og verificér:

1. feature-disabled/locked state;
2. ingen direkte worker-forbindelse eller fallback;
3. ingen stale privileged data.

Registrér observationerne:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent4-physical-read-operator.ps1 `
  -Action Record -Checkpoint default_off_feature_locked -Result Pass `
  -HttpStatus 404 -Route /api/v1/agent4/campaigns `
  -Note "Pixel viser feature-disabled uden data"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent4-physical-read-operator.ps1 `
  -Action Record -Checkpoint default_off_no_worker_fallback -Result Pass `
  -Note "Ingen direkte worker- eller fallback-forbindelse observeret"
```

## 3. Enable — paired, men uden grant

```powershell
.\ENABLE_AGENT4_PHYSICAL_READ_TEST.cmd
```

Den eksisterende pairing bevares. Pixel skal nu få præcis 403 fra backend og
vise locked state uden gamle data.

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent4-physical-read-operator.ps1 `
  -Action Record -Checkpoint paired_without_grant_403 -Result Pass `
  -HttpStatus 403 -Route /api/v1/agent4/campaigns `
  -RequestId '<redigeret-request-id>'

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent4-physical-read-operator.ps1 `
  -Action Record -Checkpoint paired_without_grant_locked_no_stale -Result Pass `
  -Note "Locked state; ingen privileged cached data"
```

`ENABLE_AGENT4_PHYSICAL_READ_TEST.cmd` nægter at fortsætte, før begge
default-off-checkpoints er bestået.

## 4. Grant — samme Pixel-token får read-adgang

```powershell
.\GRANT_AGENT4_PHYSICAL_READ_TEST.cmd
```

Grant tildeles lokalt via loopback admin-CLI og den isolerede backend-store.
Pixel må ikke parres igen.

Valider og registrér mindst:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent4-physical-read-operator.ps1 `
  -Action Record -Checkpoint grant_same_token_200 -Result Pass `
  -HttpStatus 200 -Route /api/v1/agent4/campaigns `
  -RequestId '<redigeret-request-id>' -PayloadSha256 'sha256:<64-hex>'

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent4-physical-read-operator.ps1 `
  -Action Record -Checkpoint campaign_paging_no_loss -Result Pass `
  -HttpStatus 200 -Route /api/v1/agent4/campaigns `
  -PayloadSha256 'sha256:<64-hex>' -CursorSha256 'sha256:<64-hex>' `
  -Note "Side 1+2: ingen dubletter eller tab"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent4-physical-read-operator.ps1 `
  -Action Record -Checkpoint timeline_paging_no_loss -Result Pass `
  -HttpStatus 200 -Route /api/v1/agent4/campaigns/a4-18-physical-primary/timeline `
  -PayloadSha256 'sha256:<64-hex>' -CursorSha256 'sha256:<64-hex>' `
  -Note "Side 1+2: ingen dubletter eller tab"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent4-physical-read-operator.ps1 `
  -Action Record -Checkpoint evidence_paging_no_loss -Result Pass `
  -HttpStatus 200 -Route /api/v1/agent4/campaigns/a4-18-physical-primary/evidence `
  -PayloadSha256 'sha256:<64-hex>' -CursorSha256 'sha256:<64-hex>' `
  -Note "Side 1+2: ingen dubletter eller tab"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent4-physical-read-operator.ps1 `
  -Action Record -Checkpoint detail_verification_matches -Result Pass `
  -HttpStatus 200 -Route /api/v1/agent4/campaigns/a4-18-physical-primary `
  -PayloadSha256 'sha256:<64-hex>' `
  -Note "Detail og verification-status matcher canonical read-model"

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent4-physical-read-operator.ps1 `
  -Action Record -Checkpoint no_write_controls -Result Pass `
  -Note "Ingen write-, lifecycle- eller grant-kontrol i Android"
```

Brug hash af den redigerede payload/cursor, ikke rå følsomme payloads. Alle
UI-beviser skal registreres som korte, redigerede `-Note`-observationer.
`-ScreenshotPath` må ikke bruges i en acceptance-kampagne.

## 5. Bevis stale campaign-record snapshot

Behold campaign-side 1 og dens oprindelige `head_cursor` i app/sessionen. Kør:

```powershell
.\MUTATE_AGENT4_CAMPAIGN_SNAPSHOT.cmd
```

Mutationen stopper kun den registrerede worker, ændrer den isolerede fixture,
skriver en mutation-receipt og starter den samme forventede worker igen. Forsøg
nu continuation med den gamle `after` + originale `head_cursor`. Backend skal
give redigeret 422, og appen skal rydde listen og kræve ny side 1.

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent4-physical-read-operator.ps1 `
  -Action Record -Checkpoint stale_campaign_record_422 -Result Pass `
  -HttpStatus 422 -Route /api/v1/agent4/campaigns `
  -CursorSha256 'sha256:<64-hex>' `
  -Note "Gammel campaign cursor afvist; app krævede refresh"
```

## 6. Bevis stale rendered-summary snapshot

Hent en frisk campaign-side 1 og behold dens cursor. Kør:

```powershell
.\MUTATE_AGENT4_SUMMARY_SNAPSHOT.cmd
```

Fortsættelse med den gamle cursor skal igen give 422, selv om ændringen kun er i
den viste timeline/evidence-summary.

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent4-physical-read-operator.ps1 `
  -Action Record -Checkpoint stale_summary_422 -Result Pass `
  -HttpStatus 422 -Route /api/v1/agent4/campaigns `
  -CursorSha256 'sha256:<64-hex>' `
  -Note "Ændret rendered summary afviste gammel campaign cursor"
```

## 7. Recovery og fail-closed-fejl

Mens grant stadig er aktivt:

```powershell
.\RESTART_AGENT4_PHYSICAL_WORKER.cmd
.\RESTART_AGENT4_PHYSICAL_BACKEND.cmd
```

Registrér recovery efter en vellykket frisk read:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent4-physical-read-operator.ps1 -Action Record -Checkpoint worker_restart_recovery -Result Pass -HttpStatus 200 -Route /api/v1/agent4/campaigns
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent4-physical-read-operator.ps1 -Action Record -Checkpoint backend_restart_recovery -Result Pass -HttpStatus 200 -Route /api/v1/agent4/campaigns
```

Afbryd kort Pixel-netværket, genetablér det og registrér `network_recovery` med
200 efter en frisk request. Verificér desuden malformed/unknown response som
synlig fejl — aldrig success — og en ukendt campaign som 404:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent4-physical-read-operator.ps1 -Action Record -Checkpoint network_recovery -Result Pass -HttpStatus 200 -Route /api/v1/agent4/campaigns
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent4-physical-read-operator.ps1 -Action Record -Checkpoint malformed_schema_fail_closed -Result Pass -HttpStatus 200 -Route /api/v1/agent4/campaigns -Note "Malformed/unknown schema blev vist som fejl, ikke success"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent4-physical-read-operator.ps1 -Action Record -Checkpoint not_found_fail_closed -Result Pass -HttpStatus 404 -Route /api/v1/agent4/campaigns/unknown-campaign
```

## 8. Revoke — samme token mister straks adgang

```powershell
.\REVOKE_AGENT4_PHYSICAL_READ_TEST.cmd
```

Næste request fra samme Pixel-token skal give 403. Tidligere campaign/detail/
timeline/evidence-data skal forsvinde eller være låst.

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent4-physical-read-operator.ps1 -Action Record -Checkpoint revoke_same_token_403 -Result Pass -HttpStatus 403 -Route /api/v1/agent4/campaigns
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent4-physical-read-operator.ps1 -Action Record -Checkpoint revoke_clears_data -Result Pass -Note "Privileged data blev ryddet/låst efter revoke"
```

Genstart appen og backend uden at regrante. Adgangen må ikke komme tilbage:

```powershell
.\RESTART_AGENT4_PHYSICAL_BACKEND.cmd
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent4-physical-read-operator.ps1 -Action Record -Checkpoint restart_does_not_restore_grant -Result Pass -HttpStatus 403 -Route /api/v1/agent4/campaigns
```

## 9. Regrant uden re-pairing

```powershell
.\REGRANT_AGENT4_PHYSICAL_READ_TEST.cmd
```

Samme Pixel-token skal igen få 200:

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent4-physical-read-operator.ps1 -Action Record -Checkpoint regrant_same_token_200 -Result Pass -HttpStatus 200 -Route /api/v1/agent4/campaigns
```

## 10. Status og final receipt

Status kan ses uden mutation:

```powershell
.\STATUS_AGENT4_PHYSICAL_READ_TEST.cmd
```

Når alle 21 checkpoints er registreret som `pass`:

```powershell
.\FINALIZE_AGENT4_PHYSICAL_READ_TEST.cmd GO
```

Finalizeren:

- kræver fase `regranted`;
- nedgraderer automatisk GO til NO-GO, hvis ét checkpoint mangler/fejler;
- stopper kun de registrerede og identitetsverificerede processer;
- accepterer safety-gatens verificerede pre-stop som cleanup-bevis, men kun når
  de oprindelige registrerede PID'er er væk og begge porte fortsat er frie;
- fjerner firewall-reglen og den ACL-beskyttede admin-nøgle;
- kræver port 8080 og 8099 fri;
- skriver `validation/agent4-physical-read-latest.json` med exact SHA, Pixel/build-
  identitet, redigerede tekstobservationer, fil-hashes og cleanup-resultat;
- inkluderer ingen pairing-kode, Bearer-token eller admin-nøgle;
- skriver `public_network=false` og `production_activation=false`.

Kør derefter den obligatoriske receipt-audit med den samme exact SHA:

```powershell
.\AUDIT_AGENT4_PHYSICAL_READ_RECEIPT.cmd $ExpectedSha
```

Auditoren scanner runtime-evidensfiler (`.json`, `.log`, `.txt`) for
credential-lignende indhold og afviser billedfiler, symlinks, manglende
safety-binding, ændrede digests, superseded heads og ufuldstændig cleanup.

Et manuelt NO-GO kan altid udstedes:

```powershell
.\FINALIZE_AGENT4_PHYSICAL_READ_TEST.cmd NO-GO
```

## Nødstop

```powershell
.\STOP_AGENT4_PHYSICAL_READ_TEST.cmd
```

Nødstop fabricerer ikke en GO-receipt. Hvis en ukendt proces har overtaget en af
portene, bevares den og cleanup markeres som fejlet; operatoren dræber aldrig en
proces, den ikke kan binde til sit eget forventede executable/command line.

## Acceptance

A4-18 er kun GO, når:

1. exact clean validation-head er dokumenteret;
2. default-off og paired-without-grant er fail-closed;
3. samme Pixel-token går 403 → 200 → 403 → 200 gennem grant/revoke/regrant;
4. campaign-, timeline- og evidence-paging passerer to sider uden tab/dubletter;
5. campaign-record- og rendered-summary-ændringer begge afviser gamle cursors;
6. restart/netværks-/schema-/not-found-fejl aldrig vises som success;
7. Android har ingen write/lifecycle/grant-kontrol;
8. receipt og alle runtime-evidensfiler er credential-fri, kun redigerede
   tekstobservationer bruges, og cleanup er grøn;
9. exact-head-, SDK-, hardening- og basisauditoren returnerer `PASS`;
10. `public_network=false` og `production_activation=false`.
