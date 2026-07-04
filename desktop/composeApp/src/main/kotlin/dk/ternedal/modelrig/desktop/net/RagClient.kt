package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

@Serializable
private data class RagChatRequest(
    val query: String,
    val top_k: Int = 4,
    val model: String? = null,
    val source: String? = null,
)

@Serializable
private data class RagSourceHit(val source: String = "")

@Serializable
private data class RagSourcesLine(val sources: List<RagSourceHit>? = null)

@Serializable
private data class RagMsg(val content: String = "")

@Serializable
private data class RagContentLine(val message: RagMsg = RagMsg())

@Serializable
private data class RagSourceEntry(val source: String = "")

@Serializable
private data class RagSourceListResponse(val sources: List<RagSourceEntry> = emptyList())

/**
 * Client for the ModelRig backend's RAG endpoints (`/api/v1/rag/chat`,
 * `/api/v1/rag/sources`). Deliberately separate from `OllamaClient`/
 * `ChatRouter`: RAG only makes sense against the backend+worker, never local
 * Ollama directly or Ollama Cloud, so it isn't part of the local/cloud
 * auto-fallback -- it's its own explicit mode.
 *
 * Mirrors Android's `ModelRigClient.ragChatStream()` / `listRagSources()`
 * exactly (same request/response shapes, already verified against the
 * worker's actual contract there): first NDJSON line is a sources header
 * (`{"sources":[{"source":...}]}`), then chat-shaped lines
 * (`{"message":{"content":...}}`).
 *
 * Known simplification (same as Android): single-shot per question -- the
 * worker's `/rag/chat` takes one `query` string, not a message list, so prior
 * conversation turns aren't fed back in as context.
 */
class RagClient(private val baseUrl: String, private val bearer: String?) {
    private val http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build()
    private val json = Json { ignoreUnknownKeys = true }

    fun chatStream(
        query: String,
        model: String?,
        sourceFilter: String?,
        onSources: (List<String>) -> Unit,
        onDelta: (String) -> Unit,
    ) {
        val payload = json.encodeToString(
            RagChatRequest.serializer(),
            RagChatRequest(query = query, model = model, source = sourceFilter),
        )
        val builder = HttpRequest.newBuilder()
            .uri(URI.create(baseUrl.trimEnd('/') + "/api/v1/rag/chat"))
            .timeout(Duration.ofSeconds(120))
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(payload))
        bearer?.let { builder.header("Authorization", "Bearer $it") }

        val resp = try {
            http.send(builder.build(), HttpResponse.BodyHandlers.ofLines())
        } catch (e: Exception) {
            throw OllamaException("cannot reach $baseUrl: ${e.message}")
        }
        if (resp.statusCode() !in 200..299) {
            throw OllamaException("rag chat failed (${resp.statusCode()})")
        }
        var first = true
        resp.body().forEach { line ->
            if (line.isBlank()) return@forEach
            if (first) {
                first = false
                val srcs = runCatching {
                    json.decodeFromString(RagSourcesLine.serializer(), line).sources
                }.getOrNull()
                if (srcs != null) {
                    onSources(srcs.map { it.source }.filter { it.isNotEmpty() })
                    return@forEach
                }
                // fell through: first line wasn't a sources header, treat as content below
            }
            val delta = runCatching {
                json.decodeFromString(RagContentLine.serializer(), line).message.content
            }.getOrDefault("")
            if (delta.isNotEmpty()) onDelta(delta)
        }
    }

    /** Lists ingested RAG source names, for the source-filter picker. */
    fun listSources(): List<String> {
        val builder = HttpRequest.newBuilder()
            .uri(URI.create(baseUrl.trimEnd('/') + "/api/v1/rag/sources"))
            .timeout(Duration.ofSeconds(10))
            .GET()
        bearer?.let { builder.header("Authorization", "Bearer $it") }
        val resp = try {
            http.send(builder.build(), HttpResponse.BodyHandlers.ofString())
        } catch (e: Exception) {
            throw OllamaException("cannot reach $baseUrl: ${e.message}")
        }
        if (resp.statusCode() !in 200..299) {
            throw OllamaException("rag sources failed (${resp.statusCode()})")
        }
        return json.decodeFromString(RagSourceListResponse.serializer(), resp.body())
            .sources.map { it.source }.filter { it.isNotEmpty() }
    }
}
