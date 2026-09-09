package dk.ternedal.modelrig.desktop.net

import java.nio.charset.StandardCharsets
import java.net.URLEncoder
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
data class Agent3MemoryReceipt(
    val requested: Boolean = false,
    @SerialName("sent_to_model") val sentToModel: Boolean = false,
    val target: String? = null,
    @SerialName("included_ids") val includedIds: List<String> = emptyList(),
    @SerialName("excluded_ids") val excludedIds: List<String> = emptyList(),
    @SerialName("character_count") val characterCount: Int = 0,
    val sha256: String? = null,
)

@Serializable
data class Agent3CapabilityBlocker(
    @SerialName("capability_id") val capabilityId: String = "",
    val state: String = "",
    val reason: String = "",
)

@Serializable
data class Agent3CapabilityReceipt(
    val schema: String = "",
    @SerialName("graph_sha256") val graphSha256: String = "",
    @SerialName("plan_sha256") val planSha256: String = "",
    val route: String = "",
    val allowed: Boolean = false,
    @SerialName("required_capability_ids") val requiredCapabilityIds: List<String> = emptyList(),
    val blockers: List<Agent3CapabilityBlocker> = emptyList(),
    @SerialName("production_activation") val productionActivation: Boolean = false,
)

@Serializable
data class Agent3ReadReview(
    val enabled: Boolean = false,
    val waiting: Boolean = false,
    @SerialName("window_start") val windowStart: Int? = null,
    @SerialName("window_end") val windowEnd: Int? = null,
    @SerialName("removable_step_ids") val removableStepIds: List<String> = emptyList(),
    @SerialName("completed_step_id") val completedStepId: String? = null,
    @SerialName("completed_tool") val completedTool: String? = null,
    @SerialName("updated_at") val updatedAt: Double? = null,
)

@Serializable
data class Agent3TerminationPlan(
    val state: String = "",
    @SerialName("can_request") val canRequest: Boolean = false,
    @SerialName("request_scope") val requestScope: String = "",
    val effect: String = "",
    val reason: String = "",
)

@Serializable
data class Agent3TerminationModelStream(
    val state: String = "",
    val active: Boolean = false,
    @SerialName("can_request") val canRequest: Boolean = false,
    @SerialName("handle_present") val handlePresent: Boolean = false,
    val reason: String = "",
)

@Serializable
data class Agent3TerminationActiveTool(
    @SerialName("step_id") val stepId: String = "",
    val tool: String = "",
    val state: String = "",
    val semantics: String? = null,
    @SerialName("handle_present") val handlePresent: Boolean = false,
    @SerialName("can_request") val canRequest: Boolean = false,
    @SerialName("request_state") val requestState: String = "",
    val reason: String = "",
)

@Serializable
data class Agent3TerminationReceipt(
    val schema: String = "",
    val plan: Agent3TerminationPlan = Agent3TerminationPlan(),
    @SerialName("model_stream") val modelStream: Agent3TerminationModelStream = Agent3TerminationModelStream(),
    @SerialName("active_tool") val activeTool: Agent3TerminationActiveTool? = null,
    @SerialName("production_activation") val productionActivation: Boolean = true,
)

@Serializable
data class Agent3PlanPreview(
    @SerialName("plan_id") val planId: String? = null,
    @SerialName("expires_in_seconds") val expiresInSeconds: Int? = null,
    val route: Agent3Route = Agent3Route(),
    val rationale: String = "",
    val plan: List<Agent3Step> = emptyList(),
    val executed: Boolean = false,
    @SerialName("memory_context") val memoryContext: Agent3MemoryReceipt = Agent3MemoryReceipt(),
    @SerialName("capability_receipt") val capabilityReceipt: Agent3CapabilityReceipt? = null,
    @SerialName("review_reads") val reviewReads: Boolean = false,
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
    val termination: Agent3TerminationReceipt? = null,
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
    @SerialName("review_reads") val reviewReads: Boolean = false,
    @SerialName("use_memory") val useMemory: Boolean = false,
    @SerialName("memory_subjects") val memorySubjects: List<String> = emptyList(),
    @SerialName("memory_max_chars") val memoryMaxChars: Int = 4_000,
    @SerialName("memory_max_records") val memoryMaxRecords: Int = 25,
)

@Serializable
private data class ConfirmRequest(
    @SerialName("step_id") val stepId: String,
    val decision: String,
    val digest: String,
)

@Serializable
private data class RetryRequest(
    @SerialName("cloud_ready") val cloudReady: Boolean = false,
)

@Serializable
data class Agent3RunEnvelope(
    val run: Agent3Run = Agent3Run(),
    @SerialName("review_reads") val reviewReads: Boolean = false,
    @SerialName("read_review") val readReview: Agent3ReadReview = Agent3ReadReview(),
    @SerialName("capability_receipt") val capabilityReceipt: Agent3CapabilityReceipt? = null,
    val termination: Agent3TerminationReceipt? = null,
)

@Serializable
private data class RunsEnvelope(val runs: List<Agent3Run> = emptyList())

@Serializable
private data class EventsEnvelope(val events: List<Agent3Event> = emptyList())

/** Experimental Agent 3.0 transport. Used only by the explicit developer UI. */
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
        reviewReads: Boolean = false,
        useMemory: Boolean = false,
        memorySubjects: List<String> = emptyList(),
        memoryMaxChars: Int = 4_000,
        memoryMaxRecords: Int = 25,
    ): Agent3PlanPreview {
        val preview = decode<Agent3PlanPreview>(
            post(
                "/api/v1/experimental/agent3/plan",
                json.encodeToString(
                    PlanRequest(
                        message = message,
                        mode = mode,
                        rag = rag,
                        allowRagCloud = allowRagCloud,
                        allowPrivateCloud = allowPrivateCloud,
                        cloudReady = cloudReady,
                        conversationId = conversationId,
                        plannerModel = plannerModel,
                        proactive = proactive,
                        reviewReads = reviewReads,
                        useMemory = useMemory,
                        memorySubjects = memorySubjects,
                        memoryMaxChars = memoryMaxChars,
                        memoryMaxRecords = memoryMaxRecords,
                    )
                ),
            )
        )
        validateCapabilityReceipt(preview.capabilityReceipt)
        return preview
    }

    fun startPlanEnvelope(planId: String): Agent3RunEnvelope =
        decodeRunEnvelope(
            post("/api/v1/experimental/agent3/plans/${seg(planId)}/start", "{}"),
        )

    fun startPlan(planId: String): Agent3Run = startPlanEnvelope(planId).run

    fun getRun(runId: String): Agent3Run =
        decodeRunEnvelope(
            get("/api/v1/experimental/agent3/runs/${seg(runId)}"),
            expectedRunId = runId,
        ).run

    fun listRuns(): List<Agent3Run> =
        decode<RunsEnvelope>(get("/api/v1/experimental/agent3/runs")).runs

    fun events(runId: String): List<Agent3Event> =
        decode<EventsEnvelope>(get("/api/v1/experimental/agent3/runs/${seg(runId)}/events")).events

    fun retry(runId: String, cloudReady: Boolean = false): Agent3Run =
        decodeRunEnvelope(
            post(
                "/api/v1/experimental/agent3/runs/${seg(runId)}/retry",
                json.encodeToString(RetryRequest(cloudReady)),
            ),
            expectedRunId = runId,
        ).run

    fun confirm(runId: String, stepId: String, digest: String, approve: Boolean): Agent3Run {
        val body = json.encodeToString(
            ConfirmRequest(stepId, if (approve) "approve" else "deny", digest)
        )
        return decodeRunEnvelope(
            post("/api/v1/experimental/agent3/runs/${seg(runId)}/confirm", body),
            expectedRunId = runId,
        ).run
    }

    fun resume(runId: String): Agent3Run =
        decodeRunEnvelope(
            post("/api/v1/experimental/agent3/runs/${seg(runId)}/resume", "{}"),
            expectedRunId = runId,
        ).run

    fun cancel(runId: String): Agent3Run =
        decodeRunEnvelope(
            post("/api/v1/experimental/agent3/runs/${seg(runId)}/cancel", "{}"),
            expectedRunId = runId,
        ).run

    private fun decodeRunEnvelope(
        body: String,
        expectedRunId: String? = null,
    ): Agent3RunEnvelope {
        val envelope = decode<Agent3RunEnvelope>(body)
        validateCapabilityReceipt(envelope.capabilityReceipt)
        val termination = validateTerminationReceipt(envelope.termination, envelope.run)
        if (expectedRunId != null && envelope.run.id != expectedRunId) {
            throw Agent3Exception("Invalid Agent 3.0 run envelope: server returned another run id")
        }
        return envelope.copy(
            run = envelope.run.copy(termination = termination),
            termination = termination,
        )
    }

    internal fun validateTerminationReceipt(
        receipt: Agent3TerminationReceipt?,
        run: Agent3Run,
    ): Agent3TerminationReceipt {
        val value = receipt
            ?: throw Agent3Exception("Invalid termination receipt: missing for run envelope")
        if (value.schema != "kaliv-agent3-termination/v1") {
            throw Agent3Exception("Unsupported Agent 3.0 termination receipt schema: ${value.schema}")
        }
        if (value.productionActivation) {
            throw Agent3Exception("Invalid termination receipt: it must never activate production")
        }

        val runStates = setOf(
            "running",
            "waiting_confirmation",
            "blocked",
            "completed",
            "failed",
            "cancelled",
        )
        val terminalStates = setOf("blocked", "completed", "failed", "cancelled")
        val stepStates = setOf(
            "pending",
            "completed_after_cancel",
            "waiting_confirmation",
            "approved",
            "executing",
            "succeeded",
            "denied",
            "blocked",
            "failed",
        )
        val requestStates = setOf("available", "pending", "terminal", "unavailable", "not_active")
        val semantics = setOf<String?>(null, "none", "cooperative", "runtime")

        if (run.id.isBlank() || run.state !in runStates || run.currentStep < 0 || run.currentStep > run.steps.size) {
            throw Agent3Exception("Invalid termination receipt: run identity/state/current step is invalid")
        }
        if (run.steps.any { it.state == null || it.state !in stepStates }) {
            throw Agent3Exception("Invalid termination receipt: run step state is outside Agent 3")
        }

        val terminal = run.state in terminalStates
        val expectedPlanState = if (terminal) "terminal" else "available"
        val current = run.steps.getOrNull(run.currentStep)
        val executing = current?.state == "executing"
        val expectedEffect = if (executing) {
            "prevent_future_steps_active_tool_continues"
        } else {
            "prevent_future_steps"
        }
        val plan = value.plan
        if (
            plan.state != expectedPlanState ||
            plan.canRequest != !terminal ||
            plan.requestScope != "plan" ||
            plan.effect != expectedEffect ||
            plan.reason.isBlank()
        ) {
            throw Agent3Exception("Invalid termination receipt: plan scope disagrees with run")
        }

        val stream = value.modelStream
        if (
            stream.state != "not_active" ||
            stream.active ||
            stream.canRequest ||
            stream.handlePresent ||
            stream.reason.isBlank()
        ) {
            throw Agent3Exception("Invalid termination receipt: model stream disagrees with Agent 3 run")
        }

        val active = value.activeTool
        if ((active == null) != (current == null)) {
            throw Agent3Exception("Invalid termination receipt: active tool disagrees with current step")
        }
        if (active == null) return value

        if (
            active.stepId.isBlank() ||
            active.tool.isBlank() ||
            active.state !in stepStates ||
            active.requestState !in requestStates ||
            active.reason.isBlank() ||
            active.semantics !in semantics ||
            active.stepId != current?.id ||
            active.tool != current?.tool ||
            active.state != current?.state ||
            (active.canRequest && !active.handlePresent) ||
            (active.canRequest && active.semantics !in setOf("cooperative", "runtime"))
        ) {
            throw Agent3Exception("Invalid termination receipt: active tool disagrees with current step")
        }
        if (active.state == "executing" && active.requestState == "terminal") {
            throw Agent3Exception("Invalid termination receipt: executing tool cannot be terminal")
        }
        if (active.state == "completed_after_cancel" && active.requestState != "terminal") {
            throw Agent3Exception("Invalid termination receipt: late completion is not terminal")
        }
        if (active.requestState == "available" && !active.canRequest) {
            throw Agent3Exception("Invalid termination receipt: available tool control cannot be requested")
        }
        return value
    }

    private fun validateCapabilityReceipt(receipt: Agent3CapabilityReceipt?) {
        if (receipt == null) return
        if (receipt.schema != "kaliv-agent3-capability-receipt/v1") {
            throw Agent3Exception("Unsupported Agent 3.0 capability receipt schema: ${receipt.schema}")
        }
        if (receipt.productionActivation) {
            throw Agent3Exception("Invalid capability receipt: it must never activate production")
        }
        val digest = Regex("^[0-9a-f]{64}$")
        if (!digest.matches(receipt.graphSha256) || !digest.matches(receipt.planSha256)) {
            throw Agent3Exception("Invalid capability receipt: malformed SHA-256 binding")
        }
        if (receipt.route.isBlank()) {
            throw Agent3Exception("Invalid capability receipt: route is missing")
        }
        if (receipt.requiredCapabilityIds.any { it.isBlank() } ||
            receipt.requiredCapabilityIds.size != receipt.requiredCapabilityIds.distinct().size
        ) {
            throw Agent3Exception("Invalid capability receipt: required capability ids are invalid")
        }
        if (receipt.blockers.any { it.capabilityId.isBlank() || it.state.isBlank() || it.reason.isBlank() }) {
            throw Agent3Exception("Invalid capability receipt: blocker is incomplete")
        }
        if (receipt.allowed && receipt.blockers.isNotEmpty()) {
            throw Agent3Exception("Invalid capability receipt: allowed plan contains blockers")
        }
    }

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

    /**
     * Encode een sti-komponent. Se Agent3PathSegmentTest paa Android-siden:
     * maalt 27/07-2026 gav runId="../../healthz" stien
     * /api/v1/experimental/healthz/confirm, fordi traversalen oploeses foer
     * requesten sendes. Desktop havde samme eksponering; den blev overset da
     * Android blev rettet.
     */
    private fun seg(value: String): String =
        URLEncoder.encode(value, StandardCharsets.UTF_8).replace("+", "%20")

}
