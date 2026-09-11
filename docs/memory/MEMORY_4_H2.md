# Memory 4.0 H2 — no-redirect loopback worker egress

Memory 4 worker HTTP calls carry private per-turn material and therefore treat the
configured loopback worker as the complete egress boundary, not merely the first
hop.

`production_activation=false`

## Boundary

Both backend worker calls use the same internal Memory 4 HTTP client:

- R05 `POST /experimental/memory4/context-for-turn`;
- W04-B `POST /experimental/memory4/commit-completed-turn`.

The client preserves the existing request timeout but sets `CheckRedirect` to
`http.ErrUseLastResponse`. A 3xx response is therefore returned to the caller and
handled as a normal worker refusal/failure. The request is never replayed to the
redirect target.

This matters because Go's default `http.Client` follows redirects. In particular,
a 307/308 redirect can resend a POST body unchanged. For Memory 4 that body can
contain either the current user's memory query or the completed user/assistant
turn plus server-created provenance.

## Failure semantics

R05 remains fail-closed: if the loopback context worker responds with a redirect,
context retrieval fails and the model call is not made.

W04-B remains stream-preserving and non-fatal after a successful chat: if the
post-turn worker responds with a redirect, the already-delivered chat response is
unchanged and the memory write is discarded.

No redirect target is conditionally accepted, even when it is itself loopback.
Keeping the policy as "no redirects" avoids a second URL-authority decision after
private request material has already been constructed.

## Qualification

Focused Go regressions use `307 Temporary Redirect`, which would preserve and
resend the POST body under Go's default redirect behavior. They prove that:

- the R05 redirect target receives zero requests and Ollama receives zero requests;
- the W04-B redirect target receives zero requests while the successful chat body
  remains byte-for-byte unchanged;
- the original loopback worker is contacted exactly once in each case.

H2 changes no worker URL allowlist, memory storage semantics, cloud-memory path,
Agent 3 authority, scheduler behavior, or production activation.
