package dk.ternedal.modelrig.net

/**
 * Reviewed Start keeps the server-authored Start envelope bound to the exact
 * review mode and capability receipt that were visible in the reviewed Preview.
 *
 * The reviewed transport baseline-validates plan/run/termination/capability
 * structure before exposing the raw top-level review mode separately. A raw mode
 * conflict therefore grants only a safely bound run id as recovery reference;
 * the rejected Start payload never becomes UI authority. Fresh server truth must
 * then independently prove the exact run id, reviewed mode and checkpoint. The
 * already-proven Start capability receipt remains immutable review evidence across
 * that recovery only after the same fresh run response re-proves plan identity.
 */
internal fun Agent3Client.startReviewedPlanEnvelope(
    planId: String,
    expectedReviewReads: Boolean,
    expectedCapabilityReceipt: Agent3Client.CapabilityReceipt?,
): Agent3Client.RunEnvelope {
    val transport = startReviewedPlanTransport(planId)
    val envelope = transport.envelope
    if (envelope.capabilityReceipt != expectedCapabilityReceipt) {
        throw ModelRigException(
            "Ugyldigt Agent 3.0 Start-svar: capability receipt matcher ikke previewet",
        )
    }

    if (transport.responseReviewReads != expectedReviewReads) {
        return recoverReviewedStartEnvelope(
            recoveryRunId = envelope.run.id,
            expectedReviewReads = expectedReviewReads,
            expectedCapabilityReceipt = expectedCapabilityReceipt,
            originalFailure = ModelRigException(
                "Ugyldigt Agent 3.0 Start-svar: serverens Read review matcher ikke previewet; " +
                    "det baseline-validerede run-id er kun recovery-reference",
            ),
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
        recoveryRunId = envelope.run.id,
        expectedReviewReads = expectedReviewReads,
        expectedCapabilityReceipt = expectedCapabilityReceipt,
        originalFailure = validationFailure,
    )
}

private fun Agent3Client.recoverReviewedStartEnvelope(
    recoveryRunId: String,
    expectedReviewReads: Boolean,
    expectedCapabilityReceipt: Agent3Client.CapabilityReceipt?,
    originalFailure: ModelRigException,
): Agent3Client.RunEnvelope {
    if (recoveryRunId.isBlank()) throw originalFailure

    return try {
        val fresh = getRunEnvelope(
            runId = recoveryRunId,
            expectedReviewReads = expectedReviewReads,
        )
        validateReviewedStartCheckpoint(fresh, expectedReviewReads)

        if (expectedCapabilityReceipt != null) {
            val current = fresh.capabilityReceipt
                ?: throw ModelRigException(
                    "Ugyldigt Agent 3.0 frisk run-status: same-snapshot capability receipt mangler",
                )
            if (
                current.planSha256 != expectedCapabilityReceipt.planSha256 ||
                current.route != expectedCapabilityReceipt.route ||
                current.requiredCapabilityIds != expectedCapabilityReceipt.requiredCapabilityIds
            ) {
                throw ModelRigException(
                    "Ugyldigt Agent 3.0 frisk run-status: same-snapshot run-plan matcher ikke previewet",
                )
            }
        }

        // The current receipt proves only that this exact fresh run snapshot is
        // still the reviewed plan. Historical review authority remains exactly
        // the receipt the operator saw (including null).
        fresh.copy(capabilityReceipt = expectedCapabilityReceipt)
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
