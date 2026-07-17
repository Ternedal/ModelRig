package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

@Serializable
data class Agent3RoutingPreviewRequest(
    val message: String,
    val mode: String = "rig",
    val tools: Boolean = false,
    val rag: Boolean = false,
    @SerialName("has_image") val hasImage: Boolean = false,
    val voice: Boolean = false,
    @SerialName("allow_rag_cloud") val allowRagCloud: Boolean = false,
    @SerialName("auto_cloud_fallback") val autoCloudFallback: Boolean = false,
)

@Serializable
data class Agent3RoutingPreviewRoute(
    val kind: String = "",
    val reason: String = "",
    @SerialName("uses_cloud") val usesCloud: Boolean = false,
    @SerialName("uses_rig") val usesRig: Boolean = false,
    @SerialName("uses_tools") val usesTools: Boolean = false,
    @SerialName("uses_rag") val usesRag: Boolean = false,
    @SerialName("requires_user_choice") val requiresUserChoice: Boolean = false,
)

@Serializable
data class Agent3RoutingPreviewProofs(
    @SerialName("developer_preview_evidence") val developerPreviewEvidence: Boolean = false,
    @SerialName("write_pilot_evidence") val writePilotEvidence: Boolean = false,
    @SerialName("capability_graph_schema") val capabilityGraphSchema: String = "",
    @SerialName("capability_graph_production_activation")
    val capabilityGraphProductionActivation: Boolean = false,
    @SerialName("actual_surface_unchanged") val actualSurfaceUnchanged: Boolean = false,
)

@Serializable
data class Agent3RoutingPreview(
    val schema: String = "",
    @SerialName("selected_surface") val selectedSurface: String = "",
    @SerialName("candidate_surface") val candidateSurface: String? = null,
    @SerialName("eligible_for_agent3_preview") val eligibleForAgent3Preview: Boolean = false,
    @SerialName("message_sha256") val messageSha256: String = "",
    @SerialName("message_characters") val messageCharacters: Int = 0,
    val route: Agent3RoutingPreviewRoute = Agent3RoutingPreviewRoute(),
    @SerialName("required_capabilities") val requiredCapabilities: List<String> = emptyList(),
    val blockers: List<String> = emptyList(),
    val warnings: List<String> = emptyList(),
    val proofs: Agent3RoutingPreviewProofs = Agent3RoutingPreviewProofs(),
    @SerialName("production_activation") val productionActivation: Boolean = false,
    val executed: Boolean = false,
    val planned: Boolean = false,
)

/**
 * Read-only transport for the Agent 3.0 routing-preview endpoint.
 *
 * This client never starts a plan or run. It also rejects any response claiming
 * that preview changed the selected surface, planned/executed work, or activated
 * production. The normal desktop chat path remains completely separate.
 */
class Agent3RoutingPreviewClient(baseUrl: String, private val bearer: String) {
    private val base = baseUrl.trimEnd('/')
    private val json = Json {
        ignoreUnknownKeys = true
        encodeDefaults = true
    }
    private val http: HttpClient = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(10))
        .build()

    fun preview(request: Agent3RoutingPreviewRequest): Agent3RoutingPreview {
        require(request.message.isNotBlank()) { "Routing preview requires a non-empty message" }
        require(request.message.length <= 20_000) { "Routing preview message exceeds 20,000 characters" }
        require(request.mode == "rig" || request.mode == "cloud") { "Routing preview mode must be rig or cloud" }

        val body = json.encodeToString(request)
        val httpRequest = HttpRequest.newBuilder(
            URI.create(base + "/api/v1/experimental/agent3/routing-preview")
        )
            .header("Authorization", "Bearer $bearer")
            .header("Content-Type", "application/json")
            .header("Accept", "application/json")
            .timeout(Duration.ofSeconds(20))
            .POST(HttpRequest.BodyPublishers.ofString(body))
            .build()
        val response = http.send(httpRequest, HttpResponse.BodyHandlers.ofString())
        if (response.statusCode() !in 200..299) {
            throw Agent3Exception(
                "Agent 3.0 routing preview failed (${response.statusCode()}): " +
                    response.body().take(500)
            )
        }
        val preview = try {
            json.decodeFromString<Agent3RoutingPreview>(response.body())
        } catch (e: Exception) {
            throw Agent3Exception("Agent 3.0 routing preview returned invalid JSON: ${e.message}")
        }
        validate(preview)
        return preview
    }

    private fun validate(preview: Agent3RoutingPreview) {
        if (preview.schema != "kaliv-agent3-routing-preview/v1") {
            throw Agent3Exception("Unsupported Agent 3.0 routing-preview schema: ${preview.schema}")
        }
        if (preview.selectedSurface != "agent_v2") {
            throw Agent3Exception("Invalid routing preview: actual surface must remain Agent v2")
        }
        if (!preview.proofs.actualSurfaceUnchanged) {
            throw Agent3Exception("Invalid routing preview: server did not prove the actual surface is unchanged")
        }
        if (
            preview.productionActivation ||
            preview.proofs.capabilityGraphProductionActivation ||
            preview.executed ||
            preview.planned
        ) {
            throw Agent3Exception(
                "Invalid routing preview: preview must never activate, plan, or execute work"
            )
        }
        if (preview.messageSha256.length != 64) {
            throw Agent3Exception("Invalid routing preview: missing message SHA-256 receipt")
        }
        if (preview.messageCharacters < 0) {
            throw Agent3Exception("Invalid routing preview: negative message character count")
        }
    }
}
