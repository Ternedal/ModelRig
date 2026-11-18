# Rig simulator — operators run in CI before they run on the rig

_Added 16-11-2026. Status words follow `docs/KALIV_SYSTEM_DEFINITION.md`: this
tool is **software-qualified** at best and produces no physical evidence._

## Why

Rig days have mostly found defects in the apparatus, not in the product: a
path that does not exist on the rig (#2390 Blok 0), an argument a script does
not take (#638), a PowerShell construct 5.1 rejects, a token set one step too
late (#347), `.To4()` on a .NET object (#658). None of those needs a GPU to
show up. They need the scripts to be run once, on Windows, against something
that answers like the appliance.

The rule the simulator enforces is simple: **no operator reaches the rig
without having run in CI first.** The rig is the second run, never the first.

## What runs

`.github/workflows/rig-simulator.yml` runs on `windows-latest` under Windows
PowerShell 5.1 (the rig's shell) and does, in one job:

1. installs the worker's pinned dependencies and builds the backend;
2. starts a mock Ollama, a heartbeat ticker, the real worker and the real
   backend on loopback, and waits for both `/healthz`
   (`scripts/rig_simulator/run_operators.py`);
3. runs every operator in `scripts/rig_simulator/operators.json` with the
   manifest's placeholders filled in, and judges each run: exit code in the
   allowed set, JSON on stdout when required, a journal line with the required
   flags when required, and never a Python traceback;
4. uploads one report and the stack logs.

The manifest has two kinds of entry:

| Kind | Meaning |
|---|---|
| `operators` | run against the simulated stack, with an expectation |
| `pending` | named by the release qualification, cannot run here yet; carries the issue and the reason |

`tests/workflow_rig_simulator.py` (Linux CI, every PR) requires that every
script `docs/KALIV_SYSTEM_RELEASE_QUALIFICATION.md` names is one or the other,
proves the judge can fail (a judge that cannot fail proves nothing), and runs
the static operators through the runner on Linux.

## What the first slice covers (16/11)

| Operator | Proves |
|---|---|
| `ps51-parse-all-scripts` | every root, `scripts/`, `scripts/rig_simulator/` and `deploy/` `.ps1` parses under Windows PowerShell 5.1 (`tests/workflow_ps1_encoding.py` already parses them with pwsh 7 on Linux; 5.1 is the parser the rig uses) |
| `cmd-launcher-targets-exist` | every source file a root `.cmd` or operator `.ps1` points at exists, exact spelling |
| `system-release-gate-all-pending` | the final V1 gate answers `BLOCKED` as JSON for an all-pending manifest |
| `v1-rig-smoke` | the read-only readiness smoke reaches a verdict against a live backend and worker |
| `recovery-soak-sample-once` | the gate 9 collector journals one probe with all four health flags true |
| `e2e-latency-voice-driver` | the gate 8 driver fails closed with JSON when the voice runtime is absent |

Pending, with the issue that tracks each: the gate 2 operator (#2407), the gate
1 assembler (#2408), the qualifiers that need evidence from the rig or from the
sister repositories, and `freeze_check.py` (needs a token by design).

## What it does not prove

- That a verdict would be PASS on the rig. The simulator has no GPU, no
  Ollama, no voice runtime, no camera and no supervisor; the mock answers
  deterministically.
- Anything about the Android app, the Quest or BodyRig.
- Anything about the physical Stage A/B chain. Those operators (`stage_a_one_click.py`,
  `stage_b_one_click_v2.py`, the campaign scripts) switch branches, start
  stacks and write evidence; simulating them is a later slice with `-WhatIf`
  support in the scripts themselves.

## Adding an operator

1. Add an entry to `operators.json` with `id`, `script`, `kind`, `args`
   (placeholders: `${REPO}`, `${HEAD_SHA}`, `${BACKEND_URL}`, `${WORKER_URL}`,
   `${OLLAMA_URL}`, `${HEARTBEAT}`, `${FRESH_WAV}`, `${WORK_DIR}`, `${PYTHON}`),
   an `expect` that can fail, and a `why` sentence.
2. Run `python scripts/rig_simulator/run_operators.py --only <id> --backend-bin <modelrig-server>`
   locally, then `python tests/workflow_rig_simulator.py`.
3. Expectations describe what the simulator guarantees, not what the rig
   would answer. An operator that cannot run here goes under `pending` with an
   issue; it is not a pass.

## Outputs

Everything the simulator writes lands below `validation/rig-simulator/`,
which `.gitignore` excludes, so a run can never dirty a candidate checkout.
The report (`report.json`) carries `production_activation: false` and is not
evidence for any gate.
