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
            current.sendMessage(KalivCastVoiceProtocol.NAMESPACE, message.toString())
            true
        } catch (_: Exception) {
            false
        }
    }
}
