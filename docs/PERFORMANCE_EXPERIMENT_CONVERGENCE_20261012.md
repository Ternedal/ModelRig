# Performance experiment convergence — 2026-10-12

Status: **planning and evidence inventory only**. Base: `experiment/resource-benchmark-capture-20261012`; frozen `main` unchanged.

## Existing isolated work

| Branch | Compared with main | Relevant deliverable |
| --- | --- | --- |
| `experiment/resource-budget-v1-20261011` | 19 ahead / 0 behind | Keep-alive candidate and offline tests in `worker/app/ollama_client.py`, resource decision rules |
| `experiment/ollama-local-latency-diagnostics-20261010` | 5 ahead / 0 behind | `scripts/ollama_local_perf_probe.py` and negative tests |
| `experiment/resource-benchmark-capture-20261012` | 1 ahead / 0 behind | `scripts/resource_snapshot.ps1` |

These branches are independent experiments. **Do not merge wholesale or interpret commit counts as unique changes**. Review changes and tests individually, then create a separate integration branch if justified.

## Safe qualification sequence

1. Run static review and offline negative tests for the latency probe: loopback-only URL, proxy bypass, no redirects, no downloads, no response logging, no file overwrite, symlink protection.
2. Check the resource snapshot script against failure paths: missing nvidia-smi, unavailable Ollama, null model list, PowerShell 7, JSON schema stability. It must never change settings.
3. Review keep-alive changes and tests for cold-start, eviction, cancellation, concurrency and model separation. Do not modify V1 defaults based on theory.
4. On the physical rig, record an idle baseline, then repeat identical synthetic requests (at least five runs per profile) and measure p50/p95, throughput, CPU/RAM, per-GPU VRAM/power and error rates. Separate cold from warm runs. Record the actual Ollama port (often 11435) and effective worker environment.
5. Evaluate alternatives one at a time (30m vs 5m vs 1m residency; 7B vs 12B; concurrency 1 vs 2; context sizes) with Danish-language, tool-policy, retrieval and safety regressions.
6. Promote only an evidence-backed Pareto improvement via a reviewed PR and the existing exact-head, CI, security and physical gates.

## Non-negotiable release boundary

No direct writes to main, no activation or release claims from these experiments, no production configuration changes, no cloud fallback as an implicit optimization. Hardware acceptance and signed release evidence remain separate.

## Current gaps

No rig measurements were collected in this documentation pass. There is no verified speedup percentage, no validated optimal keep-alive setting, and no basis for declaring V1 performance or physical acceptance green.
