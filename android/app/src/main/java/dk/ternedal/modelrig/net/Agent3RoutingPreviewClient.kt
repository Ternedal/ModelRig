package dk.ternedal.modelrig.net

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

/**
 * Read-only transport for Agent 3.0 routing preview.
 *
 * The client accepts only turn fields, never runtime readiness or validation
 * evidence. It rejects responses that claim preview planned/executed work,
 * activated production, or changed the actual Agent v2 surface.
 */
class Agent3RoutingPreviewClient(baseUrl: String, private val token: String) {
    private val base = baseUrl.trimEnd('/')
    private val jsonType = "application/json".toMediaType()
    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .build()

    data class RequestInput(
        val message: String,
        val mode: String = "rig",
        val tools: Boolean = false,
        val rag: Boolean = false,
        val hasImage: Boolean = false,
        val voice: Boolean = false,
        val allowRagCloud: Boolean = false,
        val autoCloudFallback: Boolean = false,
    )

    data class Route(
        val kind: String,
        val reason: String,
        val usesCloud: Boolean,
        val usesRig: Boolean,
        val usesTools: Boolean,
        val usesRag: Boolean,
        val requiresUserChoice: Boolean,
    )

    data class Proofs(
        val developerPreviewEvidence: Boolean,
        val writePilotEvidence: Boolean,
        val capabilityGraphSchema: String,
        val capabilityGraphProductionActivation: Boolean,
        val actualSurfaceUnchanged: Boolean,
    )

    data class Preview(
        val schema: String,
        val selectedSurface: String,
        val candidateSurface: String?,
        val eligibleForAgent3Preview: Boolean,
        val messageSha256: String,
        val messageCharacters: Int,
        val route: Route,
        val requiredCapabilities: List<String>,
        val blockers: List<String>,
        val warnings: List<String>,
        val proofs: Proofs,
        val productionActivation: Boolean,
        val executed: Boolean,
        val planned: Boolean,
    )

    fun preview(input: RequestInput): Preview {
        require(input.message.isNotBlank()) { "Routing preview kræver en besked" }
        require(input.message.length <= 20_000) { "Routing preview-beskeden er for lang" }
        require(input.mode == "rig" || input.mode == "cloud") {
            "Routing preview-mode skal være rig eller cloud"
        }

        val body = JSONObject()
            .put("message", input.message)
            .put("mode", input.mode)
            .put("tools", input.tools)
            .put("rag", input.rag)
            .put("has_image", input.hasImage)
            .put("voice", input.voice)
            .put("allow_rag_cloud", input.allowRagCloud)
            .put("auto_cloud_fallback", input.autoCloudFallback)
        val root = execute(
            Request.Builder()
                .url(base + "/api/v1/experimental/agent3/routing-preview")
                .post(body.toString().toRequestBody(jsonType))
                .header("Authorization", "Bearer $token")
                .header("Accept", "application/json")
                .build(),
        )
        val routeJson = root.optJSONObject("route") ?: JSONObject()
        val proofsJson = root.optJSONObject("proofs") ?: JSONObject()
        val result = Preview(
            schema = root.optString("schema"),
            selectedSurface = root.optString("selected_surface"),
            candidateSurface = root.nullableString("candidate_surface"),
            eligibleForAgent3Preview = root.optBoolean("eligible_for_agent3_preview", false),
            messageSha256 = root.optString("message_sha256"),
            messageCharacters = root.optInt("message_characters", -1),
            route = Route(
                kind = routeJson.optString("kind"),
                reason = routeJson.optString("reason"),
                usesCloud = routeJson.optBoolean("uses_cloud", false),
                usesRig = routeJson.optBoolean("uses_rig", false),
                usesTools = routeJson.optBoolean("uses_tools", false),
                usesRag = routeJson.optBoolean("uses_rag", false),
                requiresUserChoice = routeJson.optBoolean("requires_user_choice", false),
            ),
            requiredCapabilities = root.optJSONArray("required_capabilities").toStrings(),
            blockers = root.optJSONArray("blockers").toStrings(),
            warnings = root.optJSONArray("warnings").toStrings(),
            proofs = Proofs(
                developerPreviewEvidence = proofsJson.optBoolean(
                    "developer_preview_evidence",
                    false,
                ),
                writePilotEvidence = proofsJson.optBoolean("write_pilot_evidence", false),
                capabilityGraphSchema = proofsJson.optString("capability_graph_schema"),
                capabilityGraphProductionActivation = proofsJson.optBoolean(
                    "capability_graph_production_activation",
                    true,
                ),
                actualSurfaceUnchanged = proofsJson.optBoolean(
                    "actual_surface_unchanged",
                    false,
                ),
            ),
            productionActivation = root.optBoolean("production_activation", true),
            executed = root.optBoolean("executed", true),
            planned = root.optBoolean("planned", true),
        )
        validate(input, result)
        return result
    }

    private fun validate(input: RequestInput, result: Preview) {
        if (result.schema != "kaliv-agent3-routing-preview/v1") {
            throw ModelRigException("Ukendt Agent 3.0 routing-preview schema: ${result.schema}")
        }
        if (result.selectedSurface != "agent_v2" || !result.proofs.actualSurfaceUnchanged) {
            throw ModelRigException("Ugyldig routing-preview: normal Agent v2-routing skal være uændret")
        }
        if (
            result.productionActivation ||
            result.proofs.capabilityGraphProductionActivation ||
            result.executed ||
            result.planned
        ) {
            throw ModelRigException(
                "Ugyldig routing-preview: preview må ikke aktivere, planlægge eller eksekvere"
            )
        }
        if (result.messageCharacters != input.message.length) {
            throw ModelRigException("Ugyldig routing-preview: beskedlængden matcher ikke")
        }
        if (result.messageSha256 != sha256(input.message)) {
            throw ModelRigException("Ugyldig routing-preview: message receipt matcher ikke")
        }
    }

    private fun execute(request: Request): JSONObject {
        http.newCall(request).execute().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                val detail = runCatching {
                    val root = JSONObject(text)
                    root.optString("error").ifBlank { root.optString("detail") }
                }.getOrNull()?.ifBlank { null } ?: text.take(500)
                throw ModelRigException(
                    "Agent 3.0 routing-preview fejlede (${response.code}): $detail"
                )
            }
            return runCatching { JSONObject(text) }
                .getOrElse {
                    throw ModelRigException("Agent 3.0 routing-preview returnerede ugyldig JSON")
                }
        }
    }

    private fun sha256(value: String): String = MessageDigest.getInstance("SHA-256")
        .digest(value.toByteArray(Charsets.UTF_8))
        .joinToString("") { byte -> "%02x".format(byte) }

    private fun JSONArray?.toStrings(): List<String> = buildList {
        val values = this@toStrings ?: return@buildList
        for (index in 0 until values.length()) {
            values.optString(index).takeIf { it.isNotBlank() }?.let(::add)
        }
    }

    private fun JSONObject.nullableString(name: String): String? =
        if (!has(name) || isNull(name)) null else optString(name).ifBlank { null }
}
