package dk.ternedal.modelrig.desktop.net

/**
 * Reviewed Start boundary for the desktop operator surface.
 *
 * The transport first proves the raw top-level review mode plus its existing
 * plan/termination/capability authority. Only then may the parsed read-review
 * state reach the UI, and both review state and capability authority must agree
 * with the exact Preview shown to the operator.
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
    if (envelope.readReview.enabled != expectedReviewReads) {
        throw Agent3Exception(
            "Invalid Agent 3.0 Start envelope: read_review state does not match reviewed intent"
        )
    }
    if (envelope.capabilityReceipt != expectedCapabilityReceipt) {
        throw Agent3Exception(
            "Invalid Agent 3.0 Start envelope: capability receipt does not match reviewed Preview"
        )
    }
    return envelope
}
