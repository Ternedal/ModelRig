package dk.ternedal.modelrig.ui

import dk.ternedal.modelrig.net.MediaJob
import dk.ternedal.modelrig.net.MediaJobState

/**
 * What the owner may do after a job ended. The app never acts on its own:
 * there is no idempotency key, so an automatic resubmit could run (and cost)
 * a generation twice.
 */
enum class MediaJobRetry {
    /** Submitting the same request again is reasonable. */
    RESUBMIT,

    /** The rig is busy or must be restarted; the same request may work later. */
    LATER,

    /** The request itself is the problem: change it first. */
    FIX_INPUT,

    /** Nothing to retry (completed or cancelled). */
    NONE,
}

data class MediaJobOutcome(val message: String, val retry: MediaJobRetry)

/** Danish text for the job screen. Pure; no Android types. */
object MediaJobPresentation {

    fun stateLabel(state: MediaJobState): String = when (state) {
        MediaJobState.QUEUED -> "I kø"
        MediaJobState.RUNNING -> "Genererer"
        MediaJobState.PUBLISHING -> "Gemmer i galleriet"
        MediaJobState.COMPLETED -> "Færdig"
        MediaJobState.FAILED -> "Fejlede"
        MediaJobState.CANCELLED -> "Annulleret"
        MediaJobState.EXPIRED -> "Udløbet"
    }

    /**
     * Every error the job store and the media executor write, keyed exactly as
     * stored. tests/workflow_media_job_contract.py fails when one is missing.
     * The two sentences are the store's own restart errors (not codes, today).
     */
    val ERRORS: Map<String, MediaJobOutcome> = mapOf(
        "expired_unclaimed" to MediaJobOutcome(
            "Jobbet ventede over 24 timer uden at blive startet.", MediaJobRetry.RESUBMIT),
        "generation_failed" to MediaJobOutcome(
            "Genereringen fejlede.", MediaJobRetry.RESUBMIT),
        "publication_failed" to MediaJobOutcome(
            "Resultatet blev lavet, men kunne ikke gemmes i galleriet.", MediaJobRetry.RESUBMIT),
        "generation_request_rejected" to MediaJobOutcome(
            "Riggen afviste anmodningen. Ret indstillingerne og prøv igen.", MediaJobRetry.FIX_INPUT),
        "source_image_unavailable" to MediaJobOutcome(
            "Kildebilledet findes ikke længere eller kan ikke bruges. Vælg et andet.", MediaJobRetry.FIX_INPUT),
        "gpu_busy" to MediaJobOutcome(
            "GPU'en er optaget. Prøv igen senere.", MediaJobRetry.LATER),
        "gpu_unavailable" to MediaJobOutcome(
            "GPU'en var optaget for længe. Prøv igen senere.", MediaJobRetry.LATER),
        "gpu_memory_retained" to MediaJobOutcome(
            "GPU-hukommelsen blev ikke frigivet. Riggen skal genstartes, før der kan genereres igen.",
            MediaJobRetry.LATER),
        "interrupted by restart" to MediaJobOutcome(
            "Jobbet blev afbrudt, fordi riggen genstartede.", MediaJobRetry.RESUBMIT),
        "interrupted during publication" to MediaJobOutcome(
            "Jobbet blev afbrudt, mens resultatet blev gemt.", MediaJobRetry.RESUBMIT),
    )

    private val UNKNOWN_ERROR = MediaJobOutcome("Jobbet fejlede.", MediaJobRetry.RESUBMIT)

    /** Null while the job is still active. An unknown error is never shown verbatim. */
    fun outcome(job: MediaJob): MediaJobOutcome? = when (job.state) {
        MediaJobState.QUEUED, MediaJobState.RUNNING, MediaJobState.PUBLISHING -> null
        MediaJobState.COMPLETED -> MediaJobOutcome("Færdig. Resultatet ligger i galleriet.", MediaJobRetry.NONE)
        MediaJobState.CANCELLED -> MediaJobOutcome("Jobbet blev annulleret.", MediaJobRetry.NONE)
        MediaJobState.FAILED, MediaJobState.EXPIRED -> ERRORS[job.error] ?: UNKNOWN_ERROR
    }
}

/**
 * How often the job screen asks again. Pure so it can be tested without a
 * clock. The server is the authority for every transition, including expiry;
 * the phone never computes a state from its own clock.
 */
object MediaJobPolling {
    const val FIRST_MS = 2_000L
    const val ACTIVE_MAX_MS = 15_000L

    /** A queued job may wait hours for the GPU (Ollama keeps VRAM; video is long). */
    const val QUEUED_MAX_MS = 60_000L

    /** Offline or a failed request: keep the last known job on screen and back off to this. */
    const val OFFLINE_MAX_MS = 120_000L

    /**
     * Delay before the next request, or null to stop. [attempt] counts
     * consecutive requests in the current state (0 right after a change), or
     * consecutive failures when [lastRequestFailed].
     */
    fun nextDelayMs(state: MediaJobState?, attempt: Int, lastRequestFailed: Boolean = false): Long? {
        if (state != null && state.terminal) return null
        val cap = when {
            lastRequestFailed -> OFFLINE_MAX_MS
            state == MediaJobState.QUEUED -> QUEUED_MAX_MS
            else -> ACTIVE_MAX_MS
        }
        val shift = attempt.coerceIn(0, 16)
        return (FIRST_MS shl shift).coerceAtMost(cap)
    }
}
