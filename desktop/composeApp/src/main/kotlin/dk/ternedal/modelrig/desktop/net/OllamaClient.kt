package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

@Serializable
data class ChatMessage(val role: String, val content: String)

@Serializable
private data class ChatRequest(
    val model: String,
    val messages: List<ChatMessage>,
    val stream: Boolean = false,
)

@Serializable
private data class RespMessage(val role: String = "", val content: String = "")

@Serializable
private data class ChatResponse(val message: RespMessage = RespMessage())

@Serializable
private data class TagModel(val name: String = "")

@Serializable
private data class TagsResponse(val models: List<TagModel> = emptyList())

class OllamaException(message: String) : RuntimeException(message)

/**
 * Minimal non-streaming chat client for any Ollama-compatible /api/chat endpoint.
 *
 * The same request/response shape works against all three of:
 *   - local Ollama:        baseUrl=http://localhost:11434, path=/api/chat
 *   - Ollama Cloud:        baseUrl=https://ollama.com,      path=/api/chat, bearer=OLLAMA_API_KEY
 *   - the ModelRig backend: baseUrl=http://host:8080,       path=/api/v1/chat, bearer=deviceToken
 *
 * Streaming is intentionally omitted for V1; add an NDJSON reader for token
 * streaming in V1.1.
 */
class OllamaClient(
    private val baseUrl: String,
    private val chatPath: String = "/api/chat",
    private val bearer: String? = null,
    connectTimeout: Duration = Duration.ofSeconds(5),
    private val requestTimeout: Duration = Duration.ofSeconds(120),
) {
    private val http: HttpClient = HttpClient.newBuilder()
        .connectTimeout(connectTimeout)
        .build()

    private val json = Json { ignoreUnknownKeys = true }

    fun chat(model: String, messages: List<ChatMessage>): String {
        val payload = json.encodeToString(
            ChatRequest.serializer(),
            ChatRequest(model = model, messages = messages, stream = false),
        )
        val builder = HttpRequest.newBuilder()
            .uri(URI.create(baseUrl.trimEnd('/') + chatPath))
            .timeout(requestTimeout)
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(payload))
        bearer?.let { builder.header("Authorization", "Bearer $it") }

        val resp: HttpResponse<String> = try {
            http.send(builder.build(), HttpResponse.BodyHandlers.ofString())
        } catch (e: Exception) {
            throw OllamaException("cannot reach $baseUrl: ${e.message}")
        }
        if (resp.statusCode() !in 200..299) {
            throw OllamaException("chat failed (${resp.statusCode()}): ${resp.body().take(200)}")
        }
        return json.decodeFromString(ChatResponse.serializer(), resp.body()).message.content
    }

    /**
     * Streaming chat: invokes onDelta for each NDJSON token chunk as it arrives.
     * Uses stream=true; each line is a partial ChatResponse whose message.content
     * is the delta.
     */
    fun chatStream(model: String, messages: List<ChatMessage>, onDelta: (String) -> Unit) {
        val payload = json.encodeToString(
            ChatRequest.serializer(),
            ChatRequest(model = model, messages = messages, stream = true),
        )
        val builder = HttpRequest.newBuilder()
            .uri(URI.create(baseUrl.trimEnd('/') + chatPath))
            .timeout(requestTimeout)
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(payload))
        bearer?.let { builder.header("Authorization", "Bearer $it") }

        val resp = try {
            http.send(builder.build(), HttpResponse.BodyHandlers.ofLines())
        } catch (e: Exception) {
            throw OllamaException("cannot reach $baseUrl: ${e.message}")
        }
        if (resp.statusCode() !in 200..299) {
            throw OllamaException("chat failed (${resp.statusCode()})")
        }
        resp.body().forEach { line ->
            if (line.isBlank()) return@forEach
            val delta = runCatching {
                json.decodeFromString(ChatResponse.serializer(), line).message.content
            }.getOrDefault("")
            if (delta.isNotEmpty()) onDelta(delta)
        }
    }

    /** Lists available model names via /api/tags (local) or the backend equivalent. */
    fun listModels(modelsPath: String = "/api/tags"): List<String> {
        val builder = HttpRequest.newBuilder()
            .uri(URI.create(baseUrl.trimEnd('/') + modelsPath))
            .timeout(Duration.ofSeconds(10))
            .GET()
        bearer?.let { builder.header("Authorization", "Bearer $it") }
        val resp = try {
            http.send(builder.build(), HttpResponse.BodyHandlers.ofString())
        } catch (e: Exception) {
            throw OllamaException("cannot reach $baseUrl: ${e.message}")
        }
        if (resp.statusCode() !in 200..299) {
            throw OllamaException("models failed (${resp.statusCode()})")
        }
        return json.decodeFromString(TagsResponse.serializer(), resp.body())
            .models.map { it.name }.filter { it.isNotEmpty() }
    }
}
