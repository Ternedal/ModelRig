# Memory 4.0 H2 — no-redirect loopback worker egress

Status: hardening slice for the landed R05 read path and W04-B post-turn write
path. `production_activation=false`.

## Boundary

Memory 4 backend calls carrying private memory material may target only the
already-validated loopback worker. A loopback URL check on the initial request is
not sufficient if the HTTP client follows redirects: an HTTP 30x could otherwise
cause Go to replay a POST body to the redirect destination.

H2 therefore uses a Memory 4-specific HTTP client whose `CheckRedirect` returns
`http.ErrUseLastResponse`. The original 30x response is returned to the existing
caller and no redirected request is issued.

This applies to both backend-to-worker calls:

- R05 `POST /experimental/memory4/context-for-turn`, which carries the current
  user's bounded memory query;
- W04-B `POST /experimental/memory4/commit-completed-turn`, which carries the
  bounded original user turn, assistant turn and server-created `source_ref`.

The generic proxy package is unchanged. H2 does not broaden worker targets or add
a second egress path.

## Failure semantics

A redirect from the loopback worker is treated exactly like another non-200 worker
response:

- R05 fails closed with `memory context unavailable` before any model call;
- W04-B treats the post-turn write as failed but leaves an already-successful chat
  status/body/stream unchanged.

Existing timeout, response-size bounds and strict receipt validation remain
unchanged for direct successful loopback responses.

## Qualification

Focused Go regressions use HTTP `307 Temporary Redirect`, because 307 preserves
the POST method and request body under normal redirect handling. They prove:

- the configured loopback worker receives exactly the original request;
- the redirect target receives zero requests and therefore zero private payload
  bytes;
- R05 does not call the model after a redirected context request;
- W04-B keeps the completed chat response successful when the post-turn worker
  attempts to redirect.

## Non-goals

H2 adds no cloud memory egress, storage/lifecycle change, Agent 3 activation,
scheduler authority, retry queue, tool authority or production activation.

`production_activation=false`
