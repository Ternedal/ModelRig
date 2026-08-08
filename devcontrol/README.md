# Kaliv Development Control — landed foundations through DC-L11

These slices are the dormant, bounded foundation defined by
`docs/devcontrol/ADR-DC-001_DEVCONTROL_AUTHORITY_BOUNDARY.md` and the landed
DC-L00 decomposition contract.

## DC-L01 authority

DC-L01 supplies immutable task contracts, canonical repository-relative scope,
bounded reads/search, fail-closed patching, deterministic raw-byte receipts,
fixed command templates, exact-HEAD and clean-state binding, bounded subprocess
supervision and disposable Git sandboxes.

`default_registry()` remains empty. Product code must not import
`kaliv_dev_control`.

## DC-L02 authority

DC-L02 adds local, dormant campaign and review structure:

- immutable hash-chained campaign state;
- crash-durable create-once and atomic-replace publication primitives;
- a compare-and-swap `CampaignStore` with fail-closed stale-lock recovery;
- independent structural review requests and verdicts; and
- deterministic draft pull-request proposals with human-only merge authority.

## DC-L03 authority

DC-L03 adds immutable catalog and toolchain contracts plus a fixed-host, HTTPS,
GET-only GitHub read boundary. The default ModelRig catalog and default registry
remain empty, and every non-empty catalog materialization is rejected fail-closed.
Python, Go, sandbox and custom-static command execution remain deferred.

## DC-L04 authority

DC-L04 defines the signed physical Windows-isolation evidence contract. It
provides eleven mandatory probe identities, canonical unsigned and signed report
models, exact authority binding, separate collection and approval actors,
bounded stable evidence reads and crash-durable create-once publication.

A failed probe can be recorded honestly but cannot authorize anything. Historical
physical evidence remains stale until the final authority closure is frozen and a
fresh physical campaign is run.

## DC-L05 authority

DC-L05 lands the product-side native Windows containment substrate without
activating DevControl:

- Job Object assignment before resume, process and memory limits, and kill-on-close;
- AppContainer/restricted-token launch with a workspace-scoped capability;
- bounded product-side stdout/stderr capture and whole-process-tree cleanup;
- exact working-directory and reviewed environment handling;
- runtime-lifetime immutability checks; and
- a dormant Tier-A Windows launch surface used only by explicit product-side tests.

The product modules under `worker/app/` do not import `kaliv_dev_control`.

## DC-L06 authority

DC-L06 lands the first non-executing Tier-A authority identities:

- exact execution-lease identity and canonical task binding;
- reviewed application environment policy;
- canonical workspace and regular-file authority;
- signed physical-evidence capture and leased catalog materialization;
- retained v1 launch-plan identity and deterministic construction; and
- an import-only compatibility core with no process-launch entrypoint.

The default catalog remains empty and no command is activated.

## DC-L07 authority

DC-L07 adds deterministic, non-executing runtime evidence:

- bounded streaming create-once publication;
- crash-durable permission metadata before immutable publication evidence;
- deterministic single-runtime staging receipts;
- signed multi-file runtime-closure models, verification and staging receipts;
- canonical Tier-A launch-plan v2/v3 identity with exact cwd and closure binding;
- bounded binary-safe execution-result models without an executor;
- a reviewed single-file `modelrig-version-check` closure builder; and
- a v5 toolhost hash over the complete stage-local non-executing authority chain.

Positive staging evidence is not issued until file metadata and the containing
directory have been flushed.

## DC-L08 authority

DC-L08 adds verified-only Tier-A execution through the private
`tier_a_execution_v3` module:

- every invocation rematerializes a fresh lease from signed physical evidence;
- only a command-specific signed runtime closure may be staged and launched;
- the exact executable, cwd, workspace, authority bundle, manifest, signature and
  staging receipt are rechecked immediately before process creation;
- execution uses the existing AppContainer and Job Object substrate;
- stdout and stderr are captured as bounded binary-safe evidence;
- timeout closes the Job Object, reaps the process tree and returns a canonical
  timed-out result through `TierAExecutionTimeout`; and
- runtime-closure lifetime locks remain held until process-tree shutdown is proven.

## DC-L09 authority

DC-L09 adds the complete local trusted-Git and command-receipt boundary:

- a manifest for every file in one operator-reviewed Git runtime package;
- create-once, crash-durable runtime staging and authenticated recovery evidence;
- a no-shell `TrustedGitRunner` with isolated HOME, configuration, hooks and temp;
- fixed local-only Git protocol policy with prompts, credentials and remote
  transports disabled;
- canonical before/after/reset workspace snapshots with bounded binary diffs;
- one-command receipt orchestration that joins the exact Git runtime identity to
  the canonical Tier-A result and resets mutations to the exact task base; and
- `tier_a_execution.py` as the single final public compatibility facade routing
  to the v3 executor and the Git-aware receipt orchestrator.

The v7 toolhost identity includes the private executor, trusted-Git runtime,
command receipt and final facade. Package root, `tier_a_authority`,
`runtime_staging` and `_tier_a_execution_core` still expose no process-launch
function. The default catalog remains empty, so no product route or normal
package import activates execution.

## DC-L10 authority

DC-L10 adds two separate offline verification boundaries without extending
Tier-A process authority:

- verification-only Ed25519 authority with pinned public keys, issuer identities,
  validity windows, monotonic keyring epochs, custody-policy binding and
  verification-time revocation;
- canonical semantic-review requests bound to one exact task, staged patch,
  passing Git-aware Tier-A receipt, fixed review policy and current v7 execution
  authority identity;
- structured independent verdicts with one ordered assessment per acceptance
  criterion and fail-closed approval semantics;
- authenticated v1 review-verdict compatibility using reviewer-held HMAC material
  outside the developer and execution workspace; and
- crash-durable, create-once offline publication of requests and signed verdicts.

The Ed25519 runtime contains no private-key type, signer, private-key loader,
credential adapter or transport. Semantic review cannot inspect a mutable
workspace, launch a process, reset Git or select another command. Neither module
is exported from package root or included in the v7 Tier-A execution bundle.

## DC-L11 authority

DC-L11 adds authenticated readiness and publication-intent evidence without a
live publisher:

- one deterministic draft pull-request readiness proposal derived from the exact
  task, staged patch, passing Tier-A receipt and authenticated semantic approval;
- repository, base, proposed head branch, title and body generated by policy rather
  than supplied by a caller;
- a separately authenticated publisher actor who must differ from both developer
  and semantic reviewer;
- one nonce-bound publisher request with a fixed ordered plan for readiness check,
  candidate commit, branch, push and draft pull-request creation;
- a deterministic dry-run receipt whose repository-write, network-write, commit,
  branch, push, pull-request, ready-for-review, reviewer, merge, release and deploy
  result flags must all remain false; and
- crash-durable create-once publication of readiness, request, signed request and
  dry-run receipt artifacts.

Publisher-request v1 authentication uses publisher-held HMAC material and is not
represented as Ed25519 authorization. The plan may describe operations that a
future publisher would require, but DC-L11 contains no Git runner, HTTP/GitHub
client, credential adapter or mutation entrypoint. Readiness and dry-run modules
remain outside package root and the v7 Tier-A execution bundle.

## Physical evidence operator flow

The physical harness writes one canonical unsigned report matching
`schemas/windows-isolation-physical-report-v1.schema.json`. Signing and
verification are separate operator actions. The key file must remain outside the
developer workspace.

```bash
PYTHONPATH=devcontrol/src python -m kaliv_dev_control sign-physical-report \
  /operator/evidence/i0b-unsigned.json \
  /operator/evidence/i0b-signed.json \
  --key-file /operator/keys/isolation.key \
  --key-id operator-key-2026

PYTHONPATH=devcontrol/src python -m kaliv_dev_control verify-physical-report \
  /operator/evidence/attestation.json \
  --evidence-root /operator/evidence \
  --key-file /operator/keys/isolation.key \
  --key-id operator-key-2026
```

## Deliberately absent

DC-L01–DC-L11 provide no remote Git transport, Git credential mechanism,
HTTP/GitHub write adapter, live commit or branch mutation, push, pull-request
creation or update, ready-for-review mutation, reviewer request, one-time
publisher authorization, replay/recovery authority, local candidate
materialization, merge, release, deployment or activation authority. The trusted
Git runtime remains local-only, L11 is evidence and dry-run intent only, and the
default command catalog remains empty.

## Validation

```bash
PYTHONPATH=devcontrol/src python -m unittest discover -s devcontrol/tests -p 'test_*.py' -v
PYTHONPATH=devcontrol/src python -m kaliv_dev_control validate-task task.json
python3 tests/workflow_test_coverage.py
cd backend && go test ./cmd/modelrig-version-check
```

CI keeps the closure-bound executor and Git-aware receipt on a real Windows
kernel. DC-L10's asymmetric and semantic-review gates and DC-L11's readiness and
dry-run gate remain portable and offline. Exact-path, provenance, mutation,
validation and review evidence for this slice lives under
`docs/devcontrol/dc-l11/`.


## DC-L12 — one-time authorization and authenticated recovery

DC-L12 adds verification-only Ed25519 authorization for one exact signed publisher request, crash-durable one-time nonce consumption, dual-role authenticated replay recovery, a physically primary recovery ledger and deterministic missing-v3-receipt finalization.

Every authorization verification also reads an injected external monotonic keyring-state provider. Generation rollback, same-generation drift, a signature below the external minimum epoch and external key revocation all fail closed. No local file is accepted as the monotonic anchor.

The landed boundary intentionally excludes the rejected dynamic v1/HMAC compatibility authority, private keys, signers, credentials, Git/HTTP/GitHub adapters, subprocess publishers, remote writes and DC-L13 local candidate materialization. Package-root, Tier-A facade and execution-bundle exports remain unchanged.

## DC-L13 local-only candidate materialization

The landed DC-L13 boundary consumes one exact verified DC-L12 preflight chain
and may create only a deterministic candidate commit plus proposed branch inside
a new isolated local bare repository. Every Git command is executed through a
complete staged `TrustedGitRuntime`, and source, tree, commit, ref and receipt
bytes are re-verified before evidence is accepted.

The boundary configures no remote and provides no network fetch, push,
credential helper, signer, GitHub mutation, reviewer request, ready conversion,
merge, release, deployment or activation authority. The historical dynamic
legacy proxy and `_compatibility_v1` package are not distributed; the modern
facade uses a static internal validation/evidence support package only.

## DC-L14 final authority closure and packaging

DC-L14 closes the reviewable Tier-A authority inventory and package boundary. The
50-file authority bundle is generated and cryptographically locked, the historical
execution core is documented as an import-only identity facade, and wheel/sdist
artifacts are built through an exact local toolchain with deterministic metadata.

The supported artifacts physically exclude `kaliv_dev_control._compatibility_v1`.
They retain the static `_local_candidate_materialization_legacy` evidence-support
package, but add no live publisher, remote Git, GitHub mutation, credential,
private-key, merge, release, deployment or activation adapter.
