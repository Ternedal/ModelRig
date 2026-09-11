package dk.ternedal.modelrig.desktop.net

/**
 * Reviewed Start boundary for the desktop operator surface.
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
    expectedCapabilityReceipt: Agent3CapabilityReceipt? = null,
): Agent3RunEnvelope {
    val transport = startReviewedPlanTransport(
        planId = planId,
        expectedReviewReads = expectedReviewReads,
        expectedCapabilityReceipt = expectedCapabilityReceipt,
    )

    val envelope = when (transport) {
        is Agent3ReviewedStartTransportResult.Accepted -> transport.envelope
        is Agent3ReviewedStartTransportResult.RawReviewConflict -> {
            val originalFailure = Agent3Exception(
                "Invalid Agent 3.0 Start envelope: server review_reads does not match reviewed intent"
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
            throw Agent3Exception(
                "Invalid Agent 3.0 Start envelope: read_review state does not match reviewed intent"
            )
        }
        validateReviewedStartCheckpoint(envelope, expectedReviewReads)
    }.exceptionOrNull()

    if (validationFailure == null) return envelope
    if (validationFailure !is Agent3Exception) throw validationFailure

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
    originalFailure: Agent3Exception,
    requireRawReviewBinding: Boolean,
): Agent3RunEnvelope {
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
