package dk.ternedal.modelrig.net

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Direct client for Ollama Cloud (https://ollama.com/api) — no local rig needed.
 *
 * Auth is the account API key as a bearer token. The chat endpoint is the native
 * Ollama shape (`/api/chat` with {model, messages, stream}), streamed as NDJSON —
 * so the same line-by-line parsing as the rig path is reused.
 *
 * Blocking OkHttp — always call from a background dispatcher (Dispatchers.IO).
 * Get a cloud key at https://ollama.com/settings/keys. Cloud model names are used
 * directly (e.g. "gpt-oss:120b"); pick from the cloud model list.
 */
class CloudClient(private val apiKey: String, baseUrl: String = "https://ollama.com") {

    private val base = baseUrl.trimEnd('/')

    private val http = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(180, TimeUnit.SECONDS)
        .build()

    private val jsonType = "application/json".toMediaType()

    /** Fetch available cloud model names. Tries the native /api/tags, then the
     *  OpenAI-compatible /v1/models. Returns empty on failure (caller falls back
     *  to the manually-typed model). */
    fun listModels(): List<String> {
        for (path in listOf("/api/tags", "/v1/models")) {
            try {
                val req = Request.Builder()
                    .url("$base$path")
                    .header("Authorization", "Bearer $apiKey")
                    .get()
                    .build()
                http.newCall(req).execute().use { resp ->
                    if (!resp.isSuccessful) return@use
                    val obj = JSONObject(resp.body?.string() ?: return@use)
                    val names = mutableListOf<String>()
                    when {
                        obj.has("models") -> {
                            val arr = obj.getJSONArray("models")
                            for (i in 0 until arr.length()) names.add(arr.getJSONObject(i).optString("name"))
                        }
                        obj.has("data") -> {
                            val arr = obj.getJSONArray("data")
                            for (i in 0 until arr.length()) names.add(arr.getJSONObject(i).optString("id"))
                        }
                    }
                    val clean = names.filter { it.isNotBlank() }
                    if (clean.isNotEmpty()) return clean
                }
            } catch (_: Exception) {
                // try next path
            }
        }
        return emptyList()
    }

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
            // Ollama vision: attach base64 images (no data-URI prefix) to a
            // message via an "images" array. We only ever attach to the LAST
            // message (the current user turn) -- history images aren't resent,
            // same pragmatic scope as RAG. Requires a vision-capable model.
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

        val req = Request.Builder()
            .url("$base/api/chat")
            .header("Authorization", "Bearer $apiKey")
            .post(body)
            .build()

        val call = http.newCall(req)
        registerCall?.invoke(call)
        call.execute().use { resp ->
            if (!resp.isSuccessful) {
                throw ModelRigException("cloud chat failed (${resp.code}): ${resp.body?.string().orEmpty()}")
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
}
