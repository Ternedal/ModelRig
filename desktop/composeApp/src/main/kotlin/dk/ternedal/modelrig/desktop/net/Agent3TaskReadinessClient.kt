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
data class Agent3TaskPilot(
    val configured: Boolean = false,
    val present: Boolean = false,
    @SerialName("structurally_valid") val structurallyValid: Boolean = false,
    val fresh: Boolean = false,
    @SerialName("version_match") val versionMatch: Boolean = false,
    @SerialName("code_match") val codeMatch: Boolean = false,
    @SerialName("finished_at") val finishedAt: String? = null,
    @SerialName("age_seconds") val ageSeconds: Double? = null,
    @SerialName("max_age_hours") val maxAgeHours: Double = 168.0,
    @SerialName("report_sha256") val reportSha256: String? = null,
    @SerialName("candidate_git_sha") val candidateGitSha: String? = null,
    val tasks: Int? = null,
    val successes: Int? = null,
    val failures: Int? = null,
    @SerialName("task_success_rate") val taskSuccessRate: Double? = null,
    val replans: Int? = null,
    @SerialName("retry_events") val retryEvents: Int? = null,
    @SerialName("stop_fallback_proven") val stopFallbackProven: Boolean = false,
)

@Serializable
data class Agent3TaskRigValidation(
    @SerialName("eligible_for_developer_preview") val eligibleForDeveloperPreview: Boolean = false,
    @SerialName("version_match") val versionMatch: Boolean = false,
    @SerialName("code_match") val codeMatch: Boolean = false,
    @SerialName("report_sha256") val reportSha256: String? = null,
)

@Serializable
data class Agent3TaskUiContract(
    @SerialName("route_source") val routeSource: String = "",
    @SerialName("stop_visible") val stopVisible: Boolean = false,
    @SerialName("fallback_visible") val fallbackVisible: Boolean = false,
    @SerialName("receipts_visible") val receiptsVisible: Boolean = false,
    @SerialName("replans_visible") val replansVisible: Boolean = false,
    @SerialName("outcomes_visible") val outcomesVisible: Boolean = false,
)

@Serializable
data class Agent3TaskReadiness(
    val schema: String = "",
    @SerialName("selected_surface") val selectedSurface: String = "",
    @SerialName("candidate_surface") val candidateSurface: String = "",
    @SerialName("fallback_surface") val fallbackSurface: String = "",
    @SerialName("eligible_for_task_ui") val eligibleForTaskUi: Boolean = false,
    @SerialName("operator_enabled") val operatorEnabled: Boolean = false,
    @SerialName("normal_chat_route_unchanged") val normalChatRouteUnchanged: Boolean = false,
    @SerialName("production_activation") val productionActivation: Boolean = false,
    val reason: String = "unknown",
    val reasons: List<String> = emptyList(),
    val pilot: Agent3TaskPilot = Agent3TaskPilot(),
    @SerialName("rig_validation") val rigValidation: Agent3TaskRigValidation = Agent3TaskRigValidation(),
    @SerialName("ui_contract") val uiContract: Agent3TaskUiContract = Agent3TaskUiContract(),
)

/**
 * Read-only task-readiness transport. Unknown schema/surface values fail closed;
 * the dormant contract may only select Agent 2 and cannot mutate routing.
 */
class Agent3TaskReadinessClient(baseUrl: String, private val bearer: String) {
    private val base = baseUrl.trimEnd('/')
    private val json = Json { ignoreUnknownKeys = true }
    private val http: HttpClient = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(10))
        .build()

    fun readiness(): Agent3TaskReadiness {
        val request = HttpRequest.newBuilder(
            URI.create(base + "/api/v1/experimental/agent3/task-readiness")
        )
            .header("Authorization", "Bearer $bearer")
            .timeout(Duration.ofSeconds(20))
            .GET()
            .build()
        val response = http.send(request, HttpResponse.BodyHandlers.ofString())
        if (response.statusCode() !in 200..299) {
            throw Agent3Exception(
                "Agent 3.0 task-readiness failed (${response.statusCode()}): " +
                    response.body().take(500)
            )
        }
        val value = try {
            json.decodeFromString<Agent3TaskReadiness>(response.body())
        } catch (e: Exception) {
            throw Agent3Exception("Agent 3.0 task-readiness returned invalid JSON: ${e.message}")
        }
        if (value.schema != "kaliv-agent3-task-readiness/v1") {
            throw Agent3Exception("Unknown Agent 3.0 task-readiness contract")
        }
        if (
            value.selectedSurface != "agent2" ||
            value.candidateSurface != "agent3_readonly" ||
            value.fallbackSurface != "agent2"
        ) {
            throw Agent3Exception("Invalid Agent 3.0 task-readiness: unknown or active surface")
        }
        if (value.productionActivation || !value.normalChatRouteUnchanged) {
            throw Agent3Exception("Invalid Agent 3.0 task-readiness: normal chat must remain unchanged")
        }
        if (value.uiContract.routeSource != "server_authoritative") {
            throw Agent3Exception("Invalid Agent 3.0 task-readiness: routing is not server-authoritative")
        }
        return value
    }
}
