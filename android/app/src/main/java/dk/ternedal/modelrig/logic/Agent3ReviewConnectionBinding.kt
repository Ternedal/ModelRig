package dk.ternedal.modelrig.logic

/**
 * Immutable in-memory authority for one Android Agent 3 review connection context.
 * The credential is deliberately never persisted, rendered or included in toString().
 */
internal class Agent3ReviewConnectionBinding private constructor(
    val baseUrl: String,
    internal val token: String,
) {
    override fun equals(other: Any?): Boolean =
        other is Agent3ReviewConnectionBinding && baseUrl == other.baseUrl && token == other.token

    override fun hashCode(): Int = 31 * baseUrl.hashCode() + token.hashCode()

    override fun toString(): String =
        "Agent3ReviewConnectionBinding(baseUrl=$baseUrl, token=<redacted>)"

    companion object {
        fun capture(baseUrl: String?, token: String?): Agent3ReviewConnectionBinding? {
            val normalizedBase = baseUrl?.trim()?.trimEnd('/').orEmpty()
            val normalizedToken = token?.trim().orEmpty()
            if (normalizedBase.isBlank() || normalizedToken.isBlank()) return null
            return Agent3ReviewConnectionBinding(normalizedBase, normalizedToken)
        }
    }
}

/** Shared Start authority for the Android reviewed-preview surface. */
internal object Agent3ReviewConnectionPolicy {
    fun canStart(
        planId: String?,
        hasSteps: Boolean,
        busy: Boolean,
        hasRun: Boolean,
        currentConnection: Agent3ReviewConnectionBinding?,
        previewConnection: Agent3ReviewConnectionBinding?,
    ): Boolean = Agent3TaskUiPolicy.canStartReviewPreview(
        planId = planId,
        hasSteps = hasSteps,
        busy = busy,
        hasRun = hasRun,
    ) && currentConnection != null && currentConnection == previewConnection
}
