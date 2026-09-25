# C30-H — Bounded episode-closure evidence

Status: draft, stacked on C30-G, `production_activation=false`.

C30-H reduces one **closed** C30 experiential episode to a bounded,
reference-only evidence object at the exact moment C30-G applies a real episode
boundary.

It does not create durable autobiographical memory and it does not retain the
closed episode as a hidden history store.

## What is retained in the result

`EpisodeClosureEvidence` contains only bounded structural evidence:

- canonical closed episode ref;
- boundary signal ref;
- Self and Person Revision bindings;
- open/close reasons and temporal anchor ids;
- objective elapsed time and sequence bounds;
- total/evicted/retained moment accounting;
- retained moment-kind counts;
- up to 16 salient source refs;
- bounded participant refs and active-goal refs;
- maximum retained salience.

The evidence contains **no raw user text**, **no model chain-of-thought**, and no
durable Memory 4 contents.

## Boundary semantics

- `KEEP` emits no closure evidence.
- `CLOSE_ONLY` emits exactly one closure evidence object.
- `CLOSE_AND_ROTATE` emits exactly one closure evidence object for the closed
  predecessor, while the successor remains an empty active episode.
- Evidence must bind the same closed episode ref, boundary signal ref and
  boundary anchor id as the C30-G receipt.

## Memory authority

C30-H only marks non-empty closure evidence as
`REFERENCE_EVIDENCE_ONLY`. It does **not** create a C7
`ExperienceCandidate`, call Memory 4, or write durable memory.

An empty closed episode is explicitly marked `NO_MOMENTS` so segmentation
alone cannot masquerade as an experience worth remembering.

## No parallel episode history

The C30-G result may carry the bounded closure evidence to its immediate caller,
but the C19 session owner still retains only the active successor and latest
boundary receipt. The full closed episode is discarded.

## Authority boundary

C30-H adds no model call, SelfState-store write, Memory 4 write, scheduler,
timer, tool execution, goal activation, identity mutation, or BodyRig/VoiceRig
mutation.

## Qualification

Focused tests prove:

- active episodes cannot emit closure evidence;
- bounded structural reduction of closed episodes;
- raw text/chain-of-thought exclusion;
- deterministic salient-source truncation;
- explicit empty-episode disposition;
- `KEEP` produces no evidence;
- close/rotate evidence binds the exact C30-G receipt.

## Next slice

C30-I may plan an explicit, review-only bridge from non-empty closure evidence
into C7 experience-candidate evaluation without granting automatic Memory 4
persistence authority.
