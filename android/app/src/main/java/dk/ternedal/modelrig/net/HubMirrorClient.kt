package dk.ternedal.modelrig.net

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.net.URI
import java.util.UUID
import java.util.concurrent.TimeUnit
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * Best-effort output mirroring to the user's opt-in KalivHub receiver.
 *
 * Does NOT invoke an AI model and does NOT send chat history, prompts, ModelRig
 * bearer tokens or cloud API keys. Only an already completed assistant reply
 * goes to the explicitly configured private IPv4 address.
 *
 * Transport on a trusted private LAN is plain HTTP. HMAC authenticates and
 * prevents replay, but does NOT encrypt the reply. Never use this on open Wi-Fi.
 */
object HubMirrorClient {
    private val http = OkHttpClient.Builder()
        .connectTimeout(2, TimeUnit.SECONDS)
        .readTimeout(3, TimeUnit.SECONDS)
        .callTimeout(6, TimeUnit.SECONDS)
        .followRedirects(false)
        .followSslRedirects(false)
        .build()

    /** No DNS redirects, credentials, query strings, public URLs or userinfo. */
    fun endpoint(raw: String): String? {
        val url = try { URI(raw.trim()) } catch (_: Exception) { return null }
        if (url.scheme != "http" || url.rawUserInfo != null ||
            url.rawQuery != null || url.rawFragment != null ||
            url.port !in 1..65535) return null
        if (url.rawPath !in listOf("", "/", "/v1/events")) return null
        val host = url.host ?: return null
        if (!privateIpv4(host)) return null
        return "http://$host:${url.port}/v1/events"
    }

    fun privateIpv4(raw: String): Boolean {
        val parts = raw.split(".")
        if (parts.size != 4) return false
        val octets = parts.map { it.toIntOrNull() ?: return false }
        if (octets.any { it !in 0..255 }) return false
        if (octets.indices.any { octets[it].toString() != parts[it] }) return false
        val a = octets[0]
        val b = octets[1]
        return a == 10 ||
            (a == 172 && b in 16..31) ||
            (a == 192 && b == 168) ||
            (a == 100 && b in 64..127) // Tailscale / RFC 6598
    }

    internal fun limitVisibleText(text: String): String {
        var value = text.trim().take(2000)
        if (value.isNotEmpty() && Character.isHighSurrogate(value.last())) {
            value = value.dropLast(1)
        }
        return value
    }

    internal fun signature(secret: String, timestamp: String, body: String): String {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(secret.toByteArray(Charsets.UTF_8), "HmacSHA256"))
        val bytes = mac.doFinal((timestamp + "\n" + body).toByteArray(Charsets.UTF_8))
        return "v1=" + bytes.joinToString("") { "%02x".format(it.toInt() and 0xff) }
    }

    /** Called only after persisting an actual successful assistant turn. */
    fun sendCompleted(configuredUrl: String, secret: String, completed: String): Boolean {
        val target = endpoint(configuredUrl) ?: return false
        if (secret.length < 32 || completed.isBlank()) return false
        // Cast's JS string-length limit counts UTF-16 code units, as Kotlin does.
        // Do not split a surrogate pair at the display boundary.
        val visible = limitVisibleText(completed)
        if (visible.isBlank()) return false
        val body = JSONObject()
            .put("version", 1)
            .put("type", "assistant_complete")
            .put("event_id", UUID.randomUUID().toString())
            .put("text", visible)
            .toString()
        val timestamp = (System.currentTimeMillis() / 1000L).toString()
        val signature = signature(secret, timestamp, body)
        val request = Request.Builder()
            .url(target)
            .header("X-Kaliv-Timestamp", timestamp)
            .header("X-Kaliv-Signature", signature)
            .post(body.toRequestBody("application/json; charset=utf-8".toMediaType()))
            .build()
        return http.newCall(request).execute().use { response ->
            // 202 = queued, not proof that the physical receiver displayed it.
            response.code == 202 || response.code == 409
        }
    }
}
