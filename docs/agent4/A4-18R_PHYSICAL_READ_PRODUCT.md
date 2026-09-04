# A4-18R — fysisk current-product read-validering

> Authority: dette er en fysisk kvalifikationsrunbook, ikke en release- eller
> aktiveringsprocedure. `CURRENT_STATE.md` er autoritativ for repository-state.

## Formål og authority

A4-18R validerer den nuværende, read-only Agent 4-produktvej på én fysisk
Windows-rig og én fysisk Google Pixel:

```text
isoleret A425f-app-id, men current main Android-produktkilder
  -> paired-device Bearer
  -> ModelRig backend på én konkret privat LAN-adresse
  -> backend-proxied Agent 4 operator API
  -> loopback worker
  -> canonical Agent 4 fixture
```

Den fysiske kørsel skal altid bindes til en **fresh current-main exact SHA**,
som er skrevet eksplicit på issue #421 efter softwarekvalifikation. En gammel
A4-18 PR-head, historisk receipt eller branch er reference — aldrig launch
authority for den nuværende app.

Før fysisk kørsel skal den samme exact SHA være grøn i mindst:

- `ci`
- `codeql`
- `agent3-diagnostics`
- `agent3-full-diagnostics`
- `exact-head-qualification`
- `agent4-a4-18r-harness`

Hvis én af disse ikke er grøn på den exact SHA, stop. PR-CI på en anden SHA er
ikke et substitut.

A4-18R giver ingen release, tag, promotion eller production activation. Alle
harness-/fixture-/receipt-objekter er bundet til `production_activation=false`
og `public_network=false`.

## Hvorfor A425f-varianten bruges

`a425f` er kun en eksisterende fysisk-test **applicationId-isolation**. Den
kompilerer de normale current `main` Android-kilder, herunder
`Agent4OperatorClient`, `Agent4OperatorScreen` og `Agent4CampaignDetailScreen`,
men installeres som `dk.ternedal.modelrig.a425f` med separat app-sandbox og
AndroidKeyStore. Derfor overskriver testen ikke brugerens normale Kaliv-app.

A4-18R bruger ikke A4-25f snapshot-prober som acceptance af read-produktet.
Produkt-UI'et og current `Agent4OperatorClient` skal observeres fysisk.

## Hårde forudsætninger

- Windows PowerShell 5.1 som administrator.
- Exact clean checkout på SHA'en registreret på #421.
- `git`, Python, Go, `adb`, Java og Android SDK/Gradle-wrapper tilgængelige.
- Én fysisk Google Pixel, eller eksplicit `-Serial` hvis flere ADB-enheder ses.
- Pixel og rig på samme betroede private LAN.
- Den valgte rig-adresse er RFC1918, aktiv og har Windows-netværksprofil
  `Private`; virtuelle/Tailscale/WSL/Docker-interface accepteres ikke.
- Port 18180 og 18199 er fri.
- En tom evidence-mappe **uden for repositoryet**.
- Ingen screenshots bruges som acceptance-evidens.

Harnessen stopper ved forkert SHA, dirty tree, ukendt listener/PID, public/ukendt
netværksprofil, emulator, forkert fysisk producent/model eller credential-formet
evidence.

## 0. Bind exact SHA og output-root

Eksempel — brug SHA'en, som er dokumenteret på #421; gæt den aldrig:

```powershell
cd C:\Users\admin\Desktop\ModelRig-git
git fetch origin
$ExpectedSha = '<SHA-fra-#421>'
git switch --detach $ExpectedSha
if ((git rev-parse HEAD).Trim() -ne $ExpectedSha) { throw 'Forkert checkout' }
if (git status --porcelain) { throw 'Working tree er ikke ren' }

$Out = "C:\Users\Public\Documents\ModelRig-A4-18R\$($ExpectedSha.Substring(0,12))"
```

Hvis issue #421 ikke har en fresh current-main exact SHA med de seks grønne
gates ovenfor, stop her.

## 1. PrepareOff — current app-kilder, feature default-off

Vælg riggens konkrete private LAN-adresse eksplicit:

```powershell
$Lan = '192.168.1.50'   # eksempel; brug den faktiske private adresse
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent4_a4_18r_physical_operator.ps1 `
  PrepareOff -ExpectedSha $ExpectedSha -OutputRoot $Out -LanAddress $Lan
```

Operatoren:

1. bygger canonical fixture uden for repoet;
2. bygger current backend + loopback-only grant CLI;
3. bygger `a425f`-varianten med current product sources og installerer den på den
   fysiske Pixel;
4. binder worker **kun** til `127.0.0.1:18199`;
5. binder backend direkte til den valgte private LAN-adresse på 18180 — aldrig
   wildcard;
6. laver en Windows Private-profile firewallregel bundet til backend-programmet,
   den konkrete local address og den konkrete Pixel-IP;
7. genererer en kortlivet admin-key i en ACL-beskyttet runtimefil og en
   single-use pairing-kode. Koden vises i konsollen, men gemmes ikke i evidence.

Par den isolerede A425f-app med den viste server-URL og kode. Åbn Agent 4 og
bekræft feature-disabled/locked state, ingen data og ingen worker-fallback.

Registrér:

```powershell
$Op = '.\scripts\agent4_a4_18r_physical_operator.ps1'
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Record -ExpectedSha $ExpectedSha -OutputRoot $Out `
  -Checkpoint default_off_feature_locked -Result Pass -HttpStatus 404 `
  -Route /api/v1/experimental/agent4/operator/campaigns `
  -Note 'Pixel viser feature-disabled uden privileged data'
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Record -ExpectedSha $ExpectedSha -OutputRoot $Out `
  -Checkpoint default_off_no_worker_fallback -Result Pass `
  -Note 'Ingen direkte worker- eller fallback-forbindelse observeret'
```

## 2. Enable — paired, uden `agent4:read`

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Enable -ExpectedSha $ExpectedSha -OutputRoot $Out
```

Samme Pixel-token skal nu få 403 og UI'et skal være låst uden stale data:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Record -ExpectedSha $ExpectedSha -OutputRoot $Out `
  -Checkpoint paired_without_grant_403 -Result Pass -HttpStatus 403 `
  -Route /api/v1/experimental/agent4/operator/campaigns
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Record -ExpectedSha $ExpectedSha -OutputRoot $Out `
  -Checkpoint paired_without_grant_locked_no_stale -Result Pass `
  -Note 'Locked state; ingen tidligere privileged Agent 4-data vises'
```

## 3. Grant — backend-single-writer, loopback admin

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Grant -ExpectedSha $ExpectedSha -OutputRoot $Out
```

Grant-handlingen skriver **ikke** pairing-store direkte og bruger ingen
portproxy. LAN-backenden stoppes ved exact PID, samme backend + samme isolerede
store startes kortvarigt på `127.0.0.1:18180` med grant-admin slået til,
`modelrig-agent4-grants` muterer over loopback, loopback-backenden stoppes, og
den normale exact-LAN backend genstartes med grant-admin slået fra.

Verificér fysisk i current UI:

- samme token får 200 uden re-pairing;
- kampagneliste >25 elementer kan page uden dubletter/tab;
- timeline >25 elementer kan page uden dubletter/tab;
- evidence >25 elementer kan page uden dubletter/tab;
- detail/verification matcher canonical read-model;
- ingen start/pause/cancel/retry/grant/write-kontrol findes i Agent 4 UI.

Registrér hashes af **redigeret/canonical observation**, aldrig rå cursor/token.
Hvis du ikke har en forsvarlig hash for et hash-krævende checkpoint, registrér
ikke Pass.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Record -ExpectedSha $ExpectedSha -OutputRoot $Out -Checkpoint grant_same_token_200 -Result Pass -HttpStatus 200 -Route /api/v1/experimental/agent4/operator/campaigns -PayloadSha256 'sha256:<64-hex>'
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Record -ExpectedSha $ExpectedSha -OutputRoot $Out -Checkpoint campaign_paging_no_loss -Result Pass -HttpStatus 200 -Route /api/v1/experimental/agent4/operator/campaigns -PayloadSha256 'sha256:<64-hex>' -CursorSha256 'sha256:<64-hex>'
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Record -ExpectedSha $ExpectedSha -OutputRoot $Out -Checkpoint timeline_paging_no_loss -Result Pass -HttpStatus 200 -Route /api/v1/experimental/agent4/operator/campaigns/a4-18r-physical-primary/timeline -PayloadSha256 'sha256:<64-hex>' -CursorSha256 'sha256:<64-hex>'
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Record -ExpectedSha $ExpectedSha -OutputRoot $Out -Checkpoint evidence_paging_no_loss -Result Pass -HttpStatus 200 -Route /api/v1/experimental/agent4/operator/campaigns/a4-18r-physical-primary/evidence -PayloadSha256 'sha256:<64-hex>' -CursorSha256 'sha256:<64-hex>'
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Record -ExpectedSha $ExpectedSha -OutputRoot $Out -Checkpoint detail_verification_matches -Result Pass -HttpStatus 200 -Route /api/v1/experimental/agent4/operator/campaigns/a4-18r-physical-primary -PayloadSha256 'sha256:<64-hex>'
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Record -ExpectedSha $ExpectedSha -OutputRoot $Out -Checkpoint no_write_controls -Result Pass -Note 'Current UI har kun read-navigation'
```

## 4. Stale campaign snapshot

Behold første campaign-side og dens head i app-sessionen, og kør:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File $Op MutateCampaignSnapshot -ExpectedSha $ExpectedSha -OutputRoot $Out
```

Harnessen stopper kun den exact registrerede worker, ændrer canonical fixture med
én ekstra campaign, skriver en content-bound mutation receipt og starter worker
igen. Fortsættelse med den gamle campaign cursor/head skal få 422 og appen skal
kræve frisk side 1.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Record -ExpectedSha $ExpectedSha -OutputRoot $Out -Checkpoint stale_campaign_record_422 -Result Pass -HttpStatus 422 -Route /api/v1/experimental/agent4/operator/campaigns -CursorSha256 'sha256:<64-hex>' -Note 'Gammel campaign snapshot blev afvist; UI krævede refresh'
```

## 5. Stale rendered-summary snapshot

Efter en frisk side 1:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File $Op MutateSummarySnapshot -ExpectedSha $ExpectedSha -OutputRoot $Out
```

Mutationen tilføjer præcis én evidence/timeline-summary ændring uden at ændre
campaign count. Fortsættelse med gammel cursor/head skal igen give 422.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Record -ExpectedSha $ExpectedSha -OutputRoot $Out -Checkpoint stale_summary_422 -Result Pass -HttpStatus 422 -Route /api/v1/experimental/agent4/operator/campaigns -CursorSha256 'sha256:<64-hex>' -Note 'Ændret rendered summary afviste gammel campaign snapshot'
```

## 6. Recovery og fail-closed wire-fejl

Worker- og backend-restart må ikke ændre grant eller canonical read-resultat:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File $Op RestartWorker -ExpectedSha $ExpectedSha -OutputRoot $Out
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Record -ExpectedSha $ExpectedSha -OutputRoot $Out -Checkpoint worker_restart_recovery -Result Pass -HttpStatus 200 -Route /api/v1/experimental/agent4/operator/campaigns
powershell -NoProfile -ExecutionPolicy Bypass -File $Op RestartBackend -ExpectedSha $ExpectedSha -OutputRoot $Out
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Record -ExpectedSha $ExpectedSha -OutputRoot $Out -Checkpoint backend_restart_recovery -Result Pass -HttpStatus 200 -Route /api/v1/experimental/agent4/operator/campaigns
```

Afbryd kort Pixelens netværk, genetablér det, refresh Agent 4 og registrér kun
Pass efter en frisk 200:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Record -ExpectedSha $ExpectedSha -OutputRoot $Out -Checkpoint network_recovery -Result Pass -HttpStatus 200 -Route /api/v1/experimental/agent4/operator/campaigns
```

Malformed-schema er reproducerbar uden at ændre produktkode. Kør det reversible
wire-fault-vindue; det stopper den rigtige LAN-backend, binder en credential-blind
fault-host til samme private adresse med en lige så snæver Pixel-firewallregel,
returnerer HTTP 200 + korrekt Agent-4 medietype men ukendt schema, og gendanner
den rigtige backend i `finally`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent4_a4_18r_fault_window.ps1 -ExpectedSha $ExpectedSha -OutputRoot $Out
```

Mens vinduet er aktivt skal current Agent 4 UI vise protocol-failure, aldrig en
tom/successful kampagneliste. Når den rigtige backend er gendannet:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Record -ExpectedSha $ExpectedSha -OutputRoot $Out -Checkpoint malformed_schema_fail_closed -Result Pass -HttpStatus 200 -Route /api/v1/experimental/agent4/operator/campaigns -Note 'Ukendt schema blev vist som protocol-failure, aldrig success'
```

En ukendt campaign på den rigtige backend skal give 404/fail-closed:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Record -ExpectedSha $ExpectedSha -OutputRoot $Out -Checkpoint not_found_fail_closed -Result Pass -HttpStatus 404 -Route /api/v1/experimental/agent4/operator/campaigns/unknown-campaign
```

## 7. Revoke og restart uden implicit regrant

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Revoke -ExpectedSha $ExpectedSha -OutputRoot $Out
```

Samme token skal straks få 403, og tidligere privileged data skal være
låst/ryddet i UI'et:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Record -ExpectedSha $ExpectedSha -OutputRoot $Out -Checkpoint revoke_same_token_403 -Result Pass -HttpStatus 403 -Route /api/v1/experimental/agent4/operator/campaigns
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Record -ExpectedSha $ExpectedSha -OutputRoot $Out -Checkpoint revoke_clears_data -Result Pass -Note 'Privileged Agent 4-data blev låst/ryddet efter revoke'
```

Genstart backend, stadig uden grant. Adgangen må ikke komme tilbage:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File $Op RestartBackend -ExpectedSha $ExpectedSha -OutputRoot $Out
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Record -ExpectedSha $ExpectedSha -OutputRoot $Out -Checkpoint restart_does_not_restore_grant -Result Pass -HttpStatus 403 -Route /api/v1/experimental/agent4/operator/campaigns
```

## 8. Regrant uden re-pairing

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Regrant -ExpectedSha $ExpectedSha -OutputRoot $Out
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Record -ExpectedSha $ExpectedSha -OutputRoot $Out -Checkpoint regrant_same_token_200 -Result Pass -HttpStatus 200 -Route /api/v1/experimental/agent4/operator/campaigns
```

## 9. Status, final receipt og audit

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Status -ExpectedSha $ExpectedSha -OutputRoot $Out
```

Når alle 21 checkpoints er reelt observeret som Pass, kan den menneskelige
physical decision registreres. `GO` er **kun** A4-18R physical qualification;
det er ikke release/promotion/production activation:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Finalize -ExpectedSha $ExpectedSha -OutputRoot $Out -Decision GO
python .\scripts\agent4_a4_18r_audit.py --output-root $Out --expected-sha $ExpectedSha
```

Finalizer/auditor kræver blandt andet:

- exact SHA på state, fixture, begge mutationer og hovedreceipt;
- alle 21 checkpoints;
- current Android/backend/worker source-hashes plus APK/backend/grant-binær;
- fysisk Google Pixel-identitet som hash-bundet serial, aldrig rå credential;
- exact PID-cleanup, fri port 18180/18199, firewall fjernet;
- isoleret app afinstalleret;
- admin-key og pairing/device-store slettet før audit;
- ingen symlinks/path traversal;
- ingen credential-aliaser, Bearer, pairing code, raw token eller token forklædt
  som fri `sha256:`-tekst;
- `public_network=false` og `production_activation=false`.

Hvis den menneskelige vurdering er NO-GO, brug:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Finalize -ExpectedSha $ExpectedSha -OutputRoot $Out -Decision NO-GO
```

En NO-GO receipt er stadig nyttig evidence, men lukker ikke #421.

## Nødstop

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File $Op Stop -ExpectedSha $ExpectedSha -OutputRoot $Out
```

Nødstop må kun stoppe de PIDs, som state binder til A4-18R-identiteten. En
ukendt listener bevares og giver fail-closed fejl; harnessen må aldrig dræbe en
proces bare fordi den bruger samme port.
