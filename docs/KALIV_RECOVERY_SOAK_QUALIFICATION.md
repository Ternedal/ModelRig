# Kaliv recovery-soak qualification

`scripts/kaliv_recovery_soak_qualification.py` produces the canonical evidence
for the `recovery_soak` Kaliv system release gate. It validates an observations
file. `scripts/kaliv_recovery_soak_collector.py` produces that file from the
running appliance.

Neither script starts, stops, restarts, updates or activates anything. The
collector sends GET requests to loopback only and reads one file, the
supervisor heartbeat.

> **Not yet run on the rig.** The collector is covered by its contract test
> against a fake appliance, on Linux and on a Windows CI runner. The scheduled
> task and the real heartbeat path have not been exercised. Do the smoke in
> step 0 before any run that is meant as evidence.

## What the gate requires

The qualifier accepts an observations file (`kaliv-recovery-soak-observations/v1`)
only when all of the following hold:

- every sample reports `backend_healthy`, `worker_healthy`, `supervisor_looping`
  and `state_error_absent` as true;
- the samples span at least `policy.required_duration_seconds`, with no two
  consecutive samples further apart than `policy.max_sample_gap_seconds`;
- the four recovery events (`reboot`, `backend_restart`, `worker_restart`,
  `interruption_recovery`) carry exactly the evidence reference and timestamp of
  the Stage-B report's hash-bound lifecycle artefacts, and every one of them
  lies **inside** the sample window;
- the Stage-B final report is complete, re-validates, and names the checkout's
  own candidate.

The last-but-one point decides the order of work: **sampling has to begin
before Stage B's first trial and run through all of them.** A soak started
after Stage B cannot pass, because the recovery events would lie before its
first sample.

The policy is declared by the operator. The qualifier enforces whatever
duration and gap the file declares; it does not set them. The values in
`eval/recovery_soak_observations.example.json` are six hours and fifteen
minutes.

## What a probe records

| Field | True when |
|---|---|
| `backend_healthy` | `GET <backend>/healthz` answers 200 with `status` = `ok`. |
| `worker_healthy` | `GET <worker>/healthz` answers 200 with `status` = `ok`, and `GET <worker>/health/full` reports `ok` = true. |
| `supervisor_looping` | The supervisor heartbeat file advances while the probe watches it. A file that exists but stands still is a dead supervisor. |
| `state_error_absent` | `/health/full` reports `checks.tools.ok` = true, which is the tool gate's `state_error is None`. |

Anything the probe cannot determine is recorded as false. Each probe also
records the backend and worker versions and the worker's commit, for the
assembly record.

Every probe is appended to an append-only journal and forced to disk, red or
green. The journal is never rewritten.

## Red probes

Stage B takes the appliance down on purpose: the interrupted update, the good
update, the reboot and the two supervisor restarts. A probe that lands in that
downtime is red, and a red probe cannot be a sample.

Stage B stamps each recovery *after* the service is back, so a trial's downtime
precedes its stamp. The trial period therefore:

- opens a declared lead before the first of the four stamps. The lead defaults
  to the policy's `max_sample_gap_seconds` and may not exceed it;
- closes at the last stamp. Nothing is added after it.

`assemble` leaves a red probe out of the observations only when the probe
**began** inside that period. A probe is placed by when it began
(`probe_started_at`), because what it saw, it saw after that. A red probe that
took more than two minutes is never excused.

**Every other red probe in the window fails the assembly, and no file is
written.** That includes a red probe before the first or after the last healthy
probe. Nothing is trimmed silently: to leave later (or earlier) probes out of
the claim, declare the window with `--window-end` (or `--window-start`). Probes
outside a declared window are counted in the record.

A journal line that cannot be read as a probe (a torn write) is treated as a
red probe that began some time between its readable neighbours.

From the reboot onwards every sample must report the Stage-B candidate's
version, so a soak cannot continue unnoticed on another release. Samples before
the reboot stamp may be on the source release, because the interruption trial
runs there and has to lie inside the window. A healthy probe on the candidate
before the reboot stamp is not release acceptance of anything.

### Limits of this evidence

- **The qualifier does not see the exclusions.** It validates the observations
  file only. The journal and the assembly record
  (`validation/recovery-soak-assembly.json`, which carries the journal's
  SHA-256 and lists every excluded probe) are a separate trust boundary. A
  qualified verdict says the samples satisfy the policy; that the left-out
  probes were legitimately left out is checked by a reviewer against the
  journal.
- **Downtime inside the trial period is not attributed.** A red probe there is
  excused whether or not a trial caused it. The record shows that the appliance
  was down during Stage B's trials; it does not show why. It is not proof of
  uninterrupted health between the trials.
- **The journal is unsigned.** It is written by the operator's own machine and
  is only as trustworthy as the checkout it was collected in.

## Run

All paths are relative to the candidate checkout. The journal, the observations
file and the record must lie below `validation/`: untracked files there are the
only local output the freeze gate accepts in a candidate checkout.

### 0. Smoke, before anything that is meant as evidence

Take two probes by hand and read them back. The appliance must be running.

```powershell
python scripts\kaliv_recovery_soak_collector.py sample --once --journal validation\recovery-soak-smoke.jsonl
python scripts\kaliv_recovery_soak_collector.py sample --once --journal validation\recovery-soak-smoke.jsonl
python scripts\kaliv_recovery_soak_collector.py status --journal validation\recovery-soak-smoke.jsonl
```

All four fields must print `ok` on both lines, and `status` must report two
healthy probes. If `supervisor_looping` is `RED`, the heartbeat path is wrong:
pass `--heartbeat`. If you use the scheduled task below, create it, wait for
its first two probes and check them the same way before starting Stage B.
Delete the smoke journal afterwards.

### 1. Start sampling, before Stage B

In a separate window, from the candidate checkout:

```powershell
python scripts\kaliv_recovery_soak_collector.py sample
```

It probes every five minutes and prints one line per probe. The heartbeat is
read from `C:\Rig\ModelRig\logs\supervisor-heartbeat`; pass `--heartbeat` if the
appliance lives elsewhere.

The loop does not survive the Stage-B reboot. Either start it again within the
policy's gap after logging in, or let Windows run single probes instead:

```powershell
schtasks /Create /F /TN KalivSoakProbe /SC MINUTE /MO 5 /TR "cmd /c cd /d C:\Users\admin\Desktop\ModelRig-git && python scripts\kaliv_recovery_soak_collector.py sample --once"
```

Remove the task when the soak is over:

```powershell
schtasks /Delete /F /TN KalivSoakProbe
```

### 2. Run Stage B

As the Stage-B runbook describes. Leave the appliance running afterwards.

### 3. Watch the window

```powershell
python scripts\kaliv_recovery_soak_collector.py status --required-duration-seconds 21600
```

`seconds_remaining` reaches 0 when the window is long enough. `red` lists every
red probe.

### 4. Assemble and qualify

`assemble` re-runs the qualifier's Stage-B validation, which includes the
freeze check. Set `GITHUB_TOKEN` first, as for the freeze check itself.

```powershell
python scripts\kaliv_recovery_soak_collector.py assemble `
  --stage-b-report validation\stage-b-physical-final-latest.json `
  --required-duration-seconds 21600 `
  --max-sample-gap-seconds 900

python scripts\kaliv_recovery_soak_qualification.py `
  validation\recovery-soak-observations.json `
  --stage-b-report validation\stage-b-physical-final-latest.json `
  --report validation\kaliv-recovery-soak-latest.json
```

`assemble` hands the exact bytes it is about to write to the qualifier and
writes nothing if the qualifier refuses them. The second command is the
qualification; its `release_evidence_ref` is the reference for the release
manifest:

```text
kaliv-recovery-soak:<modelrig-sha>:<sha256>
```

If the appliance was used or stopped after the soak, declare where the window
ends, so later probes are not part of the claim:

```powershell
  --window-end 2026-01-01T18:00:00+00:00
```

`--window-start` does the same at the other end. Without a declared window
every probe in the journal is part of the claim, and a red one outside Stage
B's trial period fails the assembly.

## Review checklist for the evidence

Before the `kaliv-recovery-soak:` reference goes into a release manifest:

1. The qualifier's report is `qualified: true` for the pinned ModelRig SHA.
2. `validation/recovery-soak-assembly.json` names the same observations SHA-256
   as the qualifier's report.
3. The journal's SHA-256 equals `journal.sha256` in the record.
4. Every entry in `red_probes_excluded` is one the reviewer accepts as Stage-B
   downtime. The record cannot make that judgement.
5. `probes_outside_declared_window` is 0, or the declared window is explained.
6. `observed_in_samples` names only the source release and the candidate.

## Authority boundary

A qualified verdict means the declared policy held over the sampled window on
the Stage-B candidate, with the limits above. It does not prove any other
release gate, and it keeps `production_activation` false.
