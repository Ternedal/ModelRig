package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

@Serializable
data class Agent3TaskEvidenceBinding(
    @SerialName("pilot_report_sha256") val pilotReportSha256: String = "",
    @SerialName("pilot_candidate_git_sha") val pilotCandidateGitSha: String = "",
    @SerialName("rig_validation_report_sha256") val rigValidationReportSha256: String = "",
)

@Serializable
data class Agent3TaskBlocker(
    @SerialName("capability_id") val capabilityId: String = "",
    val state: String = "",
    val reason: String = "",
)

@Serializable
data class Agent3TaskCapabilityReceipt(
    val schema: String = "",
    @SerialName("graph_sha256") val graphSha256: String = "",
    @SerialName("plan_sha256") val planSha256: String = "",
    val route: String = "",
    val allowed: Boolean = false,
    val blockers: List<Agent3TaskBlocker> = emptyList(),
    @SerialName("production_activation") val productionActivation: Boolean = true,
)

@Serializable
data class Agent3ReadonlyTaskStep(
    val id: String? = null,
    val tool: String = "",
    val args: JsonObject = JsonObject(emptyMap()),
    val risk: String = "",
    val sensitivity: String = "",
    val egress: String = "",
    val idempotent: Boolean = false,
    val summary: String = "",
    val state: String? = null,
    val error: String? = null,
)

@Serializable
data class Agent3ReadonlyTaskRoute(
    val kind: String = "",
    @SerialName("uses_cloud") val usesCloud: Boolean = true,
    @SerialName("uses_rig") val usesRig: Boolean = false,
    @SerialName("uses_tools") val usesTools: Boolean = false,
    @SerialName("uses_rag") val usesRag: Boolean = true,
)

@Serializable
data class Agent3ReadonlyTaskPreview(
    @SerialName("task_surface") val taskSurface: String = "",
    @SerialName("selected_surface") val selectedSurface: String = "",
    @SerialName("fallback_surface") val fallbackSurface: String = "",
    val reason: String = "",
    @SerialName("production_activation") val productionActivation: Boolean = true,
    @SerialName("normal_chat_route_unchanged") val normalChatRouteUnchanged: Boolean = false,
    val route: Agent3ReadonlyTaskRoute = Agent3ReadonlyTaskRoute(),
    val rationale: String = "",
    val plan: List<Agent3ReadonlyTaskStep> = emptyList(),
    @SerialName("plan_id") val planId: String? = null,
    @SerialName("expires_in_seconds") val expiresInSeconds: Int? = null,
    val executed: Boolean = true,
    @SerialName("readiness_binding") val evidence: Agent3TaskEvidenceBinding = Agent3TaskEvidenceBinding(),
    @SerialName("capability_receipt") val capabilityReceipt: Agent3TaskCapabilityReceipt? = null,
) {
    val canStart: Boolean
        get() = planId != null && plan.isNotEmpty() && capabilityReceipt?.allowed != false
}

@Serializable
data class Agent3ReadonlyTaskRunRoute(val kind: String = "")

@Serializable
data class Agent3ReadonlyTaskRun(
    val id: String = "",
    val state: String = "",
    val route: Agent3ReadonlyTaskRunRoute = Agent3ReadonlyTaskRunRoute(),
    @SerialName("current_step") val currentStep: Int = 0,
    val steps: List<Agent3ReadonlyTaskStep> = emptyList(),
    val answer: String? = null,
    val error: String? = null,
)

@Serializable
data class Agent3ReadonlyTaskEvent(
    val ts: Double = 0.0,
    val kind: String = "",
    val payload: JsonElement? = null,
)

@Serializable
data class Agent3ReadonlyTaskSnapshot(
    @SerialName("task_surface") val taskSurface: String = "",
    @SerialName("selected_surface") val selectedSurface: String = "",
    @SerialName("fallback_surface") val fallbackSurface: String = "",
    val reason: String = "",
    val run: Agent3ReadonlyTaskRun = Agent3ReadonlyTaskRun(),
    val events: List<Agent3ReadonlyTaskEvent> = emptyList(),
    @SerialName("readiness_binding") val evidence: Agent3TaskEvidenceBinding = Agent3TaskEvidenceBinding(),
    @SerialName("capability_receipt") val capabilityReceipt: Agent3TaskCapabilityReceipt? = null,
    val terminal: Boolean = false,
    @SerialName("production_activation") val productionActivation: Boolean = true,
    @SerialName("normal_chat_route_unchanged") val normalChatRouteUnchanged: Boolean = false,
)

/**
 * Normal desktop transport for the readiness-bound read-only task surface.
 *
 * It intentionally exposes only preview, single-use start, task-scoped status
 * and task-scoped Stop. Generic Agent 3 runs, confirmation, retry, resume,
 * memory, cloud, RAG and client-authored plans are absent from the API.
 */
class Agent3ReadonlyTaskClient(baseUrl: String, private val bearer: String) {
    private val base = baseUrl.trimEnd('/')
    private val json = Json { ignoreUnknownKeys = true }
    private val http: HttpClient = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(10))
        .build()

    fun preview(message: String, conversationId: String? = null): Agent3ReadonlyTaskPreview {
        if (message.isBlank()) throw Agent3Exception("Read-only task message is empty")
        val escapedMessage = json.encodeToString(String.serializer(), message)
        val body = buildString {
            append("{\"message\":")
            append(escapedMessage)
            conversationId?.takeIf { it.isNotBlank() }?.let {
                append(",\"conversation_id\":")
                append(json.encodeToString(String.serializer(), it))
            }
            append('}')
        }
        return parsePreview(send("POST", PLAN_PATH, body, Duration.ofMinutes(5)))
    }

    fun start(planId: String): Agent3ReadonlyTaskSnapshot {
        requireOpaqueId(planId, "plan id")
        return parseSnapshot(
            send("POST", "$PLAN_PREFIX/$planId/start", "{}", Duration.ofMinutes(5)),
            expectedRunId = null,
        )
    }

    fun status(runId: String): Agent3ReadonlyTaskSnapshot {
        requireOpaqueId(runId, "run id")
        return parseSnapshot(
            send("GET", "$RUN_PREFIX/$runId", null, Duration.ofSeconds(20)),
            expectedRunId = runId,
        )
    }

    fun cancel(runId: String): Agent3ReadonlyTaskSnapshot {
        requireOpaqueId(runId, "run id")
        return parseSnapshot(
            send("POST", "$RUN_PREFIX/$runId/cancel", "{}", Duration.ofSeconds(20)),
            expectedRunId = runId,
        )
    }

    internal fun parsePreview(body: String): Agent3ReadonlyTaskPreview {
        val root = parseObject(body, "preview")
        if (root["executed"]?.jsonPrimitive?.booleanOrNull != false) {
            throw Agent3Exception("Invalid read-only task preview: preview must not execute")
        }
        val value = decode<Agent3ReadonlyTaskPreview>(body, "preview")
        validateEnvelope(
            taskSurface = value.taskSurface,
            selectedSurface = value.selectedSurface,
            fallbackSurface = value.fallbackSurface,
            reason = value.reason,
            productionActivation = value.productionActivation,
            normalChatRouteUnchanged = value.normalChatRouteUnchanged,
        )
        if (
            value.route.kind != ROUTE ||
            value.route.usesCloud ||
            !value.route.usesRig ||
            !value.route.usesTools ||
            value.route.usesRag
        ) {
            throw Agent3Exception("Invalid read-only task preview: route is not local read-only")
        }
        validateSteps(value.plan)
        if (value.plan.isNotEmpty() && (value.planId == null || !OPAQUE_ID.matches(value.planId))) {
            throw Agent3Exception("Invalid read-only task preview: executable plan lacks a single-use id")
        }
        if (value.plan.isEmpty() && value.planId != null) {
            throw Agent3Exception("Invalid read-only task preview: empty plan must not have a start token")
        }
        validateEvidence(value.evidence)
        value.capabilityReceipt?.let(::validateReceipt)
        return value
    }

    internal fun parseSnapshot(body: String, expectedRunId: String? = null): Agent3ReadonlyTaskSnapshot {
        val root = parseObject(body, "snapshot")
        val terminal = root["terminal"]?.jsonPrimitive?.booleanOrNull
            ?: throw Agent3Exception("Invalid read-only task snapshot: terminal is missing")
        val value = decode<Agent3ReadonlyTaskSnapshot>(body, "snapshot")
        validateEnvelope(
            taskSurface = value.taskSurface,
            selectedSurface = value.selectedSurface,
            fallbackSurface = value.fallbackSurface,
            reason = value.reason,
            productionActivation = value.productionActivation,
            normalChatRouteUnchanged = value.normalChatRouteUnchanged,
        )
        if (value.run.id.isBlank() || value.run.state !in RUN_STATES) {
            throw Agent3Exception("Invalid read-only task snapshot: run identity or state is invalid")
        }
        if (expectedRunId != null && value.run.id != expectedRunId) {
            throw Agent3Exception("Invalid read-only task snapshot: server returned another run id")
        }
        if (value.run.state == "waiting_confirmation") {
            throw Agent3Exception("Invalid read-only task snapshot: confirmation is not allowed")
        }
        if (value.run.route.kind != ROUTE) {
            throw Agent3Exception("Invalid read-only task snapshot: route changed")
        }
        validateSteps(value.run.steps)
        if (terminal != (value.run.state in TERMINAL_STATES)) {
            throw Agent3Exception("Invalid read-only task snapshot: terminal disagrees with run state")
        }
        validateEvidence(value.evidence)
        value.capabilityReceipt?.let(::validateReceipt)
        return value
    }

    private inline fun <reified T> decode(body: String, label: String): T = try {
        json.decodeFromString<T>(body)
    } catch (e: Exception) {
        throw Agent3Exception("Agent 3.0 read-only task $label returned invalid JSON: ${e.message}")
    }

    private fun parseObject(body: String, label: String): JsonObject = try {
        json.parseToJsonElement(body).jsonObject
    } catch (e: Exception) {
        throw Agent3Exception("Agent 3.0 read-only task $label returned invalid JSON: ${e.message}")
    }

    private fun validateEnvelope(
        taskSurface: String,
        selectedSurface: String,
        fallbackSurface: String,
        reason: String,
        productionActivation: Boolean,
        normalChatRouteUnchanged: Boolean,
    ) {
        if (
            taskSurface != SURFACE ||
            selectedSurface != SURFACE ||
            fallbackSurface != FALLBACK ||
            reason != SELECTED_REASON
        ) {
            throw Agent3Exception("Invalid read-only task contract: surface or fallback changed")
        }
        if (productionActivation || !normalChatRouteUnchanged) {
            throw Agent3Exception("Invalid read-only task contract: normal chat must remain unchanged")
        }
    }

    private fun validateSteps(steps: List<Agent3ReadonlyTaskStep>) {
        if (steps.any { it.tool.isBlank() || it.risk != "read" || it.egress != "local" || !it.idempotent }) {
            throw Agent3Exception("Invalid read-only task contract: only local idempotent reads are allowed")
        }
    }

    private fun validateEvidence(value: Agent3TaskEvidenceBinding) {
        if (
            !SHA256.matches(value.pilotReportSha256) ||
            !GIT_SHA.matches(value.pilotCandidateGitSha) ||
            !SHA256.matches(value.rigValidationReportSha256)
        ) {
            throw Agent3Exception("Invalid read-only task contract: evidence binding is missing")
        }
    }

    private fun validateReceipt(value: Agent3TaskCapabilityReceipt) {
        if (
            value.schema != RECEIPT_SCHEMA ||
            !SHA256.matches(value.graphSha256) ||
            !SHA256.matches(value.planSha256) ||
            value.route != ROUTE ||
            value.productionActivation ||
            (value.allowed && value.blockers.isNotEmpty()) ||
            value.blockers.any { it.capabilityId.isBlank() || it.state.isBlank() || it.reason.isBlank() }
        ) {
            throw Agent3Exception("Invalid read-only task capability receipt")
        }
    }

    private fun send(method: String, path: String, body: String?, timeout: Duration): String {
        val builder = HttpRequest.newBuilder(URI.create(base + path))
            .header("Authorization", "Bearer $bearer")
            .timeout(timeout)
        if (body == null) {
            builder.GET()
        } else {
            builder.header("Content-Type", "application/json")
                .method(method, HttpRequest.BodyPublishers.ofString(body))
        }
        val response = http.send(builder.build(), HttpResponse.BodyHandlers.ofString())
        if (response.statusCode() !in 200..299) {
            throw Agent3Exception(
                "Agent 3.0 read-only task failed (${response.statusCode()}): ${response.body().take(500)}",
            )
        }
        return response.body()
    }

    private fun requireOpaqueId(value: String, label: String) {
        if (!OPAQUE_ID.matches(value)) throw Agent3Exception("Invalid read-only task $label")
    }

    companion object {
        private const val PLAN_PATH = "/api/v1/experimental/agent3/task/plan"
        private const val PLAN_PREFIX = "/api/v1/experimental/agent3/task/plans"
        private const val RUN_PREFIX = "/api/v1/experimental/agent3/task/runs"
        private const val SURFACE = "agent3_readonly"
        private const val FALLBACK = "agent2"
        private const val SELECTED_REASON = "agent3_readonly_selected"
        private const val ROUTE = "rig_tools_local"
        private const val RECEIPT_SCHEMA = "kaliv-agent3-capability-receipt/v1"
        private val OPAQUE_ID = Regex("^[A-Za-z0-9_-]{1,200}$")
        private val SHA256 = Regex("^[0-9a-f]{64}$")
        private val GIT_SHA = Regex("^[0-9a-f]{40}$")
        private val RUN_STATES = setOf(
            "running",
            "blocked",
            "waiting_confirmation",
            "completed",
            "failed",
            "cancelled",
        )
        private val TERMINAL_STATES = setOf("blocked", "completed", "failed", "cancelled")
    }
}
