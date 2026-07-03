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

    /** Streaming chat: invokes onDelta per NDJSON token chunk as it arrives. */
    fun chatStream(model: String, messages: List<Pair<String, String>>, onDelta: (String) -> Unit) {
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

        http.newCall(builder.build()).execute().use { resp ->
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
}
