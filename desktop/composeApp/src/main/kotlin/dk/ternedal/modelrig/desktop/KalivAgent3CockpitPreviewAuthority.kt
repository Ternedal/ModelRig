package dk.ternedal.modelrig.desktop

/** Exact visible operator intent represented by one Kaliv Agent 3 Preview. */
internal data class KalivAgent3CockpitPreviewIntent(
    val message: String,
) {
    companion object {
        fun capture(message: String): KalivAgent3CockpitPreviewIntent? {
            val normalized = message.trim()
            if (normalized.isBlank()) return null
            return KalivAgent3CockpitPreviewIntent(normalized)
        }
    }
}

/**
 * Immutable in-memory connection authority for a Kaliv Agent 3 Preview.
 *
 * The bearer may legitimately be empty for a locally configured experimental
 * endpoint, so only the normalized base URL is required. Credentials are never
 * persisted, rendered or included in toString().
 */
internal class KalivAgent3CockpitPreviewConnection private constructor(
    val baseUrl: String,
    internal val bearer: String,
) {
    override fun equals(other: Any?): Boolean =
        other is KalivAgent3CockpitPreviewConnection &&
            baseUrl == other.baseUrl && bearer == other.bearer

    override fun hashCode(): Int = 31 * baseUrl.hashCode() + bearer.hashCode()

    override fun toString(): String =
        "KalivAgent3CockpitPreviewConnection(baseUrl=$baseUrl, bearer=<redacted>)"

    companion object {
        fun capture(baseUrl: String, bearer: String?): KalivAgent3CockpitPreviewConnection? {
            val normalizedBase = baseUrl.trim().trimEnd('/')
            if (normalizedBase.isBlank()) return null
            return KalivAgent3CockpitPreviewConnection(
                baseUrl = normalizedBase,
                bearer = bearer?.trim().orEmpty(),
            )
        }
    }
}

/** Local publication and Start authority for the exact Preview the operator saw. */
internal object KalivAgent3CockpitPreviewAuthorityPolicy {
    fun canPublish(
        requestIntent: KalivAgent3CockpitPreviewIntent?,
        currentIntent: KalivAgent3CockpitPreviewIntent?,
        requestConnection: KalivAgent3CockpitPreviewConnection?,
        currentConnection: KalivAgent3CockpitPreviewConnection?,
    ): Boolean = requestIntent != null &&
        requestIntent == currentIntent &&
        requestConnection != null &&
        requestConnection == currentConnection

    fun canStart(
        planId: String?,
        hasSteps: Boolean,
        previewFresh: Boolean,
        busy: Boolean,
        hasRun: Boolean,
        currentIntent: KalivAgent3CockpitPreviewIntent?,
        previewIntent: KalivAgent3CockpitPreviewIntent?,
        currentConnection: KalivAgent3CockpitPreviewConnection?,
        previewConnection: KalivAgent3CockpitPreviewConnection?,
    ): Boolean = !planId.isNullOrBlank() &&
        hasSteps &&
        previewFresh &&
        !busy &&
        !hasRun &&
        currentIntent != null &&
        currentIntent == previewIntent &&
        currentConnection != null &&
        currentConnection == previewConnection
}
