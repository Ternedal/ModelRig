package dk.ternedal.modelrig.net

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Normal-client transport for the readiness-bound Agent 3 read-only task surface.
 *
 * Deliberately exposes only preview, single-use start, task-scoped status and
 * task-scoped cancellation. It has no generic run, confirmation, retry, resume,
 * cloud, RAG, memory or client-authored-plan API.
 */
class Agent3ReadonlyTaskClient(baseUrl: String, private val token: String) {
    private val base = baseUrl.trimEnd('/')
    private val jsonType = "application/json".toMediaType()
    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.MINUTES)
        .build()

    data class EvidenceBinding(
        val pilotReportSha256: String,
        val pilotCandidateGitSha: String,
        val rigValidationReportSha256: String,
    )

    data class Blocker(
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
        val blockers: List<Blocker>,
        val productionActivation: Boolean,
    )

    data class Step(
        val id: String?,
        val tool: String,
        val args: String,
        val risk: String,
        val sensitivity: String,
        val egress: String,
        val idempotent: Boolean,
        val summary: String,
        val state: String?,
        val error: String?,
    )

    data class Preview(
        val planId: String?,
        val expiresInSeconds: Int?,
        val rationale: String,
        val steps: List<Step>,
        val evidence: EvidenceBinding,
        val capabilityReceipt: CapabilityReceipt?,
    ) {
        val canStart: Boolean
            get() = planId != null &&
                steps.isNotEmpty() &&
                capabilityReceipt?.allowed != false
    }

    data class Run(
        val id: String,
        val state: String,
        val routeKind: String,
        val currentStep: Int,
        val steps: List<Step>,
        val answer: String?,
        val error: String?,
    )

    data class Event(
        val timestamp: Double,
        val kind: String,
        val payload: String,
    )

    data class PlanTermination(
        val state: String,
        val canRequest: Boolean,
        val requestScope: String,
        val effect: String,
        val reason: String,
    )

    data class ModelStreamTermination(
        val state: String,
        val active: Boolean,
        val canRequest: Boolean,
        val handlePresent: Boolean,
        val reason: String,
    )

    data class ActiveToolTermination(
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
        val plan: PlanTermination,
        val modelStream: ModelStreamTermination,
        val activeTool: ActiveToolTermination?,
        val productionActivation: Boolean,
    )

    data class Started(
        val run: Run,
        val events: List<Event>,
        val evidence: EvidenceBinding,
        val capabilityReceipt: CapabilityReceipt?,
        val termination: TerminationReceipt,
        val terminal: Boolean,
    )

    fun preview(message: String, conversationId: String? = null): Preview {
        val payload = JSONObject().put("message", message)
        conversationId?.takeIf { it.isNotBlank() }?.let { payload.put("conversation_id", it) }
        return parsePreview(post(PLAN_PATH, payload))
    }

    fun start(planId: String): Started {
        requireOpaqueId(planId, "read-only task plan-id")
        return parseStarted(post("$PLAN_PREFIX/$planId/start", JSONObject()))
    }

    fun status(runId: String): Started {
        requireOpaqueId(runId, "read-only task run-id")
        return parseStarted(get("$RUN_PREFIX/$runId")).requireRunId(runId)
    }

    fun cancel(runId: String): Started {
        requireOpaqueId(runId, "read-only task run-id")
        return parseStarted(post("$RUN_PREFIX/$runId/cancel", JSONObject())).requireRunId(runId)
    }

    internal fun parsePreview(root: JSONObject): Preview {
        validateEnvelope(root)
        if (root.optBoolean("executed", true)) {
            throw ModelRigException("Ugyldig task-preview: preview må ikke eksekvere")
        }
        val route = root.optJSONObject("route")
            ?: throw ModelRigException("Task-preview mangler route")
        if (
            route.optString("kind") != ROUTE ||
            route.optBoolean("uses_cloud", true) ||
            !route.optBoolean("uses_rig", false) ||
            !route.optBoolean("uses_tools", false) ||
            route.optBoolean("uses_rag", true)
        ) {
            throw ModelRigException("Ugyldig task-preview: ruten er ikke lokal read-only")
        }
        val steps = parseSteps(root.optJSONArray("plan") ?: JSONArray())
        validateSteps(steps)
        val planId = root.nullableString("plan_id")
        if (steps.isNotEmpty() && (planId == null || !OPAQUE_ID.matches(planId))) {
            throw ModelRigException("Ugyldig task-preview: executable plan mangler single-use id")
        }
        if (steps.isEmpty() && planId != null) {
            throw ModelRigException("Ugyldig task-preview: tom plan må ikke have start-token")
        }
        return Preview(
            planId = planId,
            expiresInSeconds = root.nullableInt("expires_in_seconds"),
            rationale = root.optString("rationale"),
            steps = steps,
            evidence = parseEvidence(root.requireObject("readiness_binding")),
            capabilityReceipt = parseCapabilityReceipt(root.optJSONObject("capability_receipt")),
        )
    }

    internal fun parseStarted(root: JSONObject): Started {
        validateEnvelope(root)
        val run = parseRun(root.requireObject("run"))
        if (run.state == "waiting_confirmation") {
            throw ModelRigException("Ugyldigt read-only task-run: confirmation er ikke tilladt")
        }
        if (run.routeKind != ROUTE) {
            throw ModelRigException("Ugyldigt read-only task-run: route er ændret")
        }
        validateSteps(run.steps)
        val terminal = root.requireBoolean("terminal")
        if (terminal != (run.state in TERMINAL_STATES)) {
            throw ModelRigException("Ugyldigt read-only task-run: terminal-status matcher ikke run-state")
        }
        val termination = parseTermination(root.requireObject("termination"), run, terminal)
        return Started(
            run = run,
            events = parseEvents(root.optJSONArray("events") ?: JSONArray()),
            evidence = parseEvidence(root.requireObject("readiness_binding")),
            capabilityReceipt = parseCapabilityReceipt(root.optJSONObject("capability_receipt")),
            termination = termination,
            terminal = terminal,
        )
    }

    private fun Started.requireRunId(expected: String): Started {
        if (run.id != expected) {
            throw ModelRigException("Ugyldigt read-only task-run: serveren returnerede et andet run-id")
        }
        return this
    }

    private fun validateEnvelope(root: JSONObject) {
        if (
            root.optString("task_surface") != SURFACE ||
            root.optString("selected_surface") != SURFACE ||
            root.optString("fallback_surface") != FALLBACK ||
            root.optString("reason") != SELECTED_REASON
        ) {
            throw ModelRigException("Ugyldig read-only task-kontrakt: surface eller fallback er ændret")
        }
        if (
            root.optBoolean("production_activation", true) ||
            !root.optBoolean("normal_chat_route_unchanged", false)
        ) {
            throw ModelRigException("Ugyldig read-only task-kontrakt: normal chat må ikke ændres")
        }
    }

    private fun parseRun(value: JSONObject): Run = Run(
        id = value.optString("id"),
        state = value.optString("state"),
        routeKind = value.optJSONObject("route")?.optString("kind").orEmpty(),
        currentStep = value.optInt("current_step"),
        steps = parseSteps(value.optJSONArray("steps") ?: JSONArray()),
        answer = value.nullableString("answer"),
        error = value.nullableString("error"),
    ).also {
        if (
            it.id.isBlank() ||
            it.state !in RUN_STATES ||
            it.currentStep < 0 ||
            it.currentStep > it.steps.size
        ) {
            throw ModelRigException("Ugyldigt read-only task-run: run-identitet eller state er ugyldig")
        }
    }

    private fun parseSteps(values: JSONArray): List<Step> = buildList {
        for (index in 0 until values.length()) {
            val value = values.optJSONObject(index)
                ?: throw ModelRigException("Ugyldigt read-only task-step")
            add(
                Step(
                    id = value.nullableString("id"),
                    tool = value.optString("tool"),
                    args = value.optJSONObject("args")?.toString() ?: "{}",
                    risk = value.optString("risk"),
                    sensitivity = value.optString("sensitivity"),
                    egress = value.optString("egress"),
                    idempotent = value.optBoolean("idempotent", false),
                    summary = value.optString("summary"),
                    state = value.nullableString("state"),
                    error = value.nullableString("error"),
                ),
            )
        }
    }

    private fun validateSteps(steps: List<Step>) {
        if (steps.any {
                it.tool.isBlank() ||
                    it.risk != "read" ||
                    it.egress != "local" ||
                    !it.idempotent
            }
        ) {
            throw ModelRigException("Ugyldig read-only task-kontrakt: kun lokale idempotente reads er tilladt")
        }
    }

    private fun parseTermination(
        value: JSONObject,
        run: Run,
        terminal: Boolean,
    ): TerminationReceipt {
        val planValue = value.requireObject("plan")
        val modelValue = value.requireObject("model_stream")
        val activeValue = value.optJSONObject("active_tool")
        val receipt = TerminationReceipt(
            schema = value.optString("schema"),
            plan = PlanTermination(
                state = planValue.optString("state"),
                canRequest = planValue.requireBoolean("can_request"),
                requestScope = planValue.optString("request_scope"),
                effect = planValue.optString("effect"),
                reason = planValue.optString("reason"),
            ),
            modelStream = ModelStreamTermination(
                state = modelValue.optString("state"),
                active = modelValue.requireBoolean("active"),
                canRequest = modelValue.requireBoolean("can_request"),
                handlePresent = modelValue.requireBoolean("handle_present"),
                reason = modelValue.optString("reason"),
            ),
            activeTool = activeValue?.let {
                ActiveToolTermination(
                    stepId = it.optString("step_id"),
                    tool = it.optString("tool"),
                    state = it.optString("state"),
                    semantics = it.nullableString("semantics"),
                    handlePresent = it.requireBoolean("handle_present"),
                    canRequest = it.requireBoolean("can_request"),
                    requestState = it.optString("request_state"),
                    reason = it.optString("reason"),
                )
            },
            productionActivation = value.requireBoolean("production_activation"),
        )
        validateTermination(receipt, run, terminal)
        return receipt
    }

    private fun validateTermination(
        receipt: TerminationReceipt,
        run: Run,
        terminal: Boolean,
    ) {
        val plan = receipt.plan
        val model = receipt.modelStream
        val active = receipt.activeTool
        val current = run.steps.getOrNull(run.currentStep)

        if (
            receipt.schema != TERMINATION_SCHEMA ||
            receipt.productionActivation ||
            plan.state !in PLAN_TERMINATION_STATES ||
            plan.requestScope != "plan" ||
            plan.effect !in PLAN_EFFECTS ||
            plan.reason.isBlank() ||
            plan.canRequest != (plan.state == "available") ||
            plan.canRequest == terminal
        ) {
            throw ModelRigException("Ugyldigt read-only termination-receipt: plan-scope er inkonsistent")
        }
        val expectedEffect = if (current?.state == "executing") {
            "prevent_future_steps_active_tool_continues"
        } else {
            "prevent_future_steps"
        }
        if (plan.effect != expectedEffect) {
            throw ModelRigException("Ugyldigt read-only termination-receipt: plan-effekt matcher ikke aktivt step")
        }
        if (
            model.state != "not_active" ||
            model.active ||
            model.canRequest ||
            model.handlePresent ||
            model.reason.isBlank()
        ) {
            throw ModelRigException("Ugyldigt read-only termination-receipt: modelstream-scope er inkonsistent")
        }
        if ((active == null) != (current == null)) {
            throw ModelRigException("Ugyldigt read-only termination-receipt: aktivt tool matcher ikke current_step")
        }
        if (active == null) return
        if (
            active.stepId.isBlank() ||
            active.tool.isBlank() ||
            active.state.isBlank() ||
            active.requestState !in TOOL_REQUEST_STATES ||
            active.reason.isBlank() ||
            active.semantics !in TOOL_SEMANTICS ||
            active.stepId != current?.id ||
            active.tool != current?.tool ||
            active.state != current?.state ||
            (active.canRequest && !active.handlePresent) ||
            (active.canRequest && active.semantics !in setOf("cooperative", "runtime"))
        ) {
            throw ModelRigException("Ugyldigt read-only termination-receipt: aktivt tool er inkonsistent")
        }
        if (active.state == "executing" && active.requestState == "terminal") {
            throw ModelRigException("Ugyldigt read-only termination-receipt: executing tool kan ikke være terminalt")
        }
        if (active.state == "completed_after_cancel" && active.requestState != "terminal") {
            throw ModelRigException("Ugyldigt read-only termination-receipt: sen completion mangler terminal status")
        }
        if (active.requestState == "available" && !active.canRequest) {
            throw ModelRigException("Ugyldigt read-only termination-receipt: tilgængelig tool-kontrol kan ikke bruges")
        }
    }

    private fun parseEvidence(value: JSONObject): EvidenceBinding {
        val binding = EvidenceBinding(
            pilotReportSha256 = value.optString("pilot_report_sha256"),
            pilotCandidateGitSha = value.optString("pilot_candidate_git_sha"),
            rigValidationReportSha256 = value.optString("rig_validation_report_sha256"),
        )
        if (
            !SHA256.matches(binding.pilotReportSha256) ||
            !GIT_SHA.matches(binding.pilotCandidateGitSha) ||
            !SHA256.matches(binding.rigValidationReportSha256)
        ) {
            throw ModelRigException("Ugyldig read-only task-kontrakt: evidence-binding mangler")
        }
        return binding
    }

    private fun parseCapabilityReceipt(value: JSONObject?): CapabilityReceipt? {
        val receipt = value ?: return null
        val parsed = CapabilityReceipt(
            schema = receipt.optString("schema"),
            graphSha256 = receipt.optString("graph_sha256"),
            planSha256 = receipt.optString("plan_sha256"),
            route = receipt.optString("route"),
            allowed = receipt.optBoolean("allowed", false),
            blockers = buildList {
                val values = receipt.optJSONArray("blockers") ?: JSONArray()
                for (index in 0 until values.length()) {
                    val blocker = values.optJSONObject(index)
                        ?: throw ModelRigException("Ugyldigt capability receipt-blocker")
                    add(
                        Blocker(
                            capabilityId = blocker.optString("capability_id"),
                            state = blocker.optString("state"),
                            reason = blocker.optString("reason"),
                        ),
                    )
                }
            },
            productionActivation = receipt.optBoolean("production_activation", true),
        )
        if (
            parsed.schema != "kaliv-agent3-capability-receipt/v1" ||
            !SHA256.matches(parsed.graphSha256) ||
            !SHA256.matches(parsed.planSha256) ||
            parsed.route != ROUTE ||
            parsed.productionActivation ||
            (parsed.allowed && parsed.blockers.isNotEmpty()) ||
            parsed.blockers.any {
                it.capabilityId.isBlank() || it.state.isBlank() || it.reason.isBlank()
            }
        ) {
            throw ModelRigException("Ugyldigt read-only capability receipt")
        }
        return parsed
    }

    private fun parseEvents(values: JSONArray): List<Event> = buildList {
        for (index in 0 until values.length()) {
            val value = values.optJSONObject(index) ?: continue
            add(
                Event(
                    timestamp = value.optDouble("ts"),
                    kind = value.optString("kind"),
                    payload = value.opt("payload")?.toString().orEmpty(),
                ),
            )
        }
    }

    private fun get(path: String): JSONObject = execute(
        Request.Builder()
            .url(base + path)
            .get()
            .header("Authorization", "Bearer $token")
            .build(),
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
                    when (val raw = root.opt("detail")) {
                        is JSONObject -> raw.optString("reason").ifBlank { raw.toString() }
                        else -> root.optString("error").ifBlank { raw?.toString().orEmpty() }
                    }
                }.getOrNull()?.ifBlank { null } ?: text.take(500)
                throw ModelRigException("Read-only task fejlede (${response.code}): $detail")
            }
            return runCatching { JSONObject(text) }
                .getOrElse { throw ModelRigException("Read-only task returnerede ugyldig JSON") }
        }
    }

    private fun requireOpaqueId(value: String, label: String) {
        if (!OPAQUE_ID.matches(value)) {
            throw ModelRigException("Ugyldigt $label")
        }
    }

    private fun JSONObject.requireObject(name: String): JSONObject =
        optJSONObject(name) ?: throw ModelRigException("Read-only task mangler $name")

    private fun JSONObject.requireBoolean(name: String): Boolean {
        if (!has(name) || isNull(name) || get(name) !is Boolean) {
            throw ModelRigException("Read-only task mangler gyldig $name")
        }
        return getBoolean(name)
    }

    private fun JSONObject.nullableString(name: String): String? =
        if (!has(name) || isNull(name)) null else optString(name).ifBlank { null }

    private fun JSONObject.nullableInt(name: String): Int? =
        if (!has(name) || isNull(name)) null else optInt(name)

    companion object {
        private const val PLAN_PATH = "/api/v1/experimental/agent3/task/plan"
        private const val PLAN_PREFIX = "/api/v1/experimental/agent3/task/plans"
        private const val RUN_PREFIX = "/api/v1/experimental/agent3/task/runs"
        private const val SURFACE = "agent3_readonly"
        private const val FALLBACK = "agent2"
        private const val SELECTED_REASON = "agent3_readonly_selected"
        private const val ROUTE = "rig_tools_local"
        private const val TERMINATION_SCHEMA = "kaliv-agent3-termination/v1"
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
        private val PLAN_TERMINATION_STATES = setOf("available", "terminal")
        private val PLAN_EFFECTS = setOf(
            "prevent_future_steps",
            "prevent_future_steps_active_tool_continues",
        )
        private val TOOL_SEMANTICS = setOf<String?>(null, "none", "cooperative", "runtime")
        private val TOOL_REQUEST_STATES = setOf(
            "available",
            "pending",
            "terminal",
            "unavailable",
            "not_active",
        )
    }
}
