# UPDATER_DESIGN.md — transaktionel updater for ModelRig/Kaliv

**Status:** LIVE · implementation complete + CI-verificeret · fysisk signed-release→signed-release acceptance afventer #401 · **Ejer:** Anders (rig)

> Autoritativt design for updaterens fejl- og recovery-model. Afløser den
> inkrementelle patch-tilgang: syv audits fandt hver ét nyt edge case, fordi
> swappet ikke var én transaktion. Dette dokument samler modellen ét sted og
> skelner præcist mellem **implementeret/CI-verificeret software** og den
> **fysiske rig-accept**, som fortsat kræver en rigtig Windows-procestest.

## 1. Fejlmodel (hvad der skal overleves)

En update er tre exe-swaps (server, supervisor, worker) på en ubemandet
Windows-maskine. Crash-punkterne:

| # | Crash-punkt | Uden design | Med design |
|---|---|---|---|
| C1 | Mid-copy af ny exe | live trunkeret (fixet 1.58.25) | `.new` + atomiske renames — live røres aldrig delvist |
| C2 | Mellem de to renames | live mangler, `.old`/`.new` efterladt | per-fil `recoverTarget()` ved næste start |
| C3 | Mellem to targets | **blandet sæt** (server ny, worker gammel), intet ved det | **journal → whole-set-rollback** ved næste start |
| C4 | Under rollback | "rolled back" kunne lyve (fixet 1.58.26) | `errRollbackFailed` → `manual_recovery`, supervisor startes IKKE |
| C5 | To updaters samtidig | delte `.new`/`.old`/backup-mappe | **lock-fil (O_EXCL)** — nr. 2 fejler lukket |
| C6 | Retry efter crash | kunne slette recovery-kopier (fixet 1.58.27) / overskrive god backup | recovery kører FØRST; immutable per-forsøg-backups |

## 2. Transaktionsmodellen (Implementeret)

**Journal:** `<root>\update-transaction.json` — skrives **før** første mutation;
dens *tilstedeværelse* betyder "ikke committet". Skrives tmp (fsync) + rename
med **monoton revision**; læseren betragter BÅDE hovedfil og `.tmp` og vælger
højeste revision — et crash mellem fsync og rename kan derfor ikke få en gammel
`verifying`-hovedfil til at vinde over en nyere `committed`-tmp. Enhver
tvetydighed (ulæselig fil, ID-mismatch, ens revisioner med forskellig state)
fejler lukket. Ærlig grænse: directory-metadata flushes ikke, så fuld
power-loss-durability er ikke bevist (P2, dokumenteret).

```json
{ "id": "20260713T2155Z", "from": "1.58.28", "to": "1.58.29",
  "backup_dir": "<abs>", "state": "prepared", "swapped": ["..."], "updated_at": "..." }
```

**Tilstande:** `prepared → backed_up → swapping → verifying →`
`committed` (arkiveres som `.last`) | `rolling_back → rolled_back` (arkiveres) |
`manual_recovery` (journal **beholdes**; supervisor startes ikke).

**Whole-set-backup (fase-deling):** ALLE targets backes op **før** første swap
(`backed_up`), derefter swappes de (`swapping`, hver swap registreres). Et crash
efter et vilkårligt swap har dermed altid et komplet præ-transaktions-sæt at
gendanne fra — der findes ingen tilstand hvor et target aldrig blev fanget.

**Whole-set-recovery ved start:** før versions-læsning og ethvert netværkskald:
1. **lock** (`updater.lock`, O_EXCL — fatale stier går via `die()` der frigiver den),
2. **journal-recovery**: findes en ukommittet journal → gendan ALLE targets fra
   dens backup-dir (live-mangler håndteres: `.old` først, ellers frisk kopi),
   arkivér som `rolled_back`; kan et target ikke gendannes → `manual_recovery`,
   fail closed,
3. per-fil `recoverTarget()` (dækker pre-journal-efterladenskaber),
4. `-recover`-flagget stopper her — offline reparation uden netværk/kørende server.

**Backups:** immutable per forsøg (`backups/<ts>-<fra>-to-<til>`), claimes
atomisk med `os.Mkdir` (fejler hvis den findes) — ingen check-then-act-race.

## 3. Implementeret og verificeret

**1.58.36 (fail-closed efter 1.58.35-audit):**
- **Rollback bevises før den erklæres:** `rolled_back` arkiveres først når den
  GAMLE runtime er bevist oppe (backend+worker-versioner + fremadskridende
  supervisor-heartbeat). Ubevist → journal beholdes som `manual_recovery`;
  næste kørsel re-restorer idempotent. En nede-rig kan ikke bære en journal
  der påstår rollbacken lykkedes.
- **Tvetydig journal stopper apparatet, ikke kun updateren:** korrupt/
  konfliktende journal-evidens stopper task + processer konservativt FØR
  fail-closed — en muligvis mid-verify runtime kører ikke videre med ukendt
  status. Ingen automatisk genstart på ukendt tilstand.

**1.58.31 (fail-closed efter 1.58.30-audit):**
- **Ulæselig journal = fail closed:** main behandler ikke længere en korrupt/
  ulæselig journal som "ingen journal" — updateren stopper før per-fil-recovery
  og versions-tjek kan erklære riggen "up to date" på ukendt transaktionsstatus.
- **Revision-læser over begge filer:** crashet mellem tmp-fsync og rename
  (main=`verifying`, tmp=`committed`) ruller ikke længere en verificeret sund
  update tilbage — højeste revision vinder; konflikt fejler lukket.
- **State-aware quiescing:** terminale journaler (`committed`/`rolled_back`) og
  `prepared` stopper IKKE en sund kørende rig — kun arkivet færdiggøres, og
  riggen efterlades kørende selv hvis arkiv-renamen bliver ved at fejle.
  Aktive states stopper task + processer som før; genstart-fejl efter recovery
  logges nu i stedet for at ignoreres.

**1.58.30 (fail-closed efter 1.58.29-audit):**
- **State-aware recovery:** `committed`/`rolled_back`-journaler (kun arkiv-rename
  fejlede) rører ALDRIG binaries — en verificeret sund update kan ikke rulles
  tilbage af en fejlet forensik-rename. `prepared` = nul mutationer → arkivér,
  gendan intet.
- **Fail-closed backup-validering:** forbi `backed_up` SKAL alle targets have en
  backup; mangler én → `manual_recovery`, intet røres. Delvis recovery kan ikke
  længere arkiveres som `rolled_back`.
- **Manglende live-exe = fejlet rollback:** `atomicSwapInto`s dobbelt-fejl
  wrapper nu `errRollbackFailed`, så main går i `manual_recovery` og aldrig
  starter supervisoren på et sæt med manglende exe — også når alle andre
  targets gendannes fint.
- **Stop før recovery:** en ventende journal stopper task + processer før
  gendannelse (Windows låser kørende images) og starter først igen efter
  verificeret recovery.
- **Journal-durabilitet:** tmp-filen fsync'es før rename; journal-skrivefejl
  efter første mutation ruller tilbage i stedet for at fortsætte.

- Journal + whole-set-recovery (`journal.go`) — unit-testet inkl. crash-midt-i-
  transaktion-scenariet (A swappet, B afbrudt → begge gendannet, journal arkiveret).
- To-faset `backupAndSwap` — testet at target 2's backup findes selv når dens
  swap fejler.
- Lock (`lock.go`) — testet eksklusivitet + release. `die()` frigiver ved fatal.
- `manual_recovery`-stier: rollback-fejl (sentinel `errRollbackFailed`) og
  health-fail-rollback-fejl starter **ikke** supervisoren og beholder journalen.
- Succes arkiverer journalen som `committed` (advarer hvis arkivering fejler —
  ellers ville næste kørsel rulle en god update tilbage).
- **Windows-CI:** `test-windows-appliance` kører updater/supervisor/heartbeat-
  testene på `windows-latest` ved hvert push/PR.
- **Windows-native replace:** live-targets erstattes via `ReplaceFileW` under den
  eksisterende journal/rollback-kontrakt; Windows-CI dækker replacement,
  rollback, missing-live recovery og failure-before-mutation.
- **Recovery ved boot:** bootstrap-entrypointet kører updaterens offline recovery
  før appliance/supervisor-start, så en efterladt transaktion håndteres før normal
  drift.
- **Updater self-update:** `-version` og verificeret `-self-update` er implementeret;
  updater-asset bindes til checksum + DSSE/SLSA provenance, `.pending` claimes
  eksklusivt, og en detached helper erstatter først updateren efter proces-exit.
- **Post-commit orchestration:** en detached watcher sammenligner committed-
  transaction fingerprints og starter kun self-update efter en ny successfuld
  appliance-commit. Check/recover/version, already-current, rollback og
  `manual_recovery` trigger ikke automatisk self-update.

**Ærlige grænser:** den Windows-native live-replacement lukker det tidligere
rename-vindue for Windows-pathen, men fuld power-loss-durability og den konkrete
installerede rigs Task Scheduler/AV/file-locking/timing kan ikke bevises af CI.
Lock-filen er fortsat ikke crash-selvhelende; hårdt crash kan kræve manuel
lock-oprydning, mens journalen bevarer recovery-authority.

## 4. Fysisk acceptance — software er implementeret, rig-bevis afventer #401

Repository-implementeringen af de tidligere §4a/§4b/§4d handoff-punkter er
færdig og CI-verificeret. Det åbne arbejde er ikke endnu en updater-runtime-
feature; det er kandidatbundet fysisk end-to-end bevis på den rigtige Windows-
rig. #401 er den autoritative acceptance-issue.

### 4a. Updater self-update — IMPLEMENTERET; fysisk signed-release→signed-release proof afventer

Implementeret software:
1. `-version` eksponerer updaterens compiled release identity.
2. `-self-update` downloader kun updater-assetet og verificerer checksum samt
   release-bundet DSSE/SLSA provenance.
3. `.pending` oprettes eksklusivt; detached helper venter på den kørende updater
   og erstatter derefter live-exe uden at gøre self-update til rollback-gate.
4. En post-commit watcher starter automatisk self-update **kun** efter en ny
   committed appliance transaction og logger separat.

Fysisk acceptance i #401 skal bevise en ægte nyere signeret target-release:
source-updater → successfuld appliance commit → automatisk follow-up → ændret
live updater-hash/version. En pre-self-update updater kræver naturligt én manuel
bootstrap-erstatning før denne kæde kan eksistere.

### 4b. Windows-native replace (`ReplaceFileW`) — IMPLEMENTERET + Windows-CI

Windows-pathen bruger `ReplaceFileW` under journalens eksisterende rollback-
model; non-Windows beholder test/fallback-semantik. CI på `windows-latest`
dækker replacement og rollback-fejlklasser. Den fysiske #401-matrix skal stadig
interrupte processen omkring swap og bevise, at live-navnene forbliver intakte
på den konkrete rig.

### 4c. Proces-level acceptance matrix — FYSISK UDESTÅR i #401

Det tilbageværende bevis køres som rigtige processer på den konkrete Windows-rig
med kandidatbundne releases/evidence:

- normal update → `committed`;
- defekt worker → verificeret rollback til source-version;
- kill updater midt i swap → næste start laver whole-set recovery;
- helper-interruption efter `.pending` → gammel live-updater forbliver runnable,
  og retry kan færdiggøre target-versionen;
- Task Scheduler/bootstrap/supervisor/log/journal-evidence bindes til source- og
  target-release.

Dette må ikke beskrives som bestået ud fra unit tests eller Windows-CI alene.

### 4d. Recovery ved boot — IMPLEMENTERET; fysisk rig-konfiguration indgår i #401

Offline `modelrig-updater -recover` køres af bootstrap-flowet før normal
appliance/supervisor-start. Repository/Windows-CI beviser wiring og recovery-
semantik; #401 skal stadig bevise den faktisk installerede Task Scheduler-
konfiguration og procesadfærd på riggen.

## 5. Ikke-mål (accepterede grænser)
Versionerede installations-mapper med `current`-symlink (over-engineering for én
rig når journalen dækker C3); crash-selvhelende lock (manuel + journal er nok);
signeret manifest (SHA256SUMS uden signatur er den dokumenterede grænse).
