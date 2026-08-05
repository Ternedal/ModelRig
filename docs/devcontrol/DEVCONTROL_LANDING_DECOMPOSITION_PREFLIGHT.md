# DevControl landing decomposition — preflight

**Status:** preflight only · no implementation code moved  
**Source PR:** `#338` (`agent/devcontrol-foundation-v1`)  
**Source head:** `07dd596bd4fef6bdc8fecf0a327b28c1c66d9d3f`  
**Planning base:** `main @ 9ce48d321fb3d04a67b4038058a83c2fa627d4d5`  
**Machine-readable plan:** `docs/devcontrol/DEVCONTROL_LANDING_SLICES.json`

## 1. Purpose

PR #338 is a validated integration and reference branch, not a reviewable landing unit. At the locked source head it contains 420 commits, 219 changed files, 49,225 additions and 32 deletions. ADR-DC-001 explicitly forbids landing that body of work as one monolithic pull request.

This preflight defines how the final implementation is projected from the source branch into bounded, independently reviewable slices. It moves no DevControl code. Its job is to lock:

- landing order and dependency direction;
- common fail-closed gates;
- which authority boundary each slice owns;
- where the four unresolved P1 findings must be closed;
- how source provenance is retained without replaying 420 commits; and
- when physical I0b evidence may become valid again.

The plan is intentionally stricter than “split the diff into smaller PRs”. A slice is acceptable only when it is complete on the `main` head it targets, has no dependency on an unlanded future slice, and can be rejected or reverted without leaving a hidden half-authority behind.

## 2. Non-negotiable ADR-DC-001 invariants

Every slice inherits these invariants:

1. **DevControl remains an isolated package.** Product code must not import `kaliv_dev_control`.
2. **Human authority is terminal.** No slice may add push, PR mutation, reviewer request, ready-for-review, merge, release, settings, secret, deployment or activation authority.
3. **Every authority layer fails closed.** Missing, stale, ambiguous or unverifiable input rejects rather than degrades.
4. **Physical evidence is executable authority, not documentation.** Evidence binds exact task, rig, workspace, toolchain and authority bytes.
5. **Containment is enforced by Windows.** The claim rests on native Job Object, AppContainer, ACL and handle semantics, not process discipline.
6. **Dormancy is tested.** Importing the package must not start threads, timers, polling, subprocesses, file writes or routes.
7. **Publication requires another ADR.** Green software and physical evidence cannot silently become remote authority.
8. **The DC ADR series is authoritative.** Slice documents may report implementation status but cannot redefine architecture.

## 3. Landing model

### 3.1 Fresh-main, non-stacked PRs

Each implementation slice is created from the then-current `main`, after all declared prerequisites have landed. No review depends on a sibling PR or an unpublished branch. If `main` advances, the slice is synchronized and its exact-head matrix reruns before review.

This produces a mostly linear authority chain, with one deliberate parallel opportunity:

```text
DC-L00
  ├─ DC-L01 ─ DC-L02 ─ DC-L03 ─ DC-L04 ─┐
  └────────────────────── DC-L05 ─────────┤
                                           v
DC-L06 → DC-L07 → DC-L08 → DC-L09 → DC-L10
      → DC-L11 → DC-L12 → DC-L13 → DC-L14 → DC-L15
```

`DC-L05` can be reviewed independently because it is a native worker substrate and may not import DevControl. `DC-L06` is the first point where the evidence contract and the native substrate meet.

### 3.2 Projection, not history replay

The source branch is authoritative reference material, not merge material. Implementation slices must not cherry-pick the 420-commit history wholesale.

For every selected file or symbol, the slice records:

- source PR and source head;
- source path and Git blob SHA;
- whether the file is copied exactly or deliberately projected;
- every deliberate delta from the source branch;
- the reason for the delta; and
- the test or mutation that proves the delta is safe.

A deliberate projection is required when the final source file imports modules belonging to later slices. For example, `kaliv_dev_control.__init__` must expose only already-landed symbols; it cannot be copied in final form during the foundation slice.

### 3.3 Progressive integration surfaces

These files are expected to evolve across several slices and therefore do not have one permanent “owner slice”:

- `.github/workflows/_tests.yml`
- `devcontrol/README.md`
- `devcontrol/pyproject.toml`
- `devcontrol/src/kaliv_dev_control/__init__.py`
- `devcontrol/src/kaliv_dev_control/__main__.py`
- `tests/workflow_test_coverage.py`
- `worker/requirements.txt`

Each slice may change one of these only through an exact diff allowlist. The final source-branch version is not copied early merely for convenience.

### 3.4 Authority digest and evidence semantics

Every change to a Tier-A bundle member changes the authority digest. Therefore:

- hosted CI may use synthetic evidence throughout software landing;
- all historical physical evidence remains stale;
- no intermediate slice may claim physical readiness; and
- the real I0b campaign runs only after `DC-L14` freezes the final exact authority closure.

## 4. Required artifacts for every software slice

Before code is added, each slice must publish a preflight containing:

1. `preflight.md` — purpose, threat boundary, prerequisites and exclusions.
2. `exact-path-allowlist.json` — every path the slice may add, modify or delete.
3. `symbol-ownership.json` — top-level symbols introduced, moved or re-exported.
4. `source-provenance.json` — source head, source blob SHAs and deliberate deltas.
5. `exact-head-validation.md` — commands, workflow runs and exact tested commit.
6. `mutation-results.md` — load-bearing gates proved red by controlled mutation.
7. `independent-review-verdict.md` — verdict anchored to the exact head.

The implementation PR is not ready for review until all seven exist and agree.

## 5. Common gates

Every software slice must pass all applicable gates below.

### 5.1 Scope and provenance

- Exact base head and exact source head are recorded.
- Changed paths equal the path allowlist; no wildcard is evaluated at merge time.
- Owned symbols equal the symbol manifest with no loss, duplication or accidental re-export.
- Every copied source file matches its recorded blob, unless a deliberate delta is documented.
- No code imports a module assigned to a future slice.

### 5.2 Dormancy and authority

- `import kaliv_dev_control` has no file, thread, timer, polling, subprocess or route side effect.
- Product modules do not import `kaliv_dev_control`.
- No HTTP write method, remote Git operation, credential loader or GitHub mutation exists.
- Merge and activation remain human-only.
- Default command/tool registration remains empty unless the slice explicitly lands a reviewed immutable catalog.

### 5.3 Fail-closed behavior

- Missing, stale, extra, linked, ambiguous or tampered authority input rejects.
- Boolean values cannot satisfy integer budgets or limits.
- Canonical artifacts reject unknown fields and non-canonical reloads.
- Timeout and output overflow terminate the entire process tree where execution exists.
- A failed probe, failed review or uncertain assessment cannot produce positive authority.

### 5.4 Mutation proof

At least one mutation must be demonstrated for every load-bearing gate. Examples include:

- remove one authority file from the recursive bundle;
- replace exact SHA comparison with truthiness;
- allow a redirect or non-GET method;
- skip one physical probe;
- permit reviewer/developer identity overlap;
- remove parent-directory durability;
- allow an extra staged closure file;
- reuse a replay nonce;
- add a Git remote; or
- expose a retained legacy signer or executor publicly.

The gate must become red for the expected reason and return green when the mutation is removed.

### 5.5 Exact-head validation

The final exact commit must run:

- portable DevControl tests;
- repository Python lint and workflow coverage;
- complete repository test discovery;
- native Windows isolation contracts when relevant;
- backend, Android and desktop gates when touched;
- CodeQL for Go and Python; and
- independent diagnostics used by the repository.

A green ancestor or byte-different checkpoint is not evidence for the reviewed head.

## 6. Slice sequence

The machine-readable manifest contains candidate path families and merge blockers. The implementation preflight for each slice replaces those families with a literal path list.

### DC-L00 — landing decomposition preflight

**Purpose:** land this plan and its machine-readable companion only.

**Must prove:** the sequence covers every authority layer represented in PR #338, contains no code, grants no runtime authority and does not treat the source branch as mergeable wholesale.

### DC-L01 — task, scope, workspace and bounded command foundation

Lands the dependency-minimal package skeleton, immutable task contract, path policy, scoped files, bounded patching, fixed command templates, receipts and exact-SHA workspace management.

The public package surface is deliberately small. The default registry remains empty. No catalog, physical evidence, process launch or network boundary exists yet.

**Primary merge blockers:**

- package import has side effects;
- caller-selected executable or arbitrary argument authority;
- a future-slice import;
- non-canonical task or receipt reload; or
- workspace state not bound to the exact base commit.

### DC-L02 — durable campaign, store and structural review

Lands hash-chained campaign state, durable create-once primitives, the controlled store, structural review and proposal-only output.

This slice must close the existing `CampaignStore` finding before landing. “Existing lock means fail” is not sufficient: stale-lock recovery must be bounded, owner-aware and crash-safe, and durable commits must include the required directory metadata persistence.

**Primary merge blockers:**

- stale lock has no safe recovery protocol;
- parent directory durability is incomplete;
- immutable output can be replaced;
- review can grant remote or merge authority; or
- campaign state and journal can diverge silently.

### DC-L03 — immutable catalog and GET-only GitHub boundary

Lands trusted command IDs, immutable catalog/toolchain binding and fixed-host read-only GitHub access.

The network surface is GET-only, redirect-free and path-scoped. It may verify exact commits and read exact text; it cannot create a branch, mutate a PR or select an executable.

### DC-L04 — signed physical Windows evidence contract

Lands the canonical eleven-probe I0b model, operator CLI, separate collector/approver identities, signing and strict verification.

This is software contract landing only. No hosted result is represented as a genuine rig campaign. Evidence remains stale whenever later authority bytes change.

### DC-L05 — native Windows containment substrate

Lands the worker-side suspended launch, Job Object, AppContainer, ACL, capture and runtime-guard implementation plus native fixtures.

This slice is independent of the DevControl package and must remain so. It may strengthen the existing worker `ProcessExecutor`, but it may not register DevControl, add a route or import `kaliv_dev_control`.

**Primary merge blockers:**

- child executes before Job Object assignment;
- timeout leaves descendants;
- native claims are proved only with mocks;
- ordinary tool execution silently gains DevControl authority; or
- product code imports the package.

### DC-L06 — Tier-A authority identities and materialization

Lands the focused lease, environment, path, materialization, retained toolhost and launch-plan modules. It establishes exact object identity and evidence-to-lease conversion but exposes no supported process-launch path.

The authority bundle used at this stage must include only files actually landed. It may not list future modules merely to resemble the final source branch.

### DC-L07 — verified-only Tier-A execution and result evidence

Lands the retained legacy runner, import-only compatibility core, modern v3 executor, result model and public verified-only facade.

The completed core owns zero top-level implementation symbols. The retained legacy executor remains physically isolated and absent from the supported modern authority surface. Modern v3 names must not accidentally alias the retained non-capturing runner.

### DC-L08 — deterministic runtime staging, closure and lifetime guard

Lands single-file staging, signed multi-file closure, exact cwd, bounded native output, lifetime immutability and the standalone Go version-check closure.

This slice must close the streaming-publication permission-metadata finding before landing. Any permission repair or preparation callback that affects the durable artifact must be followed by durable metadata persistence with failure represented as a domain error.

### DC-L09 — trusted Git runtime and Git-aware execution receipt

Lands trusted Git staging, exact Git snapshots, mutation/reset evidence and the one-command receipt orchestrator.

No remote or credential mechanism is allowed. A passing receipt requires exact-base cleanliness or exact authenticated staged input; any observed mutation becomes non-passing and is followed by independently verifiable reset evidence.

### DC-L10 — asymmetric authority and independent semantic review

Lands public-key-only verification, semantic request/verdict artifacts and durable review publication.

Private signing keys remain external. The supported runtime receives verification material only. Developer and reviewer identities must differ, every criterion must be assessed, and uncertainty or any finding prevents approval.

### DC-L11 — draft readiness and publisher dry-run intent

Lands deterministic draft-only readiness, signed publisher intent and a plan whose operations remain `planned_not_executed`.

No Git, HTTP, token or repository mutation adapter may exist. The artifact can describe a future draft PR but cannot make one.

### DC-L12 — one-time authorization, replay and authenticated recovery

Lands least-privilege public-key authorization, single-use replay state, authenticated recovery receipts and one physical primary ledger implementation.

This slice must close the rollback-safe external keyring finding. Epoch and revocation state cannot be trusted solely because a local file has a valid signature; the selected external monotonic/rollback-detection mechanism, operator recovery procedure and failure semantics must be defined and tested before merge.

Retained HMAC v1 issuance remains unsupported and must not leak onto the public surface.

### DC-L13 — local-only candidate materialization

Lands deterministic creation and later verification of one isolated local bare-repository candidate.

The trusted Git binary, source repository and destination root are explicit external boundaries. Only the exact base is imported, only the exact authenticated patch is applied, only the deterministic proposed local ref is created, and no remote exists.

### DC-L14 — final authority closure, packaging and dormant integration

Freezes the complete recursive authority bundle, generated inventory, split contract, package surface, final CI gates and dormancy proof.

This slice is where integration surfaces reach their final form. It also closes the retained compatibility packaging finding: supported wheel and sdist artifacts must exclude `_compatibility_v1` and other intentionally retained historical implementation that is not part of the supported runtime distribution. Tests must inspect built artifacts, not only import visibility from the source tree.

It additionally resolves build reproducibility: the build backend and build dependencies must be exact and hash-controlled according to the repository’s chosen packaging mechanism.

**Merge blockers include:**

- any missing or duplicate recursive authority file;
- non-reproducible inventory or split contract;
- product-to-DevControl import;
- import-time activity;
- retained compatibility code installed in the supported distribution;
- unpinned build toolchain;
- remote-write or activation surface; or
- stale documentation claiming the integration branch itself is a landing unit.

### DC-L15 — fresh physical I0b campaign and pilot decision packet

Runs the eleven native probes against the exact frozen `main` head after DC-L14. Collector and approver remain independent. Evidence, logs, hashes and verdict are published as a separate physical-validation packet.

A fully green packet is still not activation. It supplies evidence for a later human pilot/no-pilot decision. Any actual publication capability or unattended activation requires a new ADR.

## 7. Cross-cutting source allocation

The source PR contains files outside `devcontrol/`; they are not incidental and must be allocated deliberately:

| Source area | Landing owner | Rule |
|---|---|---|
| `worker/app/windows_*.py` and native fixtures | DC-L05 | Native containment substrate; no DevControl import |
| `worker/app/toolhost.py` | DC-L05 | Existing executor hardening only; no registration |
| `backend/cmd/modelrig-version-check/**` | DC-L08 | Standalone closure target; default catalog unchanged |
| `worker/requirements.txt` | progressive, finalized DC-L14 | Dependency may move to package-local installation if product runtime does not need it |
| `.github/workflows/_tests.yml` | progressive, finalized DC-L14 | Each slice adds only its own gate |
| `tests/workflow_test_coverage.py` | progressive, finalized DC-L14 | Coverage must track every new executable test family |
| `scripts/tier_a_bundle_inventory.py` | DC-L14 | Final recursive authority closure only |

Documentation and schemas land with the code they specify. A schema may not land before any reader/writer exists merely to inflate completeness, and code may not land without the schema and parity test that defines its canonical artifact.

## 8. Source-branch treatment after decomposition

PR #338 remains open as a draft reference branch while decomposition is active. It should be updated only for:

- synchronization needed to preserve a trustworthy source snapshot;
- corrections discovered while projecting a slice;
- generated source inventory; and
- explicit supersession markers pointing to landed slice PRs.

It must not receive new feature scope. Once every source path is either landed, deliberately rejected or superseded—and the final physical packet is anchored—the integration PR can be closed as decomposed, not merged.

## 9. Definition of done for the decomposition

The decomposition is complete only when:

- every relevant source path has a recorded disposition;
- every software slice has landed from a fresh current-main branch;
- all four P1 findings are closed in their assigned slices;
- DC-L14 proves the final package and recursive authority closure;
- DC-L15 binds fresh physical evidence to the exact frozen head;
- PR #338 contains no unique accepted implementation left behind; and
- no slice introduced remote publication or activation authority.

Until then, PR #338 is a valuable verified source branch—but not a release candidate and not a merge candidate.
