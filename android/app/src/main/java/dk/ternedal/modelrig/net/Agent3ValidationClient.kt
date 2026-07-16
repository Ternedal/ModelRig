package dk.ternedal.modelrig.net

import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Read-only transport for the Agent 3.0 promotion assessment.
 *
 * This client performs exactly one GET against the protected experimental status
 * endpoint. It has no mutation methods and rejects any response that claims the
 * evidence activated production routing.
 */
class Agent3ValidationClient(baseUrl: String, private val token: String) {
    private val base = baseUrl.trimEnd('/')
    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .build()

    data class Proofs(
        val status: Boolean,
        val memoryBinding: Boolean,
        val readPath: Boolean,
        val confirmationPath: Boolean,
        val writeExecution: Boolean,
        val singleUse: Boolean,
        val cleanup: Boolean,
    )

    data class Assessment(
        val configured: Boolean,
        val present: Boolean,
        val structurallyValid: Boolean,
        val fresh: Boolean,
        val versionMatch: Boolean,
        val eligibleForDeveloperPreview: Boolean,
        val eligibleForWritePilot: Boolean,
        val currentVersion: String?,
        val validatedVersion: String?,
        val plannerModel: String?,
        val writeDecision: String?,
        val finishedAt: String?,
        val ageSeconds: Double?,
        val maxAgeHours: Double,
        val reportSha256: String?,
        val proofs: Proofs,
        val reasons: List<String>,
        val writePilotReasons: List<String>,
        val warnings: List<String>,
    )

    data class Status(
        val enabled: Boolean,
        val experimental: Boolean,
        val workerVersion: String?,
        val productionToolsPathUntouched: Boolean,
        val productionActivation: Boolean,
        val assessment: Assessment,
    )

    fun status(): Status {
        val request = Request.Builder()
            .url(base + "/api/v1/experimental/agent3/status")
            .get()
            .header("Authorization", "Bearer $token")
            .build()
        val root = execute(request)
        val assessmentJson = root.optJSONObject("rig_validation")
            ?: throw ModelRigException("Agent 3.0 status mangler rig_validation")
        val topActivation = root.optBoolean("production_activation", true)
        val evidenceActivation = assessmentJson.optBoolean("production_activation", true)
        if (topActivation || evidenceActivation) {
            throw ModelRigException("Ugyldig Agent 3.0-status: produktion må ikke være aktiveret af evidens")
        }
        if (!root.optBoolean("enabled", false) || !root.optBoolean("experimental", false)) {
            throw ModelRigException("Agent 3.0-status er ikke en aktiv eksperimentel developer-endpoint")
        }

        val proofs = assessmentJson.optJSONObject("proofs") ?: JSONObject()
        return Status(
            enabled = true,
            experimental = true,
            workerVersion = root.nullableString("worker_version"),
            productionToolsPathUntouched = root.optBoolean("production_tools_path_untouched", false),
            productionActivation = false,
            assessment = Assessment(
                configured = assessmentJson.optBoolean("configured", false),
                present = assessmentJson.optBoolean("present", false),
                structurallyValid = assessmentJson.optBoolean("structurally_valid", false),
                fresh = assessmentJson.optBoolean("fresh", false),
                versionMatch = assessmentJson.optBoolean("version_match", false),
                eligibleForDeveloperPreview = assessmentJson.optBoolean(
                    "eligible_for_developer_preview",
                    false,
                ),
                eligibleForWritePilot = assessmentJson.optBoolean("eligible_for_write_pilot", false),
                currentVersion = assessmentJson.nullableString("current_version"),
                validatedVersion = assessmentJson.nullableString("validated_version"),
                plannerModel = assessmentJson.nullableString("planner_model"),
                writeDecision = assessmentJson.nullableString("write_decision"),
                finishedAt = assessmentJson.nullableString("finished_at"),
                ageSeconds = assessmentJson.nullableDouble("age_seconds"),
                maxAgeHours = assessmentJson.optDouble("max_age_hours", 168.0),
                reportSha256 = assessmentJson.nullableString("report_sha256"),
                proofs = Proofs(
                    status = proofs.optBoolean("status", false),
                    memoryBinding = proofs.optBoolean("memory_binding", false),
                    readPath = proofs.optBoolean("read_path", false),
                    confirmationPath = proofs.optBoolean("confirmation_path", false),
                    writeExecution = proofs.optBoolean("write_execution", false),
                    singleUse = proofs.optBoolean("single_use", false),
                    cleanup = proofs.optBoolean("cleanup", false),
                ),
                reasons = assessmentJson.optJSONArray("reasons").toStrings(),
                writePilotReasons = assessmentJson.optJSONArray("write_pilot_reasons").toStrings(),
                warnings = assessmentJson.optJSONArray("warnings").toStrings(),
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
                throw ModelRigException("Agent 3.0 validation-status fejlede (${response.code}): $detail")
            }
            return runCatching { JSONObject(text) }
                .getOrElse { throw ModelRigException("Agent 3.0 validation-status returnerede ugyldig JSON") }
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
}
