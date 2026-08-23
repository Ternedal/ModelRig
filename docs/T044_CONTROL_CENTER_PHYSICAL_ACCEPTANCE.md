# T-044 Control Center — physical-device acceptance

This runbook records the **manual** acceptance evidence still required by issue #88 after software/CI qualification.

It is intentionally not an automated green gate. A headless emulator proves Compose/UI contracts; it does not prove a physical screen, real TalkBack focus/navigation, actual device ergonomics, or operator comprehension.

## Hard boundaries

- Run this only against a non-production/local test rig.
- `production_activation` must remain `false` throughout the run.
- Do not use a production GitHub token, production repository permission, or broad account scope.
- Use a disposable GitHub connector grant limited to a test repository and only the read operations needed by the test.
- Do not record Bearer tokens, GitHub credentials, issue/PR bodies, diffs, workflow logs, private prompts, tool arguments, or result payloads in evidence.
- A failed or missing observation is **not** green evidence. Record it as failed/blocked/unknown.
- One physical campaign is valid for exactly one 40-character **ModelRig candidate SHA**. Android, backend, worker and the Control Center/GitHub connector code exercised by the campaign must all come from the same clean checkout of that SHA.
- Historical component/PR heads are provenance only. They must not be mixed into a new physical receipt as if they were separately executable authorities.

## Candidate authority

Before collecting the first physical observation, select the exact ModelRig commit to test. It may be a freshly qualified `main` commit or a dedicated candidate commit, but the receipt is bound to the literal commit SHA rather than a moving branch name.

From the repository root on Windows:

```powershell
$ExpectedSha = "<40-char exact candidate SHA>"
$ObservedSha = (git rev-parse HEAD).Trim()
if ($ObservedSha -ne $ExpectedSha) { throw "HEAD $ObservedSha does not match expected $ExpectedSha" }
if (git status --porcelain) { throw "Working tree is not clean" }
```

Before the physical run starts, the same exact candidate SHA must have fresh green repository qualification for the software surfaces used here, including normal CI, Agent 3 diagnostics/full diagnostics, exact-head qualification and the Control Center Android accessibility/emulator gate when that workflow is applicable to the candidate tree.

Once the first physical observation is recorded, do not rebase, squash, amend, fast-forward or otherwise substitute a different SHA into that campaign. A code/head change requires a fresh physical campaign; previous observations remain evidence for the old SHA only.

## Prerequisites

1. The selected exact ModelRig candidate SHA is a clean checkout and has the fresh qualification described above.
2. Android, backend, worker, Control Center and GitHub connector authority exercised by the run are built/started from that same exact checkout; no historical stacked-PR head is substituted for one component.
3. The GitHub connector remains feature-gated/default-off outside the explicit local test setup.
4. One physical Android device is available with USB debugging enabled.
5. TalkBack is installed and can be enabled from the device accessibility settings.
6. The device is paired with the local ModelRig backend through the normal paired-device flow.
7. A disposable, narrow GitHub read grant exists for the test. Record only its `grant_id`, repository scope and scope SHA-256; never the credential.

## Build and install

From the same clean exact-candidate repository root on Windows:

```powershell
$ObservedSha = (git rev-parse HEAD).Trim()
if ($ObservedSha -ne $ExpectedSha) { throw "HEAD changed before Android build" }
if (git status --porcelain) { throw "Working tree changed before Android build" }

cd android
.\gradlew.bat :app:assembleDebug
$Apk = Resolve-Path .\app\build\outputs\apk\debug\app-debug.apk
Get-FileHash -Algorithm SHA256 $Apk
adb devices
adb install -r $Apk
```

Record the APK SHA-256 in the evidence header. The hash proves which built artifact was installed; it does not replace the exact source-SHA binding.

Record physical-device identity without collecting personal data:

```powershell
adb shell getprop ro.product.manufacturer
adb shell getprop ro.product.model
adb shell getprop ro.build.version.release
adb shell getprop ro.build.version.sdk
adb shell settings get secure enabled_accessibility_services
```

Enable TalkBack through Android's normal **Settings → Accessibility → TalkBack** UI. Do not force-enable an accessibility service with an undocumented ADB write command.

## Evidence header

Fill this before testing:

```text
Issue: #88 / T-044
Date/time (local):
Tester:
Exact ModelRig candidate SHA:
Observed git HEAD:
Working tree clean: yes/no
Normal CI qualification (run / result):
Agent 3 diagnostics qualification (run / result):
Agent 3 full diagnostics qualification (run / result):
Exact-head qualification (run / result):
Control Center accessibility/emulator qualification (run / result or not-applicable with reason):
Android APK SHA-256:
Same candidate checkout owns Android/backend/worker/connector code: yes/no
production_activation: false
Device manufacturer:
Device model:
Android release:
API level:
Physical device: yes
TalkBack enabled: yes/no
TalkBack/accessibility service identifier (redact user-specific data):
Paired-device auth works: yes/no
GitHub pilot enabled only for this local test: yes/no
Disposable grant id:
Disposable repository scope:
Disposable scope SHA-256:
```

If the exact SHA cannot be identified, the working tree is dirty, any exercised component comes from another checkout/SHA, or a required qualification is missing, stop and mark the run invalid rather than inferring provenance.

## Test A — open/close and focus order

1. Launch ModelRig.
2. Open **Settings**.
3. Activate **Control Center** using TalkBack rather than sight-only tapping.
4. Verify TalkBack announces the Control Center heading and reaches **Luk**.
5. Traverse the screen from top to bottom and back again.
6. Verify focus does not become trapped in cards, lists, progress indicators, filters or confirmation controls.
7. Close Control Center with **Luk**, reopen it and verify the flow remains usable.

Pass evidence:

- Control Center is reachable from Settings with TalkBack.
- Close/reopen is possible with TalkBack.
- Focus order is understandable and no focus trap is observed.

## Test B — health, routing and fallback

With TalkBack enabled:

1. Read **Rig-status** and the health state.
2. Read **Routering** and its summary.
3. Read **Agent 3** state.
4. If a fallback or unhealthy test condition is deliberately available, verify it is announced as such and is not presented as healthy/green.
5. Trigger **Opdatér** and verify the refresh control remains reachable and the refreshed observation is announced/readable.

Pass evidence:

- Health/routing/fallback information is understandable without relying on color.
- Unknown/stale/unavailable evidence is not announced as success.

## Test C — capabilities

1. Navigate to **Capabilities**.
2. Verify the summary count is readable.
3. Traverse at least three capability cards (or all cards if fewer than three exist).
4. Verify capability name, risk and relevant metadata are distinguishable with TalkBack.
5. Confirm there is no capability enable/disable mutation control in this read-only surface.

## Test D — schedules, jobs and execution history

1. Navigate through scheduled-task runtime/standing-grant information.
2. Read at least one schedule/job observation when data exists.
3. Read at least one execution-history entry when data exists.
4. Verify standing-grant state is not announced as if it were an execution outcome.
5. Verify missing history is announced as missing/empty rather than successful execution.

If the rig has no suitable schedule/job data, record this case as **blocked**, not passed.

## Test E — privacy and data-sharing

1. Navigate to **Privacy & data-sharing**.
2. Verify TalkBack can distinguish public/operational/private/secret policy text.
3. Verify dormant/unavailable common data-sharing evidence is announced as dormant/unavailable, not active.
4. Verify `production_activation=false` remains part of the server/client contract; no production activation control should exist in Control Center.

## Test F — generic ToolGate audit filters

1. Navigate to **Audit**.
2. Verify the fields **Task / conversation-ref**, **Capability** and **Approval** are individually announced with labels.
3. Enter a known task/ref filter and verify results narrow when matching evidence exists.
4. Repeat for capability and approval.
5. Enter a deliberately non-matching value and verify the UI says no entries match rather than showing an inferred healthy state.
6. Verify ToolGate `origin` is not described as connector identity.

## Test G — first-class connector audit filter

This test uses the dedicated GitHub connector ledger. Its connector identity must come from validated `connector=github` evidence, never from ToolGate `origin`.

1. Navigate to **GitHub connector → Connector-audit**.
2. Verify TalkBack announces filter labels **Connector**, **Repository**, **Operation** and **Udfald**.
3. Leave **Connector** blank and note the visible count.
4. Enter `github`; the same GitHub entries should remain eligible.
5. Enter `GITHUB`; case differences must not change the connector match.
6. Enter `gitlab`; zero GitHub entries must match.
7. Enter `local`; zero GitHub entries must match. This specifically proves `origin=local` is not reinterpreted as connector evidence.
8. Restore `github` and verify repository, operation and outcome filters narrow the recorded connector entries as expected.

Pass evidence must include the observed counts for blank/`github`/`gitlab`/`local`. Do not record issue/PR body content or workflow-log content.

## Test H — scoped GitHub permission revoke and external-account boundary

Use only the disposable grant prepared for this test.

### H1 — inspect without mutation

1. Verify TalkBack explicitly announces **`Ekstern konto: GitHub · <account>`** for the disposable grant.
2. Verify TalkBack reads the outbound-data explanation: repository, selected read operation and optional object id may be sent to GitHub for a read; the credential is worker-transport-only and is not displayed in Control Center.
3. Verify TalkBack announces exact repositories, allowed read operations, active/revoked state and the shortened scope digest.
4. Confirm the account/repository/read-operation text matches the disposable grant prepared for this run; do not accept a broader or ambiguous scope.
5. Activate **Tilbagekald tilladelse**.
6. Verify the confirmation text explains that new GitHub calls for this exact scope will stop and that the server revalidates the scope digest.
7. Activate **Annullér**.
8. Verify the grant remains active after cancellation.

### H2 — confirm revoke

1. Re-open **Tilbagekald tilladelse** for the disposable grant.
2. Activate **Bekræft tilbagekaldelse**.
3. Verify only one revoke can be in flight; other revoke actions must not remain independently actionable while the mutation is running.
4. After server confirmation and refresh, verify the same grant is rendered **REVOKED/tilbagekaldt**.
5. Verify the UI did not optimistically change state before server confirmation.
6. Attempt the same revoke again only if the product surface permits it; an already-revoked/stale case must not be described as “pilot missing”.

The T-036 authority owns the server-side guarantee that revocation stops new connector calls. Link the matching repository-qualified T-036 evidence that is ancestor/included in the exact ModelRig candidate rather than substituting the old T-036 implementation head as a second physical runtime authority. Do not duplicate credentials or raw connector responses in this manual report.

## Test I — light/dark and readable semantics

Repeat the main navigation/audit/revoke inspection in both available app themes if the tested build exposes both during the run.

Pass criteria:

- meaning does not rely on color alone;
- headings, fields and buttons have usable TalkBack names;
- warning/error/unavailable states remain distinguishable;
- no critical control is clipped or unreachable on the physical device.

If theme switching is not available in the tested build, record the inherited system/app theme and mark the unavailable variant as **not exercised**, not passed.

## Result table

Use exactly one status per row: `PASS`, `FAIL`, `BLOCKED`, or `NOT_EXERCISED`.

| Check | Status | Evidence note |
|---|---|---|
| A — open/close + focus order |  |  |
| B — health/routing/fallback |  |  |
| C — capabilities |  |  |
| D — schedules/jobs/history |  |  |
| E — privacy/data-sharing |  |  |
| F — task/capability/approval audit filters |  |  |
| G — first-class connector filter |  |  |
| H1 — external account/data boundary + revoke confirmation/cancel |  |  |
| H2 — confirmed disposable-grant revoke |  |  |
| I — physical readability/theme coverage |  |  |

## Required final statement

A valid acceptance comment on #88 must state all of the following explicitly:

```text
Physical-device review: PASS/FAIL
TalkBack review: PASS/FAIL
Exact ModelRig candidate SHA tested: <40-char SHA>
Observed git HEAD: <40-char SHA>
Android APK SHA-256: <64 hex>
Same candidate checkout owned Android/backend/worker/connector code: yes/no
Fresh required repository qualification on the exact candidate: yes/no
Connector filter tested from first-class connector evidence: yes/no
External GitHub account + outbound data boundary read with TalkBack: yes/no
Disposable scoped revoke tested: yes/no
production_activation=false: confirmed/not-confirmed
Known blocked/not-exercised items: <list or none>
No credential/private-content evidence attached: confirmed/not-confirmed
```

T-044 must remain open if a required acceptance item is failed, blocked, not exercised, lacks exact-candidate provenance, mixes component SHAs/checkouts, or lacks the required fresh repository qualification.
