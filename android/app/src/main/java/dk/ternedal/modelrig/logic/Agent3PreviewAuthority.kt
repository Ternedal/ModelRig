package dk.ternedal.modelrig.logic

/** Exact visible operator intent represented by one ordinary Android Agent 3 Preview. */
internal data class Agent3PreviewIntent(
    val message: String,
    val useMemory: Boolean,
    val memorySubjects: List<String>,
) {
    companion object {
        fun capture(message: String, useMemory: Boolean, memorySubjects: String): Agent3PreviewIntent? {
            val normalizedMessage = message.trim()
            if (normalizedMessage.isBlank()) return null
            val subjects = if (useMemory) {
                memorySubjects
                    .split(',')
                    .map { it.trim() }
                    .filter { it.isNotEmpty() }
                    .distinct()
                    .take(20)
            } else {
                emptyList()
            }
            return Agent3PreviewIntent(normalizedMessage, useMemory, subjects)
        }
    }
}

/** In-memory connection authority for one Preview. Credentials are never rendered or persisted. */
internal class Agent3PreviewConnection private constructor(
    val baseUrl: String,
    internal val token: String,
) {
    override fun equals(other: Any?): Boolean =
        other is Agent3PreviewConnection && baseUrl == other.baseUrl && token == other.token

    override fun hashCode(): Int = 31 * baseUrl.hashCode() + token.hashCode()

    override fun toString(): String =
        "Agent3PreviewConnection(baseUrl=$baseUrl, token=<redacted>)"

    companion object {
        fun capture(baseUrl: String?, token: String?): Agent3PreviewConnection? {
            val normalizedBase = baseUrl?.trim()?.trimEnd('/').orEmpty()
            val normalizedToken = token?.trim().orEmpty()
            if (normalizedBase.isBlank() || normalizedToken.isBlank()) return null
            return Agent3PreviewConnection(normalizedBase, normalizedToken)
        }
    }
}

/** Publication and Start authority for the ordinary Android developer Preview surface. */
internal object Agent3PreviewAuthorityPolicy {
    fun canPublish(
        requestIntent: Agent3PreviewIntent?,
        currentIntent: Agent3PreviewIntent?,
    ): Boolean = requestIntent != null && requestIntent == currentIntent

    fun canStart(
        planId: String?,
        hasSteps: Boolean,
        capabilityAllowed: Boolean?,
        previewFresh: Boolean,
        busy: Boolean,
        hasRun: Boolean,
        currentConnection: Agent3PreviewConnection?,
        previewConnection: Agent3PreviewConnection?,
        currentIntent: Agent3PreviewIntent?,
        previewIntent: Agent3PreviewIntent?,
    ): Boolean =
        !planId.isNullOrBlank() &&
            hasSteps &&
            capabilityAllowed != false &&
            previewFresh &&
            !busy &&
            !hasRun &&
            currentConnection != null &&
            currentConnection == previewConnection &&
            currentIntent != null &&
            currentIntent == previewIntent
}
