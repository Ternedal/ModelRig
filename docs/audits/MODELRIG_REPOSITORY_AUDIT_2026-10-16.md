# ModelRig repository audit — 2026-10-16

> Scope: static repository inventory and targeted file review on default branch `main`. This is **not** a comprehensive line-by-line audit, live runtime proof, or CI execution. Findings are evidence-qualified; proposed controls require owner validation. No runtime, release or signing settings are changed by this PR.

## Baseline and methodology

- Public repository `Ternedal/ModelRig`; default branch `main`.
- Complete non-truncated Git tree recorded at commit `49dbc2b46b9af2da2195e2e90e3c611145a8df3b` (tree SHA `0c633ae733794753e6bdfd7311f10df1ad231d22`): **3,095 blobs**.
- Selected subtree file totals: `tests/` 657, `worker/` 309, `backend/` 107, `android/` 394, `desktop/` 175, `devcontrol/` 494, `docs/` 344, `scripts/` 215, `vr/` 84, `.github/` 41. Counts include support files, not necessarily executable tests.
- Reviewed `README.md`, `SECURITY.md`, `.github/workflows/ci.yml`, `.gitignore`, `backend/go.mod`, public file inventory, and current open PR descriptions. No local rig or test hardware accessed.

## Findings and recommended actions

### P0 — Public Android application signing credentials (confirmed)

**Evidence:** Tracked `android/signing/modelrig.keystore` and `android/signing/keystore.properties`; the latter contains plaintext store/key passwords. `SECURITY.md` explicitly acknowledges a committed Android signing key. **Do not print the passwords or embed them in audit logs.** The keystore is potentially accessible to third parties because the repo is public.

**Impact:** A signing identity should not be considered confidential if both key material and unlock credentials are distributed. APK update trust relies on this identity. This is not proof that a malicious build has been distributed.

**Actions:**
1. Treat the signing identity as compromised; inventory deployment channels and update constraints **before** changing anything.
2. Choose a controlled Android signing-identity migration or new application-ID/reinstallation strategy consistent with Android update-signature rules and device data retention. Existing-app in-place update may not be available without a supported key-rotation path.
3. Move future key material/passwords outside Git into protected release secrets; ensure release workflows avoid exposing either in artifacts/logs. Add automated checks to fail on tracked keystores and credentials.
4. Evaluate history removal only as defense in depth; history rewrite cannot unexpose a previously published key.
5. Require explicit owner sign-off before executing migration; do **not** delete current files or rotate signing in a docs-only PR.

### P1 — Voice cancellation, context and device acceptance split across candidate PRs

**Evidence:** Open PR #2200 (OkHttp cancellation), #2201 (combined candidate), #2202 (2.0.15 release), #2203 (isolated Android voice pilot), #2205 (voice chat history); PR descriptions distinguish unit/CI evidence from still-pending physical end-to-end tests. Check present PR states before planning any merge.

**Actions:** Establish a single dependency/acceptance matrix mapping candidate SHA to Android → Go backend → Python worker → ASR → LLM → TTS → playback; test stop during capture/stream/playback, barge-in, repeat turn, audio cleanup, conversation persistence, 20-turn history limits, reconnect/restart, cloud opt-in, security failures and release rollback. Only mark hardware acceptance PASS using dated reproducible physical evidence.

### P1 — Inventory-pinned source changes create governance dependencies

**Evidence:** PR #2204 documents an authenticated capabilities-proxy change blocked by a selected-source-drift gate and requiring reviewed inventory transition. Do not work around the exact-head checks.

**Actions:** Document a single explicit source-inventory transition procedure with owner, affected pinned source, threat change, expected candidate SHA, independent approval, CI proof and rollback; keep feature PR separate until accepted.

### P1 — Release verification should be summarized in one machine-readable manifest

**Evidence:** README defines cross-repository exact SHA + physical validation + release manifest; CI workflow checks out exact PR SHA, SHA-pins actions, shares `_tests.yml` and performs separate browser fixture tests.

**Actions:** Produce a *read-only* release readiness aggregate consuming, never overwriting, exact-head evidence for ModelRig/BodyRig/VisionRig/VoiceRig; record `PASS/FAIL/BLOCKED/NOT_RUN` distinctly, candidate SHA, timestamp, provenance link, mandatory physical operator sign-off and reason blocking release. Keep all protective gates unchanged.

### P2 — CI and documentation maintainability

**Evidence:** 41 `.github/` files, 344 `docs/` files, numerous root-level handoffs/readiness notes and 657 test-directory files. File count alone does not establish duplication or poor quality.

**Actions:** Inventory current vs historical runbooks; identify canonical documents and move historical references to an index without deleting evidence. Map workflows to ownership, triggers, gates, outputs and expected duration; cache immutable tooling when safe, avoid duplicate heavyweight jobs only after proving coverage equivalence. Measure before optimization.

### P2 — Runtime performance and resources: benchmarking required, no unsupported claims

**Architecture observed:** local-first Go backend + Python worker + Ollama, desktop/Android/VR clients, staged voice/RAG/tool boundaries.

**Actions:** Establish p50/p95/p99 latency per ASR, retrieval, prefill, generation, TTS and playback, measured VRAM/RAM idle and under load, cold/warm start, concurrent cancellation and queue depth on the physical rig. Introduce trace IDs propagated through Go/Python/clients with payload/secret redaction. Tune concurrency, streaming and model residency against *measured* baselines, never at cost of isolation or ToolGate authorization.

### P2 — Dependency and supply-chain hardening

**Evidence:** SHA-pinned GitHub Actions are visible in `ci.yml`; Dependabot/CodeQL are described in `SECURITY.md`. `backend/go.mod` declares Go 1.23; dependency lifecycle and supported-version status merit explicit checks. No claim of vulnerable dependencies is made without advisory/SBOM validation.

**Actions:** Generate SBOM for Go, Python, Kotlin, Unity components; check dependency reachability, provenance, current security advisories and transitive licenses, including TTS redistribution. Set an upgrade calendar and make exception expiry visible. Validate artifact-signature/provenance guarantees independently from checksum validation.

## Prioritized delivery plan

| Priority | Workstream | Proposed completion evidence |
| --- | --- | --- |
| P0 | Signing credential exposure and safe migration decision | Threat assessment, target update path, tested rollback and owner approval |
| P1 | Android voice E2E acceptance | Exact SHA, CI + real-device matrix, verified cancellation cleanup |
| P1 | Governed source-inventory transition | Reviewed inventory diff and unmodified exact-head gate pass |
| P1 | Aggregated cross-repo release status | Provenance-bound PASS/FAIL/BLOCKED/NOT_RUN dashboard |
| P2 | Observability and real-hardware profiling | Redacted trace and reproducible p50/p95 + VRAM benchmarks |
| P2 | Workflow/doc consolidation | Workflow coverage map and canonical runbook index |
| P2 | Software supply chain | Per-ecosystem SBOM and vulnerability/license policy |

## Explicit non-goals and cautions

- No branch protection, exact-head checks, runtime flags, ports, deployed services or release artifacts are changed.
- No security key rotation is performed automatically; doing so could break updates to already-installed Kaliv apps.
- Repository file counts are not quality scores; absence of runtime test execution is explicitly **NOT_RUN**.
- CI status, PR state and actual deployed versions must be rechecked at execution time.
- Merge only after conscious review; this PR contains documentation, not production fixes.
