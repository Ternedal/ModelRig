package dk.ternedal.modelrig.desktop

import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import java.util.concurrent.ConcurrentHashMap

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
        private const val CREDENTIAL_FINGERPRINT_DOMAIN = "kaliv-agent3-reviewed-start-credential/v1"
        private val recentCredentialFingerprints = ConcurrentHashMap<String, String>()

        fun capture(baseUrl: String, token: String): Agent3DevConnectionBinding? {
            val normalizedBase = normalizeBaseUrl(baseUrl) ?: return null
            val normalizedToken = token.trim().takeIf { it.isNotEmpty() } ?: return null
            val fingerprint = credentialFingerprint(normalizedBase, normalizedToken) ?: return null
            recentCredentialFingerprints[normalizedBase] = fingerprint
            return Agent3DevConnectionBinding(normalizedBase, normalizedToken)
        }

        /** Non-secret verifier for the exact reviewed credential; raw token is never persisted. */
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

        internal fun recentCredentialFingerprint(baseUrl: String?): String? =
            normalizeBaseUrl(baseUrl)?.let(recentCredentialFingerprints::get)

        private fun normalizeBaseUrl(baseUrl: String?): String? =
            baseUrl?.trim()?.trimEnd('/')?.takeIf { it.isNotEmpty() }
    }
}

/** Exact reviewed request intent that one developer preview represents. */
internal data class Agent3DevPreviewIntent(
    val message: String,
    val useMemory: Boolean,
    val memorySubjects: List<String>,
) {
    companion object {
        fun capture(message: String, useMemory: Boolean, memorySubjects: String): Agent3DevPreviewIntent? {
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
            return Agent3DevPreviewIntent(normalizedMessage, useMemory, subjects)
        }
    }
}

/** Shared local authority for the explicit --agent3 developer surface. */
internal object Agent3DevInteractionPolicy {
    fun canPublishForConnection(
        requestConnection: Agent3DevConnectionBinding?,
        currentConnection: Agent3DevConnectionBinding?,
    ): Boolean = requestConnection != null && requestConnection == currentConnection

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

    fun canPublishPreview(
        requestIntent: Agent3DevPreviewIntent?,
        currentIntent: Agent3DevPreviewIntent?,
    ): Boolean = requestIntent != null && requestIntent == currentIntent

    fun canStart(
        planId: String?,
        planSize: Int,
        capabilityAllowed: Boolean?,
        previewFresh: Boolean,
        busy: Boolean,
        hasRun: Boolean,
        currentConnection: Agent3DevConnectionBinding?,
        previewConnection: Agent3DevConnectionBinding?,
        currentIntent: Agent3DevPreviewIntent?,
        previewIntent: Agent3DevPreviewIntent?,
    ): Boolean =
        previewFresh &&
            !busy &&
            !hasRun &&
            !planId.isNullOrBlank() &&
            planSize > 0 &&
            capabilityAllowed != false &&
            currentConnection != null &&
            currentConnection == previewConnection &&
            currentIntent != null &&
            currentIntent == previewIntent

    fun canStopPlan(
        runState: String?,
        planCanRequest: Boolean?,
        busy: Boolean,
    ): Boolean =
        runState != null &&
            !isTerminal(runState) &&
            Agent3TaskUiPolicy.canStopPlan(planCanRequest, busy)

    fun confirmation(
        confirmationDigest: String?,
        confirmationExpiresAt: Double?,
        runState: String?,
        stepState: String?,
        busy: Boolean,
        nowEpochSeconds: Double,
        confirmationConsumed: Boolean = false,
    ): KalivAgent3CockpitConfirmation = presentAgent3CockpitConfirmation(
        confirmationDigest = confirmationDigest,
        confirmationExpiresAt = confirmationExpiresAt,
        runState = runState,
        stepState = stepState,
        busy = busy,
        nowEpochSeconds = nowEpochSeconds,
        confirmationConsumed = confirmationConsumed,
    )

    fun canDecide(
        confirmationDigest: String?,
        confirmationExpiresAt: Double?,
        runState: String?,
        stepState: String?,
        busy: Boolean,
        nowEpochSeconds: Double,
        confirmationConsumed: Boolean = false,
    ): Boolean = confirmation(
        confirmationDigest = confirmationDigest,
        confirmationExpiresAt = confirmationExpiresAt,
        runState = runState,
        stepState = stepState,
        busy = busy,
        nowEpochSeconds = nowEpochSeconds,
        confirmationConsumed = confirmationConsumed,
    ).actionEnabled
}
