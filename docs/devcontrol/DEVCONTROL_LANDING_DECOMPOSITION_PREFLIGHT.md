# DevControl landing decomposition — preflight

**Status:** preflight only · dependency model corrected after exact-head author review  
**Source PR:** `#338` (`agent/devcontrol-foundation-v1`)  
**Source head:** `07dd596bd4fef6bdc8fecf0a327b28c1c66d9d3f`  
**Planning base:** `main @ 9ce48d321fb3d04a67b4038058a83c2fa627d4d5`  
**Machine-readable plan:** `docs/devcontrol/DEVCONTROL_LANDING_SLICES.json`

## 1. Purpose

PR #338 is a validated integration and reference branch, not a reviewable landing unit. At the locked source head it contains 420 commits, 219 changed files, 49,225 additions and 32 deletions. ADR-DC-001 explicitly forbids landing that body of work as one monolithic pull request.

This preflight locks:

- landing order and dependency direction;
- common fail-closed gates;
- which authority boundary each slice owns;
- where the unresolved P1 findings must be closed;
- how source provenance is retained without replaying 420 commits; and
- when physical I0b evidence may become valid again.

It moves no implementation code. A slice is acceptable only when it is complete on the `main` head it targets, has no dependency on an unlanded future slice, and can be rejected or reverted without leaving hidden half-authority behind.

## 2. Non-negotiable ADR-DC-001 invariants

Every slice inherits these invariants:

1. **DevControl remains isolated.** Product code must not import `kaliv_dev_control`.
2. **Human authority is terminal.** No slice may add push, PR mutation, reviewer request, ready-for-review, merge, release, settings, secret, deployment or activation authority.
3. **Every authority layer fails closed.** Missing, stale, ambiguous or unverifiable input rejects rather than degrades.
4. **Physical evidence is executable authority.** It binds exact task, rig, workspace, toolchain and authority bytes.
5. **Containment is enforced by Windows.** The claim rests on native Job Object, AppContainer, ACL and handle semantics.
6. **Dormancy is tested.** Importing the package starts no threads, timers, polling, subprocesses, file writes or routes.
7. **Publication requires another ADR.** Green software and physical evidence cannot silently become remote authority.
8. **The DC ADR series is authoritative.** Slice documents report implementation status but cannot redefine architecture.

## 3. Landing model

### 3.1 Fresh-main, non-stacked PRs

Each implementation slice starts from then-current `main`, after all declared prerequisites have landed. No review depends on a sibling PR or unpublished branch. If `main` advances, the exact-head matrix reruns before review.

```text
DC-L00
  ├─ DC-L01 → DC-L02 → DC-L03 → DC-L04 ─┐
  └──────────────────── DC-L05 ───────────┤
                                           v
DC-L06 → DC-L07 → DC-L08 → DC-L09 → DC-L10
      → DC-L11 → DC-L12 → DC-L13 → DC-L14 → DC-L15
```

`DC-L05` is independently reviewable because it is a native worker substrate and may not import DevControl. `DC-L06` is the first point where evidence contracts and the native substrate meet.

### 3.2 Projection, not history replay

The source branch is reference material, not merge material. Slices must not cherry-pick its 420-commit history wholesale.

For every selected file or symbol, the slice records:

- source PR, source head, path and Git blob SHA;
- whether content is copied exactly or deliberately projected;
- every deliberate delta and its reason; and
- the test or mutation proving the delta safe.

Projection is required whenever a final source file imports later-slice modules. A final-form facade may not land early merely for convenience.

### 3.3 Progressive integration surfaces

The following files intentionally evolve across slices and therefore require an exact per-slice diff allowlist:

- `.github/workflows/_tests.yml`
- `devcontrol/README.md`
- `devcontrol/pyproject.toml`
- `devcontrol/src/kaliv_dev_control/__init__.py`
- `devcontrol/src/kaliv_dev_control/__main__.py`
- `devcontrol/src/kaliv_dev_control/_tier_a_execution_core.py`
- `devcontrol/src/kaliv_dev_control/_tier_a_legacy_toolhost.py`
- `devcontrol/src/kaliv_dev_control/tier_a_authority.py`
- `tests/workflow_test_coverage.py`
- `worker/requirements.txt`

The three Tier-A files above are progressive because the compatibility facade and exact bundle closure must contain only already-landed modules. Their final source-branch bytes cannot land before the closure they name exists.

`tier_a_execution.py` is **not** progressive: its final public compatibility surface imports runtime-closure and command-receipt layers, so it lands only in `DC-L09`, after those dependencies exist.

### 3.4 Exact source-path disposition

The 219 source paths must resolve to exactly one of:

- `land:<slice-id>`;
- `progressive:<slice-id-list>`;
- `reject:<reason>`; or
- `supersede:<replacement>`.

Before `DC-L01` begins, PR #352 must contain a literal `source-path-disposition.json` covering all 219 paths with no duplicates or omissions. Rule families in this document are planning aids, not merge-time allowlists.

### 3.5 Authority digest and evidence semantics

Every Tier-A bundle change changes the authority digest. Therefore:

- hosted CI may use synthetic evidence during software landing;
- all historical physical evidence remains stale;
- no intermediate slice may claim physical readiness; and
- real I0b runs only after `DC-L14` freezes the final exact authority closure.

## 4. Required artifacts for every software slice

Before code is reviewed, each slice publishes:

1. `preflight.md`
2. `exact-path-allowlist.json`
3. `symbol-ownership.json`
4. `source-provenance.json`
5. `source-path-disposition.json`
6. `exact-head-validation.md`
7. `mutation-results.md`
8. `independent-review-verdict.md`

The implementation PR is not ready until all eight agree.

## 5. Common gates

### 5.1 Scope and provenance

- Exact base and source heads are recorded.
- Changed paths equal a literal allowlist.
- Every source path has exactly one disposition.
- Owned symbols equal the symbol manifest with no loss, duplication or accidental re-export.
- Copied files match recorded blobs unless an explicit projection delta is documented.
- No code imports a module assigned to a future slice.

### 5.2 Dormancy and authority

- `import kaliv_dev_control` has no file, thread, timer, polling, subprocess or route side effect.
- Product modules do not import `kaliv_dev_control`.
- No HTTP write method, remote Git operation, credential loader or GitHub mutation exists.
- Merge and activation remain human-only.
- Default command/tool registration remains empty unless a reviewed immutable catalog explicitly lands.

### 5.3 Fail-closed behavior

- Missing, stale, extra, linked, ambiguous or tampered authority input rejects.
- Booleans cannot satisfy integer budgets or limits.
- Canonical artifacts reject unknown fields and non-canonical reloads.
- Timeout and output overflow terminate the whole process tree where execution exists.
- A failed probe, failed review or uncertain assessment cannot produce positive authority.

### 5.4 Mutation proof

Every load-bearing gate needs a controlled red/green mutation. Examples:

- remove one authority file from the recursive bundle;
- replace an exact SHA comparison with truthiness;
- allow a redirect or non-GET method;
- skip one physical probe;
- permit reviewer/developer identity overlap;
- remove parent-directory durability;
- allow an extra staged closure file;
- reuse a replay nonce;
- add a Git remote; or
- expose a retained signer or executor publicly.

### 5.5 Exact-head validation

The reviewed commit runs all applicable portable DevControl tests, repository lint and workflow coverage, complete repository test discovery, native Windows isolation contracts, touched platform gates, CodeQL and independent diagnostics. A green ancestor or byte-different checkpoint is not evidence.

## 6. Slice sequence

Candidate path families below are replaced by literal path lists in each slice preflight.

### DC-L00 — landing decomposition preflight

Lands this plan and machine-readable companion only. Before it can be marked ready, it must also add the literal 219-path disposition inventory required by §3.4 and receive an independent review anchored to the exact head.

### DC-L01 — task, scope, workspace and bounded command foundation

Lands the dependency-minimal package skeleton, immutable task contract, path policy, scoped files, bounded patching, fixed command templates, receipts and exact-SHA workspace management.

No catalog, physical evidence, process launch or network boundary exists. The default registry remains empty.

### DC-L02 — durable campaign, store and structural review

Lands `durable_publication`, hash-chained campaign state, controlled storage, structural review and proposal-only output.

This slice must close the `CampaignStore` stale-lock and parent-directory durability findings. `streaming_publication.py` does **not** land here; it belongs to the runtime-staging slice where its metadata durability can be reviewed with its callers.

### DC-L03 — immutable catalog and GET-only GitHub boundary

Lands trusted command IDs, immutable catalog/toolchain binding and fixed-host GET-only, redirect-free GitHub reads. It cannot mutate a branch, PR or repository and cannot select an executable.

### DC-L04 — signed physical Windows evidence contract

Lands the canonical eleven-probe I0b model, operator CLI, separate collector/approver identities, signing and strict verification. This is software contract landing only, not a genuine rig campaign.

### DC-L05 — native Windows containment substrate

Lands worker-side suspended launch, Job Object, AppContainer, ACL, output capture and runtime guard plus native fixtures. It may harden the existing `ProcessExecutor`, but may not register DevControl, add a route or import `kaliv_dev_control`.

### DC-L06 — Tier-A identities and materialization

Lands lease, environment, path, materialization, retained v2 toolhost and retained v1 launch-plan identities.

It also lands **projected initial versions** of:

- `_tier_a_execution_core.py` as an import-only facade over already-landed identities;
- `_tier_a_legacy_toolhost.py` with an exact stage-local bundle tuple; and
- `tier_a_authority.py` exposing only already-landed authority.

No supported process-launch entrypoint exists.

### DC-L07 — deterministic runtime staging, closure, plan and result evidence

Lands:

- `streaming_publication.py`, with permission-metadata durability fixed;
- `runtime_staging.py`;
- runtime-closure common/model/verify/staging/public modules;
- closure-bound `tier_a_plan.py`;
- `tier_a_result.py`; and
- the standalone Go version-check closure.

This slice extends the progressive Tier-A core/toolhost/authority files only enough to include the new landed closure. It does not land either executor.

### DC-L08 — verified-only Tier-A execution

Lands the retained legacy runner, modern v3 executor and their native execution tests. It extends the progressive compatibility core, toolhost bundle and authority module to their execution-stage forms.

The completed execution path preserves timeout, process-tree termination, AppContainer, fresh workspace/toolhost/executable verification and closure re-verification. Modern v3 identities must not alias the retained non-capturing runner.

### DC-L09 — trusted Git runtime, command receipt and final public execution facade

Lands trusted Git staging, exact Git snapshots, mutation/reset evidence, the one-command receipt orchestrator and the final `tier_a_execution.py` compatibility surface.

No remote or credential mechanism is allowed. A passing receipt requires exact-base cleanliness or exact authenticated staged input; observed mutation is non-passing and followed by verifiable reset evidence.

### DC-L10 — asymmetric authority and independent semantic review

Lands public-key-only verification, semantic request/verdict artifacts and durable review publication. Private signing keys remain external. Developer and reviewer identities differ; uncertainty or findings prevent approval.

### DC-L11 — draft readiness and publisher dry-run intent

Lands deterministic draft-only readiness, signed publisher intent and operations fixed to `planned_not_executed`. No Git, HTTP, token or repository mutation adapter may exist.

### DC-L12 — one-time authorization, replay and authenticated recovery

Lands least-privilege public-key authorization, single-use replay state, authenticated recovery receipts and one physical primary ledger implementation.

It must close rollback-safe external keyring state. Signed local files alone cannot establish monotonic epoch/revocation state.

### DC-L13 — local-only candidate materialization

Lands deterministic creation and verification of one isolated local bare-repository candidate. Only the exact base and authenticated patch are used; only the deterministic local ref exists; no remote exists.

### DC-L14 — final authority closure, packaging and dormant integration

Finalizes all progressive surfaces, the recursive authority bundle, generated inventory, split contract, package surface, protocol inventory, CI coverage and dormancy proof.

Supported wheel and sdist artifacts must exclude `_compatibility_v1` and other unsupported retained implementations. Tests inspect built artifacts. Build backend and dependencies must be exact and hash-controlled.

### DC-L15 — fresh physical I0b campaign and pilot decision packet

Runs eleven native probes against the exact frozen `main` head after DC-L14. Collector and approver remain independent. A green packet is evidence for a later human decision, never automatic activation.

## 7. Cross-cutting source allocation

| Source area | Landing owner | Rule |
|---|---|---|
| `worker/app/windows_*.py`, `worker/app/toolhost.py`, native fixtures | DC-L05 | Native containment only; no DevControl import |
| `backend/cmd/modelrig-version-check/**` | DC-L07 | Standalone closure target |
| `streaming_publication.py` | DC-L07 | Lands with callers and closes metadata durability |
| `runtime_staging.py`, `runtime_closure*.py`, `tier_a_plan.py`, `tier_a_result.py` | DC-L07 | No executor yet |
| `_tier_a_legacy_runner.py`, `tier_a_execution_v3.py` | DC-L08 | Execution after closure exists |
| `tier_a_command_receipt.py`, trusted Git modules, `tier_a_execution.py` | DC-L09 | Public facade only after receipt exists |
| `_tier_a_execution_core.py`, `_tier_a_legacy_toolhost.py`, `tier_a_authority.py` | progressive, finalized DC-L14 | Stage-local closure only |
| `worker/requirements.txt`, `pyproject.toml` | progressive, finalized DC-L14 | Dependency belongs where first consumed |
| `.github/workflows/_tests.yml`, `tests/workflow_test_coverage.py` | progressive, finalized DC-L14 | Each slice adds only its own gate |
| `scripts/tier_a_bundle_inventory.py` | DC-L14 | Final recursive authority closure |

Documentation and schemas land with the code they specify. A schema may not land before a reader/writer merely to inflate completeness, and code may not land without its schema and parity tests.

## 8. Source-branch treatment

PR #338 remains a draft reference branch. It receives only source synchronization, corrections discovered while projecting, generated source inventory and supersession markers. It receives no new feature scope.

When every source path is landed, rejected or superseded, and physical evidence is anchored, PR #338 closes as decomposed rather than merged.

## 9. Definition of done

Decomposition is complete only when:

- every one of the 219 source paths has a recorded disposition;
- every software slice lands from fresh current `main`;
- all assigned P1 findings are closed;
- DC-L14 proves final packaging, dormancy and recursive authority closure;
- DC-L15 binds fresh physical evidence to the exact frozen head;
- PR #338 contains no unique accepted implementation left behind; and
- no slice introduced remote publication or activation authority.

Until then, PR #338 remains a valuable source branch, not a release or merge candidate.
