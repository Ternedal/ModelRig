package dk.ternedal.modelrig.logic

/** Exact local authority for one human-reviewed read checkpoint Resume. */
data class Agent3ReadReviewResumeAuthority(
    val runId: String,
    val completedStepId: String,
) {
    companion object {
        fun capture(runId: String?, completedStepId: String?): Agent3ReadReviewResumeAuthority? {
            val run = runId?.trim()?.takeIf { it.isNotEmpty() } ?: return null
            val step = completedStepId?.trim()?.takeIf { it.isNotEmpty() } ?: return null
            return Agent3ReadReviewResumeAuthority(run, step)
        }
    }
}

/**
 * Missing checkpoint authority is deliberately non-actionable, just like an
 * already-consumed checkpoint. The presentation can therefore fail closed
 * without inventing client authority when the server receipt is incomplete.
 */
fun isAgent3ReadReviewResumeConsumed(
    current: Agent3ReadReviewResumeAuthority?,
    consumed: Agent3ReadReviewResumeAuthority?,
): Boolean = current == null || current == consumed

fun canAgent3ReadReviewResume(
    current: Agent3ReadReviewResumeAuthority?,
    consumed: Agent3ReadReviewResumeAuthority?,
    busy: Boolean,
): Boolean = current != null && !busy && !isAgent3ReadReviewResumeConsumed(current, consumed)
