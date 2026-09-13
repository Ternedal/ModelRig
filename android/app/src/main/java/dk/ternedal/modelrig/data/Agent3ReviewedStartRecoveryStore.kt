package dk.ternedal.modelrig.data

import android.content.Context

/** URL-scoped storage for the opaque reviewed-Start recovery authority record. */
class Agent3ReviewedStartRecoveryStore(context: Context) {
    private val prefs = context.getSharedPreferences("modelrig", Context.MODE_PRIVATE)

    fun read(baseUrl: String?): String? = agent3ReviewedStartRecoveryStorageKey(baseUrl)
        ?.let { prefs.getString(it, null) }
        ?.trim()
        ?.takeIf { it.isNotEmpty() }

    fun write(baseUrl: String?, encodedAuthority: String?): Boolean {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return false
        val normalized = encodedAuthority?.trim()?.takeIf { it.isNotEmpty() }
        val editor = prefs.edit()
        if (normalized == null) editor.remove(key) else editor.putString(key, normalized)
        return editor.commit()
    }
}

internal fun agent3ReviewedStartRecoveryStorageKey(baseUrl: String?): String? =
    baseUrl
        ?.trim()
        ?.trimEnd('/')
        ?.takeIf { it.isNotEmpty() }
        ?.let { "$REVIEWED_START_RECOVERY_KEY_PREFIX:$it" }

private const val REVIEWED_START_RECOVERY_KEY_PREFIX = "agent3_reviewed_start_recovery"
