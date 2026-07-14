# UPDATER_DESIGN.md — transaktionel updater for ModelRig/Kaliv

> Autoritativt design for updaterens fejl- og recovery-model. Afløser den
> inkrementelle patch-tilgang: syv audits fandt hver ét nyt edge case, fordi
> swappet ikke var én transaktion. Dette dokument samler modellen ét sted og
> skelner præcist mellem **Implementeret (1.58.29, unit-testet + Windows-CI)**
> og **Handoff (kræver Windows-procestest)**.

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
dens *tilstedeværelse* betyder "ikke committet". Skrives atomisk (tmp+rename;
læsning falder tilbage til `.tmp`, så den kan ikke forsvinde midt i en skrivning).

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

## 3. Implementeret i 1.58.29–1.58.30 (verificeret)

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
  testene på `windows-latest` ved hvert push/PR — rename-semantikken valideres
  nu på den platform hvor den afviger.

**Ærlige grænser (uændret, dokumenteret i koden):** `os.Rename` er ikke
crash-atomisk på Windows (vinduet mellem de to renames — C2 — *repareres* nu af
recovery, men *forhindres* først af ReplaceFileW); lock-filen er ikke
crash-selvhelende (manuel sletning efter hårdt crash, journalen står der også).

## 4. Handoff — kræver Windows-procestest (implementér i denne rækkefølge)

### 4a. Updater-self-update (vigtigst — ellers når intet af ovenstående eksisterende rigs)
En kørende exe kan ikke erstatte sig selv på Windows. Design:
1. Updateren downloader + SHA-verificerer `modelrig-updater-windows-x64.exe`
   til `modelrig-updater-windows-x64.exe.pending` som **sidste** trin i en
   committet update (efter health/heartbeat — self-update må aldrig gate rollback).
2. Den spawner en detached helper — enklest PowerShell:
   `Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoProfile','-Command',
   "Wait-Process -Id <pid> -ErrorAction SilentlyContinue; Move-Item -Force '<pending>' '<live>'"`
   — og afslutter. Helperen venter på exit og swapper.
3. Næste kørsel logger sin egen version (tilføj `-version`-flag) så det kan ses
   at swappet skete.
**Accepttest (på riggen):** kør gammel updater → efter committet update ligger ny
updater-exe; kør igen → `-version` viser den nye; afbryd helperen → `.pending`
ligger urørt, live-updateren intakt.

### 4b. Windows-native replace (`ReplaceFileW`)
Erstat de to renames i `atomicSwapInto` med ét `windows.ReplaceFile`-kald
(`golang.org/x/sys/windows`, build-tag `//go:build windows`; behold nuværende
implementering som `!windows`-fallback og til tests). Lukker C2-vinduet helt.
**Accepttest:** kill -9 af updateren i en loop under swap på riggen → live-navnet
findes altid.

### 4c. Proces-integrationstest på windows-latest
Unit/fault-testene kører nu på Windows (gjort). Tilbage: et release-job-step der
kører updater + supervisor som **rigtige processer** (fx mod en lokal fil-server
med et fabrikeret release): normal update → committed; defekt worker → rollback;
kill midt i swap → næste kørsel whole-set-recovery. Kør på `windows-latest` i
release-workflowet.

### 4d. Recovery ved boot
`modelrig-updater -recover` findes (offline). Wire den ind som første action i
autostart-scriptet/Task'en, før supervisoren startes — så heler en crashet rig
ved hvert logon, ikke kun når en update køres.

## 5. Ikke-mål (accepterede grænser)
Versionerede installations-mapper med `current`-symlink (over-engineering for én
rig når journalen dækker C3); crash-selvhelende lock (manuel + journal er nok);
signeret manifest (SHA256SUMS uden signatur er den dokumenterede grænse).
