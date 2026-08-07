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
   connection setup could finish after the caller deadline and transmit the
   authenticated GET, while repeated timeouts could accumulate setup workers.
   Candidate `33b762a9145dedf93365921b359477f81d22eb5f` closed them.
7. Author-side race review then found that `http.client` could automatically
   reconnect if cancellation closed the socket after the final check but before
   request output.

Current candidate `b74701c41ef05775597b930aaf23b919df1a7533`
closes the latest race with:

- `connection.auto_open = 0` before the sole explicit `connect()`;
- no implicit reconnect if cancellation closes the socket before `_send_output`;
- an executable regression that pauses request output, lets the caller reach the
  deadline and close the socket, then resumes output and proves there is exactly
  one connect and no authenticated request send;
- continued explicit setup checks, bounded pending setup workers and transport
  cleanup.

Direct validation returns the caller deadline error, resumes the paused worker,
records `connect_count == 1`, `auto_open == 0`, no request send and definitive
worker exit. Existing public test surfaces were preserved. The latest complete
focused runtime run remains **26/26 passing** from before these final narrowly
scoped changes. No final independent verdict is claimed until the resulting
evidence head is reviewed without an actionable finding.

Required review focus:

1. automatic fixed child-tool PATH on every accepted catalog entry;
2. exact task/catalog/toolchain/attestation binding and callback snapshots;
3. fail-closed isolation and executable verification;
4. POSIX executable link, mutation, FIFO and size handling;
5. fixed GET-only GitHub host/method/ref authority;
6. caller-enforced monotonic deadline across setup, request, status, headers,
   chunk framing and body reads;
7. prevention of post-timeout request sends after delayed setup;
8. disabled `http.client` auto reconnect after socket cancellation;
9. bounded setup workers and fail-closed concurrent attempts;
10. cancellation by socket shutdown/close, response close and connection close;
11. explicit TLS roots independent of environment proxy and CA overrides;
12. task scope, response bounds, Git blob identity and receipt/schema alignment;
13. absence of write, remote Git, publication, merge or activation authority.
