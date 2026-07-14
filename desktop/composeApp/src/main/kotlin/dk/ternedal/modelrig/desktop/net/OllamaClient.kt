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

/** A bare in-stream error line from Ollama ({"error": "..."}). */
@Serializable
private data class ErrorLine(val error: String? = null)

@Serializable
private data class ChatRequest(
    val model: String,
    val messages: List<ChatMessage>,
    val stream: Boolean = false,
    // null = omitted (local default behavior); false = ask the model to answer
    // directly. Reasoning models otherwise think server-side first, which on
    // ollama.com meant 200 + silence until the request timeout.
    val think: Boolean? = null,
)

@Serializable
private data class RespMessage(val role: String = "", val content: String = "")

@Serializable
private data class ChatResponse(val message: RespMessage = RespMessage())

@Serializable
private data class TagModel(val name: String = "")

@Serializable
private data class TagsResponse(val models: List<TagModel> = emptyList())

@Serializable
private data class DetailedTagModel(val name: String = "", val size: Long = 0)

@Serializable
private data class DetailedTagsResponse(val models: List<DetailedTagModel> = emptyList())

@Serializable
private data class RunningModelInfo(val name: String = "", val size_vram: Long = 0, val expires_at: String = "")

@Serializable
private data class RunningModelsResponse(val models: List<RunningModelInfo> = emptyList())

@Serializable
private data class PullRequest(val model: String)

@Serializable
private data class PullProgressLine(
    val status: String = "",
    val total: Long = 0,
    val completed: Long = 0,
    val error: String = "",
)

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
    private val think: Boolean? = null,
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
            ChatRequest(model = model, messages = messages, stream = false, think = think),
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
            ChatRequest(model = model, messages = messages, stream = true, think = think),
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
            // An in-stream {"error": ...} line was dropped silently before (it
            // doesn't decode as a ChatResponse), ending the stream with nothing.
            if (line.contains("\"error\"")) {
                runCatching { json.decodeFromString(ErrorLine.serializer(), line) }
                    .getOrNull()?.error?.takeIf { it.isNotBlank() }
                    ?.let { throw OllamaException("cloud: $it") }
            }
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

    data class ModelInfo(val name: String, val sizeBytes: Long)
    data class RunningModel(val name: String, val sizeVramBytes: Long, val expiresAt: String)

    /** Installed models with size (vs. listModels()'s plain names for the chat picker). */
    fun listModelsDetailed(modelsPath: String = "/api/tags"): List<ModelInfo> {
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
        if (resp.statusCode() !in 200..299) throw OllamaException("models failed (${resp.statusCode()})")
        return json.decodeFromString(DetailedTagsResponse.serializer(), resp.body())
            .models.filter { it.name.isNotEmpty() }.map { ModelInfo(it.name, it.size) }
    }

    /** Models currently loaded in memory (Ollama's /api/ps, direct or via backend), with VRAM usage. */
    fun listRunningModels(psPath: String = "/api/ps"): List<RunningModel> {
        val builder = HttpRequest.newBuilder()
            .uri(URI.create(baseUrl.trimEnd('/') + psPath))
            .timeout(Duration.ofSeconds(10))
            .GET()
        bearer?.let { builder.header("Authorization", "Bearer $it") }
        val resp = try {
            http.send(builder.build(), HttpResponse.BodyHandlers.ofString())
        } catch (e: Exception) {
            throw OllamaException("cannot reach $baseUrl: ${e.message}")
        }
        if (resp.statusCode() !in 200..299) throw OllamaException("running models failed (${resp.statusCode()})")
        return json.decodeFromString(RunningModelsResponse.serializer(), resp.body())
            .models.filter { it.name.isNotEmpty() }.map { RunningModel(it.name, it.size_vram, it.expires_at) }
    }

    /**
     * Pulls (downloads) a model, streaming Ollama's NDJSON progress lines back
     * via [onProgress] (status text, bytes completed, bytes total). Can take
     * minutes for a large model.
     */
    fun pullModel(model: String, pullPath: String = "/api/pull", onProgress: (String, Long, Long) -> Unit) {
        val payload = json.encodeToString(PullRequest.serializer(), PullRequest(model))
        val builder = HttpRequest.newBuilder()
            .uri(URI.create(baseUrl.trimEnd('/') + pullPath))
            .timeout(Duration.ofMinutes(30))
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(payload))
        bearer?.let { builder.header("Authorization", "Bearer $it") }
        val resp = try {
            http.send(builder.build(), HttpResponse.BodyHandlers.ofLines())
        } catch (e: Exception) {
            throw OllamaException("cannot reach $baseUrl: ${e.message}")
        }
        if (resp.statusCode() !in 200..299) throw OllamaException("pull failed (${resp.statusCode()})")
        resp.body().forEach { line ->
            if (line.isBlank()) return@forEach
            val p = runCatching { json.decodeFromString(PullProgressLine.serializer(), line) }.getOrNull() ?: return@forEach
            if (p.error.isNotEmpty()) throw OllamaException("pull error: ${p.error}")
            onProgress(p.status, p.completed, p.total)
        }
    }

    /** Deletes an installed model. Irreversible on the Ollama/rig side. */
    fun deleteModel(model: String, deletePath: String = "/api/delete") {
        val payload = json.encodeToString(PullRequest.serializer(), PullRequest(model))
        val builder = HttpRequest.newBuilder()
            .uri(URI.create(baseUrl.trimEnd('/') + deletePath))
            .timeout(Duration.ofSeconds(15))
            .header("Content-Type", "application/json")
            .method("DELETE", HttpRequest.BodyPublishers.ofString(payload))
        bearer?.let { builder.header("Authorization", "Bearer $it") }
        val resp = try {
            http.send(builder.build(), HttpResponse.BodyHandlers.ofString())
        } catch (e: Exception) {
            throw OllamaException("cannot reach $baseUrl: ${e.message}")
        }
        if (resp.statusCode() !in 200..299) throw OllamaException("delete failed (${resp.statusCode()}): ${resp.body()}")
    }
}
