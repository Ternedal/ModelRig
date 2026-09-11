package dk.ternedal.modelrig.net

/**
 * Reviewed Start keeps the server-authored Start envelope bound to the exact
 * review mode and capability receipt that were visible in the reviewed Preview.
 *
 * The transport first proves the raw top-level review mode, termination receipt
 * and exact plan id. This boundary then proves the exact Preview capability
 * receipt before parsed read-review/checkpoint state may become UI authority.
 *
 * If that final reviewed state is rejected, the already-bound nonblank run id is
 * only a recovery reference: the rejected Start payload is never published.
 * Fresh server truth must be fetched on the same client connection and pass the
 * exact run-id, review-mode and checkpoint bindings before it can be returned.
 */
internal fun Agent3Client.startReviewedPlanEnvelope(
    planId: String,
    expectedReviewReads: Boolean,
    expectedCapabilityReceipt: Agent3Client.CapabilityReceipt?,
): Agent3Client.RunEnvelope {
    val envelope = startPlanEnvelope(
        planId = planId,
        expectedReviewReads = expectedReviewReads,
    )
    if (envelope.capabilityReceipt != expectedCapabilityReceipt) {
        throw ModelRigException(
            "Ugyldigt Agent 3.0 Start-svar: capability receipt matcher ikke previewet",
        )
    }

    val validationFailure = runCatching {
        if (envelope.readReview.enabled != expectedReviewReads) {
            throw ModelRigException(
                "Ugyldigt Agent 3.0 Start-svar: Read review-state matcher ikke previewet",
            )
        }
        validateReviewedStartCheckpoint(envelope, expectedReviewReads)
    }.exceptionOrNull()

    if (validationFailure == null) return envelope
    if (validationFailure !is ModelRigException) throw validationFailure

    return recoverReviewedStartEnvelope(
        rejectedEnvelope = envelope,
        expectedReviewReads = expectedReviewReads,
        originalFailure = validationFailure,
    )
}

private fun Agent3Client.recoverReviewedStartEnvelope(
    rejectedEnvelope: Agent3Client.RunEnvelope,
    expectedReviewReads: Boolean,
    originalFailure: ModelRigException,
): Agent3Client.RunEnvelope {
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
        val original = originalFailure.message ?: "det reviewede Start-svar blev afvist"
        val recovery = recoveryFailure.message ?: "frisk run-status kunne ikke valideres"
        throw ModelRigException(
            "$original. Frisk run-recovery fejlede: $recovery",
        )
    }
}

internal fun validateReviewedStartCheckpoint(
    envelope: Agent3Client.RunEnvelope,
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
            throw ModelRigException(
                "Ugyldigt Agent 3.0 run-svar: stale cleared Read review-checkpoint",
            )
        }
        return
    }

    if (!expectedReviewReads || !review.enabled || run.state != "running") {
        throw ModelRigException(
            "Ugyldigt Agent 3.0 run-svar: ventende Read review-checkpoint er uenig med runnet",
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
        throw ModelRigException(
            "Ugyldigt Agent 3.0 run-svar: Read review-vinduet er uenig med runnet",
        )
    }

    val window = run.steps.subList(start, end)
    if (window.any { it.id.isNullOrBlank() || it.risk != "read" || it.state != "pending" }) {
        throw ModelRigException(
            "Ugyldigt Agent 3.0 run-svar: Read review-vinduets trin er uenige med runnet",
        )
    }
    val expectedIds = window.map { requireNotNull(it.id) }
    if (review.removableStepIds != expectedIds) {
        throw ModelRigException(
            "Ugyldigt Agent 3.0 run-svar: Read review-removable ids er uenige med runnet",
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
        throw ModelRigException(
            "Ugyldigt Agent 3.0 run-svar: completed Read review-checkpoint er uenig med runnet",
        )
    }
}
