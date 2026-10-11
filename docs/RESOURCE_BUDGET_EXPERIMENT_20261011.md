# ModelRig: minimal resource budget (experimental, no V1 change)

Baseline: frozen main `0b2ff455116f4f28a1a41704d9cb81503f17d2df`. This is a read-only measurement plan; no service configuration or security policy is changed.

## Objective and non-negotiable constraints

Minimize **idle VRAM, idle RAM, CPU wakeups, GPU energy, and model reload overhead**, while preserving quality, data isolation, approval gates and user-visible latency. Do not conflate minimum idle consumption with minimum latency. Do not enable remote/cloud execution as a resource-saving shortcut without explicit authorization and privacy review.

## Current verified code observations

- `worker/app/ollama_client.py` defaults `MODELRIG_OLLAMA_KEEP_ALIVE` to `30m` and passes it to local embed/chat/chat_tools/chat_stream. The value is configurable; lowering it releases model residency earlier but increases cold-starts.
- The same client defaults `MODELRIG_GEN_MODEL` to `qwen2.5-coder:7b`, `MODELRIG_EMBED_MODEL` to `nomic-embed-text`, and `MODELRIG_OLLAMA_TIMEOUT` to 600 seconds. Verify actual running worker environment rather than assuming defaults.
- The configured local Ollama endpoint defaults to port 11434; the rig may use 11435. Verify the active endpoint before benchmarking.

## Read-only baseline on the physical Windows rig

PowerShell 7; run from a trusted interactive shell. This does not modify any setting:

```powershell
$env:OLLAMA_HOST = "127.0.0.1:11435"
ollama ps
ollama list
nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu,power.draw --format=csv
Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 15 ProcessName,Id,CPU,WorkingSet64
```

Repeat idle (10 minutes without requests), cold first turn, 10 warm turns, and concurrent two-turn tests. Log response duration, tokens/s, load_duration, prompt_eval_duration, eval_duration and peak GPU/CPU/RAM where Ollama response metadata is available. Keep prompts and outputs identical across comparisons; measure quality, failures and tail latency.

## Controlled candidates (one variable at a time)

1. **Idle residency**: test `MODELRIG_OLLAMA_KEEP_ALIVE=5m` and `1m` versus current `30m`. Do not change the default before cold/warm latency and energy measurements; keep `30m` if reload costs dominate.
2. **Model sizing**: benchmark existing 7B and 12B local models at the same quality gate; do not replace a higher-quality route solely because it uses less memory. Quantization requires semantic, safety and Danish-language regression tests.
3. **Concurrency**: benchmark one versus two simultaneous inference jobs; two RTX 3060 cards do not automatically behave as a unified 24 GB pool. Capture actual layer placement, CPU offload and PCIe transfer cost before choosing split or dedicated-per-GPU scheduling.
4. **Context budget**: measure realistic prompt lengths and KV-cache footprint. Reduce excessive context only with retrieval-recall, tool-use and long-turn regression coverage.
5. **Network overhead**: assess HTTP connection reuse, but preserve SSRF restrictions, cloud/local separation, timeouts, authentication and error handling. No broad shared client across trust boundaries without security review.
6. **Background work**: measure wakeups, queues and periodic tasks. Consider event-driven scheduling only where missed work, cancellation, and crash-recovery tests remain green.

## Acceptance gates

- Baseline and candidate tested on the *same physical rig*, same input dataset, same models, same model output/quality requirements, repeated at least 5 times.
- Report idle VRAM/RAM, mean/p95 latency, tokens/s, load time, peak power, energy per completed task and failure rate. No fabricated percentages.
- All existing CI, security checks, physical/admin release gates, and exact-head Stage-B qualification remain mandatory.
- Candidate remains on experimental branch; no merge, release, tag, re-freeze, production activation, or automatic environment change.

## Decision rule

Prefer the Pareto-optimal profile: lower resource use **without measurable loss in required quality, security or acceptable latency**. If no profile dominates, present the trade-off explicitly and obtain operator approval before changing V1 defaults.
