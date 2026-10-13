# V1 release authority: independently verified provenance contract

Status: **design contract only — NO-GO**. This document does not change or override the frozen V1 software baseline. It describes the trust boundary that a future authoritative implementation MUST enforce. Related: #2111, #2025, #2109.

## Existing checks are not release authorization

`kaliv_system_release_gate.evaluate_manifest()` checks a structural envelope: ten gate names/statuses and canonical-looking reference strings. It does **not** fetch the evidence referenced by those strings, recompute artifact hashes, authenticate the producer or attest a physical/human run. Its `QUALIFIED` and `release_ready` fields MUST NOT be interpreted as production authorization. The local evidence preflight in this branch checks bytes against a locally supplied ledger, but the ledger and files share a trust domain. Even matching SHA-256 values cannot establish origin.

Until the independent authority described below exists and is operationally reviewed, every release decision MUST remain **NO-GO** and `production_activation=false`, regardless of structural `QUALIFIED`.

## Authoritative verifier: minimum requirements

1. **Out-of-band trust roots.** The verifier MUST obtain allowed producer identities, signing public keys, allowed workflows/validator revisions and pinned repository SHAs from a separately controlled, reviewed policy source. Neither the release manifest nor its local ledger may define or override those roots.
2. **Authenticated producer attestations.** Every gate MUST have a producer-specific, cryptographically verified attestation over the actual evidence digest, exact four-repository commit tuple, gate name, run ID, producer identity, validator revision, outcome and timestamp. Reject unsigned, invalidly signed, wrong-audience, revoked or unauthorized identities. A field such as `trusted: true` or a user-supplied public key is never sufficient.
3. **Independent artifact resolution.** Resolve immutable evidence from the attestation's authorized artifact store, rehash the downloaded bytes and compare to the attested digest. Reject mutable locations, missing artifacts, digest mismatch, oversized artifacts and ambiguous paths. Never trust a hash provided only by the candidate manifest.
4. **Replay qualified validators.** Re-evaluate gate-specific evidence with pinned, reviewed validators. Compare computed PASS against the attested producer outcome. Reject stale or wrong-run receipts, duplicate/replayed run IDs, inconsistent timestamps, and mismatched pinned SHAs.
5. **Human physical acceptance.** For gates requiring operator judgement, require a separate authenticated approval by an authorized reviewer, bound to the evidence digest and exact run/commit tuple. Approval must be auditable, time-bounded and invalid on evidence replacement; the producer cannot self-approve.
6. **Two-person release control.** Production release requires an explicit separately authorized release decision after all ten gates independently verify. The verifier's successful read-only evaluation alone MUST NOT toggle production, publish tags or deploy.
7. **Fail closed and auditable.** Unknown producers, absent policy, network failure, key/identity verification failure, partial verification, conflicting evidence, or inability to replay any validator yield BLOCKED. Log artifact digest, trusted identity, run ID, policy revision and rejection reason without secrets.

## Adversarial acceptance scenarios

- Ten synthetic PASS statuses with syntactically valid canonical refs: **BLOCKED**.
- Attacker rewrites evidence bytes and rewrites a matching local ledger hash: **BLOCKED**.
- Attacker supplies a new public key together with a matching signature: **BLOCKED**.
- Real signed evidence for a different commit, gate, workflow or audience: **BLOCKED**.
- Real evidence with an unsigned or mismatched human approval: **BLOCKED**.
- Correct bytes from an unauthorized producer or mutable artifact URL: **BLOCKED**.
- Previously accepted run replayed after revocation or expiration: **BLOCKED**.
- Missing attestation verification service or unavailable trust policy: **BLOCKED**.
- Ten independently replayed PASS gates with valid attestations and human approvals: eligible for **separate manual release approval**, never automatic activation.

## Rollout boundaries

- Keep current structural tests for compatibility, but label their success *structural only* in all operator-facing output.
- Implement the authoritative verifier as a separate fail-closed entrypoint, not a boolean switch in the existing structural evaluator.
- Add isolated, mocked negative tests first; integration acceptance needs actual signed producer artifacts and independently controlled policy.
- Do not merge into frozen `main` without a new approved software freeze and fresh exact-head qualification.
