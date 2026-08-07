# DC-L10 mutation results

**Status:** load-bearing mutations encoded; final exact-head execution pending.

## Required red states

| Mutation | Detecting contract |
|---|---|
| Alter one of the fifteen locked source blobs | source provenance and exact-path review |
| Replace the pinned Ed25519 implementation or omit it from either dependency surface | workflow coverage and import gates |
| Add `Ed25519PrivateKey`, a signer, private-key loader or signing call to runtime authority | asymmetric source boundary tests and CI gate |
| Accept an unknown, stale, revoked, future or identity-mismatched key/signature | asymmetric authority adversarial tests |
| Change payload bytes without invalidating detached evidence | payload-hash and signature tests |
| Construct semantic review from a mutable workspace or selectable command/runtime | Slice 10H API-surface tests |
| Approve with uncertain/failed criteria or findings | semantic-review model and approval-gate tests |
| Reuse the developer actor as reviewer | reviewer independence and key-binding tests |
| Alter patch, receipt, task, policy or execution-authority identity | semantic-review verification tests |
| Replace durable create-once publication with overwrite/temporary replacement | H10D/H10E tests |
| Export DC-L10 symbols from package root or Tier-A facade | explicit L10 CI boundary |
| Add DC-L10 files to the v7 execution bundle | explicit bundle-exclusion gate |
| Add L11+ readiness, publisher, materialization or remote mutation modules | future-module gates |
| Omit any of the 35 landed test modules from the exact inventory | workflow coverage contract |

## Observed integration state

The raw fifteen-file source import was opened before progressive changes. CodeQL,
Agent diagnostics, product-side Windows isolation, trusted-Git receipt, browser,
desktop and appliance gates remained green. The repository test loop failed only
because `tests/workflow_test_coverage.py` still required the exact 31-module
DC-L09 inventory while 35 modules were present. The correction advances that
exact inventory and adds dependency and authority-boundary assertions; it does
not weaken or bypass a product or DevControl test.

Further concrete red states found on the frozen candidate head will be appended
before approval. Green evidence is valid only when all four required workflows
finish successfully on one unchanged commit.
