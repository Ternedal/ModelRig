package dk.ternedal.modelrig.desktop.data

import dk.ternedal.modelrig.desktop.Agent3DevConnectionBinding

/** Separate URL-scoped persistence for reviewed Start; task-surface authority is never reused. */
class Agent3ReviewedStartRecoveryStore(
    private val db: DesktopChatDb,
    private val credentialTokenProvider: (() -> String?)? = null,
) {
    fun read(baseUrl: String?): String? {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return null
        val raw = db.getSetting(key)?.trim()?.takeIf { it.isNotEmpty() } ?: return null
        val bound = decodeCredentialBoundAuthority(raw) ?: return UNRESOLVED_CREDENTIAL_BINDING
        val currentFingerprint = currentCredentialFingerprint(baseUrl)
            ?: return UNRESOLVED_CREDENTIAL_BINDING
        return if (currentFingerprint == bound.credentialFingerprint) {
            bound.encodedAuthority
        } else {
            UNRESOLVED_CREDENTIAL_BINDING
        }
    }

    fun write(baseUrl: String?, encodedAuthority: String?): Boolean {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return false
        val normalized = encodedAuthority?.trim()?.takeIf { it.isNotEmpty() }
        return runCatching {
            if (normalized == null) {
                db.putSetting(key, "")
            } else {
                val fingerprint = currentCredentialFingerprint(baseUrl) ?: return false
                db.putSetting(key, encodeCredentialBoundAuthority(fingerprint, normalized))
            }
            true
        }.getOrDefault(false)
    }

    private fun currentCredentialFingerprint(baseUrl: String?): String? {
        Agent3DevConnectionBinding.recentCredentialFingerprint(baseUrl)?.let { return it }
        val persistedToken = runCatching {
            credentialTokenProvider?.invoke()
                ?: System.getenv("MODELRIG_TOKEN")?.takeIf { it.isNotBlank() }
                ?: db.getSetting("deviceToken")
        }.getOrNull()
        return Agent3DevConnectionBinding.credentialFingerprint(baseUrl, persistedToken)
    }
}

internal fun agent3ReviewedStartRecoveryStorageKey(baseUrl: String?): String? =
    baseUrl
        ?.trim()
        ?.trimEnd('/')
        ?.takeIf { it.isNotEmpty() }
        ?.let { "$REVIEWED_START_RECOVERY_KEY_PREFIX:$it" }

private data class CredentialBoundAuthority(
    val credentialFingerprint: String,
    val encodedAuthority: String,
)

private fun encodeCredentialBoundAuthority(fingerprint: String, authority: String): String =
    "$RECOVERY_STORAGE_SCHEMA\n$fingerprint\n$authority"

private fun decodeCredentialBoundAuthority(raw: String): CredentialBoundAuthority? {
    val firstBreak = raw.indexOf('\n')
    if (firstBreak <= 0 || raw.substring(0, firstBreak) != RECOVERY_STORAGE_SCHEMA) return null
    val secondBreak = raw.indexOf('\n', firstBreak + 1)
    if (secondBreak <= firstBreak + 1) return null
    val fingerprint = raw.substring(firstBreak + 1, secondBreak)
    if (!SHA256.matches(fingerprint)) return null
    val authority = raw.substring(secondBreak + 1).trim().takeIf { it.isNotEmpty() } ?: return null
    return CredentialBoundAuthority(fingerprint, authority)
}

private const val REVIEWED_START_RECOVERY_KEY_PREFIX = "agent3ReviewedStartRecovery"
private const val RECOVERY_STORAGE_SCHEMA = "kaliv-agent3-reviewed-start-storage/v2"
private const val UNRESOLVED_CREDENTIAL_BINDING = "kaliv-agent3-reviewed-start-unresolved-credential-binding"
private val SHA256 = Regex("^[0-9a-f]{64}$")
