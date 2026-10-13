# Local ModelRig/Ollama inference speed — read-only diagnostics (DRAFT)

This is **not** Stage-B CI speed. The ongoing Stage-B work shortens
the test/release pipeline. This probe measures real token-generation
behavior on the actual Windows/WSL2 GPU rig.

## What this measures

The probe talks **only to a loopback IP** (default
http://127.0.0.1:11435). No remote URLs or redirects are allowed, proxy
variables are ignored, and it will **not pull** a missing model. The model
must already appear in Ollama's `/api/tags`. It sends one fixed,
non-sensitive Danish prompt, without tools, code execution or filesystem
access. It saves only numeric timings and model names, **never model
responses or private prompts**.

It uses Ollama's actual /api/chat timing fields:

- `load_duration`: model load seconds;
- `prompt_eval_duration` + `prompt_eval_count`: prompt processing;
- `eval_duration` + `eval_count`: decoding tokens/second;
- local monotonic total request time, separately.

It also records whether the model appeared loaded in /api/ps before
and after and its self-reported VRAM size. **This does not prove an exact
GPU/CPU split or per-GPU placement.** Use `ollama ps` and `nvidia-smi`
on the rig for that. The first request may already be warm; later
requests are called "warm repeats" only for grouping.

## Run in PowerShell on the rig (after fetching this draft branch)

```powershell
cd C:\Rig\src\ModelRig
# Probe the actual running loopback port first. Do not change OLLAMA_HOST
# or start a second Ollama service just to run this diagnostic.
$OllamaUrl = @('http://127.0.0.1:11434', 'http://127.0.0.1:11435') |
    Where-Object {
        try {
            $endpoint = $_
            $reply = Invoke-RestMethod -Method Get -Uri "$endpoint/api/tags" -NoProxy -MaximumRedirection 0 -TimeoutSec 3
            $null -ne $reply.models
        } catch { $false }
    } | Select-Object -First 1
if (-not $OllamaUrl) { throw 'No local Ollama found on 11434 or 11435; stop and check the service' }
Write-Host "Ollama diagnostic endpoint: $OllamaUrl"
nvidia-smi

# Quick, bounded, never downloads models or unloads/pins them.
python scripts/ollama_local_perf_probe.py --url $OllamaUrl --model qwen2.5-coder:7b --runs 3 --num-ctx 4096 --num-predict 96 --timeout 600

# Compare the larger installed model only when needed:
python scripts/ollama_local_perf_probe.py --url $OllamaUrl --model gemma4:26b --runs 3 --num-ctx 4096 --num-predict 96 --timeout 900
```

Optionally save a new diagnostic JSON file via `--json-out`, e.g.
`--json-out validation/ollama-diagnostic-qwen-01.json`. The probe
refuses to overwrite existing files or follow a symlink destination.
The report is **diagnostic only, never physical acceptance evidence**.

## How to interpret the result

1. **Large load time, normal warm decode:** the model is unloading or
   thrashing between turns. Verify the worker's `MODELRIG_OLLAMA_KEEP_ALIVE`
   setting and simultaneous ASR/TTS/VLM memory pressure. Don't pin
   everything permanently before checking available VRAM.
2. **Slow decode even when warm:** likely model-size / VRAM / offload /
   memory-bandwidth pressure. Inspect `ollama ps` and both GPU memory
   figures, then test a smaller installed model at the **same prompt and
   context**. On the user's two 12GB RTX 3060 cards, do **not** assume
   24GB is one unified GPU memory pool.
3. **Slow prompt processing:** inspect effective `num_ctx`, excessive
   chat history and RAG context length before changing model quality.
4. **Fast raw Ollama but slow Kaliv:** measure real application path
   (ASR, retrieval, tool confirmation, cognitive routing and TTS)
   using `docs/KALIV_END_TO_END_LATENCY_QUALIFICATION.md` — raw decode
   metrics cannot substitute for correlated production-side receipts.

Some models consume output-token budget on reasoning. The probe does
not force reasoning off or change the chosen model, tool policy,
quantization, persistence settings, safety filters, or production
configuration. An improvement is meaningful only if **quality and safety
checks are unchanged**.

## Safety and release authority

This is a **separate draft branch off frozen ModelRig V1**, with only
a stand-alone diagnostic script, pure offline negative tests and this
documentation. It does not modify the worker's Ollama client or any
release/physical gate. The JSON output is an **observation**, not proof
that system latency meets a target. No merge into frozen main without
explicit release authorization.

## Repeatable baseline protocol (no automatic tuning)

To compare two runs fairly, record the exact Git commit, installed Ollama
version, NVIDIA driver, model tag and quantization, both GPU utilization/VRAM
figures, and whether other GPU workloads were running. Use the **same**
`--num-ctx`, `--num-predict`, model and fixed probe prompt on every repeat.
Do not compare a cold load against a warm repeat as though they were identical.
Do not infer an improvement from one run: repeat the measurement and check
whether the observed difference exceeds normal run-to-run variation.

Suggested operator sequence:

1. Run `ollama ps` and `nvidia-smi` before the probe; note CPU/GPU offload
   and other resident models. Keep the system otherwise idle if possible.
2. Run the three-repeat probe for the existing installed model. Preserve the
   original JSON report under a new filename; never replace earlier evidence.
3. Capture `ollama ps` and `nvidia-smi` again. Check for model residency,
   load spikes, throttling or VRAM pressure.
4. Repeat with identical settings in a separate session before drawing a
   conclusion. If evaluating another model, treat quality, memory residency
   and inference speed as separate dimensions.
5. For Kaliv's perceived response time, collect the correlated real
   perception/cognition/outward receipts described in
   `docs/KALIV_END_TO_END_LATENCY_QUALIFICATION.md`. A raw Ollama result
   cannot measure ASR, retrieval, routing or TTS latency.

**Interpretation guardrails:** the median excludes the first request by
convention, but that does not establish that later requests were warm. The
probe's reported VRAM value is Ollama metadata, not per-card GPU proof.
Timing differences are diagnostic observations, not a release threshold.
Avoid changing keep-alive, concurrency, quantization, context size, or
security settings until a measured bottleneck and regression test justify it.
