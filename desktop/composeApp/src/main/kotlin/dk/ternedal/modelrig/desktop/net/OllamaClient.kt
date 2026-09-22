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
    // null = omitted (local default behavior); false = ask the model to answer
    // directly. Reasoning models otherwise think server-side first, which on
    // ollama.com meant 200 + silence until the request timeout.
    val think: Boolean? = null,
)

@Serializable
private data class RespMessage(val role: String = "", val content: String = "")

/** One Ollama NDJSON chat line. A terminal line carries done=true. */
@Serializable
private data class ChatResponse(
    val message: RespMessage = RespMessage(),
    val done: Boolean = false,
    val error: String? = null,
)

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

internal object OllamaClientErrors {
    fun transport(operation: String): String = "$operation unavailable"
    fun invalidEndpoint(operation: String): String = "$operation failed (invalid endpoint)"
    fun invalidRequest(operation: String): String = "$operation failed (invalid request)"
    fun http(operation: String, status: Int): String = "$operation failed ($status)"
    fun invalidResponse(operation: String): String = "$operation failed (invalid response)"
    fun remote(operation: String): String = "$operation failed (remote error)"
}

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

    private fun endpoint(path: String, operation: String): URI = try {
        URI.create(baseUrl.trimEnd('/') + path)
    } catch (_: IllegalArgumentException) {
        throw OllamaException(OllamaClientErrors.invalidEndpoint(operation))
    }

    private fun authorize(builder: HttpRequest.Builder, operation: String) {
        try {
            bearer?.let { builder.header("Authorization", "Bearer $it") }
        } catch (_: IllegalArgumentException) {
            throw OllamaException(OllamaClientErrors.invalidRequest(operation))
        }
    }

    private fun sendText(request: HttpRequest, operation: String): HttpResponse<String> =
        try {
            http.send(request, HttpResponse.BodyHandlers.ofString())
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
            throw OllamaException(OllamaClientErrors.transport(operation))
        } catch (_: Exception) {
            throw OllamaException(OllamaClientErrors.transport(operation))
        }

    private fun sendLines(request: HttpRequest, operation: String): HttpResponse<java.util.stream.Stream<String>> =
        try {
            http.send(request, HttpResponse.BodyHandlers.ofLines())
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
            throw OllamaException(OllamaClientErrors.transport(operation))
        } catch (_: Exception) {
            throw OllamaException(OllamaClientErrors.transport(operation))
        }

    fun chat(model: String, messages: List<ChatMessage>): String {
        val payload = json.encodeToString(
            ChatRequest.serializer(),
            ChatRequest(model = model, messages = messages, stream = false, think = think),
        )
        val builder = HttpRequest.newBuilder()
            .uri(endpoint(chatPath, "chat"))
            .timeout(requestTimeout)
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(payload))
        authorize(builder, "chat")

        val resp = sendText(builder.build(), "chat")
        if (resp.statusCode() !in 200..299) {
            throw OllamaException(OllamaClientErrors.http("chat", resp.statusCode()))
        }
        return runCatching {
            json.decodeFromString(ChatResponse.serializer(), resp.body()).message.content
        }.getOrElse {
            throw OllamaException(OllamaClientErrors.invalidResponse("chat"))
        }
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
            .uri(endpoint(chatPath, "chat"))
            .timeout(requestTimeout)
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(payload))
        authorize(builder, "chat")

        val resp = sendLines(builder.build(), "chat stream")
        if (resp.statusCode() !in 200..299) {
            throw OllamaException(OllamaClientErrors.http("chat", resp.statusCode()))
        }
        // Fail-closed streaming (analysis F-005, ported from PR #3): EOF is not
        // success. A dropped socket or proxy timeout also ends the sequence
        // cleanly, so completion requires Ollama's explicit done=true line, and
        // an undecodable line is an error rather than silently skipped.
        var sawDone = false
        resp.body().forEach { line ->
            if (line.isBlank()) return@forEach
            val item = runCatching {
                json.decodeFromString(ChatResponse.serializer(), line)
            }.getOrElse {
                throw OllamaException(OllamaClientErrors.invalidResponse("chat stream"))
            }
            item.error?.takeIf { it.isNotBlank() }
                ?.let { throw OllamaException(OllamaClientErrors.remote("chat stream")) }
            if (item.message.content.isNotEmpty()) onDelta(item.message.content)
            if (item.done) sawDone = true
        }
        if (!sawDone) {
            throw OllamaException(
                "chat stream ended without done=true — the response was interrupted and is not complete"
            )
        }
    }

    /** Lists available model names via /api/tags (local) or the backend equivalent. */
    fun listModels(modelsPath: String = "/api/tags"): List<String> {
        val builder = HttpRequest.newBuilder()
            .uri(endpoint(modelsPath, "models"))
            .timeout(Duration.ofSeconds(10))
            .GET()
        authorize(builder, "models")
        val resp = sendText(builder.build(), "models")
        if (resp.statusCode() !in 200..299) {
            throw OllamaException(OllamaClientErrors.http("models", resp.statusCode()))
        }
        return runCatching {
            json.decodeFromString(TagsResponse.serializer(), resp.body())
                .models.map { it.name }.filter { it.isNotEmpty() }
        }.getOrElse {
            throw OllamaException(OllamaClientErrors.invalidResponse("models"))
        }
    }

    data class ModelInfo(val name: String, val sizeBytes: Long)
    data class RunningModel(val name: String, val sizeVramBytes: Long, val expiresAt: String)

    /** Installed models with size (vs. listModels()'s plain names for the chat picker). */
    fun listModelsDetailed(modelsPath: String = "/api/tags"): List<ModelInfo> {
        val builder = HttpRequest.newBuilder()
            .uri(endpoint(modelsPath, "models"))
            .timeout(Duration.ofSeconds(10))
            .GET()
        authorize(builder, "models")
        val resp = sendText(builder.build(), "models")
        if (resp.statusCode() !in 200..299) throw OllamaException(OllamaClientErrors.http("models", resp.statusCode()))
        return runCatching {
            json.decodeFromString(DetailedTagsResponse.serializer(), resp.body())
                .models.filter { it.name.isNotEmpty() }.map { ModelInfo(it.name, it.size) }
        }.getOrElse {
            throw OllamaException(OllamaClientErrors.invalidResponse("models"))
        }
    }

    /** Models currently loaded in memory (Ollama's /api/ps, direct or via backend), with VRAM usage. */
    fun listRunningModels(psPath: String = "/api/ps"): List<RunningModel> {
        val builder = HttpRequest.newBuilder()
            .uri(endpoint(psPath, "running models"))
            .timeout(Duration.ofSeconds(10))
            .GET()
        authorize(builder, "running models")
        val resp = sendText(builder.build(), "running models")
        if (resp.statusCode() !in 200..299) throw OllamaException(OllamaClientErrors.http("running models", resp.statusCode()))
        return runCatching {
            json.decodeFromString(RunningModelsResponse.serializer(), resp.body())
                .models.filter { it.name.isNotEmpty() }.map { RunningModel(it.name, it.size_vram, it.expires_at) }
        }.getOrElse {
            throw OllamaException(OllamaClientErrors.invalidResponse("running models"))
        }
    }

    /**
     * Pulls (downloads) a model, streaming Ollama's NDJSON progress lines back
     * via [onProgress] (status text, bytes completed, bytes total). Can take
     * minutes for a large model.
     */
    fun pullModel(model: String, pullPath: String = "/api/pull", onProgress: (String, Long, Long) -> Unit) {
        val payload = json.encodeToString(PullRequest.serializer(), PullRequest(model))
        val builder = HttpRequest.newBuilder()
            .uri(endpoint(pullPath, "pull"))
            .timeout(Duration.ofHours(2))
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(payload))
        authorize(builder, "pull")
        val resp = sendLines(builder.build(), "pull")
        if (resp.statusCode() !in 200..299) throw OllamaException(OllamaClientErrors.http("pull", resp.statusCode()))
        // Same contract as Kaliv's pullModel (1.58.39) and chatStream above:
        // stream end is NOT success. Completion requires BOTH the final
        // status=success line AND the model appearing in the installed list.
        var sawSuccess = false
        resp.body().forEach { line ->
            if (line.isBlank()) return@forEach
            val p = runCatching {
                json.decodeFromString(PullProgressLine.serializer(), line)
            }.getOrElse {
                throw OllamaException(OllamaClientErrors.invalidResponse("pull stream"))
            }
            if (p.error.isNotEmpty()) throw OllamaException(OllamaClientErrors.remote("pull"))
            if (p.status == "success") sawSuccess = true
            onProgress(p.status, p.completed, p.total)
        }
        if (!sawSuccess) {
            throw OllamaException(
                "pull stream ended without Ollama status=success — the download is not complete"
            )
        }
        val modelsPath = if (pullPath.startsWith("/api/v1/")) "/api/v1/models" else "/api/tags"
        val installed = try {
            listModels(modelsPath)
        } catch (_: Exception) {
            throw OllamaException(
                "pull reported success, but installed-model verification failed"
            )
        }
        val latestName = if (model.contains(':')) model else "$model:latest"
        if (model !in installed && latestName !in installed) {
            throw OllamaException(
                "pull reported success, but $model is not present in the installed model list"
            )
        }
    }

    /** Deletes an installed model. Irreversible on the Ollama/rig side. */
    fun deleteModel(model: String, deletePath: String = "/api/delete") {
        val payload = json.encodeToString(PullRequest.serializer(), PullRequest(model))
        val builder = HttpRequest.newBuilder()
            .uri(endpoint(deletePath, "delete"))
            .timeout(Duration.ofSeconds(15))
            .header("Content-Type", "application/json")
            .method("DELETE", HttpRequest.BodyPublishers.ofString(payload))
        authorize(builder, "delete")
        val resp = sendText(builder.build(), "delete")
        if (resp.statusCode() !in 200..299) throw OllamaException(OllamaClientErrors.http("delete", resp.statusCode()))
    }
}
