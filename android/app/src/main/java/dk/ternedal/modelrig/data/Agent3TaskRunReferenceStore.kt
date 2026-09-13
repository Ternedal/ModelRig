package dk.ternedal.modelrig.data

import android.content.Context

/**
 * Stores only the opaque id needed to reattach the normal read-only task surface.
 *
 * The id is not a credential and carries no task payload. The preference key is
 * scoped to the rig URL that was active when this task surface opened, so a run
 * reference from one rig can never be reattached against another rig. Writes are
 * synchronous because a successful server start/status must not be presented as
 * recoverable until the local control-plane reference has actually reached disk.
 */
class Agent3TaskRunReferenceStore(context: Context) {
    private val prefs = context.getSharedPreferences("modelrig", Context.MODE_PRIVATE)
    private val key = agent3TaskRunReferenceStorageKey(prefs.getString(BASE_URL_KEY, null))

    fun read(): String? = key
        ?.let { prefs.getString(it, null) }
        ?.trim()
        ?.takeIf { it.isNotEmpty() }

    fun write(runId: String?): Boolean {
        val scopedKey = key ?: return false
        val normalized = runId?.trim()?.takeIf { it.isNotEmpty() }
        val editor = prefs.edit()
        if (normalized == null) editor.remove(scopedKey) else editor.putString(scopedKey, normalized)
        return editor.commit()
    }

    private companion object {
        const val BASE_URL_KEY = "base_url"
    }
}

internal fun agent3TaskRunReferenceStorageKey(baseUrl: String?): String? =
    baseUrl
        ?.trim()
        ?.trimEnd('/')
        ?.takeIf { it.isNotEmpty() }
        ?.let { "$TASK_RUN_REFERENCE_KEY_PREFIX:$it" }

private const val TASK_RUN_REFERENCE_KEY_PREFIX = "agent3_task_active_run_id"
