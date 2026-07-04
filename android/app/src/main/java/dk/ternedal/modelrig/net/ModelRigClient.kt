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
     * Streaming chat: invokes onDelta per NDJSON token chunk as it arrives.
     * `registerCall` (optional) hands back the underlying OkHttp Call so the UI
     * can cancel an in-flight generation (Stop button). Cancelling makes the
     * blocking read throw, which ends the stream cleanly.
     */
    fun chatStream(
        model: String,
        messages: List<Pair<String, String>>,
        registerCall: ((okhttp3.Call) -> Unit)? = null,
        onDelta: (String) -> Unit,
    ) {
        val arr = JSONArray()
        for ((role, content) in messages) {
            arr.put(JSONObject().put("role", role).put("content", content))
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
}
