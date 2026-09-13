package dk.ternedal.modelrig.data

import android.content.Context

/**
 * Stores only the opaque plan id needed to resolve an ambiguous read-only task Start.
 *
 * The reference carries no prompt, plan, tool arguments, receipt or evidence payload.
 * It is scoped to the rig URL that was active when this task surface opened, so a
 * plan from one rig can never be replayed against another rig. Writes are synchronous:
 * the first Start is not sent unless this same-plan recovery key has reached disk.
 */
class Agent3TaskStartRecoveryStore(context: Context) {
    private val prefs = context.getSharedPreferences("modelrig", Context.MODE_PRIVATE)
    private val key = agent3TaskStartRecoveryStorageKey(prefs.getString(BASE_URL_KEY, null))

    fun read(): String? = key
        ?.let { prefs.getString(it, null) }
        ?.trim()
        ?.takeIf { it.isNotEmpty() }

    fun write(planId: String?): Boolean {
        val scopedKey = key ?: return false
        val normalized = planId?.trim()?.takeIf { it.isNotEmpty() }
        val editor = prefs.edit()
        if (normalized == null) editor.remove(scopedKey) else editor.putString(scopedKey, normalized)
        return editor.commit()
    }

    private companion object {
        const val BASE_URL_KEY = "base_url"
    }
}

internal fun agent3TaskStartRecoveryStorageKey(baseUrl: String?): String? =
    baseUrl
        ?.trim()
        ?.trimEnd('/')
        ?.takeIf { it.isNotEmpty() }
        ?.let { "$TASK_START_RECOVERY_KEY_PREFIX:$it" }

private const val TASK_START_RECOVERY_KEY_PREFIX = "agent3_task_pending_start_plan_id"
