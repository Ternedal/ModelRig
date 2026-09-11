package dk.ternedal.modelrig.desktop.net

/**
 * Reviewed Start boundary for the desktop operator surface.
 *
 * The transport first proves the raw top-level review mode plus its existing
 * plan/termination/capability authority. Only then may the parsed read-review
 * state reach the UI: review mode and capability authority must agree with the
 * exact Preview, and any returned checkpoint must agree with the returned run.
 *
 * If that final reviewed state is rejected, the already-bound nonblank run id is
 * only a recovery reference: the rejected Start payload is never published.
 * Fresh server truth must be fetched on the same client connection and pass the
 * exact run-id, review-mode and checkpoint bindings before it can be returned.
 */
internal fun Agent3Client.startReviewedPlanEnvelope(
    planId: String,
    expectedReviewReads: Boolean,
    expectedCapabilityReceipt: Agent3CapabilityReceipt? = null,
): Agent3RunEnvelope {
    val envelope = startPlanEnvelope(
        planId = planId,
        expectedReviewReads = expectedReviewReads,
    )
    if (envelope.capabilityReceipt != expectedCapabilityReceipt) {
        throw Agent3Exception(
            "Invalid Agent 3.0 Start envelope: capability receipt does not match reviewed Preview"
        )
    }

    val validationFailure = runCatching {
        if (envelope.readReview.enabled != expectedReviewReads) {
            throw Agent3Exception(
                "Invalid Agent 3.0 Start envelope: read_review state does not match reviewed intent"
            )
        }
        validateReviewedStartCheckpoint(envelope, expectedReviewReads)
    }.exceptionOrNull()

    if (validationFailure == null) return envelope
    if (validationFailure !is Agent3Exception) throw validationFailure

    return recoverReviewedStartEnvelope(
        rejectedEnvelope = envelope,
        expectedReviewReads = expectedReviewReads,
        originalFailure = validationFailure,
    )
}

private fun Agent3Client.recoverReviewedStartEnvelope(
    rejectedEnvelope: Agent3RunEnvelope,
    expectedReviewReads: Boolean,
    originalFailure: Agent3Exception,
): Agent3RunEnvelope {
    val runId = rejectedEnvelope.run.id.takeIf { it.isNotBlank() }
        ?: throw originalFailure

    return try {
        val fresh = getRunEnvelope(
            runId = runId,
            expectedReviewReads = expectedReviewReads,
        )
        validateReviewedStartCheckpoint(fresh, expectedReviewReads)
        fresh
    } catch (recoveryFailure: Exception) {
        val original = originalFailure.message ?: "the reviewed Start envelope was rejected"
        val recovery = recoveryFailure.message ?: "fresh run status could not be validated"
        throw Agent3Exception(
            "$original. Fresh run recovery failed: $recovery"
        )
    }
}

internal fun validateReviewedStartCheckpoint(
    envelope: Agent3RunEnvelope,
    expectedReviewReads: Boolean,
) {
    val run = envelope.run
    val review = envelope.readReview

    if (!review.waiting) {
        if (
            review.windowStart != null ||
            review.windowEnd != null ||
            review.removableStepIds.isNotEmpty() ||
            review.completedStepId != null ||
            review.completedTool != null
        ) {
            throw Agent3Exception(
                "Invalid Agent 3.0 Start envelope: stale cleared read_review checkpoint"
            )
        }
        return
    }

    if (!expectedReviewReads || !review.enabled || run.state != "running") {
        throw Agent3Exception(
            "Invalid Agent 3.0 Start envelope: waiting read_review checkpoint disagrees with run"
        )
    }

    val start = review.windowStart
    val end = review.windowEnd
    if (
        start == null ||
        end == null ||
        start != run.currentStep ||
        start <= 0 ||
        end <= start ||
        end > run.steps.size
    ) {
        throw Agent3Exception(
            "Invalid Agent 3.0 Start envelope: read_review checkpoint window disagrees with run"
        )
    }

    val window = run.steps.subList(start, end)
    if (window.any { it.id.isNullOrBlank() || it.risk != "read" || it.state != "pending" }) {
        throw Agent3Exception(
            "Invalid Agent 3.0 Start envelope: read_review checkpoint window steps disagree with run"
        )
    }
    val expectedIds = window.map { requireNotNull(it.id) }
    if (review.removableStepIds != expectedIds) {
        throw Agent3Exception(
            "Invalid Agent 3.0 Start envelope: read_review removable ids disagree with run"
        )
    }

    val completedStepId = review.completedStepId?.takeIf { it.isNotBlank() }
    val completedTool = review.completedTool?.takeIf { it.isNotBlank() }
    val completed = run.steps.getOrNull(start - 1)
    if (
        completedStepId == null ||
        completedTool == null ||
        completed == null ||
        completed.id != completedStepId ||
        completed.tool != completedTool ||
        completed.risk != "read" ||
        completed.state != "succeeded"
    ) {
        throw Agent3Exception(
            "Invalid Agent 3.0 Start envelope: completed read_review checkpoint disagrees with run"
        )
    }
}
