# R17: deployment proof for the C:/Z: media layout

Anders' decision (6 Nov 2026, #2275 6686905826) is to generate media in a private work area on the internal disk (C:) and publish it on the external disk (Z:). This page is the operator pack that proves that layout **on the rig**. It complements the CI evidence and does not replace it.

**Status: pending.** Nothing here has been run on the rig. Media stays default-off throughout: R17 never switches video on.

**What to run it on.** Everything R17 needs is on `main`: the wiring (#2357) with the lease-directory check (#2345) and `MountedMediaVolume` (#2349), the C6 repair tool with the network and `subst` refusal (#2386), and the tool's volume check (#2401). Anders tests physically on a release (#2275 6751908309), so set `$Qual` to a worktree at that release's tag SHA (`$RelSha` in the runbook, #2390 6848926366, step 0). R17.7 and R17.9 are no longer skipped.

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
| A junction in a work folder is reported as a link, never followed | POSIX symlinks only: `worker_media_repair.py` (a link inside is reported), C2 `worker_media_negative_matrix.py` (a file or folder swapped for a link at the copy) | R17.9 (optional) | pending; the only physical NTFS junction evidence |
| Access lost while C6 reads (denied, locked, Z: unplugged) | simulated: `worker_media_recovery_inventory.py`, `worker_media_repair.py` (`OSError` injected) | **not on the rig** | simulated only |
| Lease directory owner and DACL by SID; a junction to it is refused, not followed (#2345) | `worker_lease_dir_acl.py`; Windows runner `windows_lease_dir_acl_contract.py` (junction case included) | R17.10 | pending |
| A job database moved into the work area keeps its old grants and is refused | `worker_media_executor_main.py`, `windows_media_work_area_contract.py` | R17.11a | pending |
| A junction as the work-area root is refused | POSIX symlink only: `worker_media_work_area.py` | R17.11b | pending |
| Z: unplugged and replugged while idle: refused while gone, and the loss sticks until restart (#2349) | `worker_media_volume.py` (`FakeProbe`) | R17.12 | pending; also measures whether Windows keeps the disk's identity across a replug |
| A different disk at Z:, even with a copied marker | `worker_media_volume.py` | R17.13 (optional) | pending |
| A crash at each of six hand-off steps | C2 `worker_media_negative_matrix.py` (`os._exit`, POSIX) | **not on the rig**: needs video on | simulated only; physical crash after video is enabled |

**What "simulated" means here.** The CI rows run on Linux. They fake the Windows facts: the mount table, an `OSError` where Windows would deny or lock, a POSIX symlink where NTFS has a junction. They prove the code's decisions, not NTFS. The Windows contract tests (`tests/support/windows_*`, on the Windows gate) run on real NTFS, but on a CI runner, not this rig. Only an R17 step run on the rig is physical evidence for this machine. Every row marked "simulated only" stays unproven physically until Anders decides otherwise.

## 2. Variables (paste into every PowerShell window)

```powershell
$Qual = "C:\Users\admin\Desktop\mr-media-qual"          # the worktree at the release tag SHA ($RelSha, #2390 runbook step 0)
$GenPy = "C:\Kaliv\media-venv\Scripts\python.exe"   # the media venv (docs/MEDIA_IMAGE_RIG_QUALIFICATION.md §4.1), the same as KALIV_MEDIA_EXECUTOR_PYTHON
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
& $GenPy "$Qual\scripts\media_volume_repair.py" inventory --media-root $Gallery --volume-root $VolumeRoot --volume-id $VolumeId --job-db $JobDb --lease-dir $LeaseDir --work-root $WorkRoot --work-dir "$WorkRoot\comfy\cuda0\output" --work-dir "$WorkRoot\comfy\cuda1\output" > "$Out\inventory-baseline.json"; "exit=$LASTEXITCODE"
& $GenPy "$Qual\scripts\media_volume_repair.py" report --media-root $Gallery --volume-root $VolumeRoot --volume-id $VolumeId --job-db $JobDb --lease-dir $LeaseDir --work-root $WorkRoot --work-dir "$WorkRoot\comfy\cuda0\output" --work-dir "$WorkRoot\comfy\cuda0\temp" --work-dir "$WorkRoot\comfy\cuda0\input" --work-dir "$WorkRoot\comfy\cuda1\output" --work-dir "$WorkRoot\comfy\cuda1\temp" --work-dir "$WorkRoot\comfy\cuda1\input" > "$Out\report-baseline.json"
```

Expected: `exit=0`, `"status": "ok"`, and `jobs: []`, `unattributed: []`, `work_area_residue: []`. A physical crash test (kill the executor during a copy, then run the inventory) follows only after Anders decides to enable video.

**R17.9 Optional: a junction on real NTFS** (non-destructive; needs C6 like R17.7). The junction points at a new empty folder, so nothing else can be touched:

```powershell
$JTarget = "C:\kaliv-junction-target"
New-Item -ItemType Directory $JTarget | Out-Null
Set-Content -Path "$JTarget\outside.txt" -Value "outside"
New-Item -ItemType Junction -Path "$WorkRoot\comfy\output\junction-test" -Target $JTarget | Out-Null
& $GenPy "$Qual\scripts\media_volume_repair.py" report --media-root $Gallery --volume-root $VolumeRoot --volume-id $VolumeId --job-db $JobDb --lease-dir $LeaseDir --work-root $WorkRoot --work-dir "$WorkRoot\comfy\output" > "$Out\report-junction.json"; "exit=$LASTEXITCODE"
cmd /c rmdir "$WorkRoot\comfy\output\junction-test"
Get-Content "$JTarget\outside.txt"
Remove-Item -Recurse $JTarget
```

Expected: `exit=0`, and `work_area_residue` holds what R17.7 found plus one entry, `"path": "junction-test"` with `"kind": "link"`. `outside.txt` never appears in the report, and `Get-Content` still prints `outside`. `cmd /c rmdir` without `/s` removes only the junction, never its target.

**R17.10 Lease directory owner and DACL (ACL/SID, #2345).** Run as the appliance account.

```powershell
Push-Location "$Qual\worker"
$Judge = "import sys; from app.lease_dir_acl_windows import lease_dir_private as p; print(p(sys.argv[1]))"
& $GenPy -c $Judge $LeaseDir
New-Item -ItemType Directory C:\kaliv-lease-negative | Out-Null
& $GenPy -c $Judge C:\kaliv-lease-negative
Remove-Item C:\kaliv-lease-negative
New-Item -ItemType Junction -Path C:\kaliv-lease-junction -Target $LeaseDir | Out-Null
& $GenPy -c $Judge C:\kaliv-lease-junction
cmd /c rmdir C:\kaliv-lease-junction
Pop-Location
icacls $LeaseDir
whoami /user
```

Expected:
1. `(True, …)` for `$LeaseDir`.
2. `(False, "<SID> can add, replace, delete or re-permission lease files")` for the new folder under `C:\`. The SID is the inherited Users or Authenticated Users entry (`S-1-5-32-545` or `S-1-5-11`).
3. `(False, …)` for the junction, with the reason naming a symlink or junction. It is refused, never judged by its target's ACL.
4. `rmdir` without `/s` removes only the junction.

**R17.11a A moved job database keeps its old grants (C: private DB work area).** A file moved within one NTFS volume keeps its security descriptor. The preflight must refuse it rather than trust where it now lies.

```powershell
New-Item -ItemType Directory C:\kaliv-db-negative | Out-Null
Set-Content C:\kaliv-db-negative\moved-test.sqlite3 -Value "x"
Move-Item C:\kaliv-db-negative\moved-test.sqlite3 "$WorkRoot\state\moved-test.sqlite3"
icacls "$WorkRoot\state\moved-test.sqlite3"
& $GenPy "$Qual\scripts\media_work_area_preflight.py" --work-root $WorkRoot --job-db "$WorkRoot\state\moved-test.sqlite3" --volume-root $VolumeRoot --volume-id $VolumeId; "exit=$LASTEXITCODE"
Remove-Item "$WorkRoot\state\moved-test.sqlite3"; Remove-Item C:\kaliv-db-negative
```

Expected:
1. `icacls` still lists the Users or Authenticated Users entry carried from `C:\`.
2. `exit=1`, with `private:moved-test.sqlite3` false (`media_work_path_not_private`).
3. Every other check `ok`.

If `icacls` shows that the move *dropped* the broad entry, record that. The step then proves nothing, and that is itself a finding about this machine.

**R17.11b A junction as the work-area root (NTFS).**

```powershell
New-Item -ItemType Junction -Path C:\kaliv-work-junction -Target $WorkRoot | Out-Null
& $GenPy "$Qual\scripts\media_work_area_preflight.py" --work-root C:\kaliv-work-junction --job-db C:\kaliv-work-junction\state\jobs.sqlite3 --volume-root $VolumeRoot --volume-id $VolumeId; "exit=$LASTEXITCODE"
cmd /c rmdir C:\kaliv-work-junction
Test-Path $JobDb
```

Expected:
1. `exit=1`, with `work_area` refused as `media_work_area_root_link` or `media_work_area_root_not_canonical`.
2. `Test-Path` prints `True`: the real database is untouched.

**R17.12 Unplugging and replugging Z: while idle (#2349's verifier).**

Safety conditions:
- Media is off, so nothing writes to Z:.
- Close Explorer windows on Z:.
- Use "Safely remove hardware" before pulling the cable.
- Never do this during a copy.

Window A: the verifier probe. Its script lives in `%TEMP%`, not on Z:.

```powershell
$Probe = Join-Path $env:TEMP "r17-volume-probe.py"
@'
import os, sys, time
from app.media_volume import MountedMediaVolume
from app.media_generation_contract import ArtifactSinkUnavailable
root, vid, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
st = os.stat(root); print("start identity", st.st_dev, st.st_ino, flush=True)
v = MountedMediaVolume(root, vid)
for i in range(n):
    try:
        v.verify(); print(i, "ok", flush=True)
    except ArtifactSinkUnavailable as exc:
        print(i, str(exc), flush=True)
    time.sleep(2)
try:
    st = os.stat(root); print("end identity", st.st_dev, st.st_ino, flush=True)
except OSError as exc:
    print("end identity unavailable", type(exc).__name__, flush=True)
'@ | Set-Content -Encoding utf8 $Probe
Push-Location "$Qual\worker"; & $GenPy $Probe $VolumeRoot $VolumeId 120 | Tee-Object "$env:TEMP\r17-unplug.log"; Pop-Location
```

Then:
1. After a few `ok` lines, eject and unplug Z:.
2. Window B, while Z: is unplugged:

   ```powershell
   & $GenPy "$Qual\scripts\media_work_area_preflight.py" --work-root $WorkRoot --job-db $JobDb --volume-root $VolumeRoot --volume-id $VolumeId; "exit=$LASTEXITCODE"
   ```

3. Replug Z: under the same letter, and wait for Window A to finish (4 min).
4. Window B again, simulating an executor restart (a new verifier):

   ```powershell
   Push-Location "$Qual\worker"; & $GenPy $Probe $VolumeRoot $VolumeId 3; Pop-Location
   ```

Expected:
- **Window A:** `ok`, then a run of `media_volume_missing` (or `media_volume_not_mounted`) while unplugged. After the replug it **stays refused**: `media_volume_lost`, or `media_volume_identity_changed` if Windows gave the disk a new identity. It never returns to `ok`.
- **The two identity lines:** record whether `start identity` equals `end identity`.
  - If they are equal, this machine confirms the documented Windows limit. A replug that happens entirely *between* two checks would be invisible here, because there is no mount-session id. Only the sticky loss protects against a replug that a check saw.
  - If they differ, record that too.
- **Window B while unplugged:** `exit=1`, with `publication_volume` false.
- **The new verifier:** 3× `ok`.

**R17.13 Optional: a different disk at Z:.** Only with a spare disk that has no data you care about.

1. Plug the spare disk in as Z:, without a marker, and run the probe with `3`. Expected: `media_volume_marker_missing`.
2. Write the same marker on the spare disk (`Set-Content -Path "Z:\.kaliv-media-volume" -Value $VolumeId -NoNewline -Encoding ascii`). Then start the probe with `120` against the **real** Z:, swap the disks while it runs, and watch the lines. Expected: `media_volume_identity_changed`, then `media_volume_lost`. A matching marker is not enough.
3. Remove the marker from the spare disk afterwards.

**R17.8 Rollback.** Stop the appliance, then:

```powershell
Remove-Item Env:KALIV_MEDIA_EXECUTOR -ErrorAction SilentlyContinue
Push-Location "$Qual\worker"; & $GenPy -m app.media_executor_main --device cuda:0; "exit=$LASTEXITCODE"; Pop-Location
```

Expected: `exit=78`. The work area, its ACL, the marker and the gallery are untouched.

- **Undoing the layout itself** is a manual step. Copy the job database back to its old place while nothing runs (copy, never move), point `KALIV_MEDIA_JOB_DB` there, and unset `KALIV_MEDIA_WORK_ROOT`.
- **Not supported:** the executor refuses to start without a work area (78), so rolling back the layout means rolling back the build too.

## 4. Evidence to post (on #2296)

- **Files:** `preflight-idle.json`, `preflight-accounts.json`, `inventory-baseline.json`, `report-baseline.json`, and `report-junction.json` if R17.9 ran.
- **R17.10:** the three tuples, `icacls $LeaseDir` and `whoami /user`.
- **R17.11a/b:** `icacls` of the moved file, and each preflight's exit code and failing check; `Test-Path $JobDb`.
- **R17.12:** `%TEMP%\r17-unplug.log` (codes and two identity numbers only) and Window B's exit codes.
- **R17.13:** if run, the probe lines. They contain paths, SIDs, sizes and reason codes, never a prompt or a token.
- **The `icacls` outputs** from R17.2.
- **The `Get-Volume` lines** from R17.3.
- **Every exit code** printed above.
- **The `$QualSha`** the pack ran at.

ChatGPT reviews the evidence, and Anders decides on any next step. A pass proves this machine at this time; it does not switch anything on.
