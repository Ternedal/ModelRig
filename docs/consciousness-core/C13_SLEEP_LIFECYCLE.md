# Consciousness Core C13-A — persisted sleep boundary

C13-A adds a default-off persistence and lifecycle seam around C12.

It deliberately does not wire the production entrypoint yet. The goal of this
slice is to prove the hard parts before runtime composition:

- feature flag off means no binding lookup, clock sampling or file access;
- no authoritative Self/Person binding means no read or write;
- one bounded JSON envelope under the existing Kaliv data root;
- SHA-256 binding to the exact SleepRecord payload;
- atomic temp-file + fsync + replace writes;
- startup may emit a C12 WakeReceipt only after identity verification;
- shutdown may persist a SleepRecord only while the process is still alive;
- no scheduler, Agent 3, Memory 4 or background cognition authority.

The lifespan wrapper preserves the original authority owner through __wrapped__
and closes the sleep boundary before the inner production lifecycle tears down.

A later C13-B may compose this wrapper into worker/app/entrypoint.py only after an
authoritative runtime SelfState-binding provider and trusted C11 clock provider
exist. C13-A refuses to guess either.

production_activation=false.
