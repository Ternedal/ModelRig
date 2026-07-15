package dk.ternedal.modelrig.net

import okhttp3.ConnectionPool
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
        // Mobile links (4G) silently kill idle sockets in the carrier NAT; a
        // reused pooled connection then hangs the full read timeout with zero
        // bytes. Ping makes a dead HTTP/2 socket fail in seconds instead, and a
        // short pool idle stops us reusing sockets that sat through an idle gap
        // (sends minutes apart -- exactly the NAT kill window, on-device 14/7).
        .pingInterval(30, TimeUnit.SECONDS)
        .connectionPool(ConnectionPool(2, 30, TimeUnit.SECONDS))
        .build()

    private val jsonType = "application/json".toMediaType()

    /** Fetch available cloud model names via the native /api/tags (the documented
     *  way to list models on ollama.com's direct API), then the OpenAI-compatible
     *  /v1/models as a fallback. Throws on an auth error so the caller can show
     *  WHY it failed instead of a silent empty list (the "cloud just times out /
     *  shows nothing" trap). Returns empty only if both succeed but list nothing. */
    fun listModels(): List<String> {
        var lastErr: String? = null
        for (path in listOf("/api/tags", "/v1/models")) {
            try {
                val req = Request.Builder()
                    .url("$base$path")
                    .header("Authorization", "Bearer $apiKey")
                    .get()
                    .build()
                http.newCall(req).execute().use { resp ->
                    if (!resp.isSuccessful) {
                        // 401/403 = bad or missing key: surface it, don't hide it.
                        lastErr = "cloud-modeller: HTTP ${resp.code} fra $path" +
                            (if (resp.code == 401 || resp.code == 403) " — tjek API-nøglen (ollama.com/settings/keys)" else "")
                        return@use
                    }
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
            } catch (e: Exception) {
                lastErr = "cloud-modeller: ${e.message ?: "netværksfejl"} ($path)"
                // try next path
            }
        }
        // Both paths gave nothing usable. If there was a hard error, raise it so
        // the picker explains the cause rather than showing an empty list.
        lastErr?.let { throw ModelRigException(it) }
        return emptyList()
    }

    fun chatStream(
        model: String,
        messages: List<Pair<String, String>>,
        registerCall: ((okhttp3.Call) -> Unit)? = null,
        imageB64: String? = null,
        onThinking: ((String) -> Unit)? = null,
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
            // Reasoning models (the new glm-4.7/5.x family, deepseek, ...) think
            // server-side FIRST. On cloud that surfaced as HTTP 200 + zero bytes
            // until OkHttp's 180s readTimeout killed the call -- "Tidsudløb" with
            // no answer (seen on-device 14/7 with glm-4.7; a bad key is rejected
            // in <1s, so the silence was the model, not auth). A phone chat wants
            // the direct answer; models without thinking ignore the field.
            // Per-model thinking policy (P2-4): most reasoning models accept a
            // boolean, but gpt-oss only accepts "low"/"medium"/"high" and
            // ignores booleans -- and it is the very model our error text
            // recommends. "low" is its closest direct-answer mode.
            .put("think", if (model.startsWith("gpt-oss")) "low" else false)
            .toString()
            .toRequestBody(jsonType)

        val req = Request.Builder()
            .url("$base/api/chat")
            .header("Authorization", "Bearer $apiKey")
            .post(body)
            .build()

        // Flaky-mobile reality (on-device 14/7): in the same minute one send
        // succeeds, one dies fast with "Network is unreachable" (a momentary
        // radio/route blip) and one hangs the full read timeout on a NAT-killed
        // socket. The user's manual retry almost always works because it is a
        // FRESH attempt -- so do that automatically: one retry on a fresh
        // connection, but ONLY if nothing of the answer arrived yet (a retried
        // POST can bill twice server-side; it must never duplicate anything the
        // user has seen) and never after a user cancel.
        // Progress tracking, split on purpose (audit P2-2/P2-3):
        //  - sawServerProgress: ANY frame arrived (content OR thinking). Blocks
        //    the automatic retry -- the server demonstrably processed the
        //    request, so re-POSTing could double the work/billing. Thinking
        //    counts even though the UI may not render it.
        //  - sawContent: something USER-VISIBLE arrived. An EOF without it is
        //    not success (HTTP 200 + empty/thinking-only stream ended as a
        //    blank bubble before); it becomes a concrete error instead.
        var sawServerProgress = false
        var sawContent = false
        var attempt = 1
        while (true) {
            val call = http.newCall(req)
            registerCall?.invoke(call)
            try {
                call.execute().use { resp ->
                    if (!resp.isSuccessful) {
                        throw ModelRigException("cloud chat failed (${resp.code}): ${resp.body?.string().orEmpty()}")
                    }
                    val source = resp.body?.source() ?: throw ModelRigException("empty response body")
                    while (!source.exhausted()) {
                        val line = source.readUtf8Line() ?: break
                        if (line.isBlank()) continue
                        val obj = runCatching { JSONObject(line) }.getOrNull() ?: continue
                        // An in-stream {"error": ...} line (bad model, quota, ...) was
                        // dropped silently before: the stream ended with no deltas and
                        // the UI showed nothing or a misleading timeout. Name it.
                        obj.optString("error").takeIf { it.isNotBlank() }?.let {
                            throw ModelRigException("cloud: $it")
                        }
                        val msg = obj.optJSONObject("message")
                        val delta = msg?.optString("content").orEmpty()
                        if (delta.isNotEmpty()) {
                            sawServerProgress = true
                            sawContent = true
                            onDelta(delta)
                        } else {
                            val th = msg?.optString("thinking").orEmpty()
                            if (th.isNotEmpty()) {
                                sawServerProgress = true
                                onThinking?.invoke(th)
                            }
                        }
                    }
                }
                // EOF without any visible content is not a success: surface it
                // as a concrete error instead of a silent empty bubble.
                if (!sawContent) {
                    throw ModelRigException(
                        if (sawServerProgress) "modellen tænkte, men afsluttede uden et svar — prøv igen eller vælg en anden model"
                        else "modellen afsluttede uden svar (tom stream) — prøv igen"
                    )
                }
                return
            } catch (e: java.io.IOException) {
                if (attempt >= 2 || sawServerProgress || call.isCanceled()) throw e
                attempt++
                // Never reuse the socket that just failed; let a radio blip
                // pass -- but stay cancellable: Stop during the backoff cancels
                // the (already dead) registered call, so re-check it every
                // 100 ms and once more before the next attempt fires (P1-3).
                http.connectionPool.evictAll()
                repeat(15) {
                    if (call.isCanceled()) throw e
                    Thread.sleep(100)
                }
                if (call.isCanceled()) throw e
            }
        }
    }
}
