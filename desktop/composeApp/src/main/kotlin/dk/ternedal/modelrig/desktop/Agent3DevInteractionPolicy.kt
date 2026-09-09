package dk.ternedal.modelrig.desktop

/**
 * Immutable in-memory authority for one explicit --agent3 connection context.
 * The credential is deliberately never persisted or included in toString().
 */
internal class Agent3DevConnectionBinding private constructor(
    val baseUrl: String,
    internal val token: String,
) {
    override fun equals(other: Any?): Boolean =
        other is Agent3DevConnectionBinding && baseUrl == other.baseUrl && token == other.token

    override fun hashCode(): Int = 31 * baseUrl.hashCode() + token.hashCode()

    override fun toString(): String =
        "Agent3DevConnectionBinding(baseUrl=$baseUrl, token=<redacted>)"

    companion object {
        fun capture(baseUrl: String, token: String): Agent3DevConnectionBinding? {
            val normalizedBase = baseUrl.trim().trimEnd('/')
            val normalizedToken = token.trim()
            if (normalizedBase.isBlank() || normalizedToken.isBlank()) return null
            return Agent3DevConnectionBinding(normalizedBase, normalizedToken)
        }
    }
}

/** Shared local authority for the explicit --agent3 developer surface. */
internal object Agent3DevInteractionPolicy {
    fun canPreview(
        message: String,
        busy: Boolean,
        runState: String?,
        activeToolState: String? = null,
        activeToolRequestState: String? = null,
    ): Boolean {
        if (message.isBlank() || busy) return false
        if (runState == null) return true
        return Agent3TaskUiPolicy.canResetTerminalHistory(
            runTerminal = isTerminal(runState),
            activeToolState = activeToolState,
            activeToolRequestState = activeToolRequestState,
            busy = busy,
        )
    }

    fun canStart(
        planId: String?,
        planSize: Int,
        capabilityAllowed: Boolean?,
        busy: Boolean,
        hasRun: Boolean,
        currentConnection: Agent3DevConnectionBinding?,
        previewConnection: Agent3DevConnectionBinding?,
    ): Boolean =
        !busy &&
            !hasRun &&
            !planId.isNullOrBlank() &&
            planSize > 0 &&
            capabilityAllowed != false &&
            currentConnection != null &&
            currentConnection == previewConnection
}
