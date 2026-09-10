package dk.ternedal.modelrig.logic

/**
 * Immutable reviewed intent for one Android Agent 3 Preview request.
 * Only normalized visible operator intent belongs here; no credential or server authority is stored.
 */
internal class Agent3ReviewPreviewIntent private constructor(
    val message: String,
    val reviewReads: Boolean,
) {
    override fun equals(other: Any?): Boolean =
        other is Agent3ReviewPreviewIntent && message == other.message && reviewReads == other.reviewReads

    override fun hashCode(): Int = 31 * message.hashCode() + reviewReads.hashCode()

    override fun toString(): String =
        "Agent3ReviewPreviewIntent(message=$message, reviewReads=$reviewReads)"

    companion object {
        fun capture(message: String, reviewReads: Boolean): Agent3ReviewPreviewIntent? {
            val normalizedMessage = message.trim()
            if (normalizedMessage.isBlank()) return null
            return Agent3ReviewPreviewIntent(normalizedMessage, reviewReads)
        }
    }
}

/** Shared publication and Start authority for an exact reviewed Android Preview intent. */
internal object Agent3ReviewPreviewPolicy {
    fun canPublish(
        requestIntent: Agent3ReviewPreviewIntent?,
        currentIntent: Agent3ReviewPreviewIntent?,
    ): Boolean = requestIntent != null && requestIntent == currentIntent

    fun canStart(
        planId: String?,
        hasSteps: Boolean,
        busy: Boolean,
        hasRun: Boolean,
        currentConnection: Agent3ReviewConnectionBinding?,
        previewConnection: Agent3ReviewConnectionBinding?,
        currentIntent: Agent3ReviewPreviewIntent?,
        previewIntent: Agent3ReviewPreviewIntent?,
    ): Boolean = Agent3ReviewConnectionPolicy.canStart(
        planId = planId,
        hasSteps = hasSteps,
        busy = busy,
        hasRun = hasRun,
        currentConnection = currentConnection,
        previewConnection = previewConnection,
    ) && currentIntent != null && currentIntent == previewIntent
}
