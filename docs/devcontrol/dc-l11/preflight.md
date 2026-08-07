# DC-L11 preflight

**Slice:** Draft readiness and publisher dry-run intent  
**Base:** `main @ 7c9bc3fefde1e3276e9f4fae452510c90658d114`  
**Locked source:** PR #338 @ `07dd596bd4fef6bdc8fecf0a327b28c1c66d9d3f`

## Authority added

DC-L11 may create canonical, authenticated evidence that one exact semantic-review-approved candidate is ready to be represented as a draft pull request. It may also create a separately authenticated publisher request and a deterministic dry-run receipt describing the fixed draft-only publication plan.

The publisher actor must differ from the developer and semantic reviewer. Task, patch, Tier-A receipt, semantic review, execution authority, repository, base, proposed head branch, title, body, nonce and publisher policy remain bound in canonical evidence.

## Authority not added

This slice contains no Git runner, HTTP client, GitHub client, credential adapter, repository mutation, commit creation, branch creation, push, pull-request creation or update, ready-for-review mutation, reviewer request, merge, release, deployment or activation entrypoint.

The dry-run plan may describe future write-requiring operations, but every execution and result flag remains false. Publisher-request v1 HMAC authentication is not one-time authorization and is not represented as Ed25519 authority.

## Integration rule

The fourteen assigned source blobs remain byte-exact. Four progressive files advance documentation, landed/future inventory, exact test coverage and CI boundary checks. Package root, CLI, product code, Tier-A authority and the v7 execution bundle remain unchanged.
