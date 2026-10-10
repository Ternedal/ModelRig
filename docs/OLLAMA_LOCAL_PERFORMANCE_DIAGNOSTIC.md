# Local ModelRig/Ollama inference speed — read-only diagnostics (DRAFT)

This is **not** Stage-B CI speed. The ongoing Stage-B work shortens
the test/release pipeline. This probe measures real token-generation
behavior on the actual Windows/WSL2 GPU rig.

## What this measures

The probe talks **only to a loopback IP** (default
http://127.0.0.1:11435). No remote URLs or redirects are allowed, proxy
variables are ignored, and it will **not pull** a missing model. The model
must already appear in Ollama's \`/api/tags\`. It sends one fixed,
non-sensitive Danish prompt, without tools, code execution or filesystem
access. It saves only numeric timings and model names, **never model
responses or private prompts**.

It uses Ollama's actual /api/chat timing fields:

- \`load_duration\`: model load seconds;
- \`prompt_eval_duration\` + \`prompt_eval_count\`: prompt processing;
- \`eval_duration\` + \`eval_count\`: decoding tokens/second;
- local monotonic total request time, separately.

It also records whether the model appeared loaded in /api/ps before
and after and its self-reported VRAM size. **This does not prove an exact
GPU/CPU split or per-GPU placement.** Use \`ollama ps\` and \`nvidia-smi\`
on the rig for that. The first request may already be warm; later
requests are called "warm repeats" only for grouping.

## Run in PowerShell on the rig (after fetching this draft branch)

\`\`\`powershell
cd C:\Rig\src\ModelRig
$env:OLLAMA_HOST = "127.0.0.1:11435"
ollama list
ollama ps
nvidia-smi

# Quick, bounded, never downloads models or unloads/pins them.
python scripts/ollama_local_perf_probe.py --model qwen2.5-coder:7b --runs 3 --num-ctx 4096 --num-predict 96 --timeout 600

# Compare the model currently involved in CPU offload, if installed:
python scripts/ollama_local_perf_probe.py --model gemma4:26b --runs 3 --num-ctx 4096 --num-predict 96 --timeout 900
\`\`\`

Optionally save a new diagnostic JSON file via \`--json-out\`, e.g.
\`--json-out validation/ollama-diagnostic-qwen-01.json\`. The probe
refuses to overwrite existing files or follow a symlink destination.
The report is **diagnostic only, never physical acceptance evidence**.

## How to interpret the result

1. **Large load time, normal warm decode:** the model is unloading or
   thrashing between turns. Verify the worker's \`MODELRIG_OLLAMA_KEEP_ALIVE\`
   setting and simultaneous ASR/TTS/VLM memory pressure. Don't pin
   everything permanently before checking available VRAM.
2. **Slow decode even when warm:** likely model-size / VRAM / offload /
   memory-bandwidth pressure. Inspect \`ollama ps\` and both GPU memory
   figures, then test a smaller installed model at the **same prompt and
   context**. On the user's two 12GB RTX 3060 cards, do **not** assume
   24GB is one unified GPU memory pool.
3. **Slow prompt processing:** inspect effective \`num_ctx\`, excessive
   chat history and RAG context length before changing model quality.
4. **Fast raw Ollama but slow Kaliv:** measure real application path
   (ASR, retrieval, tool confirmation, cognitive routing and TTS)
   using \`docs/KALIV_END_TO_END_LATENCY_QUALIFICATION.md\` — raw decode
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
