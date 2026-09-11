package dk.ternedal.modelrig.logic

/**
 * Exact local authority for one server-issued Agent 3 confirmation decision.
 *
 * Once I/O begins for this key, the client must never make the same key
 * actionable again from stale local or refreshed state. Only a genuinely new
 * run/step/digest tuple can mint fresh local decision authority.
 */
internal data class Agent3ConfirmationAuthority(
    val runId: String,
    val stepId: String,
    val digest: String,
) {
    companion object {
        fun capture(runId: String?, stepId: String?, digest: String?): Agent3ConfirmationAuthority? {
            if (runId.isNullOrBlank() || stepId.isNullOrBlank() || digest.isNullOrBlank()) return null
            return Agent3ConfirmationAuthority(runId, stepId, digest)
        }
    }
}

internal fun isAgent3ConfirmationAuthorityConsumed(
    current: Agent3ConfirmationAuthority?,
    consumed: Agent3ConfirmationAuthority?,
): Boolean = current != null && current == consumed
