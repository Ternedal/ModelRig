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
   authority and chunk-framing work that could remain inside one `read1()` call
   beyond the surrounding deadline check.

Current candidate `5eb237398cd4b9867e50bc42656476835ca4a057`
closes the latest findings with:

- reviewed fixed `PATH=/usr/bin:/bin` on every catalog command, overriding the
  small ambient PATH copied by the subprocess runner;
- rejection of every other PATH value by the fixed-value environment policy;
- a supervised daemon reader that is waited on only until the absolute monotonic
  deadline;
- socket shutdown/close and response close when blocking chunk framing outlives
  the deadline;
- continued per-read remaining-time socket timeouts, body byte bounds and
  fail-closed socket discovery;
- executable regressions for hostile PATH and a `read1()` call that blocks until
  cancellation.

Direct validation rejects the blocking read in approximately 0.05 seconds,
closes the response/socket, preserves successful reads and preserves byte-budget
rejection. The latest complete focused runtime run remains **26/26 passing**
from before these final narrowly scoped changes. No final independent verdict is
claimed until the resulting evidence head is reviewed without an actionable
finding.

Required review focus:

1. fixed child-tool PATH and positive-list process environment authority;
2. exact task/catalog/toolchain/attestation binding and callback snapshots;
3. fail-closed isolation and executable verification;
4. POSIX executable link, mutation, FIFO and size handling;
5. fixed GET-only GitHub host/method/ref authority;
6. caller-enforced monotonic deadline across chunk framing and body reads;
7. cancellation by socket shutdown/close and response close;
8. explicit TLS roots independent of environment proxy and CA overrides;
9. task scope, response bounds, Git blob identity and receipt/schema alignment;
10. absence of write, remote Git, publication, merge or activation authority.
