package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

/**
 * Client for the ModelRig backend's tools + pairing endpoints. Ported 1:1 from
 * the Android client's shapes (ModelRigClient.kt) so both clients speak the
 * exact same protocol -- v1.35.0, the desktop-love release: this is what puts
 * the V5 agent layer (card + audit) on the desktop.
 *
 * Deliberately non-streaming, like Android's tools path: the worker must see
 * the WHOLE response to decide whether a tool is being called.
 */
@Serializable
private data class PairStartResponse(val code: String = "")

@Serializable
private data class PairClaimRequest(val device_name: String, val code: String)

@Serializable
private data class PairClaimResponse(val token: String = "")

@Serializable
private data class ToolMsg(val role: String, val content: String)

@Serializable
private data class ToolChatRequest(
    val message: String,
    val model: String? = null,
    val history: List<ToolMsg> = emptyList(),
    val system: String? = null,
    val conversation_id: String? = null,
)

@Serializable
private data class ToolConfirmRequest(val confirmation_id: String, val decision: String)

@Serializable
data class ToolTurn(
    val status: String = "",
    val answer: String = "",
    val confirmation_id: String = "",
    val summary: String = "",
    val tool: String = "",
)

@Serializable
data class AuditEntry(
    val ts: String = "",
    val tool: String = "",
    val risk: String = "",
    val outcome: String = "",
    val origin: String = "local",
    val result_summary: String = "",
)

@Serializable
private data class AuditResponse(val entries: List<AuditEntry> = emptyList())

class ToolsException(message: String) : RuntimeException(message)

class ToolsClient(baseUrl: String, private val bearer: String?) {
    private val base = baseUrl.trimEnd('/')
    private val json = Json { ignoreUnknownKeys = true; encodeDefaults = false }
    private val http: HttpClient = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(10))
        .build()

    private fun builder(path: String): HttpRequest.Builder {
        val b = HttpRequest.newBuilder(URI.create("$base$path"))
            .header("Content-Type", "application/json")
            // The tools turn is non-streaming and the model may be cold --
            // mirror the app's generous voiceHttp budget, not the 120s chat one.
            .timeout(Duration.ofMinutes(5))
        if (!bearer.isNullOrBlank()) b.header("Authorization", "Bearer $bearer")
        return b
    }

    /** Dev-mode pairing: start -> code -> claim -> token, in one call.
     *  Mirrors the phone flow; MODELRIG_ADMIN_KEY-protected rigs will reject
     *  the open start, which surfaces as the thrown error text. */
    fun pair(deviceName: String): String {
        val startReq = builder("/api/v1/pair/start")
            .POST(HttpRequest.BodyPublishers.ofString("{}"))
            .build()
        val startResp = http.send(startReq, HttpResponse.BodyHandlers.ofString())
        if (startResp.statusCode() !in 200..299)
            throw ToolsException("pair/start failed (${startResp.statusCode()}): ${startResp.body().take(200)}")
        val code = json.decodeFromString<PairStartResponse>(startResp.body()).code
        if (code.isEmpty()) throw ToolsException("pair/start returned no code")

        val claimBody = json.encodeToString(PairClaimRequest(device_name = deviceName, code = code))
        val claimReq = builder("/api/v1/pair/claim")
            .POST(HttpRequest.BodyPublishers.ofString(claimBody))
            .build()
        val claimResp = http.send(claimReq, HttpResponse.BodyHandlers.ofString())
        if (claimResp.statusCode() !in 200..299)
            throw ToolsException("pair/claim failed (${claimResp.statusCode()}): ${claimResp.body().take(200)}")
        val token = json.decodeFromString<PairClaimResponse>(claimResp.body()).token
        if (token.isEmpty()) throw ToolsException("pairing response missing token")
        return token
    }

    fun toolsChat(
        message: String,
        model: String?,
        history: List<Pair<String, String>>,
        system: String?,
    ): ToolTurn {
        val body = json.encodeToString(
            ToolChatRequest(
                message = message,
                model = model,
                history = history.map { ToolMsg(it.first, it.second) },
                system = system?.takeIf { it.isNotBlank() },
            ),
        )
        val req = builder("/api/v1/tools/chat")
            .POST(HttpRequest.BodyPublishers.ofString(body))
            .build()
        val resp = http.send(req, HttpResponse.BodyHandlers.ofString())
        if (resp.statusCode() !in 200..299)
            throw ToolsException("tools chat failed (${resp.statusCode()}): ${resp.body().take(300)}")
        return json.decodeFromString<ToolTurn>(resp.body())
    }

    /** 409 = already used, 410 = expired -- both surface as thrown text, the
     *  UI shows them honestly instead of pretending. */
    fun toolsConfirm(confirmationId: String, approve: Boolean): ToolTurn {
        val body = json.encodeToString(
            ToolConfirmRequest(confirmation_id = confirmationId,
                               decision = if (approve) "approve" else "deny"),
        )
        val req = builder("/api/v1/tools/confirm")
            .POST(HttpRequest.BodyPublishers.ofString(body))
            .build()
        val resp = http.send(req, HttpResponse.BodyHandlers.ofString())
        if (resp.statusCode() !in 200..299)
            throw ToolsException("tools confirm failed (${resp.statusCode()}): ${resp.body().take(300)}")
        return json.decodeFromString<ToolTurn>(resp.body())
    }

    fun toolsAudit(limit: Int = 50): List<AuditEntry> {
        val req = builder("/api/v1/tools/audit?limit=$limit").GET().build()
        val resp = http.send(req, HttpResponse.BodyHandlers.ofString())
        if (resp.statusCode() !in 200..299)
            throw ToolsException("tools audit failed (${resp.statusCode()}): ${resp.body().take(200)}")
        return json.decodeFromString<AuditResponse>(resp.body()).entries
    }
}
