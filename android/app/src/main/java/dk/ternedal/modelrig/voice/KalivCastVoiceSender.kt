package dk.ternedal.modelrig.voice

import android.content.Context
import com.google.android.gms.cast.framework.CastContext
import com.google.android.gms.cast.framework.CastSession

/**
 * Opt-in Cast sender adapter. It does not launch a receiver or record audio.
 * Callers must first establish a Cast session using the Android Cast UI.
 *
 * Cast is never a replacement for ModelRig pairing or authorization.
 * This channel carries only bounded display messages, never credentials.
 */
class KalivCastVoiceSender(private val context: Context) {
    private fun session(): CastSession? { return try {
        val prefs = context.getSharedPreferences("kaliv_cast", Context.MODE_PRIVATE)
        val receiverId = prefs.getString("receiver_app_id", null)?.trim().orEmpty()
        if (!Regex("[A-Fa-f0-9]{8}").matches(receiverId) ||
            !prefs.getBoolean("voice_display_enabled", false)) return null
        CastContext.getSharedInstance(context).sessionManager.currentCastSession
            ?.takeIf {
                it.isConnected &&
                    it.applicationMetadata?.applicationId.equals(receiverId, ignoreCase = true) &&
                    !receiverId.equals("CC1AD845", ignoreCase = true)
            }
    } catch (_: Exception) {
        null
    }
    }

    /**
     * Listen for receiver-side acknowledgements on the existing Cast namespace.
     * The callback is invoked only for a matching session and validated status.
     * Call closeAckListener() when leaving the voice screen.
     */
    private val pending = mutableMapOf<String, Pair<String, Long>>()
    private val ackTimeoutMs = 10_000L
    private val timeoutHandler = android.os.Handler(android.os.Looper.getMainLooper())
    private val timeoutChecks = mutableMapOf<String, Runnable>()
    private var onTimeout: ((String) -> Unit)? = null
    private var ackSession: CastSession? = null
    private var ackListener: com.google.android.gms.cast.Cast.MessageReceivedCallback? = null

    fun listenForVoiceAck(sessionId: String, onAck: (String, String, String) -> Unit, timeout: (String) -> Unit = {}): Boolean {
        if (!Regex("[A-Za-z0-9_-]{8,64}").matches(sessionId)) return false
        closeAckListener()
        val active = session() ?: return false
        onTimeout = timeout
        val callback = com.google.android.gms.cast.Cast.MessageReceivedCallback { _, namespace, payload ->
            if (namespace != KalivCastVoiceProtocol.NAMESPACE) return@MessageReceivedCallback
            val data = try { org.json.JSONObject(payload) } catch (_: Exception) { return@MessageReceivedCallback }
            if (data.optInt("version") != KalivCastVoiceProtocol.VERSION ||
                data.optString("type") != "kaliv_voice_ack" ||
                data.optString("session_id") != sessionId) {
                return@MessageReceivedCallback
            }
            val messageId = data.optString("message_id")
            if (!Regex("[0-9a-fA-F-]{36}").matches(messageId)) return@MessageReceivedCallback
            val expected = pending[messageId] ?: return@MessageReceivedCallback
            if (android.os.SystemClock.elapsedRealtime() - expected.second > ackTimeoutMs) {
                pending.remove(messageId)
                timeoutChecks.remove(messageId)?.let { timeoutHandler.removeCallbacks(it) }
                return@MessageReceivedCallback
            }
            when (data.optString("kind")) {
                "text" -> {
                    val role = data.optString("role")
                    if (role !in setOf("user", "assistant")) return@MessageReceivedCallback
                    if (expected.first != "text:$role") return@MessageReceivedCallback
                    pending.remove(messageId)
                timeoutChecks.remove(messageId)?.let { timeoutHandler.removeCallbacks(it) }
                    onAck(messageId, "text", role)
                }
                "" -> {
                    val phase = data.optString("phase")
                    if (phase !in setOf("listening", "thinking", "speaking", "idle", "error")) return@MessageReceivedCallback
                    if (expected.first != "status:$phase") return@MessageReceivedCallback
                    pending.remove(messageId)
                timeoutChecks.remove(messageId)?.let { timeoutHandler.removeCallbacks(it) }
                    onAck(messageId, "status", phase)
                }
                else -> return@MessageReceivedCallback
            }
        }
        return try {
            active.setMessageReceivedCallbacks(KalivCastVoiceProtocol.NAMESPACE, callback)
            ackSession = active
            ackListener = callback
            true
        } catch (_: Exception) {
            false
        }
    }

    fun closeAckListener() {
        val active = ackSession
        ackSession = null
        ackListener = null
        pending.clear()
        timeoutChecks.values.forEach { timeoutHandler.removeCallbacks(it) }
        timeoutChecks.clear()
        onTimeout = null
        if (active != null) {
            try { active.removeMessageReceivedCallbacks(KalivCastVoiceProtocol.NAMESPACE) }
            catch (_: Exception) { /* Cast may have disconnected */ }
        }
    }

    fun activeDeviceId(): String? =
        session()?.castDevice?.deviceId

    /**
     * Queues a display-only message for the active Cast receiver.
     * The boolean reports submission, not remote acknowledgement or rendering.
     */
    fun send(message: org.json.JSONObject): Boolean {
        if (message.optInt("version") != KalivCastVoiceProtocol.VERSION) return false
        val sessionId = message.optString("session_id")
        if (!Regex("[A-Za-z0-9_-]{8,64}").matches(sessionId)) return false
        if (!Regex("[0-9a-fA-F-]{36}").matches(message.optString("message_id"))) return false
        when (message.optString("type")) {
            "kaliv_voice_status" -> {
                if (message.optString("phase") !in setOf("listening", "thinking", "speaking", "idle", "error")) return false
            }
            "kaliv_voice_text" -> {
                if (message.optString("role") !in setOf("user", "assistant")) return false
                if (message.optString("text").length > 4000) return false
            }
            else -> return false
        }
        // A Cast sendTask may fail asynchronously; do not report delivery here.
        // Keep this method's Boolean strictly as a local submission result.
        val prefs = context.getSharedPreferences("kaliv_cast", Context.MODE_PRIVATE)
        val configuredId = prefs.getString("receiver_app_id", null)?.trim().orEmpty()
        if (!Regex("[A-Fa-f0-9]{8}").matches(configuredId) ||
            configuredId.equals("CC1AD845", ignoreCase = true)) return false
        // Never route to a different receiver merely because another Cast session
        // is active. The configured custom app must own this session.
        val current = session() ?: return false
        if (!current.applicationMetadata?.applicationId.equals(configuredId, ignoreCase = true)) {
            return false
        }
        return try {
            // CastSession.sendMessage is asynchronous. A successful call only
            // means the message was submitted, not displayed by the receiver.
            val kind = if (message.optString("type") == "kaliv_voice_status")
                "status:" + message.optString("phase") else "text:" + message.optString("role")
            val messageId = message.optString("message_id")
            val now = android.os.SystemClock.elapsedRealtime()
            pending.entries.removeAll { now - it.value.second > ackTimeoutMs }
            if (pending.size >= 128) pending.remove(pending.keys.first())
            pending[messageId] = kind to now
            val check = Runnable {
                if (pending.remove(messageId) != null) onTimeout?.invoke(messageId)
                timeoutChecks.remove(messageId)
            }
            timeoutChecks[messageId] = check
            timeoutHandler.postDelayed(check, ackTimeoutMs)
            current.sendMessage(KalivCastVoiceProtocol.NAMESPACE, message.toString())
            true
        } catch (_: Exception) {
            val failedId = message.optString("message_id")
            pending.remove(failedId)
            timeoutChecks.remove(failedId)?.let { timeoutHandler.removeCallbacks(it) }
            false
        }
    }
}
