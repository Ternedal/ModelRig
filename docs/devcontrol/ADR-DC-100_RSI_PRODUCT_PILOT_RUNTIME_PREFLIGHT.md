# ADR-DC-100 — Fresh post-production product-pilot runtime preflight

## Decision

ModelRig may produce one authenticated **fresh runtime-preflight receipt** only
from a live ADR-DC-099 task-registry receipt and a host-observer claim signed by
the already-established ADR-DC-023 runtime-preflight Ed25519 authority.

No new signer or keyring domain is introduced.

## Mandatory fresh checks

The signed claim binds the exact production lineage, host DevelopmentTask
registry, DevelopmentTask/fixed command, operator surface, workspace, feature
flag and product route. It carries independent evidence digests for, and must
positively reverify:

- product-integration selection;
- the host task registry;
- canonical workspace;
- feature-flag default-off behavior;
- local-only scope and manual operator invocation;
- kill switch, revoke state and restart recovery;
- network-write block and absence of credentials;
- no unattended cadence;
- no general shell or model-defined commands;
- exact source and exact toolchain binding.

The observation must be after the fresh ADR-DC-099 registry evaluation and may
be at most 60 seconds old when verified.

## Authority

A verified receipt may set only `runtime_preflight_satisfied=true`. It keeps
`product_pilot_start_ready=false`, start authorization/start state false, task
execution authority false, local/remote mutation authority false, every
Git/GitHub/release/deploy authority false, production-activation authority
false and nonce reuse false.

A later readiness-closure boundary must combine this fresh receipt with the
ADR-DC-096 requirements manifest and still prove the remaining one-shot start
authorization/replay-guard/start-receipt requirements.
