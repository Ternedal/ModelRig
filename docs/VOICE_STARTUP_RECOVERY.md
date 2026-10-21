# Frozen voice worker startup recovery

The v2.0.17 Windows worker includes the ASR/TTS engines and NVIDIA runtime DLLs.
Its single-file executable is approximately 1.4 GB and unpacks native libraries
before its HTTP port becomes ready. The previous v2.0.16 executable was about
18 MB and omitted those voice dependencies.

On 2026-10-20 the rig log showed the new worker starting at 07:38:48, three
unhealthy polls, a watchdog restart at 07:39:38 and updater rollback at 07:39:39.
The process was still running when the watchdog restarted it. The updater then
proved the old v2.0.16 backend, worker and supervisor healthy again. These logs
establish interruption during startup, not the eventual outcome of an
uninterrupted worker boot.

The v2.0.18 startup policy originally gave a live child three minutes before
its first healthy response. The subsequent cold-start fix (#2251) raises the
default grace to four minutes and thirty seconds, still below the updater's
five-minute per-service health deadline. A crash still triggers immediate recovery. The first healthy
response ends grace, so later failures keep the existing three-poll recovery
rule. A never-ready child receives the normal failure count after grace expires.
`-startup-grace` changes the duration; zero retains the earlier behavior.

The updater waits up to five minutes **per service**, using a deadline that also
cancels an in-flight request. It requires HTTP 200 and the expected version;
incorrect versions, malformed responses and failed health checks still lead to
the existing whole-set rollback. Checksum, provenance and advancing supervisor
heartbeat checks remain required. The same readiness budget is used when proving
the restored runtime. `-startup-timeout` must be positive.

Both defaults live in `backend/internal/startup/policy.go`. The production
verifier also records the failed endpoint and last status/version or connection
error if the deadline expires.

## Upgrade from the old updater

The installed v2.0.16/v2.0.17 updater still has the old readiness window. Merely
publishing a new supervisor cannot change the updater already running the
transaction. After v2.0.18 is published, update the updater first with its
existing signed self-update command, wait for replacement, verify its version,
then run the appliance update:

```powershell
$rig = 'C:\Rig\ModelRig'
$updater = Join-Path $rig 'modelrig-updater-windows-x64.exe'
& $updater -self-update -dir $rig
if ($LASTEXITCODE -ne 0) { throw 'Updater self-update failed.' }
$deadline = [DateTime]::UtcNow.AddMinutes(2)
$updaterVersion = ''
do {
    if (-not (Test-Path (Join-Path $rig 'updater.lock'))) {
        $updaterVersion = (& $updater -version | Out-String).Trim()
        if ($LASTEXITCODE -eq 0 -and $updaterVersion -eq '2.0.18') { break }
    }
    Start-Sleep -Milliseconds 500
} while ([DateTime]::UtcNow -lt $deadline)
if ($updaterVersion -ne '2.0.18') { throw 'The v2.0.18 updater is not installed yet.' }
& $updater -dir $rig
```

Self-update verifies both the checksum and release-bound build provenance. Its
detached helper replaces the updater after it exits and releases the update
lock. The guard above prevents the old updater from starting another appliance
transaction. No SDK, Python, manual binary swap or skipped verification is needed.

## Regression evidence

Fast Go tests cover slow first boot beyond the old three-poll window, first
readiness ending grace, immediate crash recovery, grace expiry, late readiness
beyond fifteen attempts, HTTP errors with a matching version, stale versions,
invalid JSON and cancellation of a stuck health request. Existing updater
rollback and supervisor tests also remain in the suite.

The Windows worker-package CI additionally launches the actual frozen worker
through a launcher delayed by 65 seconds, under the actual supervisor with its
default policy. It calls the production updater verifier and requires an
advancing heartbeat and no worker restarts. This test covers cold-start timing;
it does not assert GPU inference, microphone or Android acceptance on the rig.
