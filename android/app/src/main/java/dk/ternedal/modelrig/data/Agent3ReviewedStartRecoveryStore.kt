package dk.ternedal.modelrig.data

import android.content.Context
import dk.ternedal.modelrig.logic.Agent3ReviewConnectionBinding
import java.util.UUID

/** Exact durable slot identity captured by one reviewed-Start operation. */
data class Agent3ReviewedStartRecoveryReservation internal constructor(
    val encodedAuthority: String,
    internal val storageKey: String,
    internal val expectedEnvelope: String,
)

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
        return bound.encodedAuthority
    }

    /** Read the current valid slot together with the exact generation that owns clearing authority. */
    fun readReservation(baseUrl: String?): Agent3ReviewedStartRecoveryReservation? {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return null
        synchronized(slotLock) {
            val raw = prefs.getString(key, null)?.trim()?.takeIf { it.isNotEmpty() } ?: return null
            val bound = decodeBoundAuthority(raw) ?: return null
            val currentFingerprint = currentCredentialFingerprint(baseUrl) ?: return null
            if (currentFingerprint != bound.credentialFingerprint) return null
            return Agent3ReviewedStartRecoveryReservation(bound.encodedAuthority, key, raw)
        }
    }

    /** Reserve an empty slot atomically across concurrent screen/store instances. */
    fun reserve(
        baseUrl: String?,
        encodedAuthority: String?,
    ): Agent3ReviewedStartRecoveryReservation? {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return null
        val authority = encodedAuthority?.trim()?.takeIf { it.isNotEmpty() } ?: return null
        val fingerprint = currentCredentialFingerprint(baseUrl) ?: return null
        val reservationGeneration = UUID.randomUUID().toString()
        val boundEnvelope = encodeBoundAuthority(fingerprint, reservationGeneration, authority)
        synchronized(slotLock) {
            val current = prefs.getString(key, null)?.trim()?.takeIf { it.isNotEmpty() }
            if (current != null) return null
            val saved = prefs.edit().putString(key, boundEnvelope).commit()
            return if (saved) {
                Agent3ReviewedStartRecoveryReservation(authority, key, boundEnvelope)
            } else {
                null
            }
        }
    }

    /** Clear only the exact rig + credential + generation captured by this operation. */
    fun clearIfMatches(
        baseUrl: String?,
        reservation: Agent3ReviewedStartRecoveryReservation,
    ): Boolean {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return false
        if (reservation.storageKey != key) return false
        synchronized(slotLock) {
            val current = prefs.getString(key, null)?.trim()?.takeIf { it.isNotEmpty() }
            if (current != reservation.expectedEnvelope) return false
            return prefs.edit().remove(key).commit()
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
