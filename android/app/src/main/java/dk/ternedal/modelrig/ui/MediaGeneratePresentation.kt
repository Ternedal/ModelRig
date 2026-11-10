package dk.ternedal.modelrig.ui

import dk.ternedal.modelrig.net.MediaJob
import dk.ternedal.modelrig.net.MediaJobContract
import dk.ternedal.modelrig.net.MediaJobException
import dk.ternedal.modelrig.net.MediaJobException.Reason
import dk.ternedal.modelrig.net.MediaJobProfile
import dk.ternedal.modelrig.net.MediaJobRequest
import dk.ternedal.modelrig.net.MediaJobState

/**
 * The generate screen as pure data (#2275 A1). No Android types, so every
 * transition is a unit test.
 *
 * ```
 * Loading → Ready → Submitting → Following(queued | running | publishing) → Finished
 *    ↘ Unavailable         ↘ Ready + error       ↘ cancelling …           (completed | failed | cancelled | expired)
 * ```
 *
 * The prompt lives only in this state, in memory. It is never written to
 * storage, a log or a saved instance state; leaving the screen forgets it.
 */
sealed interface MediaGeneratePhase {
    data object Loading : MediaGeneratePhase

    /** The rig does not offer generation (404, 503, an answer not understood, no image profile). */
    data class Unavailable(val message: String) : MediaGeneratePhase

    data object Ready : MediaGeneratePhase

    data object Submitting : MediaGeneratePhase

    data class Following(val job: MediaJob, val cancelling: Boolean = false) : MediaGeneratePhase

    data class Finished(val job: MediaJob) : MediaGeneratePhase
}

data class MediaGenerateState(
    val phase: MediaGeneratePhase = MediaGeneratePhase.Loading,
    val profiles: List<MediaJobProfile> = emptyList(),
    val profileId: String? = null,
    val prompt: String = "",
    val size: Pair<Int, Int>? = null,
    /** A message for the last action that failed; the form stays usable. */
    val error: String? = null,
) {
    val profile: MediaJobProfile? get() = profiles.firstOrNull { it.profileId == profileId }

    val canSubmit: Boolean
        get() {
            val p = profile ?: return false
            val text = prompt.trim()
            return (phase == MediaGeneratePhase.Ready || phase is MediaGeneratePhase.Finished) &&
                text.isNotEmpty() && text.length <= p.maxPromptChars && size in p.sizes
        }

    val canCancel: Boolean
        get() = (phase as? MediaGeneratePhase.Following)?.let { !it.cancelling && !it.job.cancelRequested } == true

    /** Only a verified completed job gives a gallery ID; nothing else opens a picture. */
    val completedAssetId: String?
        get() = (phase as? MediaGeneratePhase.Finished)?.job?.takeIf { it.state == MediaJobState.COMPLETED }?.assetId

    /** True while the screen should ask the rig for news. */
    val polling: Boolean get() = phase is MediaGeneratePhase.Following
}

object MediaGenerate {
    const val POLL_MILLIS = 2_000L

    fun profilesLoaded(state: MediaGenerateState, profiles: List<MediaJobProfile>): MediaGenerateState {
        if (profiles.isEmpty()) {
            return state.copy(phase = MediaGeneratePhase.Unavailable("Riggen har ingen billedprofil slået til"),
                profiles = emptyList(), profileId = null, size = null)
        }
        val keep = profiles.firstOrNull { it.profileId == state.profileId } ?: profiles.first()
        return state.copy(phase = MediaGeneratePhase.Ready, profiles = profiles, profileId = keep.profileId,
            size = state.size?.takeIf { it in keep.sizes } ?: keep.sizes.first(), error = null)
    }

    fun profilesFailed(state: MediaGenerateState, e: MediaJobException): MediaGenerateState =
        state.copy(phase = MediaGeneratePhase.Unavailable(message(e)))

    fun selectProfile(state: MediaGenerateState, id: String): MediaGenerateState {
        val p = state.profiles.firstOrNull { it.profileId == id } ?: return state
        return state.copy(profileId = p.profileId, size = state.size?.takeIf { it in p.sizes } ?: p.sizes.first())
    }

    fun selectSize(state: MediaGenerateState, size: Pair<Int, Int>): MediaGenerateState =
        if (state.profile?.sizes?.contains(size) == true) state.copy(size = size) else state

    fun editPrompt(state: MediaGenerateState, text: String): MediaGenerateState {
        val max = state.profile?.maxPromptChars ?: return state.copy(prompt = text)
        return state.copy(prompt = text.take(max))
    }

    /** The request to send, or null when the form is not ready. Never logged. */
    fun request(state: MediaGenerateState): MediaJobRequest? {
        if (!state.canSubmit) return null
        val p = state.profile ?: return null
        val (w, h) = state.size ?: return null
        return MediaJobRequest(profileId = p.profileId, prompt = state.prompt.trim(), width = w, height = h,
            steps = null, seed = null, task = MediaJobContract.IMAGE_TASK)
    }

    fun submitting(state: MediaGenerateState) = state.copy(phase = MediaGeneratePhase.Submitting, error = null)

    fun submitted(state: MediaGenerateState, job: MediaJob) = state.copy(phase = phaseFor(job), error = null)

    fun submitFailed(state: MediaGenerateState, e: MediaJobException): MediaGenerateState =
        if (e.reason == Reason.UNAVAILABLE || e.reason == Reason.UNAUTHORIZED || e.reason == Reason.NOT_PAIRED) {
            state.copy(phase = MediaGeneratePhase.Unavailable(message(e)))
        } else {
            state.copy(phase = MediaGeneratePhase.Ready, error = message(e))
        }

    /** A poll result. A job that changed identity is not ours: refuse it. */
    fun polled(state: MediaGenerateState, job: MediaJob): MediaGenerateState {
        val current = (state.phase as? MediaGeneratePhase.Following)?.job ?: return state
        if (job.id != current.id) return state.copy(phase = MediaGeneratePhase.Unavailable("Uventet svar fra riggen"))
        val following = state.phase as MediaGeneratePhase.Following
        val next = phaseFor(job)
        return if (next is MediaGeneratePhase.Following) {
            state.copy(phase = next.copy(cancelling = following.cancelling && !job.cancelRequested))
        } else {
            state.copy(phase = next)
        }
    }

    /**
     * A failed poll. A network blip keeps following (the next poll retries);
     * a job the rig no longer knows, or an answer not understood, ends it.
     */
    fun pollFailed(state: MediaGenerateState, e: MediaJobException): MediaGenerateState {
        if (state.phase !is MediaGeneratePhase.Following) return state
        return when (e.reason) {
            Reason.NETWORK -> state.copy(error = message(e))
            Reason.NOT_FOUND -> state.copy(phase = MediaGeneratePhase.Unavailable("Jobbet findes ikke længere på riggen"))
            else -> state.copy(phase = MediaGeneratePhase.Unavailable(message(e)), error = null)
        }
    }

    fun cancelling(state: MediaGenerateState): MediaGenerateState {
        val following = state.phase as? MediaGeneratePhase.Following ?: return state
        return state.copy(phase = following.copy(cancelling = true), error = null)
    }

    /** Cancel answered: show the job it returned, or keep following if it returned none. */
    fun cancelled(state: MediaGenerateState, job: MediaJob?): MediaGenerateState =
        if (job == null) state.copy(phase = (state.phase as? MediaGeneratePhase.Following)?.copy(cancelling = false) ?: state.phase)
        else polled(state, job)

    fun cancelFailed(state: MediaGenerateState, e: MediaJobException): MediaGenerateState {
        val following = state.phase as? MediaGeneratePhase.Following ?: return state
        return if (e.reason == Reason.NOT_FOUND) {
            // Already finished on the rig; the next poll shows how.
            state.copy(phase = following.copy(cancelling = false), error = "Jobbet var allerede færdigt")
        } else {
            state.copy(phase = following.copy(cancelling = false), error = message(e))
        }
    }

    /** Start another picture after a finished one; the prompt stays for editing. */
    fun again(state: MediaGenerateState): MediaGenerateState =
        if (state.phase is MediaGeneratePhase.Finished) state.copy(phase = MediaGeneratePhase.Ready, error = null) else state

    private fun phaseFor(job: MediaJob): MediaGeneratePhase =
        if (job.state.terminal) MediaGeneratePhase.Finished(job) else MediaGeneratePhase.Following(job)

    fun stateLabel(job: MediaJob): String = when (job.state) {
        MediaJobState.QUEUED -> if (job.cancelRequested) "Annulleres …" else "I kø på riggen"
        MediaJobState.RUNNING -> if (job.cancelRequested) "Annulleres …" else "Genererer …"
        MediaJobState.PUBLISHING -> "Gemmer billedet …"
        MediaJobState.COMPLETED -> "Færdig"
        MediaJobState.FAILED -> errorText(job.errorCode)
        MediaJobState.CANCELLED -> "Annulleret"
        MediaJobState.EXPIRED -> "Udløbet: riggen nåede ikke at starte jobbet inden for et døgn"
    }

    fun errorText(code: String?): String = when (code) {
        "too_late" -> "For sent at annullere: billedet var allerede ved at blive gemt"
        "gpu_unavailable" -> "Grafikkortet på riggen er ikke ledigt"
        "interrupted_by_restart" -> "Afbrudt: riggen genstartede"
        "interrupted_during_publication" -> "Afbrudt mens billedet blev gemt"
        "generation_failed" -> "Genereringen fejlede på riggen"
        "expired_unclaimed" -> "Udløbet: riggen nåede ikke at starte jobbet"
        else -> "Genereringen fejlede"
    }

    fun message(e: MediaJobException): String = when (e.reason) {
        Reason.BUSY -> when (e.code) {
            "active_limit" -> "Du har allerede tre job i gang; vent til ét er færdigt"
            else -> "Riggens kø er fuld; prøv igen om lidt"
        }
        Reason.INVALID_REQUEST -> when (e.code) {
            "profile_not_enabled" -> "Profilen er ikke slået til på riggen"
            "video_not_enabled", "task_not_served" -> "Den type generering er ikke slået til på riggen"
            else -> "Riggen afviste forespørgslen"
        }
        Reason.UNAVAILABLE -> e.message ?: "Billedgenerering er ikke tilgængelig på denne rig"
        else -> e.message ?: "Noget gik galt"
    }
}
