# Local Ollama inference performance — bounded benchmark (experimental)

**This is an opt-in local timing probe. It is not a release, security,
quality, physical GPU or four-repository qualification. The frozen ModelRig
V1 software and protected `main` stay unchanged.**

## Why this measurement exists

The existing green Stage-B CI optimization measures test completion time;
it says nothing about latency when a person speaks to Kaliv or sends a chat
message. An actual end-user speed analysis needs independently measured:
- **TTFT (time to first generated text):** wall time to the first streamed
  nonempty token. Includes queuing, prefill and cold model load.
- **Generation tokens/second:** Ollama's own `eval_count / eval_duration`
  on the final `/api/generate` event. This is NOT perceived response speed.
- **End-to-end local inference wall time**, separate from ModelRig/VoiceRig/
  BodyRig networking, ASR, TTS and GUI overhead.
- **Model load cost** from Ollama's final `load_duration`. Compare a
  warmup-discarded and a cold run to see how CPU/GPU offload affects latency.

The command makes exactly `warmup + repetitions` bounded local
`POST /api/generate` requests with `temperature=0`, deterministic
nonpersonal Danish prompt, `num_ctx=8192`, `num_predict=96`. It does
NOT download models, change Ollama/server settings, stop any services,
write reports unless `--output` is requested, contact the internet,
or alter the four V1 repositories.

The only accepted endpoint is literal loopback HTTP with explicit port:
`127.0.0.1` or `[::1]`. Requests go through `http.client`, not an
environment-configured HTTP proxy or a redirect. A non-200, malformed
stream, missing final marker, oversized data or socket timeout is a
BLOCKED result (exit 2). The output intentionally contains no response
text or raw prompt; only the prompt's SHA-256.

## On the Windows rig (PowerShell)

```powershell
cd C:\Rig\src\ModelRig
# Only run from the experimental branch or from an explicitly downloaded,
# reviewed copy of this nonproduction script. Do not switch frozen main.
python .\scripts\ollama_inference_benchmark.py `
  --base-url http://127.0.0.1:11435 `
  --model gemma4:26b --num-ctx 8192 `
  --warmup 1 --repetitions 3 `
  --output .\validation\ollama-local-benchmark.json
```

To compare another *already installed* model, change only `--model`
and use a different output file. A given model/quantization should be
measured repeatedly under the same context, prompt and resident-memory
conditions; `ollama ps` and `nvidia-smi` can separately show what the
server and GPU currently report. The benchmark itself cannot prove how
many GPUs processed the request or how much of the model was CPU-offloaded.

On a machine with the older port use the actual local port, e.g. 11434.
Avoid competing model/ASR loads when establishing a baseline. A missing
model or unavailable Ollama endpoint is an ordinary BLOCKED result; this
script does not auto-install, auto-pull or reconfigure anything.

## What qualifies as an optimization

Keep model name/quantization, context, prompt, token cap and deployment
mode fixed. Change **one parameter at a time**, record at least three
independent measured repetitions, compare TTFT and throughput *plus*
correctness of real end-to-end scenarios. Faster responses obtained by
reducing security checks, discarding context needed for correctness,
skipping model quality evaluations or cutting safety gates are NOT
acceptable optimizations.

A future performance setting may be trialed on an isolated branch/
local rig session. It must not update frozen `main`, production settings,
releases or physical acceptance receipts without deliberate re-freeze.

This tool returns `modelrig_end_to_end_proven=false`,
`gpu_attribution_proven=false`, `release_ready=false` and
`production_activation=false` even for a successful local timing run.
