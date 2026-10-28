package dk.ternedal.modelrig.voice

import org.json.JSONObject

/**
 * Versioned display-only messages for the KalivHub Cast receiver.
 *
 * These messages are deliberately separate from Home Assistant snapshots and
 * control requests. They contain no bearer tokens or raw microphone audio.
 * Receiver support must be deployed before the Android sender enables them.
 */
object KalivCastVoiceProtocol {
    const val NAMESPACE = "urn:x-cast:dk.kalivhub.lab"
    const val VERSION = 1

    fun status(sessionId: String, phase: String): JSONObject {
        requireSession(sessionId)
        require(phase in setOf("listening", "thinking", "speaking", "idle", "error"))
        return JSONObject()
            .put("type", "kaliv_voice_status")
            .put("version", VERSION)
            .put("session_id", sessionId)
            .put("message_id", java.util.UUID.randomUUID().toString())
            .put("phase", phase)
    }

    fun text(sessionId: String, role: String, value: String): JSONObject {
        requireSession(sessionId)
        require(role == "user" || role == "assistant")
        require(value.length <= 4000)
        return JSONObject()
            .put("type", "kaliv_voice_text")
            .put("version", VERSION)
            .put("session_id", sessionId)
            .put("message_id", java.util.UUID.randomUUID().toString())
            .put("role", role)
            .put("text", value)
    }

    private fun requireSession(sessionId: String) {
        require(Regex("[A-Za-z0-9_-]{8,64}").matches(sessionId)) {
            "Invalid Cast voice session ID"
        }
    }
}
