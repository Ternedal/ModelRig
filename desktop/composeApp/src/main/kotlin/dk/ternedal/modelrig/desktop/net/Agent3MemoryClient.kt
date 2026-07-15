package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.net.URI
import java.net.URLEncoder
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.nio.charset.StandardCharsets
import java.time.Duration

@Serializable
data class Agent3Memory(
    val id: String = "",
    val subject: String = "",
    val predicate: String = "",
    val value: String = "",
    val kind: String = "fact",
    val sensitivity: String = "private",
    @SerialName("source_type") val sourceType: String = "",
    @SerialName("source_ref") val sourceRef: String? = null,
    val confidence: Double = 1.0,
    @SerialName("review_status") val reviewStatus: String = "",
    @SerialName("lifecycle_status") val lifecycleStatus: String = "",
    @SerialName("supersedes_id") val supersedesId: String? = null,
    @SerialName("created_at") val createdAt: Double = 0.0,
    @SerialName("updated_at") val updatedAt: Double = 0.0,
    @SerialName("expires_at") val expiresAt: Double? = null,
    @SerialName("deleted_at") val deletedAt: Double? = null,
    @SerialName("schema_version") val schemaVersion: Int = 1,
)

@Serializable
private data class CreateMemoryRequest(
    val subject: String,
    val predicate: String,
    val value: String,
    val kind: String,
    val sensitivity: String,
    val confidence: Double = 1.0,
)

@Serializable
private data class CorrectMemoryRequest(
    val value: String,
    val sensitivity: String,
    val confidence: Double = 1.0,
)

@Serializable
private data class MemoryEnvelope(val memory: Agent3Memory = Agent3Memory())

@Serializable
private data class MemoriesEnvelope(val memories: List<Agent3Memory> = emptyList())

/** Developer-only transport for the explicit Memory 3.0 management screen. */
class Agent3MemoryClient(baseUrl: String, private val bearer: String) {
    private val base = baseUrl.trimEnd('/')
    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = false }
    private val http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10)).build()

    fun list(subject: String? = null): List<Agent3Memory> {
        val suffix = subject?.trim()?.takeIf { it.isNotEmpty() }?.let { "?subject=${query(it)}" }.orEmpty()
        return decode<MemoriesEnvelope>(get("/api/v1/experimental/agent3/memory$suffix")).memories
    }

    fun search(query: String): List<Agent3Memory> =
        decode<MemoriesEnvelope>(get("/api/v1/experimental/agent3/memory/search?q=${query(query.trim())}")).memories

    fun history(memoryId: String): List<Agent3Memory> =
        decode<MemoriesEnvelope>(get("/api/v1/experimental/agent3/memory/${path(memoryId)}/history")).memories

    fun create(subject: String, predicate: String, value: String, kind: String, sensitivity: String): Agent3Memory =
        decode<MemoryEnvelope>(
            post(
                "/api/v1/experimental/agent3/memory",
                json.encodeToString(CreateMemoryRequest(subject, predicate, value, kind, sensitivity)),
            )
        ).memory

    fun confirm(memoryId: String): Agent3Memory =
        decode<MemoryEnvelope>(post("/api/v1/experimental/agent3/memory/${path(memoryId)}/confirm", "{}")).memory

    fun reject(memoryId: String): Agent3Memory =
        decode<MemoryEnvelope>(post("/api/v1/experimental/agent3/memory/${path(memoryId)}/reject", "{}")).memory

    fun correct(memoryId: String, value: String, sensitivity: String): Agent3Memory =
        decode<MemoryEnvelope>(
            post(
                "/api/v1/experimental/agent3/memory/${path(memoryId)}/correct",
                json.encodeToString(CorrectMemoryRequest(value, sensitivity)),
            )
        ).memory

    fun delete(memoryId: String): Agent3Memory =
        decode<MemoryEnvelope>(deleteRequest("/api/v1/experimental/agent3/memory/${path(memoryId)}")).memory

    private fun request(path: String): HttpRequest.Builder = HttpRequest.newBuilder(URI.create(base + path))
        .header("Content-Type", "application/json")
        .header("Authorization", "Bearer $bearer")
        .timeout(Duration.ofSeconds(45))

    private fun get(path: String): String = send(request(path).GET().build())

    private fun post(path: String, body: String): String =
        send(request(path).POST(HttpRequest.BodyPublishers.ofString(body)).build())

    private fun deleteRequest(path: String): String = send(request(path).DELETE().build())

    private fun send(request: HttpRequest): String {
        val response = http.send(request, HttpResponse.BodyHandlers.ofString())
        if (response.statusCode() !in 200..299) {
            throw Agent3Exception("Memory 3.0 failed (${response.statusCode()}): ${response.body().take(500)}")
        }
        return response.body()
    }

    private fun query(value: String): String = URLEncoder.encode(value, StandardCharsets.UTF_8)

    private fun path(value: String): String = query(value).replace("+", "%20")

    private inline fun <reified T> decode(body: String): T = try {
        json.decodeFromString(body)
    } catch (e: Exception) {
        throw Agent3Exception("Memory 3.0 returned invalid JSON: ${e.message}")
    }
}
