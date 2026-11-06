# R17: deployment proof for the C:/Z: media layout

Anders' decision (6 Nov 2026, #2275 6686905826) is to generate media in a private work area on the internal disk (C:) and publish it on the external disk (Z:). This page is the operator pack that proves that layout **on the rig**. It complements the CI evidence and does not replace it.

**Status: pending.** Nothing here has been run on the rig. R17 is runnable once the wiring branch (`feat/media-volume-wiring`) is merged and a new `$QualSha` is set in the rig runbook (#2296). Media stays default-off throughout: R17 never switches video on.

## 1. What is proven where

| Property | CI / simulated (exists) | Rig (R17 step) | Rig status |
|---|---|---|---|
| Work area private, canonical, local; refused when Users can read | `tests/worker_media_work_area.py`; Windows: `tests/support/windows_media_work_area_contract.py` | R17.2, R17.4 | pending |
| Job database and `-wal`/`-shm`/`-journal` private; a moved file with old grants refused | `worker_media_executor_main.py`, `windows_media_work_area_contract.py` | R17.4 | pending |
| Supervisor, worker, server and executor run as one SID | code: `modelrig-supervisor` `exec.Command`, no credential change; `windows_media_preflight_contract.py` (this process and a child) | R17.5 | pending |
| Z: mounted, marked, not the system disk, not the work area's disk | `worker_media_volume.py`, `windows_media_volume_contract.py`, `worker_media_preflight.py` | R17.3, R17.4 | pending |
| Low space is visible before a job | `worker_media_preflight.py` (threshold) | R17.6 (threshold only) | pending |
| Disk full or failing write during the copy keeps the finished render | `worker_comfy_video_adapter.py`, `worker_media_staged_video_sink.py`, C2 `worker_media_video_e2e.py` (ENOSPC/EIO injected) | **not on the rig**: would fill a real disk | simulated only |
| Crash residue tied to its job; nothing partial visible | C2 (fork + `os._exit` at the copy, before publication; failed adopt, sync, registration), C6 `worker_media_recovery_inventory.py` | R17.7 baseline only (video is off) | pending; physical crash after video is enabled |
| Default-off | `worker_media_executor_main.py` | R17.1 | pending |
| Rollback | — | R17.8 | pending |

## 2. Variables (paste into every PowerShell window)

```powershell
$Qual = "C:\Users\admin\Desktop\mr-media-qual"          # the worktree at the new $QualSha (rig runbook R0)
$GenPy = Join-Path $env:LOCALAPPDATA "kaliv-qual\genvenv\Scripts\python.exe"
$WorkRoot = "C:\Kaliv\media-work"
$JobDb = "$WorkRoot\state\jobs.sqlite3"
$VolumeRoot = "Z:\"
$VolumeId = "kaliv-media-z-01"
$Gallery = "Z:\kaliv-media\gallery"
$LeaseDir = "C:\ModelRig\gpu-lease"
$Out = "Z:\kaliv-media\qual"
```

Never paste `Get-ChildItem env:` or the env file into an issue: it holds tokens. Post only the outputs named below.

## 3. Steps

**R17.1 Default-off.** With `KALIV_MEDIA_EXECUTOR` unset:

```powershell
Remove-Item Env:KALIV_MEDIA_EXECUTOR -ErrorAction SilentlyContinue
Push-Location "$Qual\worker"; & $GenPy -m app.media_executor_main --device cuda:0; "exit=$LASTEXITCODE"; Pop-Location
```

Expected: `exit=78`, and the message says the executor is off.

**R17.2 The work area (once).** Follow the setup in `docs/MEDIA_WORK_AREA.md` (icacls by SID), then:

```powershell
whoami /user
icacls $WorkRoot
icacls "$WorkRoot\state"
```

Expected: only the `whoami` SID, `NT AUTHORITY\SYSTEM` and the Administrators group (`BUILTIN\Administratorer` on a Danish Windows), each with `(OI)(CI)(F)` or inherited `(I)`. No Users, Everyone or Authenticated Users.

**R17.3 The publication disk (once).** Write the marker, then check the disk:

```powershell
Set-Content -Path "$VolumeRoot.kaliv-media-volume" -Value $VolumeId -NoNewline -Encoding ascii
Get-Volume -DriveLetter Z | Format-List DriveLetter,FileSystemType,DriveType,HealthStatus,SizeRemaining
Get-Content "$VolumeRoot.kaliv-media-volume"
```

Expected: NTFS or ReFS, `Fixed` or `Removable` (never `Network`), and the id exactly as set.

**R17.4 Preflight, no media running.**

```powershell
& $GenPy "$Qual\scripts\media_work_area_preflight.py" --work-root $WorkRoot --job-db $JobDb --volume-root $VolumeRoot --volume-id $VolumeId > "$Out\preflight-idle.json"; "exit=$LASTEXITCODE"
```

Expected: `exit=0`, `"ok": true`, and `"executor_switch": "off"`. Every check is `ok`: `work_area`, `job_db_folder_in_work_area`, `private:jobs.sqlite3` and its sidecars if present, `publication_volume`, `separate_disks`, `free_space:*`.

**Optional negative check** (non-destructive). The new folder sits directly under `C:\`, so it inherits a broad ACL:

```powershell
New-Item -ItemType Directory C:\kaliv-preflight-negative | Out-Null
& $GenPy "$Qual\scripts\media_work_area_preflight.py" --work-root C:\kaliv-preflight-negative --job-db C:\kaliv-preflight-negative\jobs.sqlite3 --volume-root $VolumeRoot --volume-id $VolumeId; "exit=$LASTEXITCODE"
Remove-Item C:\kaliv-preflight-negative
```

Expected: `exit=1`, with `work_area` refused as `media_work_area_not_private`.

**R17.5 One account for every process.** Start the appliance as usual (`modelrig-supervisor`), with media still off. Then:

```powershell
$Pids = Get-CimInstance Win32_Process -Filter "Name LIKE 'modelrig-%'" | Select-Object -ExpandProperty ProcessId
$PidArgs = $Pids | ForEach-Object { "--pid"; $_ }
& $GenPy "$Qual\scripts\media_work_area_preflight.py" --work-root $WorkRoot --job-db $JobDb --volume-root $VolumeRoot --volume-id $VolumeId @PidArgs > "$Out\preflight-accounts.json"; "exit=$LASTEXITCODE"
```

Expected: `exit=0`, and one `same_account:pid N` check per supervisor, worker and server process, all `ok`. If one is `false`, its `detail.account` names the SID it actually runs as. **Stop there**: the layout is not deployable until all of them run as one account. No ACL is widened to make it pass.

The media executor is not running yet, because media is off. It is started by the same supervisor in the same way (`exec.Command`, `backend/cmd/modelrig-supervisor/executor.go`). Its own check comes with the first enabled run: run R17.5 again then, and its `python.exe` must appear among the processes and pass.

**R17.6 Low space is visible.**

```powershell
& $GenPy "$Qual\scripts\media_work_area_preflight.py" --work-root $WorkRoot --job-db $JobDb --volume-root $VolumeRoot --volume-id $VolumeId --min-free-gib-volume 1000000; "exit=$LASTEXITCODE"
```

Expected: `exit=1`, with only `free_space:publication_volume` false and its real `free_gib` shown. A physically full disk is **not** produced on the rig, because it would fill a real disk. The ENOSPC behaviour is proven in CI (§1).

**R17.7 Residue baseline.** Video is off, so there can be no hand-off residue yet. This records the starting point:

```powershell
& $GenPy "$Qual\scripts\media_volume_repair.py" inventory --media-root $Gallery --volume-root $VolumeRoot --job-db $JobDb --lease-dir $LeaseDir --work-root $WorkRoot --work-dir "$WorkRoot\comfy\output" > "$Out\inventory-baseline.json"; "exit=$LASTEXITCODE"
& $GenPy "$Qual\scripts\media_volume_repair.py" report --media-root $Gallery --volume-root $VolumeRoot --job-db $JobDb --lease-dir $LeaseDir --work-root $WorkRoot --work-dir "$WorkRoot\comfy\output" --work-dir "$WorkRoot\comfy\temp" --work-dir "$WorkRoot\comfy\input" > "$Out\report-baseline.json"
```

Expected: `exit=0`, `"status": "ok"`, and `jobs: []`, `unattributed: []`, `work_area_residue: []`. A physical crash test (kill the executor during a copy, then run the inventory) follows only after Anders decides to enable video.

**R17.8 Rollback.** Stop the appliance, then:

```powershell
Remove-Item Env:KALIV_MEDIA_EXECUTOR -ErrorAction SilentlyContinue
Push-Location "$Qual\worker"; & $GenPy -m app.media_executor_main --device cuda:0; "exit=$LASTEXITCODE"; Pop-Location
```

Expected: `exit=78`. The work area, its ACL, the marker and the gallery are untouched.

- **Undoing the layout itself** is a manual step. Copy the job database back to its old place while nothing runs (copy, never move), point `KALIV_MEDIA_JOB_DB` there, and unset `KALIV_MEDIA_WORK_ROOT`.
- **Not supported:** the executor refuses to start without a work area (78), so rolling back the layout means rolling back the build too.

## 4. Evidence to post (on #2296)

- **Files:** `preflight-idle.json`, `preflight-accounts.json`, `inventory-baseline.json` and `report-baseline.json`. They contain paths, SIDs, sizes and reason codes, never a prompt or a token.
- **The `icacls` outputs** from R17.2.
- **The `Get-Volume` lines** from R17.3.
- **Every exit code** printed above.
- **The `$QualSha`** the pack ran at.

ChatGPT reviews the evidence, and Anders decides on any next step. A pass proves this machine at this time; it does not switch anything on.
