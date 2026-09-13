package dk.ternedal.modelrig.data

import android.content.Context

/** URL-scoped storage for the opaque reviewed-Start recovery authority record. */
class Agent3ReviewedStartRecoveryStore(context: Context) {
    private val prefs = context.getSharedPreferences("modelrig", Context.MODE_PRIVATE)

    fun read(baseUrl: String?): String? = agent3ReviewedStartRecoveryStorageKey(baseUrl)
        ?.let { prefs.getString(it, null) }
        ?.trim()
        ?.takeIf { it.isNotEmpty() }

    /** Reserve an empty slot atomically across concurrent screen/store instances. */
    fun reserve(baseUrl: String?, encodedAuthority: String?): Boolean {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return false
        val normalized = encodedAuthority?.trim()?.takeIf { it.isNotEmpty() } ?: return false
        synchronized(slotLock) {
            val current = prefs.getString(key, null)?.trim()?.takeIf { it.isNotEmpty() }
            if (current != null) return false
            return prefs.edit().putString(key, normalized).commit()
        }
    }

    /** Clear only the exact authority that originated this completion. */
    fun clearIfMatches(baseUrl: String?, encodedAuthority: String?): Boolean {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return false
        val expected = encodedAuthority?.trim()?.takeIf { it.isNotEmpty() } ?: return false
        synchronized(slotLock) {
            val current = prefs.getString(key, null)?.trim()?.takeIf { it.isNotEmpty() }
            if (current != expected) return false
            return prefs.edit().remove(key).commit()
        }
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

private const val REVIEWED_START_RECOVERY_KEY_PREFIX = "agent3_reviewed_start_recovery"
