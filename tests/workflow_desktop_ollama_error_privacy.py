from pathlib import Path


OLLAMA_CLIENT = Path(
    "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/net/OllamaClient.kt"
)


def test_desktop_ollama_operator_errors_do_not_echo_raw_server_or_transport_payloads():
    source = OLLAMA_CLIENT.read_text(encoding="utf-8")

    forbidden = (
        "resp.body().take(",
        'invalid chat stream line:',
        'chat stream: $it',
        'invalid pull stream line:',
        'pull error: ${p.error}',
        'cannot reach $baseUrl:',
        'delete failed (${resp.statusCode()}): ${resp.body()}',
        'installed-model verification failed: ${e.message}',
        ".uri(URI.create(baseUrl.trimEnd('/')",
    )
    for needle in forbidden:
        assert needle not in source, f"raw Ollama error detail remains: {needle}"

    required = (
        "ollamaFailureMessage",
        "ollamaTransportFailureMessage",
        "decodeServerResponse",
        'throw OllamaException("invalid endpoint configuration")',
        'throw OllamaException(ollamaFailureMessage("chat", resp.statusCode()))',
        'throw OllamaException(ollamaFailureMessage("delete", resp.statusCode()))',
    )
    for needle in required:
        assert needle in source, f"Ollama privacy boundary missing: {needle}"
