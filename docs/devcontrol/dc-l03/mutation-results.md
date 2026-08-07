# DC-L03 mutation results

Status: **focused mutations covered; exact-head repository CI pending**

Load-bearing mutations and expected failures:

1. Replace a returned Git blob SHA with another valid 40-hex value.
   Expected: blob-identity regression fails.
2. Remove protected-path or `.git` rejection.
   Expected: pre-network scope regression fails.
3. Permit redirects, proxies or a non-`api.github.com` authority.
   Expected: fixed-authority regressions fail.
4. Serialize the bearer token into a receipt.
   Expected: token non-persistence assertion fails.
5. Permit unreviewed process environment authority.
   Expected: the fixed-value positive-list regression rejects `GOROOT`,
   `PYTHONUSERBASE`, non-local `GOTOOLCHAIN` and an attacker-selected PATH.
6. Accept a catalog entry with omitted PATH without injecting the reviewed value.
   Expected: the default-PATH insertion regression fails.
7. Execute a pathname after verification instead of its sealed object.
   Expected: pathname-replacement regression fails.
8. Reuse a retired descriptor for an old `/proc/<pid>/fd/<n>` template.
   Expected: descriptor-retirement regression fails.
9. Follow a link, accept a hash mismatch, or wait on a FIFO.
   Expected: link/hash/FIFO regressions fail.
10. Mix catalog command resolution and hashing from different catalog objects.
    Expected: catalog-snapshot regression fails.
11. Mutate catalog specs, toolchain bindings, task or verifier proof after
    snapshot creation.
    Expected: deep-copy and private-snapshot regressions fail.
12. Replace the executable verifier during isolation verification.
    Expected: verifier-snapshot regression fails.
13. Reuse or retarget a registry for another task.
    Expected: exact-task registry regression fails.
14. Mutate the caller-owned task after registry authorization or during command
    execution.
    Expected: execution-task regression fails unless sandbox creation, budgets,
    post-run and cleanup verification, task hash and receipt all use one private
    reconstructed task snapshot.
15. Accept malformed receipt fields, repository syntax or `200.0` status.
    Expected: runtime/schema reload regressions fail.
16. Accept a moving base ref before transport.
    Expected: exact-SHA pre-network regression fails.
17. Retarget adapter task, repository, token, timeout or transport.
    Expected: sealed-adapter regression fails.
18. Materialize without independently supplied isolation evidence.
    Expected: fail-closed default regression fails.
19. Let environment proxy or CA settings choose GitHub authority.
    Expected: explicit proxy/TLS trust regression fails.
20. Return a slow-drip response that always emits a byte before each inactivity
    timeout.
    Expected: the monotonic deadline regression fails unless the total budget is
    enforced independently of inactivity timeouts.
21. Block inside `HTTPResponse.read1()` while parsing chunk framing.
    Expected: body supervisor regression fails unless the socket and response are
    cancelled at the absolute deadline.
22. Block inside `HTTPSConnection.getresponse()` while parsing status/headers.
    Expected: request supervisor regression fails unless the owned connection is
    cancelled at the absolute deadline.
23. Block DNS/connection setup until after the caller deadline.
    Expected: setup regression fails unless cancellation is checked before any
    authenticated request send after delayed setup completion.
24. Start repeated requests while one uninterruptible setup worker remains.
    Expected: the bounded setup-slot regression fails unless later requests fail
    closed without spawning further workers.
25. Close the connected socket between the final cancellation check and request
    output while leaving `http.client` automatic open enabled.
    Expected: reconnect-race regression fails unless auto reconnect is disabled
    and no second connect or auth send occurs.
26. Hide the underlying transport socket.
    Expected: request handling fails closed before accepting response evidence.
27. Remove socket shutdown, socket close, response close or connection close at
    deadline expiry.
    Expected: body/header cancellation assertions fail.

The latest complete focused runtime run produced **26/26 passing tests** before
the final hardening. The additional findings have executable contract
regressions, clean narrowly scoped commit diffs, and direct validation of private
execution-task identity, budgets and receipts; omitted-PATH insertion;
setup/body/header timeout; no post-timeout send; bounded setup workers; disabled
reconnect; cancellation; successful reads and byte-budget behavior. Full
exact-head CI and diagnostics remain pending because no Actions run has been
created for connector-authored heads.
