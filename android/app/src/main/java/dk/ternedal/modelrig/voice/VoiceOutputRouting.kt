package dk.ternedal.modelrig.voice

/**
 * Explicit output choice for a voice turn.
 *
 * The Android phone remains the safe default. A Cast target is selected only
 * after a receiver session has been established by the UI integration.
 * No implicit casting or background microphone capture.
 */
sealed interface VoiceOutputTarget {
    data object Phone : VoiceOutputTarget

    data class Cast(
        val deviceId: String,
        val displayName: String,
    ) : VoiceOutputTarget {
        init {
            require(deviceId.isNotBlank()) { "Cast device ID must not be blank" }
            require(displayName.isNotBlank()) { "Cast display name must not be blank" }
        }
    }
}

/**
 * Resolve a stale or disconnected Cast selection to local playback.
 * A transport adapter must independently verify that its receiver is ready.
 */
object VoiceOutputRouting {
    fun effectiveTarget(
        requested: VoiceOutputTarget,
        activeCastDeviceId: String?,
    ): VoiceOutputTarget = when (requested) {
        VoiceOutputTarget.Phone -> VoiceOutputTarget.Phone
        is VoiceOutputTarget.Cast ->
            if (requested.deviceId == activeCastDeviceId) requested
            else VoiceOutputTarget.Phone
    }
}
