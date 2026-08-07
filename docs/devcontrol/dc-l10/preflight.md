# DC-L10 preflight

**Slice:** Asymmetric authority and independent semantic review  
**Base:** `main @ adf8347f99612e8664c13b23ef268d387dec6d6c`  
**Locked source:** PR #338 @ `07dd596bd4fef6bdc8fecf0a327b28c1c66d9d3f`  
**Dependency:** merged DC-L09  
**Planned exact scope:** 28 paths

## Landed authority

DC-L10 lands verification-only Ed25519 public-key authority and an offline
semantic-review evidence boundary over one exact staged patch and one complete
passing Git-aware Tier-A receipt. Review requests and signed verdicts are
canonical, bounded and durably published with create-once semantics.

The asymmetric runtime accepts pinned public keys, issuer identities, validity
windows, monotonic keyring epochs, custody-policy identity and revocation state.
It contains no private-key type, signer, private-key loader, credential adapter,
transport or remote-write capability.

Semantic-review v1 remains a distinct compatibility artifact using reviewer-held
HMAC authentication outside the developer and execution workspace. DC-L10 does
not claim that this artifact has migrated to Ed25519.

## Preserved boundaries

- The v7 Tier-A execution bundle is unchanged and excludes both DC-L10 modules.
- Package root and `tier_a_execution.py` export no review or asymmetric symbols.
- Semantic review cannot inspect a mutable workspace, launch a process, choose a
  command, reset Git or alter the staged patch.
- The default command catalog remains empty.
- No new physical I0b evidence is required because process authority is unchanged.

## Hard exclusions

No draft readiness, publisher request, publisher authorization, replay/recovery,
local candidate materialization, private signing key, Git credential, remote Git,
GitHub write, reviewer request, ready-for-review mutation, merge, release,
deployment or activation authority may enter this slice.

## Required gates

- all fifteen locked source blobs match PR #338 exactly;
- the five progressive paths preserve DC-L09 and contain no L11+ implementation;
- all 35 landed DevControl test modules run in CI;
- Ed25519 verification, epoch rollback, revocation and tamper tests pass;
- semantic-review canonical binding, independence, approval and durable
  publication tests pass;
- package-root, Tier-A bundle and future-slice exclusions pass;
- all existing repository, Windows, Android, desktop, DPAPI and Browser Use gates
  pass on one exact head;
- exact path count, zero-behind relation and review state are recorded before merge.
