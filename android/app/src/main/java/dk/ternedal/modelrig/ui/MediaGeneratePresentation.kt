package dk.ternedal.modelrig.ui

import dk.ternedal.modelrig.net.MediaJob
import dk.ternedal.modelrig.net.MediaJobCancel
import dk.ternedal.modelrig.net.MediaJobContract
import dk.ternedal.modelrig.net.MediaJobException
import dk.ternedal.modelrig.net.MediaJobException.Reason
import dk.ternedal.modelrig.net.MediaJobProfile
import dk.ternedal.modelrig.net.MediaJobRequest
import dk.ternedal.modelrig.net.MediaJobState
import dk.ternedal.modelrig.net.MediaModality

/**
 * The generate screen as pure data (#2275 A1). No Android types, so every
 * transition is a unit test.
 *
 * ```
 * Loading → Ready → Submitting → Following(queued | running | publishing) → Finished
 *    ↘ Unavailable         ↘ Ready + error       ↘ cancelling …           (completed | failed | cancelled | expired)
 *                                                ↘ Stalled (rig unreachable after bounded retries; same job, "Prøv igen")
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

    /**
     * A job the screen asks the rig about. [failures] counts transient poll failures in a
     * row (network, 502/503/504) and drives the backoff; [tooLate] is set when cancel came
     * after the picture was already being saved.
     */
    data class Following(
        val job: MediaJob,
        val cancelling: Boolean = false,
        val failures: Int = 0,
        val tooLate: Boolean = false,
    ) : MediaGeneratePhase

    /**
     * The rig stopped answering while a job was followed. The job ID is kept: the job
     * may still finish on the rig, and [MediaGenerate.resume] follows it again.
     */
    data class Stalled(val job: MediaJob, val tooLate: Boolean = false) : MediaGeneratePhase

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
        get() = (phase as? MediaGeneratePhase.Following)?.let {
            !it.cancelling && !it.job.cancelRequested && !it.tooLate && it.job.state != MediaJobState.PUBLISHING
        } == true

    /** Only a verified completed job gives a gallery ID; nothing else opens a picture. */
    val completedAssetId: String?
        get() = (phase as? MediaGeneratePhase.Finished)?.job?.takeIf { it.state == MediaJobState.COMPLETED }?.assetId

    /** True while the screen should ask the rig for news. */
    val polling: Boolean get() = phase is MediaGeneratePhase.Following
}

object MediaGenerate {
    const val POLL_MILLIS = 2_000L

    /** Transient poll failures in a row before the screen stops asking and offers "Prøv igen". */
    const val MAX_POLL_FAILURES = 6

    /** The longest wait between two polls while the rig is not answering. */
    const val MAX_POLL_BACKOFF_MILLIS = 30_000L

    const val TOO_LATE_TEXT = "For sent at annullere: resultatet er allerede ved at blive gemt"

    /**
     * The wait before the next poll: [base] while all is well, then doubled per failure
     * in a row, capped at [MAX_POLL_BACKOFF_MILLIS] (2, 4, 8, 16, 30, 30 s).
     */
    fun pollDelay(state: MediaGenerateState, base: Long = POLL_MILLIS): Long {
        val failures = (state.phase as? MediaGeneratePhase.Following)?.failures ?: 0
        if (failures <= 0) return base
        val factor = 1L shl failures.coerceAtMost(16)
        return (base * factor).coerceAtMost(MAX_POLL_BACKOFF_MILLIS.coerceAtLeast(base))
    }

    fun profilesLoaded(state: MediaGenerateState, profiles: List<MediaJobProfile>): MediaGenerateState {
        if (profiles.isEmpty()) {
            return state.copy(phase = MediaGeneratePhase.Unavailable("Riggen har ingen billed- eller videoprofil slået til"),
                profiles = emptyList(), profileId = null, size = null)
        }
        val keep = profiles.firstOrNull { it.profileId == state.profileId } ?: profiles.first()
        return state.copy(phase = MediaGeneratePhase.Ready, profiles = profiles, profileId = keep.profileId,
            size = state.size?.takeIf { it in keep.sizes } ?: keep.sizes.first(), error = null)
    }

    fun profilesFailed(state: MediaGenerateState, e: MediaJobException): MediaGenerateState =
        state.copy(phase = MediaGeneratePhase.Unavailable(
            if (e.reason == Reason.TRANSIENT) "Billedgenerering er ikke tilgængelig lige nu" else message(e)))

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
            steps = null, seed = null, task = p.task)
    }

    fun submitting(state: MediaGenerateState) = state.copy(phase = MediaGeneratePhase.Submitting, error = null)

    fun submitted(state: MediaGenerateState, job: MediaJob) = state.copy(phase = phaseFor(job), error = null)

    /**
     * The job a recreated screen picks up again (#2275 backlog task 4): rotation, a
     * configuration change or the process being killed in the background. Only this
     * ID is ever saved, never the prompt; it is a job the rig already holds.
     */
    fun jobId(state: MediaGenerateState): String? = when (val p = state.phase) {
        is MediaGeneratePhase.Following -> p.job.id
        is MediaGeneratePhase.Stalled -> p.job.id
        is MediaGeneratePhase.Finished -> p.job.id
        else -> null
    }

    /** The saved job, read back once the profiles are in; only onto the empty form, never over another job. */
    fun restored(state: MediaGenerateState, id: String, job: MediaJob): MediaGenerateState = when {
        state.phase != MediaGeneratePhase.Ready -> state
        job.id != id -> state.copy(phase = MediaGeneratePhase.Unavailable("Uventet svar fra riggen"))
        else -> state.copy(phase = phaseFor(job), error = null)
    }

    fun restoreFailed(state: MediaGenerateState, e: MediaJobException): MediaGenerateState {
        if (state.phase != MediaGeneratePhase.Ready) return state
        return when (e.reason) {
            Reason.NOT_FOUND -> state.copy(error = "Det tidligere job findes ikke længere på riggen")
            Reason.UNAUTHORIZED, Reason.NOT_PAIRED -> state.copy(phase = MediaGeneratePhase.Unavailable(message(e)))
            // Never a guess: the job may well still be running, and the form says so.
            else -> state.copy(error = RESTORE_FAILED_TEXT)
        }
    }

    const val RESTORE_FAILED_TEXT = "Det tidligere job kunne ikke hentes; det kører måske stadig på riggen"

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
        // A good answer ends a run of failures and its message. "Too late" stays on screen
        // through to the finished job, so the user sees why the picture arrived anyway.
        val note = if (following.tooLate) TOO_LATE_TEXT else null
        return if (next is MediaGeneratePhase.Following) {
            state.copy(phase = next.copy(cancelling = following.cancelling && !job.cancelRequested,
                tooLate = following.tooLate), error = note)
        } else {
            state.copy(phase = next, error = note)
        }
    }

    /**
     * A failed poll (6780346935 #2). The job keeps running on the rig whatever the phone
     * sees, so a transient failure (network, 502/503/504) keeps following with backoff, and
     * after [MAX_POLL_FAILURES] in a row the screen stops asking but keeps the job
     * ([MediaGeneratePhase.Stalled]). Only a job the rig no longer knows, a pairing that is no
     * longer valid, or an answer not understood ends it; the pairing case says so plainly.
     */
    fun pollFailed(state: MediaGenerateState, e: MediaJobException): MediaGenerateState {
        val following = state.phase as? MediaGeneratePhase.Following ?: return state
        return when (e.reason) {
            Reason.NETWORK, Reason.TRANSIENT -> {
                val failures = following.failures + 1
                if (failures >= MAX_POLL_FAILURES) {
                    // tooLate travels with the job, so the reason survives a stall (6788066129).
                    state.copy(phase = MediaGeneratePhase.Stalled(following.job, tooLate = following.tooLate),
                        error = "Riggen svarer ikke; jobbet kan stadig blive færdigt. Tryk Prøv igen")
                } else {
                    state.copy(phase = following.copy(failures = failures), error = message(e))
                }
            }
            Reason.NOT_FOUND -> state.copy(phase = MediaGeneratePhase.Unavailable("Jobbet findes ikke længere på riggen"))
            Reason.UNAUTHORIZED, Reason.NOT_PAIRED -> state.copy(phase = MediaGeneratePhase.Unavailable(message(e)), error = null)
            else -> state.copy(phase = MediaGeneratePhase.Unavailable(message(e)), error = null)
        }
    }

    /** Follow a stalled job again, from a fresh backoff. */
    fun resume(state: MediaGenerateState): MediaGenerateState {
        val stalled = state.phase as? MediaGeneratePhase.Stalled ?: return state
        return state.copy(phase = MediaGeneratePhase.Following(stalled.job, tooLate = stalled.tooLate),
            error = if (stalled.tooLate) TOO_LATE_TEXT else null)
    }

    fun cancelling(state: MediaGenerateState): MediaGenerateState {
        val following = state.phase as? MediaGeneratePhase.Following ?: return state
        return state.copy(phase = following.copy(cancelling = true), error = null)
    }

    /**
     * Cancel answered (6780346935 #1). `too_late` means the picture is already being saved:
     * clear "Annulleres …", say it is too late, and keep following, since the job goes on
     * to `completed`. Otherwise show the job it returned, or keep following if none.
     */
    fun cancelled(state: MediaGenerateState, answer: MediaJobCancel): MediaGenerateState {
        val following = state.phase as? MediaGeneratePhase.Following ?: return state
        if (answer.tooLate) {
            val base = state.copy(phase = following.copy(cancelling = false, tooLate = true), error = TOO_LATE_TEXT)
            return answer.job?.let { polled(base, it).copy(error = TOO_LATE_TEXT) } ?: base
        }
        val job = answer.job ?: return state.copy(phase = following.copy(cancelling = false))
        return polled(state, job)
    }

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

    /** The modality of the profile a job was made with, when the screen knows it. */
    fun modalityOf(state: MediaGenerateState, job: MediaJob): MediaModality =
        state.profiles.firstOrNull { it.profileId == job.profileId }?.modality ?: MediaModality.IMAGE

    /** "Billede" or "Video", for the profile chips and the title. */
    fun modalityName(modality: MediaModality): String = when (modality) {
        MediaModality.IMAGE -> "Billede"
        MediaModality.VIDEO -> "Video"
    }

    fun title(state: MediaGenerateState): String =
        if (state.profiles.any { it.modality == MediaModality.VIDEO }) "Generér billede eller video" else "Generér billede"

    fun stateLabel(job: MediaJob, modality: MediaModality = MediaModality.IMAGE): String = when (job.state) {
        MediaJobState.QUEUED -> if (job.cancelRequested) "Annulleres …" else "I kø på riggen"
        MediaJobState.RUNNING -> if (job.cancelRequested) "Annulleres …" else "Genererer …"
        MediaJobState.PUBLISHING -> if (modality == MediaModality.VIDEO) "Gemmer videoen …" else "Gemmer billedet …"
        MediaJobState.COMPLETED -> "Færdig"
        MediaJobState.FAILED -> errorText(job.errorCode)
        MediaJobState.CANCELLED -> "Annulleret"
        MediaJobState.EXPIRED -> "Udløbet: riggen nåede ikke at starte jobbet inden for et døgn"
    }

    fun errorText(code: String?): String = when (code) {
        "gpu_unavailable" -> "Grafikkortet på riggen er ikke ledigt"
        "interrupted_by_restart" -> "Afbrudt: riggen genstartede"
        "interrupted_during_publication" -> "Afbrudt mens billedet blev gemt"
        "generation_failed" -> "Genereringen fejlede på riggen"
        "publication_failed" -> "Resultatet kunne ikke gemmes på riggen"
        "generation_request_rejected" -> "Riggen afviste forespørgslen"
        "gpu_busy" -> "Grafikkortet på riggen er optaget"
        "gpu_memory_retained" -> "Grafikkortets hukommelse blev ikke frigjort på riggen"
        "source_image_unavailable" -> "Kildebilledet findes ikke længere"
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
        Reason.TRANSIENT, Reason.NETWORK -> e.message ?: "Riggen svarer ikke lige nu"
        else -> e.message ?: "Noget gik galt"
    }
}
