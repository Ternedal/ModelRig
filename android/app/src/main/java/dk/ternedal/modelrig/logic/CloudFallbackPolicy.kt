package dk.ternedal.modelrig.logic

/**
 * Privacy boundary for local-first chat. A cancelled rig request must never
 * be automatically replayed against a cloud provider, even before first token.
 * Keep this pure so both send and retry use the same, JVM-testable policy.
 */
object CloudFallbackPolicy {
    fun shouldFallback(
        emittedChunks: Int,
        rigCallCancelled: Boolean,
        hasCloudKey: Boolean,
        consentEnabled: Boolean,
    ): Boolean = emittedChunks == 0 && !rigCallCancelled && hasCloudKey && consentEnabled
}
