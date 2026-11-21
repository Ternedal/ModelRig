package dk.ternedal.modelrig.desktop

import dk.ternedal.modelrig.desktop.net.DesktopMediaException
import dk.ternedal.modelrig.desktop.net.DesktopMediaJob
import dk.ternedal.modelrig.desktop.net.DesktopMediaJobState
import dk.ternedal.modelrig.desktop.net.DesktopMediaKind
import java.io.IOException
import kotlin.coroutines.cancellation.CancellationException
import java.io.OutputStream
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardCopyOption

/**
 * What a media bubble in the chat is doing (#2419, desktop): following a job
 * the turn queued, holding its finished result, or done without one.
 *
 * Everything here is pure, so the rules are tested without a window or a rig:
 * the same polling and words as the Android bubble (2 s, then doubled per
 * failure in a row up to 30 s; six transient failures in a row and the bubble
 * stops asking but offers "Prøv igen" -- the job keeps running on the rig
 * whatever the desktop sees).
 */
sealed class DesktopMediaPhase {
    /** Asking the rig; [job] is the last answer, null before the first. */
    data class Following(val job: DesktopMediaJob?, val failures: Int) : DesktopMediaPhase()

    /** The job is completed and names its result. */
    data class Completed(val job: DesktopMediaJob) : DesktopMediaPhase()

    /** Terminal without a result, or the bubble gave up; [retryable] offers asking again. */
    data class Ended(val text: String, val retryable: Boolean = false) : DesktopMediaPhase()
}

object KalivMediaJob {
    const val POLL_MILLIS = 2_000L

    /** Transient poll failures in a row before the bubble stops asking. */
    const val MAX_POLL_FAILURES = 6

    /** The longest wait between two polls while the rig is not answering. */
    const val MAX_POLL_BACKOFF_MILLIS = 30_000L

    const val GAVE_UP_TEXT = "Riggen svarer ikke; jobbet kan stadig blive færdigt"
    const val NOT_FOUND_TEXT = "Jobbet findes ikke længere på riggen"

    fun initial(): DesktopMediaPhase = DesktopMediaPhase.Following(null, 0)

    /**
     * [runCatching] for code a coroutine runs: a cancellation is never a result. `runCatching`
     * catches [CancellationException] like any other throwable, and a loop that turns it into
     * "the rig failed" keeps asking after its composable is gone (the Android bubble's review,
     * 6004386757; the same loop lives here).
     */
    inline fun <T> catching(block: () -> T): Result<T> = try {
        Result.success(block())
    } catch (e: CancellationException) {
        throw e
    } catch (e: Throwable) {
        Result.failure(e)
    }

    /**
     * How long to wait before fetching a finished picture again, after [failedFetches]
     * failures in a row -- or null to stop and leave it to "Prøv igen". The job is done, so a
     * rig that was away for a moment is asked again with the poll's backoff, up to
     * [MAX_POLL_FAILURES]; anything that would fail the same way again is not.
     */
    fun refetchDelayMillis(failedFetches: Int, error: Throwable?, base: Long = POLL_MILLIS): Long? {
        if (failedFetches < 1 || failedFetches >= MAX_POLL_FAILURES || !transferRetryable(error)) return null
        val factor = 1L shl failedFetches.coerceAtMost(16)
        return (base * factor).coerceAtMost(MAX_POLL_BACKOFF_MILLIS.coerceAtLeast(base))
    }

    /** The wait before the next poll: [base], then doubled per failure in a row, capped (2, 4, 8, 16, 30, 30 s). */
    fun delayMillis(phase: DesktopMediaPhase, base: Long = POLL_MILLIS): Long {
        val failures = (phase as? DesktopMediaPhase.Following)?.failures ?: 0
        if (failures <= 0) return base
        val factor = 1L shl failures.coerceAtMost(16)
        return (base * factor).coerceAtMost(MAX_POLL_BACKOFF_MILLIS.coerceAtLeast(base))
    }

    /** A poll answered. Non-terminal keeps following (failures reset); terminal decides. */
    fun polled(job: DesktopMediaJob, kind: DesktopMediaKind): DesktopMediaPhase = when {
        !job.state.terminal -> DesktopMediaPhase.Following(job, 0)
        job.state == DesktopMediaJobState.COMPLETED && job.assetId != null -> DesktopMediaPhase.Completed(job)
        job.state == DesktopMediaJobState.COMPLETED -> DesktopMediaPhase.Ended("Færdig, men riggen gav intet resultat-id")
        else -> DesktopMediaPhase.Ended(stateLabel(job, kind))
    }

    /** A poll failed. A definite answer ends it; a transient one counts, up to [MAX_POLL_FAILURES]. */
    fun pollFailed(phase: DesktopMediaPhase, error: Throwable): DesktopMediaPhase {
        val current = phase as? DesktopMediaPhase.Following ?: return phase
        val e = error as? DesktopMediaException
            ?: return DesktopMediaPhase.Ended("Uventet svar fra riggen")
        return when (e.reason) {
            DesktopMediaException.Reason.NETWORK, DesktopMediaException.Reason.TRANSIENT ->
                if (current.failures + 1 >= MAX_POLL_FAILURES) {
                    DesktopMediaPhase.Ended(GAVE_UP_TEXT, retryable = true)
                } else {
                    current.copy(failures = current.failures + 1)
                }
            DesktopMediaException.Reason.NOT_FOUND -> DesktopMediaPhase.Ended(NOT_FOUND_TEXT)
            else -> DesktopMediaPhase.Ended(e.message ?: "Uventet svar fra riggen")
        }
    }

    fun stateLabel(job: DesktopMediaJob, kind: DesktopMediaKind): String = when (job.state) {
        DesktopMediaJobState.QUEUED -> if (job.cancelRequested) "Annulleres …" else "I kø på riggen"
        DesktopMediaJobState.RUNNING -> if (job.cancelRequested) "Annulleres …" else "Genererer …"
        DesktopMediaJobState.PUBLISHING -> if (kind == DesktopMediaKind.VIDEO) "Gemmer videoen …" else "Gemmer billedet …"
        DesktopMediaJobState.COMPLETED -> "Færdig"
        DesktopMediaJobState.FAILED -> errorText(job.errorCode)
        DesktopMediaJobState.CANCELLED -> "Annulleret"
        DesktopMediaJobState.EXPIRED -> "Udløbet: riggen nåede ikke at starte jobbet inden for et døgn"
    }

    /** The rig's failure codes in words; never free text from the rig. Same words as the phone. */
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

    /** The one line the bubble shows while there is no picture or clip to show. */
    fun label(phase: DesktopMediaPhase, kind: DesktopMediaKind): String = when (phase) {
        is DesktopMediaPhase.Following -> phase.job?.let { stateLabel(it, kind) } ?: "I kø på riggen"
        is DesktopMediaPhase.Completed -> if (kind == DesktopMediaKind.VIDEO) "Klippet er færdigt" else "Henter billedet …"
        is DesktopMediaPhase.Ended -> phase.text
    }

    /** Why a finished result could not be fetched or saved: the client's own words when it has them. */
    fun transferFailedText(error: Throwable?, kind: DesktopMediaKind): String = when (error) {
        is DesktopMediaException -> error.message ?: fallbackTransferText(kind)
        is IOException -> "Filen kunne ikke skrives"
        else -> fallbackTransferText(kind)
    }

    /**
     * Whether "Prøv igen" is worth offering after a failed fetch: only when the rig
     * was away for a moment. Too large, the wrong type, gone or not ours would fail
     * the same way again, and a button that cannot help is not offered.
     */
    fun transferRetryable(error: Throwable?): Boolean = when ((error as? DesktopMediaException)?.reason) {
        DesktopMediaException.Reason.NETWORK, DesktopMediaException.Reason.TRANSIENT -> true
        else -> false
    }

    private fun fallbackTransferText(kind: DesktopMediaKind): String =
        if (kind == DesktopMediaKind.VIDEO) "Klippet kunne ikke hentes fra riggen" else "Billedet kunne ikke hentes fra riggen"

    // ---- the full-size viewer -------------------------------------------------------------

    const val MIN_SCALE = 1f
    const val MAX_SCALE = 8f
    private const val STEP = 1.2f

    /** One zoom step in ([steps] > 0) or out ([steps] < 0), kept inside [MIN_SCALE]..[MAX_SCALE]. */
    fun nextScale(current: Float, steps: Float): Float {
        if (steps == 0f || steps.isNaN()) return current.coerceIn(MIN_SCALE, MAX_SCALE)
        val bounded = steps.coerceIn(-8f, 8f)
        val factor = Math.pow(STEP.toDouble(), bounded.toDouble()).toFloat()
        return (current * factor).coerceIn(MIN_SCALE, MAX_SCALE)
    }

    /**
     * The pan after a drag of ([dx], [dy]): nothing to pan at fit size, and never
     * further than the zoomed picture reaches beyond a [width] x [height] view.
     */
    fun nextPan(x: Float, y: Float, dx: Float, dy: Float, scale: Float, width: Float, height: Float): Pair<Float, Float> {
        if (scale <= MIN_SCALE) return 0f to 0f
        val maxX = (width * (scale - 1f) / 2f).coerceAtLeast(0f)
        val maxY = (height * (scale - 1f) / 2f).coerceAtLeast(0f)
        return (x + dx).coerceIn(-maxX, maxX) to (y + dy).coerceIn(-maxY, maxY)
    }

    // ---- saving the result ---------------------------------------------------------------

    /** PNG, JPEG or WebP by magic bytes; anything else has no extension and is not offered for saving. */
    fun imageExtension(bytes: ByteArray): String? = when {
        bytes.size >= 8 && bytes[0] == 0x89.toByte() && bytes[1] == 0x50.toByte() &&
            bytes[2] == 0x4E.toByte() && bytes[3] == 0x47.toByte() -> "png"
        bytes.size >= 3 && bytes[0] == 0xFF.toByte() && bytes[1] == 0xD8.toByte() && bytes[2] == 0xFF.toByte() -> "jpg"
        bytes.size >= 12 && bytes[0] == 'R'.code.toByte() && bytes[1] == 'I'.code.toByte() &&
            bytes[2] == 'F'.code.toByte() && bytes[3] == 'F'.code.toByte() &&
            bytes[8] == 'W'.code.toByte() && bytes[9] == 'E'.code.toByte() &&
            bytes[10] == 'B'.code.toByte() && bytes[11] == 'P'.code.toByte() -> "webp"
        else -> null
    }

    /** `kaliv-<jobid-prefix>-<yyyyMMdd-HHmmss>.<ext>`: sortable, no prompt text, no PII. */
    fun fileName(jobId: String, extension: String, nowMillis: Long = System.currentTimeMillis()): String {
        val format = java.text.SimpleDateFormat("yyyyMMdd-HHmmss", java.util.Locale.ROOT)
        format.timeZone = java.util.TimeZone.getDefault()
        return "kaliv-${jobId.take(8)}-${format.format(java.util.Date(nowMillis))}.$extension"
    }

    /** The name the user chose, with [extension] added when they typed none of the accepted ones. */
    fun withExtension(name: String, extension: String, accepted: Set<String> = setOf(extension)): String {
        val typed = name.substringAfterLast('.', "").lowercase()
        return if (name.contains('.') && typed in accepted) name else "$name.$extension"
    }

    /**
     * Write a result to [target] through [copy], all or nothing: the bytes go to a
     * sibling `.part` file that replaces [target] only when [copy] returned, and is
     * removed when it threw. So a clip cut short by the network never sits on the
     * user's disk under its final name.
     */
    fun saveTo(target: Path, copy: (OutputStream) -> Unit): Result<Path> {
        val part = target.resolveSibling(target.fileName.toString() + ".part")
        return try {
            Files.newOutputStream(part).use(copy)
            Files.move(part, target, StandardCopyOption.REPLACE_EXISTING)
            Result.success(target)
        } catch (e: Exception) {
            runCatching { Files.deleteIfExists(part) }
            Result.failure(e)
        }
    }
}
