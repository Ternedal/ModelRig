# Slice 10L — local candidate commit and proposed-branch materialization

Slice 10L is the first downstream boundary that creates real Git objects. It
consumes one verified Slice 10K preflight receipt and materializes the exact
authorized candidate commit plus proposed branch in a new isolated **local bare
repository**.

It still has no remote, GitHub credential, network write, push, pull-request
mutation, reviewer request, ready-for-review, merge, release, settings or
deployment capability.

## Purpose

Slices 10I–10K establish:

- an approved exact patch;
- deterministic draft-PR presentation;
- authenticated publisher intent;
- an independently signed one-time authorization lease;
- durable nonce consumption; and
- a no-write preflight receipt.

Slice 10L converts only the locally materializable portion of that authority into
Git objects:

1. import the exact authorized parent commit from one trusted local repository;
2. apply the exact authenticated binary patch to an isolated Git index;
3. create and verify the candidate tree;
4. create a deterministic candidate commit;
5. create the exact proposed local branch ref; and
6. publish one canonical transaction receipt beside the bare repository.

The resulting repository is an offline candidate artifact, not a published branch.

## Authority chain

The receipt embeds the complete Slice 10K preflight receipt. Verification therefore
rechecks the complete chain:

```text
Slice 10G passing Tier-A command receipt
  -> Slice 10H authenticated semantic approval
  -> Slice 10I authenticated draft-PR readiness
  -> Slice 10J signed publisher request
  -> Slice 10K signed one-time authorization lease
  -> Slice 10K consumed replay nonce and preflight receipt
  -> Slice 10L local candidate transaction
```

Materialization re-verifies the authorization lease at the explicit
`materialized_at_utc` timestamp. An expired lease, another task, an untrusted
publisher or issuer, semantic-review tampering or current Tier-A authority drift
fails before local Git objects are published.

## Trusted Git executable

`TrustedLocalGit` requires:

- an absolute path;
- a regular, non-empty, link-free file;
- a bounded executable size; and
- an exact operator-supplied SHA-256 of the complete executable bytes.

The executable is rehashed before and after every Git invocation. Slice 10L does
not discover Git through `PATH` internally and does not accept caller-selected
commands or arguments.

The Git subprocess environment is reduced and isolated:

- separate empty `HOME` and `XDG_CONFIG_HOME`;
- system Git configuration disabled;
- explicit empty global configuration;
- empty template directory;
- empty hooks directory;
- terminal prompting disabled;
- credential-manager interaction disabled;
- replacement objects disabled;
- automatic maintenance and garbage collection disabled;
- signing disabled;
- color and quoted-path output disabled;
- all protocols denied except the local `file` protocol; and
- `shell=False` with bounded output and timeout.

The small positive-list environment retains only operating-system values required
to start Git plus fixed internal variables. No token, authorization header,
credential or remote URL is accepted by the public materialization API.

## Trusted local source repository

The source must be one absolute link-free repository containing the exact
authorized parent commit. It may be:

- a standalone worktree with a real `.git` directory; or
- a standalone bare repository.

Slice 10L rejects:

- linked worktrees or `.git` indirection files;
- `commondir` storage;
- object alternates;
- shallow history;
- non-SHA-1 object formats;
- missing or replaced base commits;
- linked object storage; and
- source repositories whose exact top-level/Git directory does not match the
  supplied path.

Before materialization, the module records:

- canonical refs;
- `HEAD` and symbolic `HEAD`;
- worktree status when applicable;
- the raw base commit object;
- the raw base tree object; and
- SHA-256 and byte counts for all bounded evidence.

The same state and objects are re-read after candidate creation. Any source mutation
fails closed. The source repository is never configured as a remote and receives no
ref, index, object or configuration write from Slice 10L.

The source path is represented in the receipt only by its SHA-256, avoiding a
machine-specific absolute path in canonical evidence.

## Isolated transaction

The materialization root must be an existing absolute link-free directory. The
transaction ID is derived deterministically from the exact Slice 10K preflight
receipt SHA-256:

```text
candidate-<32 lowercase hexadecimal characters>
```

A transaction path may not already exist. Work starts in a fresh temporary sibling
directory and is published with one directory rename only after all verification
passes.

The published transaction layout is exact:

```text
candidate-<id>/
  repository.git/
  receipt.json
  isolated-home/
  isolated-xdg/
  disabled-hooks/
  empty-template/
  empty-global-config
```

The four isolation directories and global-config file must remain empty. An extra
file or directory causes later verification to fail.

## Exact local base import

Slice 10L creates a new empty bare SHA-1 repository with an empty template. It then
imports only the exact authorized base commit using a local `file://` fetch.

The destination has:

- no configured remote;
- no fetch refspec;
- no remote-tracking branch;
- no tag import;
- no submodule recursion; and
- no network-capable protocol.

The imported base commit and tree are independently compared with the source's raw
object evidence.

## Exact patch and tree

The authenticated patch bytes are taken from the embedded Slice 10H semantic-review
request. Their length and SHA-256 must still equal the Slice 10J and Slice 10K
bindings.

A separate temporary `GIT_INDEX_FILE` is initialized from the exact base tree. Git
applies the exact binary/full-index patch to that index only. The resulting tree is
written to the isolated bare repository.

Before commit creation, Slice 10L diffs the exact parent against the new tree using
the same deterministic options as the upstream patch evidence. The resulting bytes
must be **identical** to the authenticated patch, not merely semantically
equivalent. A no-op tree or reformatted patch fails closed.

The raw tree object is then read, SHA-256-bound and independently checked against
its Git SHA-1 object ID.

## Deterministic commit

The commit metadata is not caller-selected.

- Parent: exact authorized base SHA.
- Tree: exact verified candidate tree.
- Message: the fixed Slice 10J publisher-plan message algorithm.
- Author actor: exact authenticated publisher actor.
- Committer actor: the same publisher actor.
- Author/committer name: deterministic actor-derived value.
- Author/committer email: deterministic non-deliverable actor-derived address.
- Author/committer timestamp: exact Slice 10K lease issue time converted to Unix
  epoch with `+0000` offset.
- Signing: disabled.

After `git commit-tree`, Slice 10L constructs the expected raw commit payload itself
and requires byte-for-byte equality with `git cat-file commit`. It independently
verifies:

- raw commit byte count;
- raw commit SHA-256;
- Git SHA-1 object ID;
- exact parent;
- exact tree;
- exact author and committer metadata; and
- exact message and trailing newline.

Repeating the same authorized transaction in a different empty materialization root
therefore produces the same tree SHA, commit SHA and canonical receipt.

## Proposed local branch

The only created ref is:

```text
refs/heads/<exact deterministic Slice 10I/10J head branch>
```

It is created from the all-zero expected old object ID, preventing accidental
replacement. Symbolic `HEAD` is set to the same branch. Verification requires:

- exactly one ref in the repository;
- that exact branch name;
- the exact candidate commit as target;
- symbolic `HEAD` pointing at that branch;
- no remote; and
- the exact parent/tree/commit/patch evidence still present.

The branch exists only inside the isolated local bare repository.

## Canonical receipt

`kaliv-development-local-candidate-materialization-receipt/v1` binds:

- the complete Slice 10K preflight receipt;
- preflight, lease, replay, request, readiness, task and nonce hashes;
- fixed materialization-policy hash;
- explicit materialization timestamp;
- deterministic transaction and relative paths;
- exact Git executable identity and version;
- exact source-state and base-object evidence;
- exact patch, parent, tree and commit evidence;
- deterministic author/committer metadata;
- exact proposed branch ref and target; and
- fixed local-only/no-write authority flags.

The receipt requires:

- `bare_repository: true`;
- `isolated_index: true`;
- `local_source_only: true`;
- `remote_configured: false`;
- `network_write_performed: false`;
- `remote_push_performed: false`;
- no pull-request, ready-for-review, reviewer-request, merge, release or deployment
  result; and
- `merge_authority: human`.

The transaction's `receipt.json` uses exact canonical UTF-8 bytes without a trailing
newline. Separate bounded create-once load/write helpers are also provided for
copying or exchanging the receipt outside the transaction.

## Verification

`verify_local_candidate_materialization` and
`LocalCandidateMaterializationGate` recheck:

- the complete upstream authority chain;
- lease validity at materialization time;
- exact canonical on-disk receipt;
- exact transaction layout;
- trusted Git executable bytes and version;
- unchanged source state and raw base objects;
- bare SHA-1 destination repository;
- exact sole ref and symbolic `HEAD`;
- absence of remotes;
- exact parent, tree and raw commit payload; and
- exact authenticated patch bytes reproduced by the materialized commit.

Adding a remote, changing a ref, altering an object, changing the receipt, adding an
unexpected transaction file or mutating the source makes the gate fail.

## Deliberately absent authority

Slice 10L still cannot:

- discover or clone a remote repository;
- configure a Git remote;
- load or use a GitHub credential;
- perform any network read or write;
- push the local branch;
- create or update a pull request;
- request reviewers;
- mark a pull request ready for review;
- merge;
- create tags or releases;
- change repository settings, workflows, secrets or variables;
- deploy; or
- activate unattended self-development.

The trusted Git executable, local source repository and materialization root remain
external operating boundaries. Slice 10L does not claim protection against a
separate administrator or kernel component.

The module remains outside Tier-A authority bundle v6. The physical I0b campaign is
therefore unchanged.

## Schema and tests

Schema:

- `schemas/development-local-candidate-materialization-receipt-v1.schema.json`

Adversarial tests in `tests/test_slice10l_local_candidate_materialization.py`
construct the complete Slice 10G–10K authority chain and use a real local Git
repository. They prove:

- exact patch reproduction;
- deterministic tree, commit and receipt across independent roots;
- exact raw commit metadata and object hashes;
- sole local branch and no remote;
- source-state immutability;
- expiry, wrong task and authority-drift rejection;
- wrong Git executable hash rejection;
- missing-base source rejection;
- create-once transaction behavior;
- receipt, branch-target, remote and layout tamper rejection;
- canonical file exchange and schema parity; and
- absence of a live remote/GitHub writer surface.
