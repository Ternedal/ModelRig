package dk.ternedal.modelrig.logic

import java.nio.charset.StandardCharsets
import java.security.MessageDigest

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
        private const val CREDENTIAL_FINGERPRINT_DOMAIN = "kaliv-agent3-reviewed-start-credential/v1"

        fun capture(baseUrl: String?, token: String?): Agent3ReviewConnectionBinding? {
            val normalizedBase = normalizeBaseUrl(baseUrl) ?: return null
            val normalizedToken = token?.trim()?.takeIf { it.isNotEmpty() } ?: return null
            return Agent3ReviewConnectionBinding(normalizedBase, normalizedToken)
        }

        /**
         * Non-secret verifier used only to prove that durable Start recovery is
         * being retried with the same rig credential that reviewed it. The raw
         * token is never persisted or exposed by this helper.
         */
        internal fun credentialFingerprint(baseUrl: String?, token: String?): String? {
            val normalizedBase = normalizeBaseUrl(baseUrl) ?: return null
            val normalizedToken = token?.trim()?.takeIf { it.isNotEmpty() } ?: return null
            val digest = MessageDigest.getInstance("SHA-256").digest(
                buildString {
                    append(CREDENTIAL_FINGERPRINT_DOMAIN)
                    append('\u0000')
                    append(normalizedBase)
                    append('\u0000')
                    append(normalizedToken)
                }.toByteArray(StandardCharsets.UTF_8)
            )
            return digest.joinToString("") { byte -> "%02x".format(byte.toInt() and 0xff) }
        }

        private fun normalizeBaseUrl(baseUrl: String?): String? =
            baseUrl?.trim()?.trimEnd('/')?.takeIf { it.isNotEmpty() }
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
