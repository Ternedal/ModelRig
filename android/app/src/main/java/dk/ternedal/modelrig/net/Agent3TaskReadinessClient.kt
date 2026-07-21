package dk.ternedal.modelrig.net

import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

internal fun validateAgent3TaskSurface(
    selectedSurface: String,
    candidateSurface: String,
    fallbackSurface: String,
    eligibleForTaskUi: Boolean,
    operatorEnabled: Boolean,
    normalChatRouteUnchanged: Boolean,
    productionActivation: Boolean,
    reason: String,
    routeSource: String,
): String {
    if (candidateSurface != "agent3_readonly" || fallbackSurface != "agent2") {
        throw ModelRigException("Ugyldig Agent 3 task-readiness: ukendt surface-kontrakt")
    }
    if (productionActivation || !normalChatRouteUnchanged) {
        throw ModelRigException("Ugyldig Agent 3 task-readiness: normal chat må ikke ændres")
    }
    if (routeSource != "server_authoritative") {
        throw ModelRigException("Agent 3 task-readiness har ikke server-authoritative routing")
    }
    return when (selectedSurface) {
        "agent2" -> {
            if (eligibleForTaskUi && operatorEnabled) {
                throw ModelRigException(
                    "Ugyldig Agent 3 task-readiness: klar operatørsession skal vælge read-only surface"
                )
            }
            if (reason == "agent3_readonly_selected") {
                throw ModelRigException(
                    "Ugyldig Agent 3 task-readiness: Agent 2 kan ikke påstå Agent 3-selection"
                )
            }
            selectedSurface
        }
        "agent3_readonly" -> {
            if (!eligibleForTaskUi || !operatorEnabled || reason != "agent3_readonly_selected") {
                throw ModelRigException(
                    "Ugyldig Agent 3 task-readiness: read-only surface kræver exact readiness"
                )
            }
            selectedSurface
        }
        else -> throw ModelRigException("Ugyldig Agent 3 task-readiness: ukendt selected surface")
    }
}

/**
 * Typed, read-only transport for the server-owned Agent 3 task-surface decision.
 *
 * Unknown schemas, surfaces or internally inconsistent readiness values fail
 * closed. This client has no mutation methods and never changes normal chat.
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
    )

    fun readiness(): Readiness {
        val request = Request.Builder()
            .url(base + "/api/v1/experimental/agent3/task-readiness")
            .get()
            .header("Authorization", "Bearer $token")
            .build()
        val root = execute(request)
        if (root.optString("schema") != "kaliv-agent3-task-readiness/v1") {
            throw ModelRigException("Ukendt Agent 3 task-readiness-kontrakt")
        }
        val selected = root.optString("selected_surface")
        val candidate = root.optString("candidate_surface")
        val fallback = root.optString("fallback_surface")
        val eligible = root.optBoolean("eligible_for_task_ui", false)
        val operator = root.optBoolean("operator_enabled", false)
        val productionActivation = root.optBoolean("production_activation", true)
        val normalChatUnchanged = root.optBoolean("normal_chat_route_unchanged", false)
        val reason = root.optString("reason").ifBlank { "unknown" }

        val pilot = root.optJSONObject("pilot")
            ?: throw ModelRigException("Agent 3 task-readiness mangler pilot")
        val validation = root.optJSONObject("rig_validation")
            ?: throw ModelRigException("Agent 3 task-readiness mangler rig_validation")
        val ui = root.optJSONObject("ui_contract")
            ?: throw ModelRigException("Agent 3 task-readiness mangler ui_contract")
        val routeSource = ui.optString("route_source")
        validateAgent3TaskSurface(
            selectedSurface = selected,
            candidateSurface = candidate,
            fallbackSurface = fallback,
            eligibleForTaskUi = eligible,
            operatorEnabled = operator,
            normalChatRouteUnchanged = normalChatUnchanged,
            productionActivation = productionActivation,
            reason = reason,
            routeSource = routeSource,
        )

        return Readiness(
            selectedSurface = selected,
            candidateSurface = candidate,
            fallbackSurface = fallback,
            eligibleForTaskUi = eligible,
            operatorEnabled = operator,
            normalChatRouteUnchanged = normalChatUnchanged,
            productionActivation = productionActivation,
            reason = reason,
            reasons = root.optJSONArray("reasons").toStrings(),
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
            uiContract = UiContract(
                routeSource = routeSource,
                stopVisible = ui.optBoolean("stop_visible", false),
                fallbackVisible = ui.optBoolean("fallback_visible", false),
                receiptsVisible = ui.optBoolean("receipts_visible", false),
                replansVisible = ui.optBoolean("replans_visible", false),
                outcomesVisible = ui.optBoolean("outcomes_visible", false),
            ),
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
}
