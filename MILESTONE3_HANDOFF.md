# Milestone 3 offline candidate handoff

**Status:** dormant packaging helper. It builds a local transport package for the
single Milestone 3 physical candidate. It does not run a physical pilot, merge,
push, tag, publish, release, upload or activate production.

## Build the package

From the exact clean handoff-builder checkout on Windows:

```text
BUILD_MILESTONE3_HANDOFF.cmd
```

The builder branch is:

```text
agent/milestone3-candidate-handoff-v1
```

That branch is review-only. The artifacts are **not** built from its HEAD. The
builder resolves the authoritative candidate ref:

```text
agent/milestone3-physical-candidate-v1
```

It then creates a temporary detached Git worktree at that candidate's exact SHA,
runs both builds inside that worktree, and deletes the worktree afterward. The
manifest records candidate SHA/tree separately from the builder SHA.

The builder requires:

- version `1.58.146` on the authoritative candidate;
- a clean handoff-builder working tree;
- the builder branch to descend from the candidate;
- every helper-branch change to remain inside the explicit handoff-file allowlist;
- Git, Python 3, Java 21 and the Android SDK already available;
- enough local disk space for the temporary worktree, Git bundle, APK, desktop
  uber-jar and ZIP.

It runs the existing project builds in the detached candidate worktree:

- Android: `:app:assembleDebug`;
- desktop: `:composeApp:packageUberJarForCurrentOS`.

## Output

The `handoff/` directory receives both an unpacked kit and a ZIP named from the
version and first 12 characters of the **candidate** commit SHA.

Each kit contains:

- a verified Git bundle containing the authoritative candidate branch;
- the exact debug APK built from the candidate worktree;
- the exact Windows Compose uber-jar built from the same candidate worktree;
- `candidate-manifest.json` with candidate branch, commit, tree SHA, builder
  identity, SHA-256 and byte length for every artifact;
- `SHA256SUMS.txt`;
- `START_HERE.cmd`;
- a short offline README.

The manifest always records:

```json
{
  "physical_evidence_collected": false,
  "published": false,
  "production_activation": false
}
```

## Use on the rig

1. Copy the complete kit folder or ZIP to the Windows rig.
2. Extract the ZIP without modifying its files.
3. Optionally verify `SHA256SUMS.txt` before use.
4. Double-click `START_HERE.cmd`.

The bootstrap:

- verifies the Git bundle;
- refuses to overwrite an existing destination;
- initializes a fresh local repository;
- fetches only the authoritative candidate branch from the local bundle;
- checks that `HEAD` equals the SHA embedded at package-build time;
- checks that the new checkout is clean;
- starts `START_MILESTONE3_PHYSICAL.cmd` from that checkout.

The physical launcher still requires the paired Android device and every real
operator observation. The handoff package cannot make T-020, T-022 or T-023 green.

## Safety boundary

The handoff builder has no GitHub API client, network transport, publish command,
release command or merge implementation. Existing output names are not silently
overwritten; archive or remove an old kit deliberately before rebuilding.
