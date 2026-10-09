# Jan / OpenAI-compatible provider (experimental)

Status: **feature branch only**. This work is intentionally isolated from the release branch and must remain unmerged until CI and a physical-rig smoke test are green.

## Runtime split

ModelRig can select a generation provider independently of the existing Ollama embedding runtime.

- **Generation / normal chat:** Ollama or Jan/OpenAI-compatible.
- **Tool-calling generation:** Ollama or Jan/OpenAI-compatible.
- **Streaming generation:** Ollama or Jan/OpenAI-compatible.
- **RAG embeddings / Memory semantic embeddings:** Ollama remains authoritative in this slice.
- **Ollama model management** (pull/delete/unload/running): available only when the selected generation provider is Ollama.

This means Jan can be tested without removing, reconfiguring or duplicating the current Ollama installation.

## Configuration

Default behavior is unchanged:

```powershell
$env:MODELRIG_LLM_PROVIDER="ollama"
```

Jan Desktop Local API Server (default desktop port):

```powershell
$env:MODELRIG_LLM_PROVIDER="jan"
$env:MODELRIG_LLM_URL="http://127.0.0.1:1337/v1"
$env:MODELRIG_LLM_KEY=""
$env:MODELRIG_GEN_MODEL="<model id returned by /v1/models>"
```

If the Jan server has an API key, set `MODELRIG_LLM_KEY` to the same value.

`jan serve` commonly uses a different port; point `MODELRIG_LLM_URL` at the actual `/v1` base URL shown by Jan.

Ollama configuration stays in place:

```powershell
$env:MODELRIG_OLLAMA_URL="http://127.0.0.1:11434"
$env:MODELRIG_EMBED_MODEL="nomic-embed-text"
```

## Physical-rig smoke test

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\test-jan-provider.ps1
```

To select a specific model and set the ModelRig generation variables in the current PowerShell session:

```powershell
.\scripts\test-jan-provider.ps1 -Model "<model-id>" -SetModelRigEnvironment
```

With an API key:

```powershell
.\scripts\test-jan-provider.ps1 -ApiKey "<jan-api-key>" -SetModelRigEnvironment
```

The smoke test does not modify persistent machine settings and does not stop or reconfigure Ollama.

## Compatibility contract

The backend keeps ModelRig's existing Ollama-shaped client contract. Android/Desktop/VR clients therefore do not need Jan-specific request handling.

The adapter translates:

- `GET /v1/models` -> ModelRig/Ollama-shaped model list.
- `POST /v1/chat/completions` -> ModelRig/Ollama-shaped buffered chat response.
- OpenAI-compatible SSE streaming -> ModelRig NDJSON streaming.
- OpenAI-compatible tool calls -> the existing worker tool loop. String-encoded JSON `function.arguments` is already accepted by the worker.

## Fail-closed behavior

When Jan/OpenAI-compatible is selected, ModelRig refuses Ollama-specific model-management operations rather than accidentally applying them to a separate Ollama runtime:

- model pull
- model delete
- model unload
- running-model inspection

These return HTTP 501 until a provider-neutral management contract exists.

## Merge gate

Do not merge this branch until all of the following are true:

1. CI is green on the exact branch head.
2. The direct Jan smoke test passes on the physical rig.
3. ModelRig normal chat succeeds through Jan.
4. At least one tool-calling turn succeeds through Jan.
5. RAG ingest/query still succeeds using Ollama embeddings.
6. Switching `MODELRIG_LLM_PROVIDER` back to `ollama` reproduces the current release behavior.
