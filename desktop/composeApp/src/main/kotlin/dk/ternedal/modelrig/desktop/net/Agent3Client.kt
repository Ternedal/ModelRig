package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

class Agent3Exception(message: String) : RuntimeException(message)

@Serializable
data class Agent3Route(
    val kind: String = "",
    val reason: String = "",
    @SerialName("uses_cloud") val usesCloud: Boolean = false,
    @SerialName("uses_rig") val usesRig: Boolean = false,
    @SerialName("uses_tools") val usesTools: Boolean = false,
    @SerialName("uses_rag") val usesRag: Boolean = false,
)

@Serializable
data class Agent3Step(
    val id: String? = null,
    val tool: String = "",
    val args: JsonObject = buildJsonObject {},
    val risk: String = "",
    val sensitivity: String = "",
    val egress: String = "",
    val summary: String = "",
    val state: String? = null,
    @SerialName("confirmation_digest") val confirmationDigest: String? = null,
    @SerialName("confirmation_expires_at") val confirmationExpiresAt: Double? = null,
    val error: String? = null,
)

@Serializable
data class Agent3PlanPreview(
    @SerialName("plan_id") val planId: String? = null,
    @SerialName("expires_in_seconds") val expiresInSeconds: Int? = null,
    val route: Agent3Route = Agent3Route(),
    val rationale: String = "",
    val plan: List<Agent3Step> = emptyList(),
    val executed: Boolean = false,
)

@Serializable
data class Agent3Run(
    val id: String = "",
    val state: String = "",
    val route: Agent3Route = Agent3Route(),
    @SerialName("current_step") val currentStep: Int = 0,
    val steps: List<Agent3Step> = emptyList(),
    val answer: String? = null,
    val error: String? = null,
)

@Serializable
data class Agent3Event(
    val ts: Double = 0.0,
    val kind: String = "",
    val payload: JsonElement = JsonNull,
)

@Serializable
private data class PlanRequest(
    val message: String,
    val mode: String = "rig",
    val rag: Boolean = false,
    @SerialName("allow_rag_cloud") val allowRagCloud: Boolean = false,
    @SerialName("allow_private_cloud") val allowPrivateCloud: Boolean = false,
    @SerialName("cloud_ready") val cloudReady: Boolean = false,
    @SerialName("conversation_id") val conversationId: String? = null,
    @SerialName("planner_model") val plannerModel: String? = null,
    val proactive: Boolean = false,
)

@Serializable
private data class ConfirmRequest(
    @SerialName("step_id") val stepId: String,
    val decision: String,
    val digest: String,
)

@Serializable
private data class RunEnvelope(val run: Agent3Run = Agent3Run())

@Serializable
private data class RunsEnvelope(val runs: List<Agent3Run> = emptyList())

@Serializable
private data class EventsEnvelope(val events: List<Agent3Event> = emptyList())

/** Experimental Agent 3.0 transport. Not connected to the desktop UI yet. */
class Agent3Client(baseUrl: String, private val bearer: String) {
    private val base = baseUrl.trimEnd('/')
    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = false }
    private val http: HttpClient = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(10))
        .build()

    fun previewPlan(
        message: String,
        mode: String = "rig",
        rag: Boolean = false,
        allowRagCloud: Boolean = false,
        allowPrivateCloud: Boolean = false,
        cloudReady: Boolean = false,
        conversationId: String? = null,
        plannerModel: String? = null,
        proactive: Boolean = false,
    ): Agent3PlanPreview = decode(
        post(
            "/api/v1/experimental/agent3/plan",
            json.encodeToString(
                PlanRequest(
                    message,
                    mode,
                    rag,
                    allowRagCloud,
                    allowPrivateCloud,
                    cloudReady,
                    conversationId,
                    plannerModel,
                    proactive,
                )
            ),
        )
    )

    fun startPlan(planId: String): Agent3Run =
        decode<RunEnvelope>(post("/api/v1/experimental/agent3/plans/$planId/start", "{}")).run

    fun getRun(runId: String): Agent3Run =
        decode<RunEnvelope>(get("/api/v1/experimental/agent3/runs/$runId")).run

    fun listRuns(): List<Agent3Run> =
        decode<RunsEnvelope>(get("/api/v1/experimental/agent3/runs")).runs

    fun events(runId: String): List<Agent3Event> =
        decode<EventsEnvelope>(get("/api/v1/experimental/agent3/runs/$runId/events")).events

    fun confirm(runId: String, stepId: String, digest: String, approve: Boolean): Agent3Run {
        val body = json.encodeToString(
            ConfirmRequest(stepId, if (approve) "approve" else "deny", digest)
        )
        return decode<RunEnvelope>(post("/api/v1/experimental/agent3/runs/$runId/confirm", body)).run
    }

    fun resume(runId: String): Agent3Run =
        decode<RunEnvelope>(post("/api/v1/experimental/agent3/runs/$runId/resume", "{}")).run

    fun cancel(runId: String): Agent3Run =
        decode<RunEnvelope>(post("/api/v1/experimental/agent3/runs/$runId/cancel", "{}")).run

    private fun builder(path: String): HttpRequest.Builder = HttpRequest.newBuilder(URI.create(base + path))
        .header("Content-Type", "application/json")
        .header("Authorization", "Bearer $bearer")
        .timeout(Duration.ofMinutes(5))

    private fun get(path: String): String = send(builder(path).GET().build())

    private fun post(path: String, body: String): String = send(
        builder(path).POST(HttpRequest.BodyPublishers.ofString(body)).build()
    )

    private fun send(request: HttpRequest): String {
        val response = http.send(request, HttpResponse.BodyHandlers.ofString())
        if (response.statusCode() !in 200..299) {
            throw Agent3Exception("Agent 3.0 failed (${response.statusCode()}): ${response.body().take(500)}")
        }
        return response.body()
    }

    private inline fun <reified T> decode(body: String): T = try {
        json.decodeFromString(body)
    } catch (e: Exception) {
        throw Agent3Exception("Agent 3.0 returned invalid JSON: ${e.message}")
    }
}
