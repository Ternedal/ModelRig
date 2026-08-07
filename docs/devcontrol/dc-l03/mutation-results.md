# DC-L03 mutation results

Status: **runtime mutations green on `fe415f0562f2e3d57d600c80e33673b92b58bfde`; resulting evidence head pending**

Load-bearing mutations and expected failures:

1. Replace returned bytes while retaining a syntactically valid Git blob SHA.
   Expected: decoded Git-blob identity verification fails.
2. Remove protected-path or `.git` rejection.
   Expected: scope rejection fails before any network call.
3. Permit redirects, environment proxies or a non-`api.github.com` authority.
   Expected: fixed-authority transport regressions fail.
4. Serialize the bearer token into a receipt.
   Expected: token non-persistence assertion fails.
5. Permit unreviewed process environment authority.
   Expected: the positive-list regressions reject loader, Git, Python,
   `GOTOOLCHAIN`, hostile PATH, locale and timezone values.
6. Accept an omitted PATH without injecting `/usr/bin:/bin`.
   Expected: fixed-PATH insertion regression fails.
7. Execute a pathname after verification rather than the sealed object.
   Expected: pathname-replacement regression fails.
8. Reuse a retired descriptor for an old `/proc/<pid>/fd/<n>` invocation.
   Expected: descriptor-retirement regression fails.
9. Follow a link, accept a hash mismatch, or block on a FIFO.
   Expected: link/hash/FIFO regressions fail.
10. Mix command resolution and hashing from different catalog objects.
    Expected: catalog-snapshot regression fails.
11. Mutate catalog specs, toolchain bindings, task or verifier proof after the
    private snapshot is made.
    Expected: deep-copy and private-snapshot regressions fail.
12. Replace the executable verifier during isolation verification.
    Expected: verifier-snapshot regression fails.
13. Reuse or retarget a registry for another task.
    Expected: exact-task registry regression fails.
14. Mutate the caller-owned task during execution.
    Expected: sandbox, budgets, verification and receipt remain bound to the one
    private reconstructed task snapshot.
15. Replace or mutate the sandbox bootstrap interpreter through
    `sys.executable` or registry state.
    Expected: the immutable attested bootstrap regression fails.
16. Accept malformed receipt fields, repository syntax or `200.0` status.
    Expected: strict runtime/schema reload regressions fail.
17. Accept a moving base ref before transport.
    Expected: exact-SHA pre-network regression fails.
18. Retarget adapter task, repository, token, timeout or transport.
    Expected: sealed-adapter regression fails.
19. Materialize without independently supplied isolation evidence.
    Expected: fail-closed default regression fails.
20. Let environment CA settings choose GitHub trust roots.
    Expected: explicit TLS trust regression fails.
21. Slow-drip body data while staying below inactivity timeouts.
    Expected: total monotonic deadline supervision fails.
22. Block inside chunk framing or status/header parsing.
    Expected: the owned socket/response/connection is cancelled at the absolute
    deadline.
23. Block DNS or connection setup beyond the caller deadline.
    Expected: no authenticated request is sent after delayed completion.
24. Start repeated requests while one uninterruptible setup worker remains.
    Expected: later requests fail closed without accumulating workers.
25. Close the socket between the final cancellation check and request output.
    Expected: automatic reconnect remains disabled and no auth send occurs.
26. Hide the underlying deadline-capable transport socket.
    Expected: request handling fails closed before evidence is accepted.
27. Remove socket shutdown, response close or connection close at expiry.
    Expected: cancellation assertions fail.
28. Pin only the top-level Go driver while allowing `go test` or `go vet` to
    execute mutable helpers from `GOROOT/pkg/tool`.
    Expected: construction fails because every `tool_id="go"` is rejected;
    the default catalog contains no Go command IDs and tasks granting the old
    backend commands cannot materialize them.

Exact runtime-candidate workflow evidence:

- `ci` `31156740333` — success;
- `codeql` `31156738980` — success;
- `agent3-diagnostics` `31156739176` — success;
- `agent3-full-diagnostics` `31156738930` — success.

The resulting documentation head still requires its own workflows and fresh
independent review before any final verdict is claimed.