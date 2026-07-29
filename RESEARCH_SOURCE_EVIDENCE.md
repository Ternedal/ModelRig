# T-034 verified source and citation evidence

**Status:** dormant evidence contract. It performs no DNS lookup, socket/browser
request, ToolGate action, API call or model invocation and does not activate
public research.

## Why the existing source receipt is not enough

`modelrig.research.v1` already binds a public source URL to the exact decoded
content SHA-256 used for an answer. That proves content integrity, but not the
full execution provenance required by T-034:

- which common T-032 data-sharing receipt authorized the request;
- which exact URL authorization and DNS binding was used at each redirect hop;
- whether the actual connected public peer matched the selected peer;
- whether the one-use peer ledger reached a successful terminal outcome;
- whether a final answer cited only sources with that complete evidence.

`worker/app/research_source_evidence.py` adds those missing links without
replacing the existing `SourceReceipt` or `ResearchResult` contracts.

## Verified hop

Every initial/redirect URL requires one `VerifiedResearchHop`. It can only be
constructed from:

- the canonical URL;
- one `kaliv-research-peer-transfer/v1` binding;
- the exact peer-ledger events for that binding.

The event sequence must be exactly:

```text
issued -> claimed -> finished
```

The terminal event must be `connected`, contain no error code and prove:

- authorization id/digest;
- common T-032 claim receipt id and request digest;
- URL SHA-256, host and port;
- complete sorted public DNS answer set and DNS digest;
- deterministic selected address;
- actual peer equal to the selected address;
- bounded outbound bytes;
- completion before binding expiry.

Raw redirect paths and query strings are not serialized in hop/audit evidence.
They are represented by exact URL SHA-256 values. The final public source URL
remains in the existing source receipt so the user can follow the citation.

## Verified source receipt

`kaliv-research-source-receipt/v1` binds:

- the complete existing `SourceReceipt`;
- the T-032 claim receipt id and request digest;
- SHA-256 of the canonical source receipt;
- SHA-256 of the complete `FetchTrace` projection;
- SHA-256 of the ordered peer-hop chain;
- every verified hop;
- the final peer-completion timestamp;
- `production_activation=false`.

Construction fails unless:

- requested/final URLs match the first/last trace hops;
- every visited URL has an exact resolution entry and peer binding;
- DNS answer sets match exactly;
- binding and authorization ids are unique across redirects;
- every hop belongs to the same active T-032 claim and byte ceiling;
- the event inventory contains no unknown or omitted binding;
- the existing source receipt belongs to the final URL.

The deterministic id is `vsrc_<32 hex>` and changes when source content, trace,
claim or any peer-hop evidence changes.

## Citation evidence

`VerifiedCitationBundle.from_result()` accepts an existing validated
`ResearchResult` only when **every** source receipt has exact verified execution
evidence.

For audit privacy it stores:

- answer SHA-256, not answer text;
- citation marker;
- statement SHA-256, not statement text;
- existing `source_id` values;
- corresponding verified source ids.

An unknown, missing, duplicated or metadata-drifted source fails closed. The
user-facing answer and source URLs remain in the normal research result; the
citation bundle is the independently auditable evidence layer.

## Remaining T-034 work

This slice deliberately does not:

- wire the source-evidence builder into BrowserHost or Browser Use;
- expose `browser_research` through ToolGate or an API route;
- alter confirmation or data-sharing policy;
- perform public-network validation;
- claim production readiness.

The next isolated slice should integrate the builder at the terminal runtime
boundary where the T-032 claim, per-hop peer ledgers and final `FetchTrace` are
all available. Controlled fixtures and a physical public-network campaign remain
mandatory before activation. Credentials, login, cookies, uploads and downloads
stay outside v1.
