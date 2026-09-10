package dk.ternedal.modelrig.desktop.net

/**
 * Reviewed Start boundary for the desktop operator surface.
 *
 * The transport first proves the raw top-level review mode plus its existing
 * plan/termination/capability authority. Only then may the parsed read-review
 * state reach the UI, and it must agree with the exact reviewed Preview mode.
 */
internal fun Agent3Client.startReviewedPlanEnvelope(
    planId: String,
    expectedReviewReads: Boolean,
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
    return envelope
}
