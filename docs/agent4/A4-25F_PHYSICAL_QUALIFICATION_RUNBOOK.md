# A4-25f physical qualification runbook

A4-25f is the isolated physical qualification campaign for the immutable Agent 4 snapshot authority prepared by A4-25a through A4-25e.

This runbook **does not authorize production activation**. A successful run only proves that the repository-qualified A4-25f harness produced internally consistent physical evidence on one Windows rig + Pixel execution.

## Hard boundaries

- Use only the exact repository-qualified A4-25f commit SHA recorded on PR #475 / issue #474.
- The checkout must be clean. Do not run from a modified working tree.
- Use the isolated Android package `dk.ternedal.modelrig.a425f`; do not retarget the normal Kaliv package.
- Use a concrete RFC1918 address on a Windows network profile marked **Private**.
- The firewall rule must remain restricted to the selected Pixel IP.
- Worker and admin listeners remain loopback-only.
- Never put bearer tokens, pairing codes, admin keys or raw cursors in shell history, adb extras, issue comments or receipts.
- Do not reuse or rewrite #421 / A4-18 physical evidence.
- Do not merge, tag, release, switch the production mount or activate production as part of this campaign.

## Preconditions

On the physical Windows rig:

1. Check out the exact repository-qualified A4-25f SHA.
2. Confirm `git status --porcelain` is empty.
3. Have Java/Gradle, Go, Python, adb and PowerShell available as required by the harness.
4. Connect exactly the intended Pixel through adb, or pass its serial explicitly.
5. Choose a new output directory **outside the repository** for this attempt.
6. Choose one concrete private LAN address owned by the rig.

Example variables:

```powershell
$sha = "<repository-qualified A4-25f SHA>"
$output = "C:\ModelRig-A4-25f\$sha"
$lan = "<rig RFC1918 address>"
$serial = "<adb serial>"
```

Do not copy a previous attempt's output directory into a new campaign. A failed attempt should remain preserved as failed evidence; use a fresh output directory for a clean retry.

## 1. Prepare isolated stack and pair A425f

Run PowerShell as Administrator:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\agent4_a4_25f_physical_operator.ps1 `
  -Action Prepare `
  -ExpectedSha $sha `
  -OutputRoot $output `
  -LanAddress $lan `
  -Serial $serial
```

`Prepare` must:

- verify the exact clean checkout;
- build the isolated A425f APK and test-only backend binaries;
- create the isolated synthetic fixture outside the repository;
- install only `dk.ternedal.modelrig.a425f`;
- create the narrow Pixel-only firewall rule;
- start the loopback worker and isolated dual-listener backend;
- print a one-time pairing code without persisting it.

Pair **only the isolated A425f app** using the displayed server URL and pairing code. Do not record the pairing code.

## 2. Bind the paired Pixel identity

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\agent4_a4_25f_physical_operator.ps1 `
  -Action DeviceInfo `
  -ExpectedSha $sha `
  -OutputRoot $output `
  -Serial $serial
```

The device-info receipt may contain the non-secret device id/name and backend URL hash, but never the bearer token.

## 3. Grant isolated Agent 4 read permission

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\agent4_a4_25f_physical_operator.ps1 `
  -Action Grant `
  -ExpectedSha $sha `
  -OutputRoot $output `
  -Serial $serial
```

The admin key exists only in process memory/environment for the grant call and must not be persisted in operator-state or evidence.

## 4. Run the retained-root physical matrix

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\agent4_a4_25f_physical_operator.ps1 `
  -Action RunMatrix `
  -ExpectedSha $sha `
  -OutputRoot $output `
  -Serial $serial
```

The main matrix must physically cover:

- page-1 → mutation → page-2 continuation on the retained root;
- second-page deletion without changing the retained list result;
- detail → campaign transition → timeline continuation on the retained detail root;
- evidence append races while retained timeline/evidence reads stay root-bound;
- A4-24 overlap-policy revalidation;
- worker restart;
- backend restart;
- Android process restart;
- selected-root 404;
- server-side malformed-cursor 422;
- no-current/integrity-unavailable 503;
- unknown root 410;
- retained-root expiry 410 using the bounded test-host clock offset;
- a fresh unbound read observing the later current root.

The matrix receipt must keep `production_activation=false`.

## 5. Run the four local cursor rejection probes

CursorMatrix is a **separate required physical step**. It runs after `RunMatrix` while operator-state is still `matrix_complete`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\agent4_a4_25f_cursor_matrix.ps1 `
  -ExpectedSha $sha `
  -OutputRoot $output `
  -Serial $serial
```

All four stages must pass locally as protocol rejection before a network request can reuse the mismatched cursor:

- root mismatch;
- resource type mismatch;
- list-status filter mismatch;
- campaign mismatch.

## 6. Stop and remove the isolated stack

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\agent4_a4_25f_physical_operator.ps1 `
  -Action Stop `
  -ExpectedSha $sha `
  -OutputRoot $output `
  -Serial $serial
```

`Stop` must remove the isolated A425f APK, firewall rule, harness processes and isolated backend device-store while preserving evidence files.

## 7. Verify cleanup

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\agent4_a4_25f_cleanup_verify.ps1 `
  -ExpectedSha $sha `
  -OutputRoot $output `
  -Serial $serial
```

Cleanup verification must prove:

- A425f package removed;
- firewall rule removed;
- reserved listener ports closed;
- isolated backend device-store removed;
- backend and worker processes absent;
- the same Pixel serial hash as the physical campaign;
- `production_activation=false`.

## 8. Audit the complete evidence chain

Run only after successful cleanup verification:

```powershell
py -3 .\scripts\agent4_a4_25f_audit.py `
  --output-root $output `
  --expected-sha $sha
```

The auditor fails closed unless it can verify all of the following:

- exact clean repository head;
- valid A4-25f output marker and fixture self-digest;
- one 31-campaign genesis root;
- exactly five self-digested mutation receipts in the expected root/sequence chain;
- all main-matrix receipt file hashes;
- all 14 required main physical stages;
- all four CursorMatrix stages and their receipt hashes;
- same Pixel serial hash across operator/cursor/cleanup evidence;
- no credential-bearing evidence fields;
- complete cleanup evidence;
- no public-network or production-activation claim.

A successful audit writes:

```text
<output>\a4-25f-physical-audit.json
```

The success receipt must contain:

```json
{
  "physical_qualification_evidence_valid": true,
  "human_go_authorized": false,
  "production_activation": false
}
```

`physical_qualification_evidence_valid=true` means only that this physical campaign's evidence is internally complete and cryptographically bound. It is **not** a human GO decision and is **not** permission to activate production.

## Failure handling

If any physical step fails:

1. Do not edit or manufacture receipts.
2. Run `Stop` when possible.
3. Run cleanup verification when possible.
4. Preserve the failed output directory as failed evidence.
5. Record only non-secret failure context in #474.
6. Fix the repository on a new commit, re-run repository qualification, and use a new output directory for the next physical attempt.

Never convert a failed physical run into a pass by rebinding hashes, deleting failing receipts or reusing #421 evidence.

## After a successful physical audit

A human may review the audit receipt and associated non-secret evidence and update #474 / ADR-A4-005. Any later production activation must be a **separate, explicit change** with its own authority, review and qualification. A4-25f itself never performs that activation.
