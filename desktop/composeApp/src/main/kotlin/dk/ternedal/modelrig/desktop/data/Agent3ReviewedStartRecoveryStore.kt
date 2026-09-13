package dk.ternedal.modelrig.desktop.data

import dk.ternedal.modelrig.desktop.Agent3DevConnectionBinding
import java.util.UUID

/** Separate URL-scoped persistence for reviewed Start; task-surface authority is never reused. */
class Agent3ReviewedStartRecoveryStore(
    private val db: DesktopChatDb,
    private val credentialTokenProvider: (() -> String?)? = null,
) {
    // Clear authority belongs to this store/UI instance. Keeping it instance-local
    // prevents another in-flight callback/store from replacing or retiring the
    // reservation generation that this exact callback captured.
    private val originEnvelopes = mutableMapOf<String, String>()
    private val retiredAuthorities = mutableSetOf<String>()

    fun read(baseUrl: String?): String? {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return null
        val raw = db.getSetting(key)?.trim()?.takeIf { it.isNotEmpty() } ?: return null
        val bound = decodeBoundAuthority(raw) ?: return UNRESOLVED_CREDENTIAL_BINDING
        val currentFingerprint = currentCredentialFingerprint(baseUrl)
            ?: return UNRESOLVED_CREDENTIAL_BINDING
        if (currentFingerprint != bound.credentialFingerprint) return UNRESOLVED_CREDENTIAL_BINDING
        synchronized(slotLock) {
            rememberFirstOriginEnvelope(authorityKey(key, bound.encodedAuthority), raw)
        }
        return bound.encodedAuthority
    }

    /** Reserve an empty rig-scoped slot. Existing authority is never overwritten. */
    fun reserve(baseUrl: String?, encodedAuthority: String?): Boolean {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return false
        val authority = encodedAuthority?.trim()?.takeIf { it.isNotEmpty() } ?: return false
        val fingerprint = currentCredentialFingerprint(baseUrl) ?: return false
        val reservationGeneration = UUID.randomUUID().toString()
        val boundEnvelope = encodeBoundAuthority(fingerprint, reservationGeneration, authority)
        val authorityKey = authorityKey(key, authority)
        synchronized(slotLock) {
            if (authorityKey in retiredAuthorities) return false
            val saved = runCatching { db.putRawSettingIfAbsent(key, boundEnvelope) }.getOrDefault(false)
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
            val cleared = runCatching { db.removeRawSettingIfValue(key, expectedEnvelope) }.getOrDefault(false)
            if (!cleared) {
                forgetOriginEnvelopeIfSame(authorityKey, expectedEnvelope)
                return false
            }
            forgetOriginEnvelopeIfSame(authorityKey, expectedEnvelope)
            retiredAuthorities.add(authorityKey)
            return true
        }
    }

    private fun rememberFirstOriginEnvelope(authorityKey: String, envelope: String) {
        if (authorityKey !in originEnvelopes) originEnvelopes[authorityKey] = envelope
    }

    private fun forgetOriginEnvelopeIfSame(authorityKey: String, envelope: String) {
        if (originEnvelopes[authorityKey] == envelope) originEnvelopes.remove(authorityKey)
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

    private companion object {
        // Persistence CAS must still serialize across store instances in-process.
        val slotLock = Any()
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

private const val REVIEWED_START_RECOVERY_KEY_PREFIX = "agent3ReviewedStartRecovery"
private const val RECOVERY_STORAGE_SCHEMA = "kaliv-agent3-reviewed-start-storage/v3"
private const val UNRESOLVED_CREDENTIAL_BINDING = "kaliv-agent3-reviewed-start-unresolved-credential-binding"
private val SHA256 = Regex("^[0-9a-f]{64}$")
private val UUID_LOWERCASE = Regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
