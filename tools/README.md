# ModelRig tools

## `modelrig-cli.py` — reference CLI

A dependency-free (stdlib only) client for the ModelRig backend. Useful for
smoke-testing a running stack and as a reference for how the API is used, while
the desktop/Android clients are built locally.

Runs on Python 3.9+, Windows included. Config (server URL + token) is saved to
`~/.modelrig/cli.json` after pairing.

### Commands
```
pair --code XXXX-XXXX [--name NAME]   claim a code, save the token
status                                device + upstream health
models                                list model names
chat [--model M] "message"            streaming chat (tokens print as they arrive)
rag-ingest [--source S] [--chunk-size N] [--overlap N] "text"
rag-query [--top-k K] [--no-synth] [--model M] "query"
devices                               list paired devices
revoke DEVICE_ID                      revoke a device (its token dies)
whoami                                show saved config (token masked)
```
Global: `--url`, `--token`, `--config` override the saved config.

### Example session
```bash
python modelrig-cli.py --url http://192.168.1.10:8080 pair --code 5Z2T-Q7KR
python modelrig-cli.py models
python modelrig-cli.py chat "explain the pairing flow in one sentence"
python modelrig-cli.py rag-ingest --source notes "ModelRig binds 0.0.0.0 for LAN."
python modelrig-cli.py rag-query "what host does it bind?"
python modelrig-cli.py devices
```

### Verified
Exercised end to end by `tests/e2e.py` against the real backend + worker: pair →
models → streaming chat → rag-ingest → rag-query (matches + synthesis) → devices →
revoke → post-revoke auth failure (12/12).
