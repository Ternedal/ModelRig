package dk.ternedal.modelrig.net

/**
 * Reviewed Start keeps the server-authored Start envelope bound to the exact
 * review mode and capability receipt that were visible in the reviewed Preview.
 *
 * The worker persists read-review policy before the run itself and returns that
 * policy in the Start envelope. Reject a response whose parsed review state no
 * longer agrees with the reviewed mode before run/read-review state reaches UI.
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
    if (envelope.readReview.enabled != expectedReviewReads) {
        throw ModelRigException(
            "Ugyldigt Agent 3.0 Start-svar: Read review-state matcher ikke previewet",
        )
    }
    return envelope
}
