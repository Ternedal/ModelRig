package dk.ternedal.modelrig.desktop.net

/**
 * Reviewed Start boundary for the desktop operator surface.
 *
 * The reviewed transport baseline-validates the Start envelope before exposing
 * the raw top-level review mode separately. A raw mode conflict therefore grants
 * only the already-bound nonblank run id as recovery reference; the rejected
 * Start payload never becomes UI authority. Fresh server truth must independently
 * prove the exact run id, expected review mode and checkpoint before publication.
 * When the reviewed Preview carried capability evidence, the fresh generic GET
 * must also carry current capability evidence computed from that exact same run
 * snapshot. Only its plan identity is recovery authority; graph state may drift.
 */
internal fun Agent3Client.startReviewedPlanEnvelope(
    planId: String,
    expectedReviewReads: Boolean,
    expectedCapabilityReceipt: Agent3CapabilityReceipt? = null,
): Agent3RunEnvelope {
    val transport = startReviewedPlanTransport(planId)
    val envelope = transport.envelope
    if (envelope.capabilityReceipt != expectedCapabilityReceipt) {
        throw Agent3Exception(
            "Invalid Agent 3.0 Start envelope: capability receipt does not match reviewed Preview"
        )
    }

    if (transport.responseReviewReads != expectedReviewReads) {
        return recoverReviewedStartEnvelope(
            recoveryRunId = envelope.run.id,
            expectedReviewReads = expectedReviewReads,
            expectedCapabilityReceipt = expectedCapabilityReceipt,
            originalFailure = Agent3Exception(
                "Invalid Agent 3.0 Start envelope: server review_reads does not match reviewed intent; " +
                    "the baseline-validated run id is recovery-only"
            ),
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
        recoveryRunId = envelope.run.id,
        expectedReviewReads = expectedReviewReads,
        expectedCapabilityReceipt = expectedCapabilityReceipt,
        originalFailure = validationFailure,
    )
}

private fun Agent3Client.recoverReviewedStartEnvelope(
    recoveryRunId: String,
    expectedReviewReads: Boolean,
    expectedCapabilityReceipt: Agent3CapabilityReceipt?,
    originalFailure: Agent3Exception,
): Agent3RunEnvelope {
    if (recoveryRunId.isBlank()) throw originalFailure

    return try {
        val fresh = getRunEnvelope(
            runId = recoveryRunId,
            expectedReviewReads = expectedReviewReads,
        )
        validateReviewedStartCheckpoint(fresh, expectedReviewReads)
        if (expectedCapabilityReceipt != null) {
            val current = fresh.capabilityReceipt
                ?: throw Agent3Exception(
                    "Invalid Agent 3.0 fresh run envelope: same-snapshot capability evidence is missing"
                )
            validateRecoveredCapabilityPlan(
                current = current,
                reviewed = expectedCapabilityReceipt,
            )
        }
        // Current graph state describes now, not the evidence the operator
        // reviewed. Publish only the exact historical reviewed receipt after
        // same-snapshot plan identity has been proven.
        fresh.copy(capabilityReceipt = expectedCapabilityReceipt)
    } catch (recoveryFailure: Exception) {
        val original = originalFailure.message ?: "the reviewed Start envelope was rejected"
        val recovery = recoveryFailure.message ?: "fresh run status could not be validated"
        throw Agent3Exception(
            "$original. Fresh run recovery failed: $recovery"
        )
    }
}

private fun validateRecoveredCapabilityPlan(
    current: Agent3CapabilityReceipt,
    reviewed: Agent3CapabilityReceipt,
) {
    if (
        current.planSha256 != reviewed.planSha256 ||
        current.route != reviewed.route ||
        current.requiredCapabilityIds != reviewed.requiredCapabilityIds
    ) {
        throw Agent3Exception(
            "Invalid Agent 3.0 capability evidence: current run plan does not match reviewed Preview"
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
