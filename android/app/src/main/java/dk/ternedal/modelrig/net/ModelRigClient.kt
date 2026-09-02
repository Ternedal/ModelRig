package dk.ternedal.modelrig.net

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import dk.ternedal.modelrig.logic.StreamContract
import dk.ternedal.modelrig.logic.StreamEvent
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class ModelRigException(message: String) : RuntimeException(message)

/**
 * Client for the ModelRig backend. Two calls for V1:
 *   - claimPairing: POST /api/v1/pair/claim  (exchange a code for a device token)
 *   - chat:         POST /api/v1/chat         (backend proxies Ollama; non-streaming)
 *
 * Blocking OkHttp — always call from a background dispatcher (Dispatchers.IO).
 */
class ModelRigClient(baseUrl: String, private val token: String? = null) {

    private val base = baseUrl.trimEnd('/')

    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .build()

    /**
     * Voice turns need a much longer read timeout than text chat. The first
     * voice turn on a cold rig loads Whisper large-v3 into VRAM (~2.5 GB, tens
     * of seconds), THEN runs the LLM, THEN synthesizes speech -- easily past
     * the 120s chat timeout. Confirmed on Anders' phone 2026-07-09: the first
     * turn died with "Software caused connection abort" while the rig was still
     * working. Subsequent turns are much faster (models stay cached), but the
     * first one must be allowed to finish.
     */
    /** Fast reachability probe: GET /healthz with a 3s budget. Used to fail
     *  fast and degrade honestly when the rig cannot be reached from the phone
     *  -- e.g. cloud+tools on 4G with Tailscale off, where the normal client
     *  hangs its full read timeout on a blackholed tailnet route (on-device
     *  14/7). False on ANY failure; never throws. */
    fun quickHealth(): Boolean = try {
        val quick = OkHttpClient.Builder()
            .connectTimeout(3, TimeUnit.SECONDS)
            .readTimeout(3, TimeUnit.SECONDS)
            .build()
        quick.newCall(Request.Builder().url("$base/healthz").get().build())
            .execute().use { it.isSuccessful }
    } catch (_: Exception) {
        false
    }

    /**
     * Riggens egne evner: GET /capabilities. Kaldes ved connect, saa fladen kan
     * gate paa hvad den TILSLUTTEDE worker kan i stedet for at vise en knap der
     * fejler naar man trykker.
     *
     * Kaster ALDRIG og returnerer [WorkerCapabilities.UNKNOWN] paa enhver fejl.
     * Et capability-probe der fejler maa ikke vaelte en forbindelse der virker,
     * og UNKNOWN betyder "alt tilgaengeligt" -- se WorkerCapabilities.
     * Endpointet er ugatet og billigt (kun import-checks), derfor eget korte
     * budget frem for det fulde laesetimeout.
     */
    fun workerCapabilities(): WorkerCapabilities = try {
        val quick = OkHttpClient.Builder()
            .connectTimeout(3, TimeUnit.SECONDS)
            .readTimeout(3, TimeUnit.SECONDS)
            .build()
        val rb = Request.Builder().url("$base/capabilities").get()
        token?.let { rb.header("Authorization", "Bearer $it") }
        quick.newCall(rb.build()).execute().use { resp ->
            if (!resp.isSuccessful) WorkerCapabilities.UNKNOWN
            else WorkerCapabilities.parse(resp.body?.string())
        }
    } catch (_: Exception) {
        WorkerCapabilities.UNKNOWN
    }

    private val voiceHttp = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.MINUTES)
        .writeTimeout(2, TimeUnit.MINUTES)  // uploading base64 audio
        .build()

    private val jsonType = "application/json".toMediaType()

    /** Parringssvaret bærer også enhedens id — det bruges til at kende DENNE enhed i enhedslisten. */
    data class Pairing(val token: String, val deviceId: String?)

    /** En parret enhed set fra /api/v1/devices (uden token-hash — den forlader aldrig riggen). */
    data class PairedDevice(
        val id: String,
        val name: String,
        val createdAt: String?,
        val lastSeen: String?,
    )

    fun claimPairing(deviceName: String, code: String): Pairing {
        val body = JSONObject()
            .put("device_name", deviceName)
            .put("code", code)
            .toString()
            .toRequestBody(jsonType)

        val req = Request.Builder()
            .url("$base/api/v1/pair/claim")
            .post(body)
            .build()

        http.newCall(req).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                throw ModelRigException("pairing failed (${resp.code}): $text")
            }
            val root = JSONObject(text)
            val tok = root.optString("token")
            if (tok.isEmpty()) throw ModelRigException("pairing response missing token")
            return Pairing(tok, root.optString("device_id").takeIf { it.isNotEmpty() })
        }
    }

    fun chat(model: String, messages: List<Pair<String, String>>): String {
        val arr = JSONArray()
        for ((role, content) in messages) {
            arr.put(JSONObject().put("role", role).put("content", content))
        }
        val body = JSONObject()
            .put("model", model)
            .put("messages", arr)
            .put("stream", false)
            .toString()
            .toRequestBody(jsonType)

        val builder = Request.Builder()
            .url("$base/api/v1/chat")
            .post(body)
        token?.let { builder.header("Authorization", "Bearer $it") }

        http.newCall(builder.build()).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                throw ModelRigException("chat failed (${resp.code}): $text")
            }
            return JSONObject(text).optJSONObject("message")?.optString("content").orEmpty()
        }
    }

    /**
     * Kaliv Voice: whether ASR/TTS are enabled on the rig. Returns the parsed
     * status object, or throws. Lets the UI tell the user to install the Voice
     * backends before recording (rather than failing mid-turn).
     */
    fun voiceStatus(): JSONObject {
        val builder = Request.Builder().url("$base/api/v1/voice/status").get()
        token?.let { builder.header("Authorization", "Bearer $it") }
        http.newCall(builder.build()).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ModelRigException("voice status failed (${resp.code}): $text")
            return JSONObject(text)
        }
    }

    /**
     * Kaliv Voice: one spoken turn. Uploads recorded audio (base64 WAV, 16 kHz
     * mono) to the rig, which runs ASR -> LLM -> TTS and returns the transcript,
     * the reply text, and a combined reply WAV (base64) to play back. Voice runs
     * on the rig (that's where ASR/TTS live), so it needs the rig reachable --
     * there's no cloud fallback for voice, unlike text chat.
     *
     * cloudBaseUrl/cloudKey optionally move ONLY the LLM step to Ollama Cloud,
     * so a spoken question can be answered by a large model (e.g. kimi-k2.6)
     * that a 12 GB GPU can't host. ASR and TTS stay local either way. The key
     * goes to the user's own rig over their LAN and isn't stored there.
     *
     * Returns {transcript, reply, audio_base64, time_to_first_audio_s}.
     */
    /**
     * Streaming voice turn: reads the worker's NDJSON (one JSON object per line)
     * and dispatches by "type": onTranscript once (ASR text), onChunk per spoken
     * sentence (with base64 audio to play now), onDone at the end, onError on a
     * pipeline failure. This lets the app start speaking the first sentence while
     * the rest is still generating -- the cure for the buffered endpoint's latency
     * with big cloud models. registerCall hands back the OkHttp Call so the UI can
     * cancel (barge-in / stop).
     */
    fun voiceConverseStream(
        audioB64: String,
        language: String = "da",
        model: String? = null,
        cloudBaseUrl: String? = null,
        cloudKey: String? = null,
        registerCall: ((okhttp3.Call) -> Unit)? = null,
        onTranscript: (String) -> Unit,
        onChunk: (index: Int, text: String, audioB64: String) -> Unit,
        onDone: (reply: String, model: String?, viaCloud: Boolean) -> Unit,
        onError: (status: Int, detail: String) -> Unit,
    ) {
        val payload = JSONObject().put("audio_base64", audioB64).put("language", language)
        if (model != null) payload.put("model", model)
        if (cloudBaseUrl != null && cloudKey != null) {
            payload.put("llm_base_url", cloudBaseUrl)
            payload.put("llm_api_key", cloudKey)
        }
        val body = payload.toString().toRequestBody(jsonType)
        val builder = Request.Builder().url("$base/api/v1/voice/converse/stream").post(body)
        token?.let { builder.header("Authorization", "Bearer $it") }
        val call = voiceHttp.newCall(builder.build())
        registerCall?.invoke(call)
        call.execute().use { resp ->
            if (!resp.isSuccessful) {
                val text = resp.body?.string().orEmpty()
                throw ModelRigException("voice stream failed (${resp.code}): $text")
            }
            val source = resp.body?.source() ?: throw ModelRigException("empty response body")
            // Voice had the worst version of the bug: if the stream ended
            // without "done", NO callback fired at all -- not onDone, not
            // onError -- so the turn just hung there spinning.
            var sawTerminal = false
            while (!source.exhausted()) {
                val line = source.readUtf8Line() ?: break
                when (val ev = StreamContract.parse(line)) {
                    is StreamEvent.Phase -> Unit  // stemmestroemmen udsender ingen faser endnu
                    is StreamEvent.Transcript -> onTranscript(ev.text)
                    is StreamEvent.Chunk -> onChunk(ev.index, ev.text, ev.audioB64)
                    is StreamEvent.Done -> {
                        sawTerminal = true
                        onDone(ev.reply, ev.model, ev.viaCloud)
                    }
                    is StreamEvent.Failure -> {
                        sawTerminal = true
                        onError(ev.status, ev.message)
                    }
                    else -> {}
                }
            }
            if (!sawTerminal) {
                throw ModelRigException(
                    "stemmesvaret blev afbrudt — forbindelsen lukkede før riggen var færdig; prøv igen"
                )
            }
        }
    }

    fun voiceConverse(
        audioB64: String,
        language: String = "da",
        model: String? = null,
        cloudBaseUrl: String? = null,
        cloudKey: String? = null,
    ): JSONObject {
        val payload = JSONObject().put("audio_base64", audioB64).put("language", language)
        if (model != null) payload.put("model", model)
        if (cloudBaseUrl != null && cloudKey != null) {
            payload.put("llm_base_url", cloudBaseUrl)
            payload.put("llm_api_key", cloudKey)
        }
        val body = payload.toString().toRequestBody(jsonType)
        val builder = Request.Builder().url("$base/api/v1/voice/converse").post(body)
        token?.let { builder.header("Authorization", "Bearer $it") }
        voiceHttp.newCall(builder.build()).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ModelRigException("voice failed (${resp.code}): $text")
            return JSONObject(text)
        }
    }

    /**
     * Streaming chat: invokes onDelta per NDJSON token chunk as it arrives.
     * `registerCall` (optional) hands back the underlying OkHttp Call so the UI
     * can cancel an in-flight generation (Stop button). Cancelling makes the
     * blocking read throw, which ends the stream cleanly.
     */
    fun chatStream(
        model: String,
        messages: List<Pair<String, String>>,
        registerCall: ((okhttp3.Call) -> Unit)? = null,
        imageB64: String? = null,
        onDelta: (String) -> Unit,
    ) {
        val arr = JSONArray()
        for ((i, m) in messages.withIndex()) {
            val (role, content) = m
            val msg = JSONObject().put("role", role).put("content", content)
            // Vision: attach base64 image to the current (last) user message
            // only. The backend forwards it to Ollama unchanged. Requires a
            // vision-capable model pulled on the rig (e.g. llama3.2-vision).
            if (imageB64 != null && i == messages.lastIndex && role == "user") {
                msg.put("images", JSONArray().put(imageB64))
            }
            arr.put(msg)
        }
        val body = JSONObject()
            .put("model", model)
            .put("messages", arr)
            .put("stream", true)
            .toString()
            .toRequestBody(jsonType)

        val builder = Request.Builder().url("$base/api/v1/chat").post(body)
        token?.let { builder.header("Authorization", "Bearer $it") }

        val call = http.newCall(builder.build())
        registerCall?.invoke(call)
        call.execute().use { resp ->
            if (!resp.isSuccessful) {
                throw ModelRigException("chat failed (${resp.code}): ${resp.body?.string().orEmpty()}")
            }
            val source = resp.body?.source() ?: throw ModelRigException("empty response body")
            // One contract for every stream (StreamContract): the body running
            // out is not completion -- a proxy timeout ends it identically --
            // and an in-stream {"error"} line is a failure, not an empty delta
            // to drop on the floor. Both bit here before 1.58.49.
            var sawDone = false
            var sawContent = false
            while (!source.exhausted()) {
                val line = source.readUtf8Line() ?: break
                when (val ev = StreamContract.parse(line)) {
                    is StreamEvent.Delta -> { sawContent = true; onDelta(ev.text) }
                    is StreamEvent.Done -> {
                        if (ev.trailingDelta.isNotEmpty()) { sawContent = true; onDelta(ev.trailingDelta) }
                        sawDone = true
                    }
                    is StreamEvent.Failure -> throw ModelRigException("chat: ${ev.message}")
                    else -> {}
                }
            }
            StreamContract.terminalFailure(sawDone, sawContent)?.let { throw ModelRigException(it) }
        }
    }

    /**
     * RAG chat: retrieval-augmented answer over ingested sources, streamed.
     * The first NDJSON line is `{"sources":[{"source","chunk_index","score"}]}`,
     * reported via onSources before any content deltas. `sourceFilter` narrows
     * retrieval to one ingested source name; null searches all sources.
     */
    fun ragChatStream(
        query: String,
        model: String?,
        sourceFilter: String?,
        registerCall: ((okhttp3.Call) -> Unit)? = null,
        onSources: (List<String>) -> Unit,
        onDelta: (String) -> Unit,
        onPhase: (String) -> Unit = {},
    ) {
        val body = JSONObject()
            .put("query", query)
            .put("top_k", 4)
            .apply {
                if (model != null) put("model", model)
                if (sourceFilter != null) put("source", sourceFilter)
            }
            .toString()
            .toRequestBody(jsonType)

        val builder = Request.Builder().url("$base/api/v1/rag/chat").post(body)
        token?.let { builder.header("Authorization", "Bearer $it") }

        val call = http.newCall(builder.build())
        registerCall?.invoke(call)
        call.execute().use { resp ->
            if (!resp.isSuccessful) {
                throw ModelRigException("rag chat failed (${resp.code}): ${resp.body?.string().orEmpty()}")
            }
            val source = resp.body?.source() ?: throw ModelRigException("empty response body")
            // The sources header is now recognised by SHAPE, not by position --
            // it was "the first line", which quietly meant a stream that opened
            // with anything else lost its header handling.
            var sawDone = false
            var sawContent = false
            while (!source.exhausted()) {
                val line = source.readUtf8Line() ?: break
                when (val ev = StreamContract.parse(line)) {
                    is StreamEvent.Sources -> onSources(ev.names)
                    // En fase er IKKE indhold: sawContent bliver staaende, saa
                    // en stroem der kun naaede at annoncere en fase rapporteres
                    // som "aldrig startet", ikke som "afbrudt undervejs".
                    is StreamEvent.Phase -> onPhase(ev.name)
                    is StreamEvent.Delta -> { sawContent = true; onDelta(ev.text) }
                    is StreamEvent.Done -> {
                        if (ev.trailingDelta.isNotEmpty()) { sawContent = true; onDelta(ev.trailingDelta) }
                        sawDone = true
                    }
                    is StreamEvent.Failure -> throw ModelRigException("rag chat: ${ev.message}")
                    else -> {}
                }
            }
            StreamContract.terminalFailure(sawDone, sawContent)?.let { throw ModelRigException(it) }
        }
    }

    /**
     * En RAG-kilde med rigens egne tal: antal udsnit og hvornår den sidst
     * blev indekseret. Begge felter HAR ligget i /rag/sources hele tiden —
     * klienten smed dem bare væk før nu.
     */
    data class RagSource(
        val name: String,
        val chunks: Int,
        val lastIngestedAt: Double?,
        /**
         * Om kilden må hentes fra. Ældre rigge kender ikke feltet — så regnes
         * kilden som TÆNDT, hvilket er præcis den adfærd de faktisk har.
         */
        val enabled: Boolean = true,
    )

    /** Kilder med tal. Rækkefølgen er rigens: nyest indekseret først. */
    fun listRagSourceDetails(): List<RagSource> {
        val rb = Request.Builder().url("$base/api/v1/rag/sources")
        token?.let { rb.header("Authorization", "Bearer $it") }
        http.newCall(rb.build()).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ModelRigException("rag sources failed (${resp.code}): $text")
            val arr = JSONObject(text).optJSONArray("sources") ?: return emptyList()
            val out = ArrayList<RagSource>(arr.length())
            for (i in 0 until arr.length()) {
                val o = arr.optJSONObject(i) ?: continue
                val name = o.optString("source")
                if (name.isEmpty()) continue
                out.add(
                    RagSource(
                        name = name,
                        chunks = o.optInt("chunks", 0),
                        lastIngestedAt = if (o.isNull("last_ingested_at")) null else o.optDouble("last_ingested_at"),
                        enabled = o.optBoolean("enabled", true),
                    ),
                )
            }
            return out
        }
    }

    /**
     * Tænder eller slukker for hentning fra én kilde.
     *
     * Sletter intet: chunksene bliver, og kontakten kan vippes tilbage.
     * Returnerer RIGGENS tilstand bagefter — klienten antager aldrig at dens
     * egen skrivning lykkedes.
     */
    fun setRagSourceEnabled(source: String, enabled: Boolean): Boolean {
        val payload = JSONObject().put("source", source).put("enabled", enabled)
        val rb = Request.Builder()
            .url("$base/api/v1/rag/source/enabled")
            .post(payload.toString().toRequestBody(jsonType))
        token?.let { rb.header("Authorization", "Bearer $it") }
        http.newCall(rb.build()).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ModelRigException("rag source toggle failed (${resp.code}): $text")
            return JSONObject(text).optBoolean("enabled", enabled)
        }
    }

    /**
     * Fjerner ALLE udsnit for en kilde og returnerer hvor mange der blev slettet.
     * Riggen svarer 404 hvis kilden ikke har nogen udsnit — det er ikke en
     * stille succes, og kaldet kaster derfor også dér.
     */
    fun deleteRagSource(source: String): Int {
        val encoded = java.net.URLEncoder.encode(source, "UTF-8")
        val rb = Request.Builder().url("$base/api/v1/rag/source?source=$encoded").delete()
        token?.let { rb.header("Authorization", "Bearer $it") }
        http.newCall(rb.build()).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ModelRigException("rag delete failed (${resp.code}): $text")
            return JSONObject(text).optInt("removed", 0)
        }
    }

    /** Lists ingested RAG source names (for the source-filter picker). */
    fun listRagSources(): List<String> {
        val rb = Request.Builder().url("$base/api/v1/rag/sources")
        token?.let { rb.header("Authorization", "Bearer $it") }
        http.newCall(rb.build()).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ModelRigException("rag sources failed (${resp.code}): $text")
            val arr = JSONObject(text).optJSONArray("sources") ?: return emptyList()
            val out = mutableListOf<String>()
            for (i in 0 until arr.length()) {
                val name = arr.optJSONObject(i)?.optString("source").orEmpty()
                if (name.isNotEmpty()) out.add(name)
            }
            return out
        }
    }

    /** Lists available model names via the backend's /api/v1/models. */
    /**
     * Actually checks the rig responds, rather than trusting that a URL and
     * token are stored. GET /healthz is unauthenticated, so this works even if
     * the token has gone stale. Short timeout: this is a liveness check, not a
     * request that should hang the UI.
     *
     * Exists because "✓ forbundet" used to mean only "a pairing is saved" --
     * Anders hit this on 2026-07-09: the app showed "forbundet" while every
     * message silently fell back to cloud, because the rig's IP had changed.
     */
    fun ping(): Boolean {
        return try {
            val pingHttp = OkHttpClient.Builder()
                .connectTimeout(3, TimeUnit.SECONDS)
                .readTimeout(3, TimeUnit.SECONDS)
                .build()
            val req = Request.Builder().url("$base/healthz").get().build()
            pingHttp.newCall(req).execute().use { it.isSuccessful }
        } catch (_: Exception) {
            false
        }
    }

    fun listModels(): List<String> {
        val rb = Request.Builder().url("$base/api/v1/models")
        token?.let { rb.header("Authorization", "Bearer $it") }
        http.newCall(rb.build()).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ModelRigException("models failed (${resp.code}): $text")
            val arr = JSONObject(text).optJSONArray("models") ?: return emptyList()
            val out = mutableListOf<String>()
            for (i in 0 until arr.length()) {
                val name = arr.optJSONObject(i)?.optString("name").orEmpty()
                if (name.isNotEmpty()) out.add(name)
            }
            return out
        }
    }

    data class ModelInfo(val name: String, val sizeBytes: Long)
    data class RunningModel(val name: String, val sizeVramBytes: Long, val expiresAt: String)

    /** Installed models with size, for the model-management screen (vs. listModels()'s plain names for the chat picker). */
    fun listModelsDetailed(): List<ModelInfo> {
        val rb = Request.Builder().url("$base/api/v1/models")
        token?.let { rb.header("Authorization", "Bearer $it") }
        http.newCall(rb.build()).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ModelRigException("models failed (${resp.code}): $text")
            val arr = JSONObject(text).optJSONArray("models") ?: return emptyList()
            val out = mutableListOf<ModelInfo>()
            for (i in 0 until arr.length()) {
                val o = arr.optJSONObject(i) ?: continue
                val name = o.optString("name")
                if (name.isNotEmpty()) out.add(ModelInfo(name, o.optLong("size", 0L)))
            }
            return out
        }
    }

    /** Models currently loaded in memory (Ollama's /api/ps), with VRAM usage and expiry. */
    fun listRunningModels(): List<RunningModel> {
        val rb = Request.Builder().url("$base/api/v1/models/running")
        token?.let { rb.header("Authorization", "Bearer $it") }
        http.newCall(rb.build()).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ModelRigException("running models failed (${resp.code}): $text")
            val arr = JSONObject(text).optJSONArray("models") ?: return emptyList()
            val out = mutableListOf<RunningModel>()
            for (i in 0 until arr.length()) {
                val o = arr.optJSONObject(i) ?: continue
                val name = o.optString("name")
                if (name.isNotEmpty()) out.add(RunningModel(name, o.optLong("size_vram", 0L), o.optString("expires_at")))
            }
            return out
        }
    }

    /** Parrede enheder. Riggen udleverer aldrig token-hashes — kun id, navn og tidsstempler. */
    fun listDevices(): List<PairedDevice> {
        val rb = Request.Builder().url("$base/api/v1/devices")
        token?.let { rb.header("Authorization", "Bearer $it") }
        http.newCall(rb.build()).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ModelRigException("devices failed (${resp.code}): $text")
            val arr = JSONObject(text).optJSONArray("devices") ?: return emptyList()
            val out = ArrayList<PairedDevice>(arr.length())
            for (i in 0 until arr.length()) {
                val o = arr.optJSONObject(i) ?: continue
                val id = o.optString("id")
                if (id.isEmpty()) continue
                out.add(
                    PairedDevice(
                        id = id,
                        name = o.optString("name").ifEmpty { "Uden navn" },
                        createdAt = o.optString("created_at").takeIf { it.isNotEmpty() },
                        lastSeen = o.optString("last_seen").takeIf { it.isNotEmpty() },
                    ),
                )
            }
            return out
        }
    }

    /**
     * Fjerner en enheds adgang. Riggen slår enheden op i sit live-lager ved
     * HVERT kald, så et tilbagekaldt token holder op med at virke med det samme
     * — også midt i en igangværende session.
     */
    fun revokeDevice(deviceId: String) {
        val rb = Request.Builder().url("$base/api/v1/devices/$deviceId").delete()
        token?.let { rb.header("Authorization", "Bearer $it") }
        http.newCall(rb.build()).execute().use { resp ->
            if (!resp.isSuccessful) {
                throw ModelRigException("revoke failed (${resp.code}): ${resp.body?.string().orEmpty()}")
            }
        }
    }

    /**
     * Rig-side system measurement (B3a: GET /api/v1/system/status).
     * Every field is nullable on purpose: the endpoint is fail-soft and
     * reports null for anything it cannot measure (no nvidia-smi, unknown
     * OS), so the screen can say "ukendt" honestly instead of failing.
     */
    data class SystemStatus(
        val gpuName: String?,
        val gpuTempC: Int?,
        val gpuUtilPct: Int?,
        val vramTotalMb: Int?,
        val vramUsedMb: Int?,
        val vramFreeMb: Int?,
        val cpuPct: Double?,
        /** Backend-processens levetid i sekunder; null på rigge uden feltet. */
        val uptimeSeconds: Long?,
    )

    /** Resultatet af en VRAM-frigørelse: hvad riggen FAKTISK slap. */
    data class UnloadResult(val unloaded: List<String>, val freedBytes: Long, val failed: List<String>)

    /**
     * Beder riggen slippe alle indlæste modeller (Ollamas keep_alive=0).
     * Ingen processer genstartes; næste prompt indlæser modellen igen.
     * Kaster ved 404 fra ældre rigge — kalderen viser opgraderingsnoten.
     */
    fun unloadModels(): UnloadResult {
        val rb = Request.Builder()
            .url("$base/api/v1/models/unload")
            .post(ByteArray(0).toRequestBody(jsonType))
        token?.let { rb.header("Authorization", "Bearer $it") }
        http.newCall(rb.build()).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ModelRigException("unload failed (${resp.code}): $text")
            val root = JSONObject(text)
            val names = ArrayList<String>()
            root.optJSONArray("unloaded")?.let { arr ->
                for (i in 0 until arr.length()) {
                    arr.optJSONObject(i)?.optString("name")?.takeIf { it.isNotEmpty() }?.let(names::add)
                }
            }
            val failed = ArrayList<String>()
            root.optJSONArray("failed")?.let { arr ->
                for (i in 0 until arr.length()) {
                    arr.optString(i).takeIf { it.isNotEmpty() }?.let(failed::add)
                }
            }
            return UnloadResult(names, root.optLong("freed_bytes", 0L), failed)
        }
    }

    /** Throws when the rig predates the endpoint (404) — caller shows the upgrade hint. */
    fun systemStatus(): SystemStatus {
        val rb = Request.Builder().url("$base/api/v1/system/status")
        token?.let { rb.header("Authorization", "Bearer $it") }
        http.newCall(rb.build()).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ModelRigException("system status failed (${resp.code}): $text")
            val root = JSONObject(text)
            val gpu = root.optJSONObject("gpu")
            val cpu = root.optJSONObject("cpu")
            fun JSONObject?.intOrNull(key: String): Int? =
                if (this == null || !has(key) || isNull(key)) null else optInt(key)
            return SystemStatus(
                gpuName = gpu?.optString("name")?.takeIf { it.isNotEmpty() },
                gpuTempC = gpu.intOrNull("temperature_c"),
                gpuUtilPct = gpu.intOrNull("utilization_pct"),
                vramTotalMb = gpu.intOrNull("vram_total_mb"),
                vramUsedMb = gpu.intOrNull("vram_used_mb"),
                vramFreeMb = gpu.intOrNull("vram_free_mb"),
                cpuPct = if (cpu == null || !cpu.has("utilization_pct") || cpu.isNull("utilization_pct")) {
                    null
                } else {
                    cpu.optDouble("utilization_pct")
                },
                uptimeSeconds = if (!root.has("uptime_seconds") || root.isNull("uptime_seconds")) {
                    null
                } else {
                    root.optLong("uptime_seconds")
                },
            )
        }
    }

    /**
     * Pulls (downloads) a model, streaming Ollama's NDJSON progress lines back
     * via [onProgress] (status text, bytes completed, bytes total — total/
     * completed are 0 until the download phase reports them). Can take minutes
     * for a large model; pass [registerCall] to get the underlying OkHttp Call
     * so the caller can cancel it (same pattern as chatStream/ragChatStream).
     */
    fun pullModel(
        name: String,
        registerCall: ((okhttp3.Call) -> Unit)? = null,
        onProgress: (status: String, completed: Long, total: Long) -> Unit,
    ) {
        val body = JSONObject().put("model", name).toString().toRequestBody(jsonType)
        val builder = Request.Builder().url("$base/api/v1/models/pull").post(body)
        token?.let { builder.header("Authorization", "Bearer $it") }
        val call = http.newCall(builder.build())
        registerCall?.invoke(call)
        // Stream END is not success (audit 1.58.36 #7): a proxy timeout or a
        // dropped connection also ends the stream cleanly, and this function
        // used to return normally then -- the UI said "Færdig" for a model
        // that was never installed. Success now requires BOTH Ollama's final
        // {"status":"success"} line AND the model actually appearing in the
        // installed list afterwards.
        var sawSuccess = false
        call.execute().use { resp ->
            if (!resp.isSuccessful) {
                throw ModelRigException("pull failed (${resp.code}): ${resp.body?.string().orEmpty()}")
            }
            val source = resp.body?.source() ?: throw ModelRigException("empty response body")
            while (!source.exhausted()) {
                val line = source.readUtf8Line() ?: break
                if (line.isBlank()) continue
                runCatching {
                    val o = JSONObject(line)
                    val err = o.optString("error")
                    if (err.isNotEmpty()) throw ModelRigException("pull error: $err")
                    val st = o.optString("status")
                    if (st == "success") sawSuccess = true
                    onProgress(st, o.optLong("completed", 0L), o.optLong("total", 0L))
                }.onFailure { if (it is ModelRigException) throw it }
            }
        }
        if (!sawSuccess) {
            throw ModelRigException(
                "download-strømmen sluttede uden Ollamas 'success' — hentningen er IKKE fuldført (afbrudt forbindelse eller timeout). Prøv igen."
            )
        }
        // Verify: trust, but check the shelf. Ollama registers untagged names
        // as "<name>:latest".
        val installed = runCatching { listModels() }.getOrElse {
            throw ModelRigException("pull meldte succes, men verifikationen kunne ikke køre (${it.message}) — tjek modeloversigten manuelt")
        }
        if (name !in installed && "$name:latest" !in installed) {
            throw ModelRigException("pull meldte succes, men $name findes ikke i modeloversigten — tjek riggen")
        }
    }

    /** Deletes an installed model. Irreversible on the rig — confirm with the user before calling this. */
    fun deleteModel(name: String) {
        val body = JSONObject().put("model", name).toString().toRequestBody(jsonType)
        val builder = Request.Builder().url("$base/api/v1/models/delete").delete(body)
        token?.let { builder.header("Authorization", "Bearer $it") }
        http.newCall(builder.build()).execute().use { resp ->
            if (!resp.isSuccessful) {
                throw ModelRigException("delete failed (${resp.code}): ${resp.body?.string().orEmpty()}")
            }
        }
    }

    /**
     * Ingests one text document into the RAG index (worker's POST /rag/ingest,
     * body {"documents":[{"text","source"}]}). Plain JSON — the worker takes
     * text content, not a file upload, so the caller reads the file's text
     * itself first (see AppUi.kt's file-picker flow). txt/md content only;
     * no PDF/DOCX extraction on either side yet.
     */
    fun ingestText(source: String, text: String, chunkSize: Int = 800, overlap: Int = 150): IngestResult {
        val doc = JSONObject().put("text", text).put("source", source)
        val payload = JSONObject()
            .put("documents", JSONArray().put(doc))
            .put("chunk_size", chunkSize)
            .put("overlap", overlap)
            .toString()
            .toRequestBody(jsonType)
        val builder = Request.Builder().url("$base/api/v1/rag/ingest").post(payload)
        token?.let { builder.header("Authorization", "Bearer $it") }
        http.newCall(builder.build()).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ModelRigException("ingest failed (${resp.code}): $body")
            val o = JSONObject(body)
            return IngestResult(o.optInt("documents"), o.optInt("chunks_added"), o.optInt("total"))
        }
    }

data class IngestResult(val documents: Int, val chunksAdded: Int, val total: Int)

    /**
     * Ingests a PDF into the RAG index by uploading its bytes (base64) to the
     * rig, which extracts text with PyMuPDF and runs the same chunk/embed/store
     * pipeline as ingestText. Returns chunks added. The worker returns 501 if
     * PyMuPDF isn't installed, 422 if the PDF has no extractable text (a scan).
     */
    /**
     * One chat turn in which the rig's model may propose a tool (Kaliv Tools).
     *
     * Returns either an answer, or a proposal that has executed NOTHING and is
     * waiting for a human. The confirmation_id is opaque: the app cannot change
     * the arguments between the card and the execution, because it never sends
     * them again. The worker parked them.
     *
     * 403 when the tool layer is off on the rig.
     *
     * Pass cloudBaseUrl/cloudKey to have a CLOUD model do the proposing. Reads
     * still run without asking; writes still stop at the confirmation card.
     * Risk decides, not origin (Anders, 2026-07-10).
     */
    /**
     * Payload'en for en vaerktoejstur, delt af [toolsChat] og
     * [toolsChatStream]. Udtrukket saa de to indgange ikke kan drive fra
     * hinanden -- samme grund som paa riggen, hvor begge endpoints kalder
     * _tools_chat_turn.
     */
    private fun toolsChatPayload(
        message: String,
        model: String?,
        conversationId: String?,
        cloudBaseUrl: String?,
        cloudKey: String?,
        history: List<Pair<String, String>>,
        rag: Boolean,
        ragSource: String?,
        allowRagCloud: Boolean,
        imageB64: String?,
        system: String?,
    ): JSONObject {
        val payload = JSONObject().put("message", message)
        // Send the system prompt in its own field, not at the head of history.
        // The rig protects a leading system message when trimming, but an
        // explicit field cannot be crowded out by a long conversation at all.
        system?.takeIf { it.isNotBlank() }?.let { payload.put("system", it) }
        // Without history, turning Tools on made Kaliv amnesiac: "write down
        // what we just discussed" had nothing to write. The rig trims it again
        // on arrival; this is the polite bound, not the enforced one.
        if (history.isNotEmpty()) {
            val arr = JSONArray()
            for ((role, content) in history) {
                arr.put(JSONObject().put("role", role).put("content", content))
            }
            payload.put("history", arr)
        }
        // Tools used to silently discard document context. Both can be on.
        if (rag) {
            payload.put("rag", true)
            ragSource?.let { payload.put("rag_source", it) }
            // D4 consent: only sent when the user has explicitly allowed RAG
            // document content to reach a cloud model this session. Default off
            // -> the rig refuses RAG+cloud and keeps document content local.
            if (allowRagCloud) payload.put("allow_rag_cloud", true)
        }
        // An attached image used to vanish the moment Tools was on.
        imageB64?.let { payload.put("image_base64", it) }
        if (model != null) payload.put("model", model)
        if (conversationId != null) payload.put("conversation_id", conversationId)
        // Routing a cloud model THROUGH the rig is the only way it can propose
        // a tool: the app's direct CloudClient never touches the worker, so the
        // gate isn't there to bypass. The key is sent per request and never
        // persisted on the rig -- same contract as voice.
        if (cloudBaseUrl != null && cloudKey != null) {
            payload.put("cloud_base_url", cloudBaseUrl)
            payload.put("cloud_key", cloudKey)
        }
        return payload
    }

    fun toolsChat(
        message: String,
        model: String? = null,
        conversationId: String? = null,
        cloudBaseUrl: String? = null,
        cloudKey: String? = null,
        history: List<Pair<String, String>> = emptyList(),
        rag: Boolean = false,
        ragSource: String? = null,
        allowRagCloud: Boolean = false,
        imageB64: String? = null,
        system: String? = null,
    ): ToolTurn {
        val payload = toolsChatPayload(message, model, conversationId, cloudBaseUrl,
            cloudKey, history, rag, ragSource, allowRagCloud, imageB64, system)
        val builder = Request.Builder().url("$base/api/v1/tools/chat")
            .post(payload.toString().toRequestBody(jsonType))
        token?.let { builder.header("Authorization", "Bearer $it") }
        // Long timeout: this is an LLM turn, possibly two.
        voiceHttp.newCall(builder.build()).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ModelRigException("tools chat failed (${resp.code}): $body")
            return parseToolTurn(JSONObject(body))
        }
    }

    /**
     * Samme tur som [toolsChat], men riggen fortaeller undervejs hvad den laver.
     *
     * En vaerktoejstur er lang -- modellen taenker, et vaerktoej koerer,
     * modellen taenker igen -- og med det gamle endpoint sker alt det bag en
     * lukket doer: een statisk tekst og ingen tegn paa liv foer svaret lander.
     *
     * [onPhase] kaldes paa netvaerkstraaden; kalderen laegger selv opdateringen
     * over paa UI-traaden.
     *
     * Fail-closed som de tre andre stroem-laesere her: en udtoemt stroem UDEN
     * en resultatlinje er en fejl, ikke en tom succes. Et droppet socket
     * afslutter body'en praecis som en faerdig tur.
     */
    fun toolsChatStream(
        message: String,
        model: String? = null,
        conversationId: String? = null,
        cloudBaseUrl: String? = null,
        cloudKey: String? = null,
        history: List<Pair<String, String>> = emptyList(),
        rag: Boolean = false,
        ragSource: String? = null,
        allowRagCloud: Boolean = false,
        imageB64: String? = null,
        system: String? = null,
        registerCall: ((okhttp3.Call) -> Unit)? = null,
        onPhase: (String) -> Unit = {},
    ): ToolTurn {
        val payload = toolsChatPayload(message, model, conversationId, cloudBaseUrl,
            cloudKey, history, rag, ragSource, allowRagCloud, imageB64, system)
        val builder = Request.Builder().url("$base/api/v1/tools/chat/stream")
            .post(payload.toString().toRequestBody(jsonType))
        token?.let { builder.header("Authorization", "Bearer $it") }
        val call = voiceHttp.newCall(builder.build())
        registerCall?.invoke(call)
        call.execute().use { resp ->
            if (!resp.isSuccessful) {
                val body = resp.body?.string().orEmpty()
                throw ModelRigException("tools chat failed (${resp.code}): $body")
            }
            val source = resp.body?.source() ?: throw ModelRigException("tom stream")
            var turn: ToolTurn? = null
            while (!source.exhausted()) {
                val line = source.readUtf8Line() ?: break
                if (line.isBlank()) continue
                val o = runCatching { JSONObject(line) }.getOrNull() ?: continue
                val err = o.optString("error")
                if (err.isNotEmpty()) throw ModelRigException("tools chat: $err")
                o.optJSONObject("result")?.let { turn = parseToolTurn(it); return@let }
                val phase = o.optString("phase")
                if (phase.isNotEmpty()) onPhase(phase)
            }
            return turn ?: throw ModelRigException(
                "værktøjsturen blev afbrudt undervejs — forbindelsen lukkede før riggen var færdig; prøv igen",
            )
        }
    }

    /**
     * Approve or deny a pending write. The rig executes exactly the arguments
     * it showed on the card, then phrases the answer.
     *
     * 409 if the confirmation was already used, 410 if it expired. Both are
     * refusals -- a timeout is never an acceptance.
     */
    fun toolsConfirm(confirmationId: String, approve: Boolean): ToolTurn {
        val payload = JSONObject()
            .put("confirmation_id", confirmationId)
            .put("decision", if (approve) "approve" else "deny")
        val builder = Request.Builder().url("$base/api/v1/tools/confirm")
            .post(payload.toString().toRequestBody(jsonType))
        token?.let { builder.header("Authorization", "Bearer $it") }
        voiceHttp.newCall(builder.build()).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ModelRigException("confirm failed (${resp.code}): $body")
            return parseToolTurn(JSONObject(body))
        }
    }

    /** Whether the rig has the tool layer switched on, and which tools exist. */
    fun toolsEnabled(): Boolean = toolsList().enabled

    /** The registry as the rig reports it: the kill switch, and each tool. */
    fun toolsList(): ToolRegistry {
        val builder = Request.Builder().url("$base/api/v1/tools").get()
        token?.let { builder.header("Authorization", "Bearer $it") }
        http.newCall(builder.build()).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ModelRigException("tools list failed (${resp.code}): $body")
            return parseRegistry(JSONObject(body))
        }
    }

    /**
     * The kill switch, reachable from the phone.
     *
     * Omit [tool] to switch the whole layer off. Until now this only existed as
     * an env var on the rig, so stopping a misbehaving tool meant killing the
     * worker and restarting it -- the wrong way round for an emergency brake.
     *
     * Turning a tool OFF also un-advertises it: the model is no longer told it
     * exists, so it cannot suggest re-enabling it.
     */
    fun setToolsEnabled(enabled: Boolean, tool: String? = null): ToolRegistry {
        val payload = JSONObject().put("enabled", enabled)
        if (tool != null) payload.put("tool", tool)
        val builder = Request.Builder().url("$base/api/v1/tools/enabled")
            .post(payload.toString().toRequestBody(jsonType))
        token?.let { builder.header("Authorization", "Bearer $it") }
        http.newCall(builder.build()).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ModelRigException("tools toggle failed (${resp.code}): $body")
            return parseRegistry(JSONObject(body))
        }
    }

    private fun parseRegistry(o: JSONObject): ToolRegistry {
        val arr = o.optJSONArray("tools")
        val tools = (0 until (arr?.length() ?: 0)).map { i ->
            val t = arr!!.getJSONObject(i)
            ToolInfo(
                name = t.optString("name"),
                risk = t.optString("risk"),
                description = t.optString("description"),
                enabled = t.optBoolean("enabled"),
            )
        }
        return ToolRegistry(
            enabled = o.optBoolean("enabled", false),
            toolsDir = o.optString("tools_dir").takeIf { it.isNotEmpty() },
            tools = tools,
        )
    }

    /**
     * The append-only audit log: every tool proposal, approval, denial and
     * failure the rig has recorded. An audit log nobody can read is only half a
     * safeguard -- you would only find misuse by opening the SQLite file on the
     * rig by hand. Read-only; the app cannot alter or clear it (there is no
     * delete path on the rig either).
     */
    fun toolsAudit(limit: Int = 50): List<AuditEntry> {
        val builder = Request.Builder().url("$base/api/v1/tools/audit?limit=$limit").get()
        token?.let { builder.header("Authorization", "Bearer $it") }
        http.newCall(builder.build()).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ModelRigException("audit failed (${resp.code}): $body")
            val arr = JSONObject(body).optJSONArray("entries") ?: return emptyList()
            return (0 until arr.length()).map { i ->
                val o = arr.getJSONObject(i)
                AuditEntry(
                    ts = o.optString("ts"),
                    tool = o.optString("tool"),
                    risk = o.optString("risk"),
                    outcome = o.optString("outcome"),
                    origin = o.optString("origin", "local"),
                    summary = o.optString("result_summary"),
                )
            }
        }
    }

    private fun parseToolTurn(o: JSONObject): ToolTurn = ToolTurn(
        status = o.optString("status"),
        answer = o.optString("answer", ""),
        tool = o.optString("tool").takeIf { it.isNotEmpty() && it != "null" },
        confirmationId = o.optString("confirmation_id").takeIf { it.isNotEmpty() },
        summary = o.optString("summary").takeIf { it.isNotEmpty() },
        expiresInSeconds = o.optInt("expires_in_seconds", 0),
        sources = o.optJSONArray("sources")?.let { a ->
            (0 until a.length()).map { a.getString(it) }
        } ?: emptyList(),
        context = o.optJSONArray("context")?.let { a ->
            (0 until a.length()).mapNotNull { i ->
                val c = a.optJSONObject(i) ?: return@mapNotNull null
                val src = c.optString("source")
                if (src.isEmpty()) return@mapNotNull null
                UsedChunk(
                    source = src,
                    chunkIndex = if (c.isNull("chunk_index")) null else c.optInt("chunk_index"),
                    score = c.optDouble("score", 0.0),
                    excerpt = c.optString("excerpt"),
                )
            }
        } ?: emptyList(),
        personName = o.optJSONObject("person")?.optString("display_name")?.takeIf { it.isNotBlank() },
        personRevision = o.optJSONObject("person")?.optString("person_revision")?.takeIf { it.isNotBlank() },
    )

    fun ingestPdf(source: String, pdfBytes: ByteArray, chunkSize: Int = 800, overlap: Int = 150): IngestResult {
        val b64 = android.util.Base64.encodeToString(pdfBytes, android.util.Base64.NO_WRAP)
        val payload = JSONObject()
            .put("pdf_base64", b64)
            .put("source", source)
            .put("chunk_size", chunkSize)
            .put("overlap", overlap)
            .toString()
            .toRequestBody(jsonType)
        val builder = Request.Builder().url("$base/api/v1/rag/ingest/pdf").post(payload)
        token?.let { builder.header("Authorization", "Bearer $it") }
        // Long timeout: a large PDF means many embedding calls to Ollama.
        voiceHttp.newCall(builder.build()).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ModelRigException("PDF ingest failed (${resp.code}): $body")
            val o = JSONObject(body)
            // PDF response has no "documents" field; report 1 doc for the UI.
            return IngestResult(1, o.optInt("chunks_added"), o.optInt("total"))
        }
    }

    /** Ingest a photo (a document page, a whiteboard, a receipt) into the RAG
     *  index: a vision model on the worker transcribes it, then the text goes
     *  through the same chunk/embed/store pipeline. Requires KALIV_VISION_MODEL
     *  on the worker -- a 501 comes back as a clear message if it's unset. */
    fun ingestImage(source: String, imageBytes: ByteArray, chunkSize: Int = 800, overlap: Int = 150): IngestResult {
        val b64 = android.util.Base64.encodeToString(imageBytes, android.util.Base64.NO_WRAP)
        val payload = JSONObject()
            .put("image_base64", b64)
            .put("source", source)
            .put("chunk_size", chunkSize)
            .put("overlap", overlap)
            .toString()
            .toRequestBody(jsonType)
        val builder = Request.Builder().url("$base/api/v1/rag/ingest/image").post(payload)
        token?.let { builder.header("Authorization", "Bearer $it") }
        // Long timeout: a vision-model extraction plus embeddings is a slow turn.
        voiceHttp.newCall(builder.build()).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ModelRigException("Foto-ingest fejlede (${resp.code}): $body")
            val o = JSONObject(body)
            return IngestResult(1, o.optInt("chunks_added"), o.optInt("total"))
        }
    }

    /**
     * Ingests a .docx into the RAG index by uploading its bytes (base64) to the
     * rig, which extracts text with python-docx (paragraphs + tables) and runs
     * the same pipeline as ingestText. Mirrors ingestPdf. 501 if python-docx
     * isn't installed, 400 for a legacy .doc, 422 if there's no text.
     */
    fun ingestDocx(source: String, docxBytes: ByteArray, chunkSize: Int = 800, overlap: Int = 150): IngestResult {
        val b64 = android.util.Base64.encodeToString(docxBytes, android.util.Base64.NO_WRAP)
        val payload = JSONObject()
            .put("docx_base64", b64)
            .put("source", source)
            .put("chunk_size", chunkSize)
            .put("overlap", overlap)
            .toString()
            .toRequestBody(jsonType)
        val builder = Request.Builder().url("$base/api/v1/rag/ingest/docx").post(payload)
        token?.let { builder.header("Authorization", "Bearer $it") }
        // Long timeout: a large document means many embedding calls to Ollama.
        voiceHttp.newCall(builder.build()).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ModelRigException("DOCX ingest failed (${resp.code}): $body")
            val o = JSONObject(body)
            return IngestResult(1, o.optInt("chunks_added"), o.optInt("total"))
        }
    }

    /**
     * Ingests a .pptx into the RAG index. The rig extracts shape text, table
     * cells and speaker notes with python-pptx. Mirrors ingestDocx. 501 if
     * python-pptx isn't installed, 400 for a legacy .ppt, 422 for an
     * image-only deck.
     */
    fun ingestPptx(source: String, pptxBytes: ByteArray, chunkSize: Int = 800, overlap: Int = 150): IngestResult {
        val b64 = android.util.Base64.encodeToString(pptxBytes, android.util.Base64.NO_WRAP)
        val payload = JSONObject()
            .put("pptx_base64", b64)
            .put("source", source)
            .put("chunk_size", chunkSize)
            .put("overlap", overlap)
            .toString()
            .toRequestBody(jsonType)
        val builder = Request.Builder().url("$base/api/v1/rag/ingest/pptx").post(payload)
        token?.let { builder.header("Authorization", "Bearer $it") }
        // Long timeout: a large deck means many embedding calls to Ollama.
        voiceHttp.newCall(builder.build()).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ModelRigException("PPTX ingest failed (${resp.code}): $body")
            val o = JSONObject(body)
            return IngestResult(1, o.optInt("chunks_added"), o.optInt("total"))
        }
    }

    /**
     * Ingests a saved web page (.html) into the RAG index. Extraction uses the
     * Python standard library on the rig, so this never returns 501 -- unlike
     * PDF/DOCX/PPTX there is nothing to install. Sends raw bytes rather than a
     * decoded string: the page may be cp1252, and the rig sniffs the encoding.
     */
    fun ingestHtml(source: String, htmlBytes: ByteArray, chunkSize: Int = 800, overlap: Int = 150): IngestResult {
        val b64 = android.util.Base64.encodeToString(htmlBytes, android.util.Base64.NO_WRAP)
        val payload = JSONObject()
            .put("html_base64", b64)
            .put("source", source)
            .put("chunk_size", chunkSize)
            .put("overlap", overlap)
            .toString()
            .toRequestBody(jsonType)
        val builder = Request.Builder().url("$base/api/v1/rag/ingest/html").post(payload)
        token?.let { builder.header("Authorization", "Bearer $it") }
        voiceHttp.newCall(builder.build()).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw ModelRigException("HTML ingest failed (${resp.code}): $body")
            val o = JSONObject(body)
            return IngestResult(1, o.optInt("chunks_added"), o.optInt("total"))
        }
    }
}

/**
 * One turn of a tool conversation. Top-level: it crosses the net/ui boundary.
 *
 * status is "answered" (a read tool ran, or no tool was used),
 * "confirmation_required" (a write is waiting for a human, nothing executed),
 * "executed" (approved and done) or "denied".
 *
 * Deliberately carries no arguments field. The app must not be able to send
 * back a modified version of what the user approved -- the worker parked the
 * arguments alongside the confirmation_id, and executes those.
 */
/**
 * One row of the tool audit log. outcome is one of: executed, denied, expired,
 * blocked, error. origin is "local" or "cloud" -- who proposed the action.
 */
/** One tool as the rig's registry describes it. risk is "read" or "write". */
data class ToolInfo(
    val name: String,
    val risk: String,
    val description: String,
    val enabled: Boolean,
)

/** The rig's tool registry: the kill switch, where writes may land, the tools. */
data class ToolRegistry(
    val enabled: Boolean,
    val toolsDir: String?,
    val tools: List<ToolInfo>,
)

data class AuditEntry(
    val ts: String,
    val tool: String,
    val risk: String,
    val outcome: String,
    val origin: String,
    val summary: String,
)

data class ToolTurn(
    val status: String,
    val answer: String,
    val tool: String?,
    val confirmationId: String?,
    val summary: String?,
    val expiresInSeconds: Int,
    /** RAG sources that grounded this turn, if document context was used. */
    val sources: List<String> = emptyList(),
    /**
     * De udsnit der FAKTISK lå i konteksten. Tom på ældre rigge, som kun
     * sender navnene — så viser fladen chips som hidtil frem for at gætte.
     */
    val context: List<UsedChunk> = emptyList(),
    /**
     * Hvem der svarede (#752): display name og Person Revision fra riggens
     * Person Profile-registry. Null når ingen person er valgt -- så taler
     * Kaliv med appens sædvanlige persona, og fladen viser ingenting.
     */
    val personName: String? = null,
    val personRevision: String? = null,
)

/**
 * Ét hentet udsnit: hvor det kom fra, hvor godt det matchede, og hvad der
 * stod. Bevidst UDEN nogen kobling til en bestemt sætning i svaret — den
 * kobling findes ikke i riggen, og et gæt ville se ud som et bevis.
 */
data class UsedChunk(
    val source: String,
    val chunkIndex: Int?,
    val score: Double,
    val excerpt: String,
)
