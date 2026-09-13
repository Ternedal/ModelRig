package dk.ternedal.modelrig.desktop.data

/** Separate URL-scoped persistence for reviewed Start; task-surface authority is never reused. */
class Agent3ReviewedStartRecoveryStore(private val db: DesktopChatDb) {
    fun read(baseUrl: String?): String? = agent3ReviewedStartRecoveryStorageKey(baseUrl)
        ?.let(db::getSetting)
        ?.trim()
        ?.takeIf { it.isNotEmpty() }

    fun write(baseUrl: String?, encodedAuthority: String?): Boolean {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return false
        val normalized = encodedAuthority?.trim()?.takeIf { it.isNotEmpty() }
        return runCatching {
            db.putSetting(key, normalized.orEmpty())
            true
        }.getOrDefault(false)
    }
}

internal fun agent3ReviewedStartRecoveryStorageKey(baseUrl: String?): String? =
    baseUrl
        ?.trim()
        ?.trimEnd('/')
        ?.takeIf { it.isNotEmpty() }
        ?.let { "$REVIEWED_START_RECOVERY_KEY_PREFIX:$it" }

private const val REVIEWED_START_RECOVERY_KEY_PREFIX = "agent3ReviewedStartRecovery"
