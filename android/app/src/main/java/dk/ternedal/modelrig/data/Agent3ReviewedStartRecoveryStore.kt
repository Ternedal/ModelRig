package dk.ternedal.modelrig.data

import android.content.Context
import dk.ternedal.modelrig.logic.Agent3ReviewConnectionBinding

/** URL-scoped storage for the opaque reviewed-Start recovery authority record. */
class Agent3ReviewedStartRecoveryStore(
    context: Context,
    private val credentialTokenProvider: (() -> String?)? = null,
) {
    private val appContext = context.applicationContext
    private val prefs = appContext.getSharedPreferences("modelrig", Context.MODE_PRIVATE)

    fun read(baseUrl: String?): String? {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return null
        val raw = prefs.getString(key, null)?.trim()?.takeIf { it.isNotEmpty() } ?: return null
        val bound = decodeBoundAuthority(raw) ?: return UNRESOLVED_CREDENTIAL_BINDING
        val currentFingerprint = currentCredentialFingerprint(baseUrl)
            ?: return UNRESOLVED_CREDENTIAL_BINDING
        if (currentFingerprint != bound.credentialFingerprint) return UNRESOLVED_CREDENTIAL_BINDING
        synchronized(slotLock) {
            originEnvelopes[authorityKey(key, bound.encodedAuthority)] = raw
        }
        return bound.encodedAuthority
    }

    /** Reserve an empty slot atomically across concurrent screen/store instances. */
    fun reserve(baseUrl: String?, encodedAuthority: String?): Boolean {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return false
        val authority = encodedAuthority?.trim()?.takeIf { it.isNotEmpty() } ?: return false
        val fingerprint = currentCredentialFingerprint(baseUrl) ?: return false
        val boundEnvelope = encodeBoundAuthority(fingerprint, authority)
        val authorityKey = authorityKey(key, authority)
        synchronized(slotLock) {
            if (authorityKey in retiredAuthorities) return false
            val current = prefs.getString(key, null)?.trim()?.takeIf { it.isNotEmpty() }
            if (current != null) return false
            val saved = prefs.edit().putString(key, boundEnvelope).commit()
            if (saved) originEnvelopes[authorityKey] = boundEnvelope
            return saved
        }
    }

    /** Clear only the exact credential-bound authority that originated this completion. */
    fun clearIfMatches(baseUrl: String?, encodedAuthority: String?): Boolean {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return false
        val authority = encodedAuthority?.trim()?.takeIf { it.isNotEmpty() } ?: return false
        val authorityKey = authorityKey(key, authority)
        synchronized(slotLock) {
            val expectedEnvelope = originEnvelopes[authorityKey] ?: return false
            val current = prefs.getString(key, null)?.trim()?.takeIf { it.isNotEmpty() }
            if (current != expectedEnvelope) return false
            val cleared = prefs.edit().remove(key).commit()
            if (cleared) {
                originEnvelopes.remove(authorityKey)
                retiredAuthorities.add(authorityKey)
            }
            return cleared
        }
    }

    private fun currentCredentialFingerprint(baseUrl: String?): String? {
        val persistedToken = runCatching {
            credentialTokenProvider?.invoke() ?: TokenStore(appContext).token
        }.getOrNull()
        return Agent3ReviewConnectionBinding.credentialFingerprint(baseUrl, persistedToken)
    }

    private companion object {
        val slotLock = Any()
        val originEnvelopes = mutableMapOf<String, String>()
        val retiredAuthorities = mutableSetOf<String>()
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

private fun authorityKey(storageKey: String, authority: String): String =
    "$storageKey\u0000$authority"

private fun encodeBoundAuthority(fingerprint: String, authority: String): String =
    "$RECOVERY_STORAGE_SCHEMA\n$fingerprint\n$authority"

private fun decodeBoundAuthority(raw: String): CredentialBoundAuthority? {
    val firstBreak = raw.indexOf('\n')
    if (firstBreak <= 0 || raw.substring(0, firstBreak) != RECOVERY_STORAGE_SCHEMA) return null
    val secondBreak = raw.indexOf('\n', firstBreak + 1)
    if (secondBreak <= firstBreak + 1) return null
    val fingerprint = raw.substring(firstBreak + 1, secondBreak)
    if (!SHA256.matches(fingerprint)) return null
    val authority = raw.substring(secondBreak + 1).trim().takeIf { it.isNotEmpty() } ?: return null
    return CredentialBoundAuthority(fingerprint, authority)
}

private const val REVIEWED_START_RECOVERY_KEY_PREFIX = "agent3_reviewed_start_recovery"
private const val RECOVERY_STORAGE_SCHEMA = "kaliv-agent3-reviewed-start-storage/v2"
private const val UNRESOLVED_CREDENTIAL_BINDING = "kaliv-agent3-reviewed-start-unresolved-credential-binding"
private val SHA256 = Regex("^[0-9a-f]{64}$")
