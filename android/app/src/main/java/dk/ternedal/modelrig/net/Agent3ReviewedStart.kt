package dk.ternedal.modelrig.net

/**
 * Reviewed Start keeps the server-authored Start envelope bound to the exact
 * capability receipt that was visible in the reviewed Preview.
 *
 * The worker stores that receipt with the single-use plan and requires the
 * start-time re-evaluation to equal it. Mirror that authority at the Android
 * response boundary before run/read-review state can be published to UI.
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
    return envelope
}
