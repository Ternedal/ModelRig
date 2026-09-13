package dk.ternedal.modelrig.desktop

/** Exact local authority for one server-issued Agent 3 confirmation decision. */
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
