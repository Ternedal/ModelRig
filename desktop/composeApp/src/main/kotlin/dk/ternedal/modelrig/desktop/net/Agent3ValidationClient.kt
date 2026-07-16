package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

@Serializable
data class Agent3ValidationProofs(
    val status: Boolean = false,
    @SerialName("memory_binding") val memoryBinding: Boolean = false,
    @SerialName("read_path") val readPath: Boolean = false,
    @SerialName("confirmation_path") val confirmationPath: Boolean = false,
    @SerialName("write_execution") val writeExecution: Boolean = false,
    @SerialName("single_use") val singleUse: Boolean = false,
    val cleanup: Boolean = false,
)

@Serializable
data class Agent3ValidationAssessment(
    val configured: Boolean = false,
    val present: Boolean = false,
    @SerialName("structurally_valid") val structurallyValid: Boolean = false,
    val fresh: Boolean = false,
    @SerialName("version_match") val versionMatch: Boolean = false,
    @SerialName("eligible_for_developer_preview") val eligibleForDeveloperPreview: Boolean = false,
    @SerialName("eligible_for_write_pilot") val eligibleForWritePilot: Boolean = false,
    @SerialName("production_activation") val productionActivation: Boolean = false,
    @SerialName("current_version") val currentVersion: String? = null,
    @SerialName("validated_version") val validatedVersion: String? = null,
    @SerialName("planner_model") val plannerModel: String? = null,
    @SerialName("write_decision") val writeDecision: String? = null,
    @SerialName("finished_at") val finishedAt: String? = null,
    @SerialName("age_seconds") val ageSeconds: Double? = null,
    @SerialName("max_age_hours") val maxAgeHours: Double = 168.0,
    @SerialName("report_sha256") val reportSha256: String? = null,
    val proofs: Agent3ValidationProofs = Agent3ValidationProofs(),
    val reasons: List<String> = emptyList(),
    @SerialName("write_pilot_reasons") val writePilotReasons: List<String> = emptyList(),
    val warnings: List<String> = emptyList(),
)

@Serializable
data class Agent3ValidationStatus(
    val enabled: Boolean = false,
    val experimental: Boolean = false,
    @SerialName("worker_version") val workerVersion: String? = null,
    @SerialName("production_tools_path_untouched") val productionToolsPathUntouched: Boolean = false,
    @SerialName("production_activation") val productionActivation: Boolean = false,
    @SerialName("rig_validation") val assessment: Agent3ValidationAssessment = Agent3ValidationAssessment(),
)

/**
 * Read-only Agent 3.0 promotion transport.
 *
 * It exposes only GET status and rejects responses that claim evidence activated
 * production routing. There are deliberately no mutation methods in this class.
 */
class Agent3ValidationClient(baseUrl: String, private val bearer: String) {
    private val base = baseUrl.trimEnd('/')
    private val json = Json { ignoreUnknownKeys = true }
    private val http: HttpClient = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(10))
        .build()

    fun status(): Agent3ValidationStatus {
        val request = HttpRequest.newBuilder(URI.create(base + "/api/v1/experimental/agent3/status"))
            .header("Authorization", "Bearer $bearer")
            .timeout(Duration.ofSeconds(20))
            .GET()
            .build()
        val response = http.send(request, HttpResponse.BodyHandlers.ofString())
        if (response.statusCode() !in 200..299) {
            throw Agent3Exception(
                "Agent 3.0 validation-status failed (${response.statusCode()}): " +
                    response.body().take(500)
            )
        }
        val status = try {
            json.decodeFromString<Agent3ValidationStatus>(response.body())
        } catch (e: Exception) {
            throw Agent3Exception("Agent 3.0 validation-status returned invalid JSON: ${e.message}")
        }
        if (!status.enabled || !status.experimental) {
            throw Agent3Exception("Agent 3.0 status is not an enabled experimental developer endpoint")
        }
        if (status.productionActivation || status.assessment.productionActivation) {
            throw Agent3Exception("Invalid Agent 3.0 status: evidence must never activate production")
        }
        return status
    }
}
