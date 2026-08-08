# DC-L12 mutation results

**Status:** load-bearing mutations encoded; implementation exact-head validation in progress.

## Required red states

| Mutation | Detecting contract |
|---|---|
| Change one of the 36 locked source blobs without recording a projection | provenance and exact-path review |
| Reintroduce dynamic legacy proxy, `_compatibility_v1`, HMAC issuer or shared secret | public-surface, historical-v1 and CI boundary tests |
| Add private key, signer, credential, subprocess, HTTP/GitHub or remote-write adapter | source-boundary and workflow gates |
| Reuse a nonce or overwrite durable ledger/recovery state | replay/recovery adversarial tests |
| Accept one recovery role, stale signatures or wrong state snapshot | dual-role and signature-window tests |
| Roll external keyring generation backward | `test_generation_rollback_fails_closed` |
| Change state within one generation | same-generation drift test |
| Lower the external minimum epoch or ignore external revocation | keyring minimum/revocation tests |
| Read keyring monotonic state from a local file | explicit source gate |
| Export L12 authority from package root, Tier-A facade or bundle | explicit L12 workflow gate |
| Land DC-L13 materialization | workflow and coverage future-module gates |
| Omit any of the 49 landed test modules | exact workflow coverage inventory |

## Observed integration states

The raw 36-file import kept CodeQL and both diagnostics workflows green. CI failed at the expected fail-closed inventory because 48 modules were present against the DC-L11 exact inventory of 39 and L11 explicitly required L12 modules to remain absent.

A separate Windows isolation run passed the native Job Object/AppContainer/environment contracts and then hit an unrelated CP1252 console-encoding error while printing a replacement character from `tests/worker_toolhost.py`; no DC-L12 containment boundary was weakened in response.

The landing projection removes rejected v1 runtime authority, separates L13 materialization, advances the exact inventory to 49 modules and adds the external rollback-safe keyring anchor.