package dk.ternedal.modelrig.data

import android.content.Context
import dk.ternedal.modelrig.logic.Agent3ReviewConnectionBinding
import java.util.UUID

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
            rememberFirstOriginEnvelope(authorityKey(key, bound.encodedAuthority), raw)
        }
        return bound.encodedAuthority
    }

    /** Reserve an empty slot atomically across concurrent screen/store instances. */
    fun reserve(baseUrl: String?, encodedAuthority: String?): Boolean {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return false
        val authority = encodedAuthority?.trim()?.takeIf { it.isNotEmpty() } ?: return false
        val fingerprint = currentCredentialFingerprint(baseUrl) ?: return false
        val reservationGeneration = UUID.randomUUID().toString()
        val boundEnvelope = encodeBoundAuthority(fingerprint, reservationGeneration, authority)
        val authorityKey = authorityKey(key, authority)
        synchronized(slotLock) {
            if (authorityKey in retiredAuthorities) return false
            val current = prefs.getString(key, null)?.trim()?.takeIf { it.isNotEmpty() }
            if (current != null) return false
            val saved = prefs.edit().putString(key, boundEnvelope).commit()
            if (saved) rememberFirstOriginEnvelope(authorityKey, boundEnvelope)
            return saved
        }
    }

    /** Clear only the exact credential-bound reservation generation that originated this completion. */
    fun clearIfMatches(baseUrl: String?, encodedAuthority: String?): Boolean {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return false
        val authority = encodedAuthority?.trim()?.takeIf { it.isNotEmpty() } ?: return false
        val authorityKey = authorityKey(key, authority)
        synchronized(slotLock) {
            val expectedEnvelope = originEnvelopes[authorityKey] ?: return false
            val current = prefs.getString(key, null)?.trim()?.takeIf { it.isNotEmpty() }
            if (current != expectedEnvelope) {
                forgetOriginEnvelopeIfSame(authorityKey, expectedEnvelope)
                return false
            }
            val cleared = prefs.edit().remove(key).commit()
            if (cleared) {
                forgetOriginEnvelopeIfSame(authorityKey, expectedEnvelope)
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

        fun rememberFirstOriginEnvelope(authorityKey: String, envelope: String) {
            if (authorityKey !in originEnvelopes) originEnvelopes[authorityKey] = envelope
        }

        fun forgetOriginEnvelopeIfSame(authorityKey: String, envelope: String) {
            if (originEnvelopes[authorityKey] == envelope) originEnvelopes.remove(authorityKey)
        }
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
    val reservationGeneration: String,
    val encodedAuthority: String,
)

private fun authorityKey(storageKey: String, authority: String): String =
    "$storageKey\u0000$authority"

private fun encodeBoundAuthority(
    fingerprint: String,
    reservationGeneration: String,
    authority: String,
): String = "$RECOVERY_STORAGE_SCHEMA\n$fingerprint\n$reservationGeneration\n$authority"

private fun decodeBoundAuthority(raw: String): CredentialBoundAuthority? {
    val firstBreak = raw.indexOf('\n')
    if (firstBreak <= 0 || raw.substring(0, firstBreak) != RECOVERY_STORAGE_SCHEMA) return null
    val secondBreak = raw.indexOf('\n', firstBreak + 1)
    if (secondBreak <= firstBreak + 1) return null
    val thirdBreak = raw.indexOf('\n', secondBreak + 1)
    if (thirdBreak <= secondBreak + 1) return null
    val fingerprint = raw.substring(firstBreak + 1, secondBreak)
    if (!SHA256.matches(fingerprint)) return null
    val reservationGeneration = raw.substring(secondBreak + 1, thirdBreak)
    if (!UUID_LOWERCASE.matches(reservationGeneration)) return null
    val authority = raw.substring(thirdBreak + 1).trim().takeIf { it.isNotEmpty() } ?: return null
    return CredentialBoundAuthority(fingerprint, reservationGeneration, authority)
}

private const val REVIEWED_START_RECOVERY_KEY_PREFIX = "agent3_reviewed_start_recovery"
private const val RECOVERY_STORAGE_SCHEMA = "kaliv-agent3-reviewed-start-storage/v3"
private const val UNRESOLVED_CREDENTIAL_BINDING = "kaliv-agent3-reviewed-start-unresolved-credential-binding"
private val SHA256 = Regex("^[0-9a-f]{64}$")
private val UUID_LOWERCASE = Regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
