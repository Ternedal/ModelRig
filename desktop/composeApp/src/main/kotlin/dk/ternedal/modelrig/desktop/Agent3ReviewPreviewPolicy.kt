package dk.ternedal.modelrig.desktop

/** Exact visible operator intent represented by one reviewed Preview request. */
internal data class Agent3ReviewPreviewIntent(
    val message: String,
    val reviewReads: Boolean,
) {
    companion object {
        fun capture(message: String, reviewReads: Boolean): Agent3ReviewPreviewIntent? {
            val normalizedMessage = message.trim()
            if (normalizedMessage.isBlank()) return null
            return Agent3ReviewPreviewIntent(normalizedMessage, reviewReads)
        }
    }
}

/** Local publication and Start authority for the isolated reviewed Preview surface. */
internal object Agent3ReviewPreviewPolicy {
    fun canPublish(
        requestIntent: Agent3ReviewPreviewIntent?,
        currentIntent: Agent3ReviewPreviewIntent?,
    ): Boolean = requestIntent != null && requestIntent == currentIntent

    fun canStart(
        planId: String?,
        planSize: Int,
        previewFresh: Boolean,
        busy: Boolean,
        currentConnection: Agent3DevConnectionBinding?,
        previewConnection: Agent3DevConnectionBinding?,
        currentIntent: Agent3ReviewPreviewIntent?,
        previewIntent: Agent3ReviewPreviewIntent?,
    ): Boolean =
        previewFresh &&
            !busy &&
            !planId.isNullOrBlank() &&
            planSize > 0 &&
            currentConnection != null &&
            currentConnection == previewConnection &&
            currentIntent != null &&
            currentIntent == previewIntent

    fun shouldMarkExpired(
        planId: String?,
        planSize: Int,
        previewFresh: Boolean,
    ): Boolean =
        !planId.isNullOrBlank() &&
            planSize > 0 &&
            !previewFresh
}
