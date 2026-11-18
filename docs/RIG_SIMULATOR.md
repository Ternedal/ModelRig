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

## Slice 2a (18/11): the gate 2 operator up to its preflight

| Operator | Proves |
|---|---|
| `v1-gate2-operator-preflight-fail-closed` | `consciousness_live_lifecycle_operator.py` (#2407) starts on the rig's interpreter, reads two profile fixtures, reaches `/experimental/consciousness/status` on the production worker entrypoint, parses the runtime-status schema and stops with exit 2 and its own message (`STOPPED: the worker is not ready for the lifecycle gate: flags not set to 1: …`) because the simulated worker runs without the consciousness flags. A traceback, a hang, exit 0/1 or another refusal (`already exists`, `checkout is not clean`) is a defect. |

Two things made this possible and are available to every operator:

- `${SCRATCH}`: a directory the runner creates empty for each run
  (`validation/rig-simulator/scratch/<utc stamp>/`). Operators that refuse an
  existing output path (`--out`) take it from there, so a second local run
  does not fail on "already exists".
- `expect.stdout_contains`: a list of strings that must all occur on stdout.
  It is how a fail-closed message is pinned when the operator prints prose
  instead of JSON. It never reads stderr, so a traceback cannot satisfy it.

Still pending, with the issue that tracks each: a simulated gate 2 *verdict*
(needs a worker started with the consciousness flags, `KALIV_SCHEDULER=1` and
the qualification snapshot, a SelfState, an approved Person Revision and a
restart the operator asks a human for), the gate 1 assembler (#2408), the
qualifiers that need evidence from the rig or from the sister repositories,
and `freeze_check.py` (needs a token by design).

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
   `${OLLAMA_URL}`, `${HEARTBEAT}`, `${FRESH_WAV}`, `${WORK_DIR}`, `${SCRATCH}`, `${PYTHON}`),
   an `expect` that can fail (`exit`, and at least one of `stdout_json`,
   `jsonl_last`, `files_exist`, `stdout_contains`), and a `why` sentence.
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
