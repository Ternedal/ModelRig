# T-033 protected memory leak-surface gate

**Status:** dormant promotion gate. It audits the protected reader/writer and the
current runtime boundary; it does not mount protected memory, expose a route,
rotate a key or activate Agent 3.

## Purpose

The protected store is useful only if private/secret plaintext stays inside an
explicit authorized read. Encryption-at-rest alone is not enough: status JSON,
metadata previews, receipts, exceptions, logs, SQLite backups, indexes or an
accidental planner/outcome mount could create a readable copy.

`worker/app/agent3/memory_protected_leak_gate.py` therefore evaluates canaries
without storing their plaintext in its report:

- every canary is represented only by SHA-256;
- supplied status/preview/receipt/error/log projections are scanned;
- the SQLite database, WAL, journal, SHM and supplied backups are scanned;
- indexes, triggers and views may not reference `value`, `source_ref` or their
  protected-envelope columns;
- protected reader/writer symbols must remain absent from current production
  mount, planner, memory API and outcome paths;
- all reports contain `production_activation=false`.

## Authorized opening is not a leak

The adversarial fixture proves `LOCAL_MANAGEMENT` can reopen private/secret
values and protected source references. Those authorized records are deliberately
not fed to the leak scanner. The scanner instead covers every projection that
must remain content-free:

- reader status;
- metadata-only records;
- planner memory receipts (hash/count/IDs only);
- exception and captured log text;
- simulated preview, embedding and outcome inventories;
- raw storage and backup bytes.

`LOCAL_CONTEXT` is also exercised: a private value may be opened locally while a
secret remains redacted and source provenance stays hidden. The current protected
store remains unmounted, so no protected value reaches planner preview or outcome
context.

## Windows proof

The dedicated `agent3-memory-protected-store-windows` workflow runs:

1. protected reader tests;
2. protected writer tests;
3. the adversarial leak/mutation suite;
4. a second leak fixture using real Windows DPAPI current-user protection.

The DPAPI fixture reopens the secret under the same Windows user, creates a real
SQLite backup and requires the leak report to remain green without plaintext in
report or database family.

## Mutation coverage

The suite turns each boundary red independently:

- a canary inserted into a preview/status projection;
- plaintext inserted into a backup artifact;
- an index added over `agent_memories.value`;
- a protected reader imported by a runtime-boundary file;
- duplicate/ambiguous canary inventory.

Findings contain surface, kind, location and canary digest only — never the
original value.

## Promotion boundary

A future protected-memory runtime integration must not simply remove the dormant
mount check. It needs a separate reviewed slice that:

- supplies explicit read/write authorization;
- defines which private values may enter local context;
- keeps secret values out of planner, preview, embeddings and outcome context;
- replaces the static no-mount assertion with endpoint- and prompt-level canary
  evidence;
- preserves backup/restore, wrong-scope and Windows DPAPI tests.

Until then, the existing plaintext `MemoryStore` runtime is unchanged and the
protected reader/writer remain evaluation-only.
