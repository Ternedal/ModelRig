# Kaliv next-generation capability architecture (proposal v0.1)

Status: PROPOSAL ONLY. No runtime flags, production endpoints or release gates changed.
Owner: ModelRig cognitive/control plane; Kaliv clients are presentation; Nexus is a future separate integration plane.

## Non-negotiable boundaries
- Preserve existing ModelRig V1/V2 compatibility and current release behavior.
- Consciousness Core and vision admission remain default-off; proposal does not imply consciousness.
- No unapproved side effects, self-modification in production, or unrestricted agent permissions.
- No API keys or private memory in public repository logs; local-first storage, explicit cloud opt-in.
- External media assets go to configured external media root, with quota and safe-path checks.
- GitHub changes go to branches/PRs with required checks; never bypass main protection.

## 1. Continuum: shared task and context authority
One canonical task identity across Android, desktop, VR and Hub. Durable event log and resumable task checkpoints; device sessions attach to a task, not duplicate it. Keep model-independent memory authority in ModelRig. Separate consented autobiographical memory from transient task context.

Suggested envelopes:
```json
{"schema":"kaliv.task.v1","task_id":"uuid","conversation_id":"uuid","actor_id":"local-user","origin_device":"android","status":"pending_approval","created_at":"RFC3339","capabilities":["github.read"],"correlation_id":"uuid"}
```
States: queued -> planning -> awaiting_approval -> executing -> verifying -> completed; failure -> retryable_failed or terminal_failed; cancellation -> cancelled. Enforce idempotency keys and replay-safe effects.

## 2. Swarm: orchestrated bounded agents
A planner produces an inspectable DAG of subtasks. A policy engine evaluates tool scopes, resource budgets, data sensitivity and side effects. Workers run in isolated sandboxes; a verifier checks evidence. No agent can grant itself permissions. The Nexus adapter registry is untrusted input, not an execution authority.

Minimum interfaces:
- CapabilityDescriptor: name, version, input/output JSON schema, permissions, sensitivity, idempotency, estimated cost.
- TaskPlan: nodes, dependencies, acceptance criteria, rollback/compensation and approval checkpoints.
- ExecutionReceipt: exact tool/version, timestamps, redacted inputs, result digest, trace_id, approval reference.
- AgentResult: artifact references, evidence, limitations, confidence and tests.

## 3. Reality Engine: grounded world and scene graph
VisionRig owns perceptual observations and epistemic uncertainty; BodyRig owns avatar identity/motion; SkyPlayer owns XR/media presentation; ModelRig reasons over derived world evidence. Do not conflate generated scene content with real observations.
WorldEntity: entity_id, coordinate_frame, timestamp, source, evidence_ref, confidence, ttl, privacy_class. Simulated worlds have a distinct namespace and no automatic access to real-home actuators.

## 4. Nexus integration plane (future repository)
Adapters for external APIs, GitHub, Home Assistant, search, pricing and media. Registry metadata requires provenance, licensing, auth model, quotas, data handling, failure modes and health checks. All requests pass ModelRig policy and scoped user authorization. No blind execution of third-party API catalog entries.

## First end-to-end vertical slice
User: "Investigate my NAS health and prepare a remediation plan; don't change anything."
1. Android creates task and gets task_id.
2. Planner requests read-only SMART and backup-status capabilities.
3. Policy approves read-only scopes, or requests credentials/consent.
4. Nexus adapters collect observations with timestamps and provenance.
5. Verifier produces a report distinguishing measured facts from hypotheses.
6. Continuum persists progress; Hub and VR can render same task state.
7. Any proposed write operation becomes a separate approval-gated task.

Acceptance: restart-resume without duplicate effects; disconnected client reconnect; revoked token fails closed; no writes during read-only flow; deterministic test fixtures; redacted logs; per-tool timeout; audit trail.

## Implementation order
P0: contracts, threat model, test fixtures and policy decisions.
P1: Continuum task store + events + read-only status API.
P2: Swarm planner/verifier with mock tools and hard execution budgets.
P3: Nexus adapter sandbox with one read-only NAS capability.
P4: multi-client task handoff and notifications.
P5: Reality Engine scene/evidence contracts; opt-in spatial demo.
P6: richer generative and autonomous experiences after physical qualification.

## Repository allocation
- ModelRig: cognitive state, task authority, policy and orchestration contracts.
- Future Kaliv Nexus: adapters and external capability registry.
- Kaliv clients: tasks, approval UI, progress, artifact viewer.
- BodyRig/VisionRig/VoiceRig: remain separate domain authorities.
- KalivHub: read-only task/status projection by default.

This is an architecture proposal, not a claim of implemented features.
