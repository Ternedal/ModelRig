# A4-25f physical qualification runbook

A4-25f is the isolated physical qualification campaign for the immutable Agent 4 snapshot authority prepared by A4-25a through A4-25e.

This runbook **does not authorize production activation**. A successful run only proves that the repository-qualified A4-25f harness produced complete physical evidence on one Windows rig + Pixel execution and that a human explicitly accepted or rejected that physical campaign.

## Repository authority

The old PR #475 head is historical reference material, not a launch SHA. The harness was clean-landed on `main` through PR #510 and was subsequently hardened after real rig failures. The physical target must therefore be one freshly repository-qualified **exact current-main SHA**, recorded at campaign preparation time.

Before physical evidence starts, require the same exact SHA to have successful repository qualification for `ci`, `codeql`, `agent3-diagnostics`, `agent3-full-diagnostics`, `exact-head-qualification` and the dedicated `agent4-a4-25f-harness` workflow. Do not copy a SHA from an old PR, issue body or failed physical attempt. Once the first authority-bearing physical observation is taken, that exact SHA is immutable for the campaign.

Issue #474 is the current physical acceptance tracker. It records the qualification requirements and physical matrix, but its prose is not a substitute for resolving and verifying the exact current-main SHA at run time.

## Hard boundaries

- Use only the freshly exact-head-qualified current-main A4-25f SHA selected under issue #474.
- Never use PR #475 / `371b0dc4da35461cfa670305f2839a0d8d5e4462` as a new physical launch authority.
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

1. Fetch `origin/main`, resolve one exact current-main SHA, and verify all required A4-25f/repository gates are green on that same SHA.
2. Check out that exact SHA and confirm `git status --porcelain` is empty.
3. Have Java/Gradle, Go, Python, adb and PowerShell available as required by the harness.
4. Connect exactly the intended Pixel through adb, or pass its serial explicitly.
5. Choose a new output directory **outside the repository** for this attempt.
6. Choose one concrete private LAN address owned by the rig.

Example variables:

```powershell
$sha = "<freshly exact-head-qualified current-main SHA>"
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

The physical backend records only redacted Agent 4 HTTP evidence to `<output>\backend-device-store.json.agent4-evidence.jsonl`: safe route-kind, HTTP status, query-key names, SHA-256 of the raw query/body, media type and body size. It never records Authorization, query values, raw roots/cursors or campaign ids.

Pair **only the isolated A425f app** using the displayed server URL and pairing code. Do not record the pairing code.

## 2. Bind the paired Pixel identity

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\agent4_a4_25f_physical_operator.ps1 `
  -Action DeviceInfo `
  -ExpectedSha $sha `
  -OutputRoot $output `
  -Serial $serial
```

The device-info receipt records only non-secret physical/build identity:

- device id/name;
- Pixel manufacturer/model;
- Android release + SDK level;
- isolated package name, versionName/versionCode and debuggable identity;
- backend URL hash;
- expected/actual HTTP 200 from the authenticated status call.

It never records the bearer token.

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

Exactly 14 physical Agent 4 HTTP requests are expected. The redacted backend trace is the actual-status authority for those trials. The repository-qualified proxy contract `TestAgent4OperatorPreservesSnapshotQueryStatusBodyAndMediaType` separately proves that snapshot query bytes and worker status/body/media type are forwarded without rewrite.

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

The CursorMatrix must not add Agent 4 requests to the backend trace; these are local client rejections.

## 6. Stop and remove the isolated stack

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\agent4_a4_25f_physical_operator.ps1 `
  -Action Stop `
  -ExpectedSha $sha `
  -OutputRoot $output `
  -Serial $serial
```

`Stop` must remove the isolated A425f APK, firewall rule, harness processes and isolated backend device-store while preserving evidence files, including the redacted HTTP trace.

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

## 8. Finalize the complete physical evidence

Run only after successful cleanup verification, on the same physical Windows rig and exact clean checkout:

```powershell
py -3 .\scripts\agent4_a4_25f_finalize_evidence.py `
  --output-root $output `
  --expected-sha $sha
```

The finalizer first runs the fail-closed integrity auditor and then adds the issue-required physical evidence. It fails unless it can verify all of the following:

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
- exactly 14 redacted backend HTTP trace entries in expected order;
- expected versus actual HTTP status for every physical Agent 4 trial;
- expected v2 response media type plus hashed query/body evidence;
- Pixel model, Android version and isolated Android build identity;
- Windows release/build, CPU architecture, Python version/implementation + executable hash and Go version;
- no public-network or production-activation claim.

The finalizer writes both:

```text
<output>\a4-25f-physical-audit.json
<output>\a4-25f-qualification-evidence.json
```

The qualification receipt must contain:

```json
{
  "physical_qualification_evidence_complete": true,
  "all_expected_http_trials_verified": true,
  "human_go_recorded": false,
  "human_go_authorized": false,
  "production_activation": false
}
```

This proves evidence completeness only. It is **not** a human GO decision and is **not** permission to activate production.

## 9. Human review and immutable GO/NO-GO

Only a human reviewer may perform this step after reviewing the non-secret evidence. Record the physical-campaign decision explicitly:

```powershell
py -3 .\scripts\agent4_a4_25f_record_decision.py `
  --output-root $output `
  --expected-sha $sha `
  --decision GO `
  --reviewer "<human reviewer>" `
  --reason "<why this physical campaign is accepted>"
```

Use `--decision NO-GO` when the reviewed campaign should not be accepted.

The decision receipt is immutable and binds the exact `a4-25f-qualification-evidence.json` file + canonical digest. An existing decision cannot be overwritten. A human `GO` means **A4-25f physical qualification accepted only**; the receipt always keeps:

```json
{
  "production_activation_authorized": false,
  "production_activation": false
}
```

The human decision is written to:

```text
<output>\a4-25f-human-decision.json
```

## Failure handling

If any physical/evidence step fails:

1. Do not edit, delete or manufacture receipts/traces to make the attempt pass.
2. Run `Stop` when possible.
3. Run cleanup verification when possible.
4. Preserve the failed output directory as failed evidence.
5. Record only non-secret failure context in #474.
6. Fix the repository on a new commit, re-run repository qualification, and use a new output directory for the next physical attempt.

Never convert a failed physical run into a pass by rebinding hashes, dropping unexpected HTTP trace entries, deleting failing receipts or reusing #421 evidence.

## After a human physical GO

A human may update #474 / ADR-A4-005 with the immutable decision and non-secret evidence digests. Any later production activation must be a **separate, explicit change** with its own authority, review and qualification. A4-25f itself never performs or authorizes that activation.
