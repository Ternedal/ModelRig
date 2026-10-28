package dk.ternedal.modelrig.voice

/**
 * A small, testable boundary between the existing ModelRig streaming callbacks
 * and the optional Cast display. Cast delivery is best effort; failure must
 * never fail the voice turn or prevent local playback.
 */
class CastVoiceDisplayBridge(
    private val send: (org.json.JSONObject) -> Boolean,
    private val sessionId: String,
) {
    fun thinking(): Boolean = attempt { KalivCastVoiceProtocol.status(sessionId, "thinking") }
    fun transcript(text: String): Boolean =
        attempt { KalivCastVoiceProtocol.text(sessionId, "user", text.take(4000)) }
    fun speaking(text: String): Boolean {
        val stateSent = attempt { KalivCastVoiceProtocol.status(sessionId, "speaking") }
        val textSent = attempt { KalivCastVoiceProtocol.text(sessionId, "assistant", text.take(4000)) }
        return stateSent && textSent
    }
    fun idle(): Boolean = attempt { KalivCastVoiceProtocol.status(sessionId, "idle") }
    fun error(): Boolean = attempt { KalivCastVoiceProtocol.status(sessionId, "error") }

    private inline fun attempt(build: () -> org.json.JSONObject): Boolean =
        try { send(build()) } catch (_: Exception) { false }
}
