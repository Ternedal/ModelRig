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
        attempt { KalivCastVoiceProtocol.text(sessionId, "user", boundedText(text)) }
    fun speaking(text: String): Boolean {
        val stateSent = attempt { KalivCastVoiceProtocol.status(sessionId, "speaking") }
        // The receiver rejects blank subtitles; do not wait for an ACK it cannot send.
        if (text.isBlank()) return stateSent
        val textSent = attempt { KalivCastVoiceProtocol.text(sessionId, "assistant", boundedText(text)) }
        return stateSent && textSent
    }

    private fun boundedText(value: String): String {
        if (value.length <= 4000) return value
        // Cast limits UTF-16 units; never cut between an emoji's surrogate halves.
        val end = if (Character.isHighSurrogate(value[3999]) &&
            Character.isLowSurrogate(value[4000])) 3999 else 4000
        return value.substring(0, end)
    }
    fun idle(): Boolean = attempt { KalivCastVoiceProtocol.status(sessionId, "idle") }
    fun error(): Boolean = attempt { KalivCastVoiceProtocol.status(sessionId, "error") }

    private inline fun attempt(build: () -> org.json.JSONObject): Boolean =
        try { send(build()) } catch (_: Exception) { false }
}
