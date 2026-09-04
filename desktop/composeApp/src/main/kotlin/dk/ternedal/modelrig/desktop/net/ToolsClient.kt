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
data class ToolStreamLine(
    // Praecis een af dem er sat pr. linje. Alle tre er nullable, saa en linje
    // vi ikke kender endnu bliver en tom ToolStreamLine og ignoreres -- nye
    // linjetyper fra en nyere worker maa ikke braekke en aeldre klient.
    val phase: String? = null,
    val result: ToolTurn? = null,
    val error: String? = null,
)

@Serializable
data class ToolTurn(
    val status: String = "",
    val answer: String = "",
    val confirmation_id: String = "",
    val summary: String = "",
    val tool: String = "",
    // The card's own classification. `risk` is too coarse to warn with --
    // note_append, delete_model and pull_model are all risk=write -- so the
    // worker states `impact` (write / destructive / admin) and the client no
    // longer has to keep a tool-name table that goes stale.
    val risk: String = "",
    val impact: String = "",
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

    /**
     * Minter EN parringskode uden at bruge den — koden er til en ANDEN enhed
     * (telefonen), som selv claimer den. Desktop'en maa altsaa ikke gaa videre
     * til /pair/claim her; goer den det, er koden brugt op inden telefonen ser
     * den.
     */
    fun mintPairingCode(): String {
        val startReq = builder("/api/v1/pair/start")
            .POST(HttpRequest.BodyPublishers.ofString("{}"))
            .build()
        val resp = http.send(startReq, HttpResponse.BodyHandlers.ofString())
        if (resp.statusCode() !in 200..299)
            throw ToolsException("pair/start failed (${resp.statusCode()}): ${resp.body().take(200)}")
        val code = json.decodeFromString<PairStartResponse>(resp.body()).code
        if (code.isEmpty()) throw ToolsException("pair/start returned no code")
        return code
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

    /**
     * Samme tur som [toolsChat], men riggen fortaeller undervejs hvad den laver.
     *
     * En vaerktoejstur kan tage lang tid -- modellen taenker, et vaerktoej
     * koerer, modellen taenker igen -- og med det gamle endpoint sker alt det
     * bag en lukket doer: brugeren ser een statisk tekst og ingen tegn paa liv
     * foer svaret lander. Her kommer fasen loebende.
     *
     * [onPhase] kaldes paa laesetraaden, ikke paa UI-traaden. Kalderen laegger
     * selv opdateringen over paa sin egen scope.
     *
     * Fail-closed som resten af stroem-laeserne: en udtoemt stroem UDEN en
     * resultatlinje er en fejl, ikke en tom succes. Et droppet socket afslutter
     * body'en praecis som en faerdig tur, saa fravaeret af resultatet er det
     * eneste der skelner dem.
     */
    fun toolsChatStream(
        message: String,
        model: String?,
        history: List<Pair<String, String>>,
        system: String?,
        onPhase: (String) -> Unit = {},
    ): ToolTurn {
        val body = json.encodeToString(
            ToolChatRequest(
                message = message,
                model = model,
                history = history.map { ToolMsg(it.first, it.second) },
                system = system?.takeIf { it.isNotBlank() },
            ),
        )
        val req = builder("/api/v1/tools/chat/stream")
            .POST(HttpRequest.BodyPublishers.ofString(body))
            .build()
        val resp = http.send(req, HttpResponse.BodyHandlers.ofLines())
        if (resp.statusCode() !in 200..299)
            throw ToolsException("tools chat failed (${resp.statusCode()})")
        var turn: ToolTurn? = null
        resp.body().forEach { line ->
            if (line.isBlank()) return@forEach
            runCatching {
                json.decodeFromString(ToolStreamLine.serializer(), line)
            }.getOrNull()?.let { parsed ->
                when {
                    parsed.error != null ->
                        throw ToolsException("tools chat: ${parsed.error}")
                    parsed.result != null -> turn = parsed.result
                    parsed.phase != null -> onPhase(parsed.phase)
                }
            }
        }
        return turn ?: throw ToolsException(
            "vaerktoejsturen blev afbrudt undervejs — forbindelsen lukkede før riggen var færdig; prøv igen",
        )
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
