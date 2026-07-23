package dk.ternedal.modelrig.net

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/** Experimental Agent 3.0 API client. Used only by the explicit developer screen. */
class Agent3Client(baseUrl: String, private val token: String) {
    private val base = baseUrl.trimEnd('/')
    private val jsonType = "application/json".toMediaType()
    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        // Plan preview may cold-load the local planner model.
        .readTimeout(5, TimeUnit.MINUTES)
        .build()

    data class Step(
        val id: String?,
        val tool: String,
        val args: String,
        val risk: String,
        val sensitivity: String,
        val egress: String,
        val summary: String,
        val state: String?,
        val confirmationDigest: String?,
        val confirmationExpiresAt: Double?,
        val error: String?,
    )

    data class MemoryReceipt(
        val requested: Boolean,
        val sentToModel: Boolean,
        val target: String?,
        val includedIds: List<String>,
        val excludedIds: List<String>,
        val characterCount: Int,
        val sha256: String?,
    )

    data class CapabilityBlocker(
        val capabilityId: String,
        val state: String,
        val reason: String,
    )

    data class CapabilityReceipt(
        val schema: String,
        val graphSha256: String,
        val planSha256: String,
        val route: String,
        val allowed: Boolean,
        val requiredCapabilityIds: List<String>,
        val blockers: List<CapabilityBlocker>,
        val productionActivation: Boolean,
    )

    data class ReadReview(
        val enabled: Boolean,
        val waiting: Boolean,
        val windowStart: Int?,
        val windowEnd: Int?,
        val removableStepIds: List<String>,
        val completedStepId: String?,
        val completedTool: String?,
        val updatedAt: Double?,
    )

    data class TerminationPlan(
        val state: String,
        val canRequest: Boolean,
        val requestScope: String,
        val effect: String,
        val reason: String,
    )

    data class TerminationModelStream(
        val state: String,
        val active: Boolean,
        val canRequest: Boolean,
        val handlePresent: Boolean,
        val reason: String,
    )

    data class TerminationActiveTool(
        val stepId: String,
        val tool: String,
        val state: String,
        val semantics: String?,
        val handlePresent: Boolean,
        val canRequest: Boolean,
        val requestState: String,
        val reason: String,
    )

    data class TerminationReceipt(
        val schema: String,
        val plan: TerminationPlan,
        val modelStream: TerminationModelStream,
        val activeTool: TerminationActiveTool?,
        val productionActivation: Boolean,
    )

    data class PlanPreview(
        val planId: String?,
        val expiresInSeconds: Int?,
        val routeKind: String,
        val rationale: String,
        val steps: List<Step>,
        val executed: Boolean,
        val memoryContext: MemoryReceipt,
        val capabilityReceipt: CapabilityReceipt?,
        val reviewReads: Boolean,
    )

    data class Run(
        val id: String,
        val state: String,
        val routeKind: String,
        val currentStep: Int,
        val steps: List<Step>,
        val answer: String?,
        val error: String?,
        val termination: TerminationReceipt?,
    )

    data class RunEnvelope(
        val run: Run,
        val reviewReads: Boolean,
        val readReview: ReadReview,
        val capabilityReceipt: CapabilityReceipt?,
    )

    data class Event(
        val timestamp: Double,
        val kind: String,
        val payload: String,
    )

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
        useMemory: Boolean = false,
        memorySubjects: List<String> = emptyList(),
        memoryMaxChars: Int = 4_000,
        memoryMaxRecords: Int = 25,
        reviewReads: Boolean = false,
    ): PlanPreview {
        val payload = JSONObject()
            .put("message", message)
            .put("mode", mode)
            .put("rag", rag)
            .put("allow_rag_cloud", allowRagCloud)
            .put("allow_private_cloud", allowPrivateCloud)
            .put("cloud_ready", cloudReady)
            .put("proactive", proactive)
            .put("use_memory", useMemory)
            .put("memory_subjects", JSONArray(memorySubjects))
            .put("memory_max_chars", memoryMaxChars)
            .put("memory_max_records", memoryMaxRecords)
            .put("review_reads", reviewReads)
        conversationId?.let { payload.put("conversation_id", it) }
        plannerModel?.let { payload.put("planner_model", it) }
        val root = post("/api/v1/experimental/agent3/plan", payload)
        return PlanPreview(
            planId = root.nullableString("plan_id"),
            expiresInSeconds = root.nullableInt("expires_in_seconds"),
            routeKind = root.optJSONObject("route")?.optString("kind").orEmpty(),
            rationale = root.optString("rationale"),
            steps = parseSteps(root.optJSONArray("plan") ?: JSONArray()),
            executed = root.optBoolean("executed", false),
            memoryContext = parseMemoryReceipt(root.optJSONObject("memory_context")),
            capabilityReceipt = parseCapabilityReceipt(root.optJSONObject("capability_receipt")),
            reviewReads = root.optBoolean("review_reads", false),
        )
    }

    fun startPlanEnvelope(planId: String): RunEnvelope {
        val root = post("/api/v1/experimental/agent3/plans/$planId/start", JSONObject())
        return parseRunEnvelope(root)
    }

    fun startPlan(planId: String): Run = startPlanEnvelope(planId).run

    fun getRun(runId: String): Run {
        val root = get("/api/v1/experimental/agent3/runs/$runId")
        return parseRunEnvelope(root).run
    }

    fun listRuns(): List<Run> {
        val arr = get("/api/v1/experimental/agent3/runs").optJSONArray("runs") ?: JSONArray()
        return buildList {
            for (i in 0 until arr.length()) arr.optJSONObject(i)?.let { add(parseRun(it)) }
        }
    }

    fun events(runId: String): List<Event> {
        val arr = get("/api/v1/experimental/agent3/runs/$runId/events")
            .optJSONArray("events") ?: JSONArray()
        return buildList {
            for (i in 0 until arr.length()) {
                val e = arr.optJSONObject(i) ?: continue
                add(Event(e.optDouble("ts"), e.optString("kind"), e.opt("payload")?.toString().orEmpty()))
            }
        }
    }

    fun retry(runId: String, cloudReady: Boolean = false): Run {
        val payload = JSONObject().put("cloud_ready", cloudReady)
        val root = post("/api/v1/experimental/agent3/runs/$runId/retry", payload)
        return parseRunEnvelope(root).run
    }

    fun confirm(runId: String, stepId: String, digest: String, approve: Boolean): Run {
        val payload = JSONObject()
            .put("step_id", stepId)
            .put("digest", digest)
            .put("decision", if (approve) "approve" else "deny")
        val root = post("/api/v1/experimental/agent3/runs/$runId/confirm", payload)
        return parseRunEnvelope(root).run
    }

    fun resume(runId: String): Run {
        val root = post("/api/v1/experimental/agent3/runs/$runId/resume", JSONObject())
        return parseRunEnvelope(root).run
    }

    fun cancel(runId: String): Run {
        val root = post("/api/v1/experimental/agent3/runs/$runId/cancel", JSONObject())
        return parseRunEnvelope(root).run
    }

    private fun get(path: String): JSONObject = execute(
        Request.Builder().url(base + path).get().header("Authorization", "Bearer $token").build(),
    )

    private fun post(path: String, payload: JSONObject): JSONObject = execute(
        Request.Builder()
            .url(base + path)
            .post(payload.toString().toRequestBody(jsonType))
            .header("Authorization", "Bearer $token")
            .build(),
    )

    private fun execute(request: Request): JSONObject {
        http.newCall(request).execute().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                val detail = runCatching {
                    val root = JSONObject(text)
                    root.optString("error").ifBlank { root.optString("detail") }
                }.getOrNull()?.ifBlank { null } ?: text.take(500)
                throw ModelRigException("Agent 3.0 failed (${response.code}): $detail")
            }
            return runCatching { JSONObject(text) }
                .getOrElse { throw ModelRigException("Agent 3.0 returned invalid JSON") }
        }
    }

    private fun parseRunEnvelope(root: JSONObject): RunEnvelope {
        val termination = parseTerminationReceipt(root.optJSONObject("termination"))
        return RunEnvelope(
            run = parseRun(root.requireObject("run")).copy(termination = termination),
            reviewReads = root.optBoolean("review_reads", false),
            readReview = parseReadReview(root.optJSONObject("read_review")),
            capabilityReceipt = parseCapabilityReceipt(root.optJSONObject("capability_receipt")),
        )
    }

    private fun parseRun(o: JSONObject): Run = Run(
        id = o.optString("id"),
        state = o.optString("state"),
        routeKind = o.optJSONObject("route")?.optString("kind").orEmpty(),
        currentStep = o.optInt("current_step"),
        steps = parseSteps(o.optJSONArray("steps") ?: JSONArray()),
        answer = o.nullableString("answer"),
        error = o.nullableString("error"),
        termination = null,
    )

    private fun parseTerminationReceipt(o: JSONObject?): TerminationReceipt? {
        val receipt = o ?: return null
        val plan = receipt.optJSONObject("plan")
            ?: throw ModelRigException("Ugyldigt termination receipt: plan mangler")
        val modelStream = receipt.optJSONObject("model_stream")
            ?: throw ModelRigException("Ugyldigt termination receipt: model_stream mangler")
        val activeTool = receipt.optJSONObject("active_tool")?.let { active ->
            TerminationActiveTool(
                stepId = active.optString("step_id"),
                tool = active.optString("tool"),
                state = active.optString("state"),
                semantics = active.nullableString("semantics"),
                handlePresent = active.optBoolean("handle_present", false),
                canRequest = active.optBoolean("can_request", false),
                requestState = active.optString("request_state"),
                reason = active.optString("reason"),
            )
        }
        val parsed = TerminationReceipt(
            schema = receipt.optString("schema"),
            plan = TerminationPlan(
                state = plan.optString("state"),
                canRequest = plan.optBoolean("can_request", false),
                requestScope = plan.optString("request_scope"),
                effect = plan.optString("effect"),
                reason = plan.optString("reason"),
            ),
            modelStream = TerminationModelStream(
                state = modelStream.optString("state"),
                active = modelStream.optBoolean("active", false),
                canRequest = modelStream.optBoolean("can_request", false),
                handlePresent = modelStream.optBoolean("handle_present", false),
                reason = modelStream.optString("reason"),
            ),
            activeTool = activeTool,
            productionActivation = receipt.optBoolean("production_activation", true),
        )
        validateTerminationReceipt(parsed)
        return parsed
    }

    private fun validateTerminationReceipt(receipt: TerminationReceipt) {
        if (receipt.schema != "kaliv-agent3-termination/v1") {
            throw ModelRigException("Ukendt termination receipt-schema: ${receipt.schema}")
        }
        if (receipt.productionActivation) {
            throw ModelRigException("Ugyldigt termination receipt: produktion må aldrig aktiveres")
        }
        if (receipt.plan.state !in setOf("available", "terminal") ||
            receipt.plan.requestScope != "plan" ||
            receipt.plan.effect.isBlank() || receipt.plan.reason.isBlank() ||
            receipt.plan.canRequest != (receipt.plan.state == "available")
        ) {
            throw ModelRigException("Ugyldigt termination receipt: plan-scope er inkonsistent")
        }
        if (receipt.modelStream.state.isBlank() || receipt.modelStream.reason.isBlank() ||
            (receipt.modelStream.canRequest && !receipt.modelStream.handlePresent)
        ) {
            throw ModelRigException("Ugyldigt termination receipt: model-stream er inkonsistent")
        }
        receipt.activeTool?.let { active ->
            if (active.stepId.isBlank() || active.tool.isBlank() || active.state.isBlank() ||
                active.requestState.isBlank() || active.reason.isBlank() ||
                active.semantics !in setOf(null, "none", "cooperative", "runtime") ||
                (active.canRequest && !active.handlePresent)
            ) {
                throw ModelRigException("Ugyldigt termination receipt: active_tool er inkonsistent")
            }
        }
    }

    private fun parseMemoryReceipt(o: JSONObject?): MemoryReceipt {
        val receipt = o ?: JSONObject()
        return MemoryReceipt(
            requested = receipt.optBoolean("requested", false),
            sentToModel = receipt.optBoolean("sent_to_model", false),
            target = receipt.nullableString("target"),
            includedIds = receipt.optJSONArray("included_ids").toStrings(),
            excludedIds = receipt.optJSONArray("excluded_ids").toStrings(),
            characterCount = receipt.optInt("character_count", 0),
            sha256 = receipt.nullableString("sha256"),
        )
    }

    private fun parseCapabilityReceipt(o: JSONObject?): CapabilityReceipt? {
        val receipt = o ?: return null
        val parsed = CapabilityReceipt(
            schema = receipt.optString("schema"),
            graphSha256 = receipt.optString("graph_sha256"),
            planSha256 = receipt.optString("plan_sha256"),
            route = receipt.optString("route"),
            allowed = receipt.optBoolean("allowed", false),
            requiredCapabilityIds = receipt.optJSONArray("required_capability_ids").toStrings(),
            blockers = buildList {
                val values = receipt.optJSONArray("blockers") ?: JSONArray()
                for (index in 0 until values.length()) {
                    val blocker = values.optJSONObject(index) ?: continue
                    add(
                        CapabilityBlocker(
                            capabilityId = blocker.optString("capability_id"),
                            state = blocker.optString("state"),
                            reason = blocker.optString("reason"),
                        )
                    )
                }
            },
            productionActivation = receipt.optBoolean("production_activation", true),
        )
        validateCapabilityReceipt(parsed)
        return parsed
    }

    private fun validateCapabilityReceipt(receipt: CapabilityReceipt) {
        if (receipt.schema != "kaliv-agent3-capability-receipt/v1") {
            throw ModelRigException("Ukendt capability receipt-schema: ${receipt.schema}")
        }
        if (receipt.productionActivation) {
            throw ModelRigException("Ugyldigt capability receipt: produktion må aldrig aktiveres")
        }
        val digest = Regex("^[0-9a-f]{64}$")
        if (!digest.matches(receipt.graphSha256) || !digest.matches(receipt.planSha256)) {
            throw ModelRigException("Ugyldigt capability receipt: SHA-256-binding mangler")
        }
        if (receipt.route.isBlank()) {
            throw ModelRigException("Ugyldigt capability receipt: route mangler")
        }
        if (
            receipt.requiredCapabilityIds.any { it.isBlank() } ||
            receipt.requiredCapabilityIds.distinct().size != receipt.requiredCapabilityIds.size
        ) {
            throw ModelRigException("Ugyldigt capability receipt: capability-id'er er ugyldige")
        }
        if (receipt.blockers.any {
                it.capabilityId.isBlank() || it.state.isBlank() || it.reason.isBlank()
            }
        ) {
            throw ModelRigException("Ugyldigt capability receipt: blocker er ufuldstændig")
        }
        if (receipt.allowed && receipt.blockers.isNotEmpty()) {
            throw ModelRigException("Ugyldigt capability receipt: tilladt plan har blockers")
        }
    }

    private fun parseReadReview(o: JSONObject?): ReadReview {
        val review = o ?: JSONObject()
        return ReadReview(
            enabled = review.optBoolean("enabled", false),
            waiting = review.optBoolean("waiting", false),
            windowStart = review.nullableInt("window_start"),
            windowEnd = review.nullableInt("window_end"),
            removableStepIds = review.optJSONArray("removable_step_ids").toStrings(),
            completedStepId = review.nullableString("completed_step_id"),
            completedTool = review.nullableString("completed_tool"),
            updatedAt = review.nullableDouble("updated_at"),
        )
    }

    private fun parseSteps(arr: JSONArray): List<Step> = buildList {
        for (i in 0 until arr.length()) {
            val s = arr.optJSONObject(i) ?: continue
            add(
                Step(
                    id = s.nullableString("id"),
                    tool = s.optString("tool"),
                    args = s.optJSONObject("args")?.toString() ?: "{}",
                    risk = s.optString("risk"),
                    sensitivity = s.optString("sensitivity"),
                    egress = s.optString("egress"),
                    summary = s.optString("summary"),
                    state = s.nullableString("state"),
                    confirmationDigest = s.nullableString("confirmation_digest"),
                    confirmationExpiresAt = s.nullableDouble("confirmation_expires_at"),
                    error = s.nullableString("error"),
                )
            )
        }
    }

    private fun JSONArray?.toStrings(): List<String> = buildList {
        val values = this@toStrings ?: return@buildList
        for (index in 0 until values.length()) {
            values.optString(index).takeIf { it.isNotBlank() }?.let(::add)
        }
    }

    private fun JSONObject.requireObject(name: String): JSONObject =
        optJSONObject(name) ?: throw ModelRigException("Agent 3.0 response missing '$name'")

    private fun JSONObject.nullableString(name: String): String? =
        if (!has(name) || isNull(name)) null else optString(name).ifBlank { null }

    private fun JSONObject.nullableInt(name: String): Int? =
        if (!has(name) || isNull(name)) null else optInt(name)

    private fun JSONObject.nullableDouble(name: String): Double? =
        if (!has(name) || isNull(name)) null else optDouble(name)
}
