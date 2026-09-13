package dk.ternedal.modelrig.desktop.data

/** Separate URL-scoped persistence for reviewed Start; task-surface authority is never reused. */
class Agent3ReviewedStartRecoveryStore(private val db: DesktopChatDb) {
    fun read(baseUrl: String?): String? = agent3ReviewedStartRecoveryStorageKey(baseUrl)
        ?.let(db::getSetting)
        ?.trim()
        ?.takeIf { it.isNotEmpty() }

    /** Reserve an empty rig-scoped slot. Existing authority is never overwritten. */
    fun reserve(baseUrl: String?, encodedAuthority: String?): Boolean {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return false
        val normalized = encodedAuthority?.trim()?.takeIf { it.isNotEmpty() } ?: return false
        return runCatching { db.putRawSettingIfAbsent(key, normalized) }.getOrDefault(false)
    }

    /** Clear only the exact authority that originated this completion. */
    fun clearIfMatches(baseUrl: String?, encodedAuthority: String?): Boolean {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return false
        val expected = encodedAuthority?.trim()?.takeIf { it.isNotEmpty() } ?: return false
        return runCatching { db.removeRawSettingIfValue(key, expected) }.getOrDefault(false)
    }
}

internal fun agent3ReviewedStartRecoveryStorageKey(baseUrl: String?): String? =
    baseUrl
        ?.trim()
        ?.trimEnd('/')
        ?.takeIf { it.isNotEmpty() }
        ?.let { "$REVIEWED_START_RECOVERY_KEY_PREFIX:$it" }

private const val REVIEWED_START_RECOVERY_KEY_PREFIX = "agent3ReviewedStartRecovery"
