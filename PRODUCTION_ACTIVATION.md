# Production activation promotion

This is the separate authority for turning the validated 2.0.13 appliance on.
Physical evidence receipts remain immutable and continue to say
`production_activation=false`; they are evidence, not switches.

The production receipt can say `production_activation=true` only when the
machine proves all of the following in one bounded promotion session:

1. the complete machine-only BodyRig #846 final seal still validates on the
   exact remote candidate SHA and the same unmoved `origin/main` authority;
2. the Agent 3 rig report is fresh, version/code bound and
   `eligible_for_write_pilot=true` with the approved write path exercised;
3. the current `feat/production-activation-promotion` checkout descends from
   that candidate and differs only in the allowlisted promotion tooling;
4. `modelrig.env` is atomically promoted to the explicit scope below;
5. the appliance is restarted through `KalivBootstrap`, never by directly
   launching the supervisor; and
6. live authenticated Agent3/tools/scheduler surfaces are healthy after the
   restart and Agent3 is assessing the exact rig-report bytes consumed by the
   gate.

## Activation scope

Only these production surfaces are promoted:

```text
KALIV_AGENT3_ENABLED=1
KALIV_TOOLS_ENABLED=1
KALIV_SCHEDULER=1
KALIV_SCHEDULER_API=1
```

The permanent env also binds `KALIV_AGENT3_VALIDATION_REPORT` to the consumed
physical report and configures one shared `KALIV_SCHEDULER_APPROVAL_SECRET` for
backend + worker. The secret is generated locally when needed and is never
printed or serialized into a receipt.

Agent4 operator API, computer-use, web/research and connector/HomeRig pilots are
not part of this promotion and remain controlled by their existing separate
feature flags.

## Run

Prerequisites are machine evidence, not human checkboxes:

- a completed `scripts/bodyrig_unity_live_automatic_proof.ps1` evidence folder
  for the current remote #846 head;
- a fresh `validation/agent3-rig-validation-latest.json` produced with
  `scripts/run-agent3-rig-validation.ps1 -ApproveWrite` against the same worker
  code identity;
- a paired-device token already present only in the process environment as
  `MODELRIG_TOKEN`; and
- the recovery-first `KalivBootstrap` + triggerless `KalivSupervisor` tasks.

From an elevated PowerShell on the physical Windows appliance, on the current
remote `feat/production-activation-promotion` checkout:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\production_activation_promote.ps1 `
  -BodyRigEvidenceDir "<path returned by the automatic BodyRig proof>"
```

The controller validates the evidence before mutation, replaces `modelrig.env`
atomically with a local backup, recovery-first restarts the appliance, then runs
an independent final live gate. If any post-mutation step fails, it restores the
exact pre-activation env and recovery-first restarts again. A failed session
therefore ends with no `production_activation=true` receipt.

Successful output is a create-only `production-activation.json` under
`%LOCALAPPDATA%\ModelRig\ProductionActivation\...` and contains no credentials.
The local `modelrig.env.pre-production-activation-*.bak` is intentionally retained
for operator rollback and must be treated as sensitive because an env file may
contain credentials.

## Non-negotiable invariants

- Never rewrite a physical evidence receipt to `production_activation=true`.
- Never pass a device token or scheduler secret on the command line.
- Never accept a promotion branch that changes worker/backend/BodyRig/renderer
  runtime code after the physical candidate was proved.
- Never continue if #846 remote head or the `origin/main` SHA recorded by the
  BodyRig machine proof has moved.
- Never start `KalivSupervisor` directly as the promotion restart path.
- Never write the final production receipt before the live scheduler reports
  `configured=true`, `running=true`, `resources_open=true`, and Agent3 reports
  the exact write-pilot-eligible rig evidence hash.
