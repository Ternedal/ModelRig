# Prompt translation: Danish in, English to the model

**Why.** The first image run on the rig (17 Nov 2026, #2275) showed that SDXL — and the Wan video models — only really understand English. The same subject prompted in Danish produced visibly worse and often absurd images. Kaliv is Danish-first, so the translation belongs in the rig, not in the user's habits.

**What.** With `KALIV_MEDIA_TRANSLATE_MODEL` set, the media executor sends each job's prompt to a local Ollama model before rendering and renders the English answer. The job keeps the user's original prompt unchanged. When the translation changed the prompt, the rendered text is stored on the job (`effective_prompt`, same 30-day retention and the same purge as the original) and shown to the owner as `translated_prompt` in the job status — the owner can always see what was rendered in their name (#2418 review). Only an outcome code and a duration reach the executor's event stream (`translate:<job>:<outcome>:<seconds>`), never prompt text; the gallery never sees either prompt.

**Rules, all enforced in `worker/app/media_prompt_translation.py` and tested in `tests/worker_media_prompt_translation.py`:**

| Rule | How |
|---|---|
| Local only, in the URL | `KALIV_MEDIA_TRANSLATE_URL` must be plain `http` on a **numeric** loopback literal (`127.x`, `::1`, `::ffff:127.x`), no path, no credentials. Names — `localhost` included — are refused: a name is resolved by someone else at connect time, a literal cannot point off the machine. Anything else is a configuration error (exit 78) at executor start, never a request. The variable is deliberately separate from `MODELRIG_OLLAMA_URL`, which may point at Ollama Cloud. Media never leaves the rig (D4). |
| Local only, in transport | The translator has its own HTTP client (`local_only_opener`): built without any `ProxyHandler`, so `HTTP_PROXY`/`http_proxy`/`HTTPS_PROXY`/`ALL_PROXY` are never consulted; redirects are refused as the 3xx they arrived as (`fallback:http_3xx`), never followed. Tested against a proxy set in the environment (it sees nothing) and a loopback server redirecting elsewhere (the target sees nothing). |
| Local only, in execution | A local Ollama daemon also runs **cloud models** (Ollama Cloud): it forwards the prompt upstream over a connection the translator never sees (#2418 review, P2). So a cloud-tagged model name (`…:cloud`, `…-cloud`) is a configuration error, and before **every** `/api/generate` the translator calls `/api/show` with only the model name. The answer must be local model metadata — a `details` object — with no non-empty `remote_*` field; otherwise nothing is sent and the original prompt renders: `fallback:model_not_local` (remote fields), `fallback:model_unverified` (no or malformed metadata), `fallback:http_404` (model unknown to the daemon). Tested with a scripted daemon: in every refused case no `/api/generate` request is made. |
| Fail-open | Ollama down, timeout, HTTP error, non-JSON, empty answer, an answer with control characters or one that does not fit: the original prompt renders. A translation problem never fails a job. The outcome codes: `translated`, `unchanged`, `fallback:model_not_local`, `fallback:model_unverified`, `fallback:timeout`, `fallback:unreachable`, `fallback:http_<status>`, `fallback:bad_reply`, `fallback:empty`, `fallback:unprintable`, `fallback:too_long`, `fallback:error`. |
| Bounded | The answer must fit the profile's `max_prompt_chars` and may be at most 2.5× the input plus 40 characters, so a chatty model cannot replace the prompt with an essay. `num_predict` is capped at 400 tokens. |
| Deterministic | `temperature: 0`, `think: false` (reasoning preambles are also stripped if a model sends them), surrounding quotes removed, line breaks collapsed. |
| Honest about "unchanged" | An answer equal to the input is reported `unchanged`, and the request keeps the original string byte for byte. |

**Switches** (`deploy/modelrig.env.example`): `KALIV_MEDIA_TRANSLATE_MODEL` (unset = off), `KALIV_MEDIA_TRANSLATE_URL` (default `http://127.0.0.1:11434`), `KALIV_MEDIA_TRANSLATE_TIMEOUT_S` (default 30, max 300).

**Choosing the model [estimate, to be measured on the rig].** The translator runs on whichever GPU Ollama uses (GPU 0 on the rig, next to chat), so a small instruction model is the right fit: it adds one to a few seconds per job when warm, and a cold load of a 14B model would add tens of seconds to the first job. Start with a 3–4B model and measure the `translate:` event's duration; the SDXL render itself takes ~20 s at 1024² on an RTX 3060.

**Limit of the execution check [verify on the rig before turning it on].** Which fields `/api/show` uses to mark a model that runs upstream (`remote_host`, `remote_model`) is Ollama's contract, from its documentation, not something this repository controls or has measured. Before setting `KALIV_MEDIA_TRANSLATE_MODEL`, check it on the rig against the installed Ollama:

```powershell
$body = '{"model":"<model>"}'
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:11434/api/show -Body $body -ContentType application/json | Select-Object details, remote_host, remote_model
```

A local model must show `details` and no `remote_*` value. If the installed Ollama shows a cloud model without `remote_*` fields, the check cannot prove local execution: keep the translator off and report it.

**What this does not do.** It does not detect language (the model is asked to return English unchanged), it does not validate that the translation means the same (a bounded length check is not semantic validation — hence the provenance field), it does not translate video prompts differently from image prompts, and it does not touch the chat path or its cloud policy. It is off unless `KALIV_MEDIA_TRANSLATE_MODEL` is set; turning it on is Anders' product decision.
