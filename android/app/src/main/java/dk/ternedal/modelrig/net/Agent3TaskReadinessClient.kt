package dk.ternedal.modelrig.net

import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Typed, read-only transport for the server-authoritative Agent 3 task surface.
 *
 * This client can observe the selected surface but cannot start a run, submit a
 * plan or alter normal chat. Unknown or internally inconsistent contracts fail
 * closed instead of being guessed into a route.
 */
class Agent3TaskReadinessClient(baseUrl: String, private val token: String) {
    private val base = baseUrl.trimEnd('/')
    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .build()

    data class Pilot(
        val configured: Boolean,
        val present: Boolean,
        val structurallyValid: Boolean,
        val fresh: Boolean,
        val versionMatch: Boolean,
        val codeMatch: Boolean,
        val finishedAt: String?,
        val ageSeconds: Double?,
        val maxAgeHours: Double,
        val reportSha256: String?,
        val candidateGitSha: String?,
        val tasks: Int?,
        val successes: Int?,
        val failures: Int?,
        val taskSuccessRate: Double?,
        val replans: Int?,
        val retryEvents: Int?,
        val stopFallbackProven: Boolean,
    )

    data class RigValidation(
        val eligibleForDeveloperPreview: Boolean,
        val versionMatch: Boolean,
        val codeMatch: Boolean,
        val reportSha256: String?,
    )

    data class UiContract(
        val routeSource: String,
        val stopVisible: Boolean,
        val fallbackVisible: Boolean,
        val receiptsVisible: Boolean,
        val replansVisible: Boolean,
        val outcomesVisible: Boolean,
    )

    data class Readiness(
        val selectedSurface: String,
        val candidateSurface: String,
        val fallbackSurface: String,
        val eligibleForTaskUi: Boolean,
        val operatorEnabled: Boolean,
        val normalChatRouteUnchanged: Boolean,
        val productionActivation: Boolean,
        val reason: String,
        val reasons: List<String>,
        val pilot: Pilot,
        val rigValidation: RigValidation,
        val uiContract: UiContract,
    ) {
        val agent3ReadonlySelected: Boolean
            get() = selectedSurface == AGENT3_READONLY
    }

    fun readiness(): Readiness {
        val request = Request.Builder()
            .url(base + ENDPOINT)
            .get()
            .header("Authorization", "Bearer $token")
            .build()
        return parse(execute(request))
    }

    internal fun parse(root: JSONObject): Readiness {
        if (root.optString("schema") != SCHEMA) {
            throw ModelRigException("Ukendt Agent 3 task-readiness-kontrakt")
        }

        val selected = root.optString("selected_surface")
        val candidate = root.optString("candidate_surface")
        val fallback = root.optString("fallback_surface")
        val eligible = root.optBoolean("eligible_for_task_ui", false)
        val operatorEnabled = root.optBoolean("operator_enabled", false)
        val productionActivation = root.optBoolean("production_activation", true)
        val normalChatUnchanged = root.optBoolean("normal_chat_route_unchanged", false)
        val reason = root.optString("reason").ifBlank { "unknown" }
        val reasons = root.optJSONArray("reasons").toStrings()

        if (selected !in setOf(AGENT2, AGENT3_READONLY) ||
            candidate != AGENT3_READONLY ||
            fallback != AGENT2
        ) {
            throw ModelRigException("Ugyldig Agent 3 task-readiness: ukendt surface")
        }
        if (productionActivation || !normalChatUnchanged) {
            throw ModelRigException("Ugyldig Agent 3 task-readiness: normal chat må ikke ændres")
        }
        if (selected == AGENT3_READONLY &&
            (!eligible || !operatorEnabled || reason != AGENT3_SELECTED_REASON || reasons.isNotEmpty())
        ) {
            throw ModelRigException("Ugyldig Agent 3 task-readiness: Agent 3 kræver eksakt readiness")
        }
        if (selected == AGENT2 && reason == AGENT3_SELECTED_REASON) {
            throw ModelRigException("Ugyldig Agent 3 task-readiness: valgt surface og årsag er uenige")
        }

        val pilot = root.optJSONObject("pilot")
            ?: throw ModelRigException("Agent 3 task-readiness mangler pilot")
        val validation = root.optJSONObject("rig_validation")
            ?: throw ModelRigException("Agent 3 task-readiness mangler rig_validation")
        val ui = root.optJSONObject("ui_contract")
            ?: throw ModelRigException("Agent 3 task-readiness mangler ui_contract")

        val uiContract = UiContract(
            routeSource = ui.optString("route_source"),
            stopVisible = ui.optBoolean("stop_visible", false),
            fallbackVisible = ui.optBoolean("fallback_visible", false),
            receiptsVisible = ui.optBoolean("receipts_visible", false),
            replansVisible = ui.optBoolean("replans_visible", false),
            outcomesVisible = ui.optBoolean("outcomes_visible", false),
        )
        if (uiContract.routeSource != "server_authoritative" ||
            !uiContract.stopVisible ||
            !uiContract.fallbackVisible ||
            !uiContract.receiptsVisible ||
            !uiContract.replansVisible ||
            !uiContract.outcomesVisible
        ) {
            throw ModelRigException("Ugyldig Agent 3 task-readiness: UI-sikkerhedskontrakten er ufuldstændig")
        }

        return Readiness(
            selectedSurface = selected,
            candidateSurface = candidate,
            fallbackSurface = fallback,
            eligibleForTaskUi = eligible,
            operatorEnabled = operatorEnabled,
            normalChatRouteUnchanged = true,
            productionActivation = false,
            reason = reason,
            reasons = reasons,
            pilot = Pilot(
                configured = pilot.optBoolean("configured", false),
                present = pilot.optBoolean("present", false),
                structurallyValid = pilot.optBoolean("structurally_valid", false),
                fresh = pilot.optBoolean("fresh", false),
                versionMatch = pilot.optBoolean("version_match", false),
                codeMatch = pilot.optBoolean("code_match", false),
                finishedAt = pilot.nullableString("finished_at"),
                ageSeconds = pilot.nullableDouble("age_seconds"),
                maxAgeHours = pilot.optDouble("max_age_hours", 168.0),
                reportSha256 = pilot.nullableString("report_sha256"),
                candidateGitSha = pilot.nullableString("candidate_git_sha"),
                tasks = pilot.nullableInt("tasks"),
                successes = pilot.nullableInt("successes"),
                failures = pilot.nullableInt("failures"),
                taskSuccessRate = pilot.nullableDouble("task_success_rate"),
                replans = pilot.nullableInt("replans"),
                retryEvents = pilot.nullableInt("retry_events"),
                stopFallbackProven = pilot.optBoolean("stop_fallback_proven", false),
            ),
            rigValidation = RigValidation(
                eligibleForDeveloperPreview = validation.optBoolean(
                    "eligible_for_developer_preview",
                    false,
                ),
                versionMatch = validation.optBoolean("version_match", false),
                codeMatch = validation.optBoolean("code_match", false),
                reportSha256 = validation.nullableString("report_sha256"),
            ),
            uiContract = uiContract,
        )
    }

    private fun execute(request: Request): JSONObject {
        http.newCall(request).execute().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                val detail = runCatching {
                    val root = JSONObject(text)
                    root.optString("error").ifBlank { root.optString("detail") }
                }.getOrNull()?.ifBlank { null } ?: text.take(500)
                throw ModelRigException("Agent 3 task-readiness fejlede (${response.code}): $detail")
            }
            return runCatching { JSONObject(text) }
                .getOrElse { throw ModelRigException("Agent 3 task-readiness returnerede ugyldig JSON") }
        }
    }

    private fun JSONArray?.toStrings(): List<String> = buildList {
        val values = this@toStrings ?: return@buildList
        for (index in 0 until values.length()) {
            values.optString(index).takeIf { it.isNotBlank() }?.let(::add)
        }
    }

    private fun JSONObject.nullableString(name: String): String? =
        if (!has(name) || isNull(name)) null else optString(name).ifBlank { null }

    private fun JSONObject.nullableDouble(name: String): Double? =
        if (!has(name) || isNull(name)) null else optDouble(name)

    private fun JSONObject.nullableInt(name: String): Int? =
        if (!has(name) || isNull(name)) null else optInt(name)

    companion object {
        private const val ENDPOINT = "/api/v1/experimental/agent3/task-readiness"
        private const val SCHEMA = "kaliv-agent3-task-readiness/v1"
        private const val AGENT2 = "agent2"
        private const val AGENT3_READONLY = "agent3_readonly"
        private const val AGENT3_SELECTED_REASON = "agent3_readonly_selected"
    }
}
