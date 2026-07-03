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
