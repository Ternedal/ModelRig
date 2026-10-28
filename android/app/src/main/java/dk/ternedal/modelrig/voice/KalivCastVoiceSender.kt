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
    private fun session(): CastSession? = try {
        val prefs = context.getSharedPreferences("kaliv_cast", Context.MODE_PRIVATE)
        val receiverId = prefs.getString("receiver_app_id", null)?.trim().orEmpty()
        if (!Regex("[A-Fa-f0-9]{8}").matches(receiverId) ||
            !prefs.getBoolean("voice_display_enabled", false)) return null
        CastContext.getSharedInstance(context).sessionManager.currentCastSession
            ?.takeIf { it.isConnected }
    } catch (_: Exception) {
        null
    }

    fun activeDeviceId(): String? =
        session()?.castDevice?.deviceId

    /**
     * Queues a display-only message for the active Cast receiver.
     * The boolean reports submission, not remote acknowledgement or rendering.
     */
    fun send(message: org.json.JSONObject): Boolean {
        if (message.optInt("version") != KalivCastVoiceProtocol.VERSION) return false
        if (message.optString("type") !in setOf("kaliv_voice_status", "kaliv_voice_text")) return false
        val current = session() ?: return false
        return try {
            current.sendMessage(KalivCastVoiceProtocol.NAMESPACE, message.toString())
            true
        } catch (_: Exception) {
            false
        }
    }
}
