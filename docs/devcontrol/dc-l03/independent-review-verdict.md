# DC-L03 independent review verdict

Status: **pending fresh exact-head review**

Independent review history:

1. Review of `96967da26134cb68cc59242fbee004cc403228ba` found mutable
   isolation-verifier proof and blocking FIFO-open issues. Candidate
   `660e85dcb0281cdbc0991d9cb5c06a7f0064ff6f` closed both.
2. Author-side schema review found receipt repository syntax looser than runtime.
   Candidate `157b158011d120797a230912f1c96a23babb1ace` aligned them.
3. Review of `002306223eb172351f9bfd1665dc1d5f9bdcfd2a` found unreviewed
   interpreter/toolchain environment authority and no total response deadline.
   Candidate `b7cabc3524a75d980cd5e0710b2acfeed7a15eb2` closed them.
4. Review of `9829fe24227f363141c779237a9e042a1a1af2ca` found ambient PATH
   authority and chunk-framing work that could remain inside one `read1()` call.
   Candidate `5eb237398cd4b9867e50bc42656476835ca4a057` closed them.
5. Review of `3483ac687a267d6ec31aa71eaa4896baa5604d74` found that caller-supplied
   catalog entries could still omit PATH and HTTP status/header framing remained
   outside the response-body supervisor. Candidate
   `ac4eaa44fa501eba797818d8563e82c9b83ce8f0` closed them.
6. Review of `3a0a99ab987ec22219787a086a97fc7cf13f9998` found that blocked DNS/
   connection setup could finish after caller deadline and transmit the
   authenticated GET, while repeated timeouts could accumulate setup workers.
   Candidate `33b762a9145dedf93365921b359477f81d22eb5f` closed them.
7. Author-side race review found that `http.client` could automatically reconnect
   if cancellation closed the socket after the final check but before request
   output. Candidate `b74701c41ef05775597b930aaf23b919df1a7533` closed it.
8. Review of `64cab512ef45c9ebd8dba5b88ab1202eb08a4b88` found that the task-bound
   registry validated a reconstructed task but `CommandExecutor.execute()` then
   continued with the caller-owned mutable object for sandbox, budgets,
   verification and receipt authority.

Current candidate `c7c018c8f866867507eb9f3adcbaf4ae1e0d7eef`
closes the latest finding with:

- `CommandRegistry.execution_task()` reconstructing one strict private
  `DevelopmentTask` before command resolution;
- `CommandExecutor.execute()` using only that object for registry resolution,
  source/base-SHA verification, sandbox creation, runtime/output budgets,
  post-command verification, cleanup verification, task hashing and receipt
  identity;
- continued exact-task enforcement by `TaskBoundCommandRegistry.resolve()`;
- an executable regression whose runner mutates caller task A into B during
  execution and proves every observed execution task remains the same private A
  object, budgets remain A and the receipt remains bound to A;
- no new command ID, generic process launcher or activation authority;
- `devcontrol/README.md` restored to base and `commands.py` taking its place as a
  progressive surface, preserving the 16-path scope.

The latest complete focused runtime run remains **26/26 passing** from before the
final narrowly scoped hardening. The new execution-task regression is present on
the existing repository-level CI contract surface. No final independent verdict
is claimed until the resulting evidence head is reviewed without an actionable
finding.

Required review focus:

1. one private execution-task snapshot across sandbox, budgets, verification and
   receipt authority;
2. automatic fixed child-tool PATH on every accepted catalog entry;
3. exact task/catalog/toolchain/attestation binding and callback snapshots;
4. fail-closed isolation and executable verification;
5. POSIX executable link, mutation, FIFO and size handling;
6. fixed GET-only GitHub host/method/ref authority;
7. caller-enforced monotonic deadline across setup, request, status, headers,
   chunk framing and body reads;
8. prevention of post-timeout request sends and automatic reconnect;
9. bounded setup workers and fail-closed concurrent attempts;
10. explicit TLS roots independent of environment proxy and CA overrides;
11. task scope, response bounds, Git blob identity and receipt/schema alignment;
12. absence of GitHub write, remote Git, new command/launch authority,
    publication, merge or activation authority.
