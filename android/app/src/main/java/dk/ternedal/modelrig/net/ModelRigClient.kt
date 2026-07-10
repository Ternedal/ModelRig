package dk.ternedal.modelrig.net

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
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
    private val voiceHttp = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(5, TimeUnit.MINUTES)
        .writeTimeout(2, TimeUnit.MINUTES)  // uploading base64 audio
        .build()

    private val jsonType = "application/json".toMediaType()

    fun claimPairing(deviceName: String, code: String): String {
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
            val tok = JSONObject(text).optString("token")
            if (tok.isEmpty()) throw ModelRigException("pairing response missing token")
            return tok
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
            while (!source.exhausted()) {
                val line = source.readUtf8Line() ?: break
                if (line.isBlank()) continue
                val delta = runCatching {
                    JSONObject(line).optJSONObject("message")?.optString("content").orEmpty()
                }.getOrDefault("")
                if (delta.isNotEmpty()) onDelta(delta)
            }
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
            var first = true
            while (!source.exhausted()) {
                val line = source.readUtf8Line() ?: break
                if (line.isBlank()) continue
                if (first) {
                    first = false
                    val srcArr = runCatching { JSONObject(line).optJSONArray("sources") }.getOrNull()
                    if (srcArr != null) {
                        val names = mutableListOf<String>()
                        for (i in 0 until srcArr.length()) {
                            val s = srcArr.optJSONObject(i)?.optString("source").orEmpty()
                            if (s.isNotEmpty()) names.add(s)
                        }
                        onSources(names)
                        continue
                    }
                    // fell through: first line wasn't a sources header, treat as content below
                }
                val err = runCatching { JSONObject(line).optString("error") }.getOrDefault("")
                if (err.isNotEmpty()) throw ModelRigException("rag chat error: $err")
                val delta = runCatching {
                    JSONObject(line).optJSONObject("message")?.optString("content").orEmpty()
                }.getOrDefault("")
                if (delta.isNotEmpty()) onDelta(delta)
            }
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
                    onProgress(o.optString("status"), o.optLong("completed", 0L), o.optLong("total", 0L))
                }.onFailure { if (it is ModelRigException) throw it }
            }
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
    fun toolsChat(
        message: String,
        model: String? = null,
        conversationId: String? = null,
        cloudBaseUrl: String? = null,
        cloudKey: String? = null,
    ): ToolTurn {
        val payload = JSONObject().put("message", message)
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
    fun toolsEnabled(): Boolean {
        val builder = Request.Builder().url("$base/api/v1/tools").get()
        token?.let { builder.header("Authorization", "Bearer $it") }
        http.newCall(builder.build()).execute().use { resp ->
            if (!resp.isSuccessful) return false
            return JSONObject(resp.body?.string().orEmpty()).optBoolean("enabled", false)
        }
    }

    private fun parseToolTurn(o: JSONObject): ToolTurn = ToolTurn(
        status = o.optString("status"),
        answer = o.optString("answer", ""),
        tool = o.optString("tool").takeIf { it.isNotEmpty() && it != "null" },
        confirmationId = o.optString("confirmation_id").takeIf { it.isNotEmpty() },
        summary = o.optString("summary").takeIf { it.isNotEmpty() },
        expiresInSeconds = o.optInt("expires_in_seconds", 0),
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
data class ToolTurn(
    val status: String,
    val answer: String,
    val tool: String?,
    val confirmationId: String?,
    val summary: String?,
    val expiresInSeconds: Int,
)
