package dk.ternedal.modelrig.net

/**
 * Reviewed Start keeps the server-authored Start envelope bound to the exact
 * review mode and capability receipt that were visible in the reviewed Preview.
 *
 * Ordinary Start still requires an exact raw top-level review-mode match before
 * it can succeed. This reviewed-only transport additionally preserves a narrow
 * recovery reference when that raw proof conflicts: JSON/envelope shape, exact
 * plan id, termination/run identity and exact reviewed capability authority are
 * all proven before a run id can be used for one fresh same-client GET.
 *
 * The conflicting Start payload never becomes UI run authority. Fresh truth from
 * a raw-mode conflict must independently prove both its exact top-level
 * `review_reads` Boolean and parsed read-review state before checkpoint validation
 * may publish it. Post-envelope checkpoint recovery keeps the existing path.
 */
internal fun Agent3Client.startReviewedPlanEnvelope(
    planId: String,
    expectedReviewReads: Boolean,
    expectedCapabilityReceipt: Agent3Client.CapabilityReceipt?,
): Agent3Client.RunEnvelope {
    val transport = startReviewedPlanTransport(
        planId = planId,
        expectedReviewReads = expectedReviewReads,
        expectedCapabilityReceipt = expectedCapabilityReceipt,
    )

    val envelope = when (transport) {
        is Agent3Client.ReviewedStartTransportResult.Accepted -> transport.envelope
        is Agent3Client.ReviewedStartTransportResult.RawReviewConflict -> {
            val originalFailure = ModelRigException(
                "Ugyldigt Agent 3.0 Start-svar: serverens Read review matcher ikke previewet",
            )
            return recoverReviewedStartEnvelope(
                runId = transport.runId,
                expectedReviewReads = expectedReviewReads,
                originalFailure = originalFailure,
                requireRawReviewBinding = true,
            )
        }
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
        runId = envelope.run.id,
        expectedReviewReads = expectedReviewReads,
        originalFailure = validationFailure,
        requireRawReviewBinding = false,
    )
}

private fun Agent3Client.recoverReviewedStartEnvelope(
    runId: String,
    expectedReviewReads: Boolean,
    originalFailure: ModelRigException,
    requireRawReviewBinding: Boolean,
): Agent3Client.RunEnvelope {
    val recoveryRunId = runId.takeIf { it.isNotBlank() }
        ?: throw originalFailure

    return try {
        val fresh = if (requireRawReviewBinding) {
            getReviewedRunEnvelopeStrict(
                runId = recoveryRunId,
                expectedReviewReads = expectedReviewReads,
            )
        } else {
            getRunEnvelope(
                runId = recoveryRunId,
                expectedReviewReads = expectedReviewReads,
            )
        }
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
