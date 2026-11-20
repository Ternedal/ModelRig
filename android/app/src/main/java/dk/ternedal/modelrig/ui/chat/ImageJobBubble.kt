package dk.ternedal.modelrig.ui.chat

import android.graphics.Bitmap
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.net.MediaGalleryException
import dk.ternedal.modelrig.net.MediaGallerySource
import dk.ternedal.modelrig.net.MediaJob
import dk.ternedal.modelrig.net.MediaJobException
import dk.ternedal.modelrig.net.MediaJobSource
import dk.ternedal.modelrig.net.MediaJobState
import dk.ternedal.modelrig.net.MediaModality
import dk.ternedal.modelrig.ui.MediaGenerate
import dk.ternedal.modelrig.ui.components.StreamingCursor
import dk.ternedal.modelrig.ui.decodeBounded
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens
import dk.ternedal.modelrig.ui.theme.KalivType
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext

/**
 * #2419 slice B: the image bubble under an assistant turn that called
 * `image_generate`. One bubble per job id in [dk.ternedal.modelrig.net.ToolTurn.mediaJobs].
 *
 * The bubble owns nothing but a job id. It polls `GET /api/v1/media/jobs/{id}`
 * through the existing [MediaJobSource] (bearer to the paired origin only, no
 * redirects, bounded bodies), with the generate screen's backoff, until the job
 * is terminal; a completed job's `asset_id` is fetched once through
 * [MediaGallerySource.asset] and decoded bounded; tapping the picture opens
 * [ZoomableImageDialog] on the same bytes. Errors are the rig's codes
 * through [MediaGenerate.errorText], never free text from the rig, never a
 * crash. The prompt is nowhere in here: the bubble never sees it.
 *
 * Stops asking when the composable leaves the composition, when the job is
 * terminal, or after [ImageJobBubbleLogic.MAX_FAILURES] transient failures in a
 * row. Giving up is the phone's verdict, not the rig's: the job goes on there.
 * So a bubble that gave up -- or could not fetch a finished picture because the
 * rig was away for a moment -- offers "Prøv igen", which starts the asking over.
 * An end the rig itself announced (failed, cancelled, expired, gone) offers
 * nothing: asking again would get the same answer.
 */
sealed class ImageJobPhase {
    /** Asking the rig; [job] is the last answer, null before the first. */
    data class Following(val job: MediaJob?, val failures: Int) : ImageJobPhase()
    /** Terminal with a picture; [bytes] are kept for the full-size viewer (decoded larger there). */
    @Suppress("ArrayInDataClass")
    data class Shown(val job: MediaJob, val bitmap: Bitmap, val bytes: ByteArray) : ImageJobPhase()
    /** Terminal without a picture, or the bubble gave up; [text] is what to show, [retryable] offers "Prøv igen". */
    data class Ended(val text: String, val retryable: Boolean = false) : ImageJobPhase()
}

object ImageJobBubbleLogic {
    const val MAX_FAILURES = MediaGenerate.MAX_POLL_FAILURES
    const val IMAGE_SIDE_PX = 1024
    const val GAVE_UP_TEXT = "Riggen svarer ikke; billedet ligger i galleriet, når det er klar"
    const val GAVE_UP_TEXT_VIDEO = "Riggen svarer ikke; klippet ligger i galleriet, når det er klar"
    const val RETRY_LABEL = "Prøv igen"

    fun gaveUpText(modality: MediaModality): String =
        if (modality == MediaModality.VIDEO) GAVE_UP_TEXT_VIDEO else GAVE_UP_TEXT

    fun initial(): ImageJobPhase = ImageJobPhase.Following(null, 0)

    /** Delay before the next poll: base, then doubled per failure in a row, capped as the generate screen. */
    fun delayMillis(phase: ImageJobPhase, base: Long): Long {
        val failures = (phase as? ImageJobPhase.Following)?.failures ?: 0
        if (failures <= 0) return base
        val factor = 1L shl failures.coerceAtMost(16)
        return (base * factor).coerceAtMost(MediaGenerate.MAX_POLL_BACKOFF_MILLIS.coerceAtLeast(base))
    }

    /** A poll answered. Non-terminal keeps following (failures reset); terminal decides. */
    fun polled(job: MediaJob, modality: MediaModality = MediaModality.IMAGE): ImageJobPhase = when {
        !job.state.terminal -> ImageJobPhase.Following(job, 0)
        job.state == MediaJobState.COMPLETED && job.assetId != null -> ImageJobPhase.Following(job, 0) // fetch next
        job.state == MediaJobState.COMPLETED -> ImageJobPhase.Ended(
            if (modality == MediaModality.VIDEO) "Klippet er færdigt, men riggen gav intet id"
            else "Billedet er færdigt, men riggen gav intet billed-id",
        )
        else -> ImageJobPhase.Ended(MediaGenerate.stateLabel(job, modality))
    }

    /**
     * A poll failed. A definite answer ends it; a transient one counts, up to
     * [MAX_FAILURES] -- and that end is the only one here that can be tried again.
     */
    fun pollFailed(
        phase: ImageJobPhase,
        e: MediaJobException,
        modality: MediaModality = MediaModality.IMAGE,
    ): ImageJobPhase {
        val cur = phase as? ImageJobPhase.Following ?: return phase
        return when (e.reason) {
            MediaJobException.Reason.NOT_FOUND -> ImageJobPhase.Ended("Jobbet findes ikke længere på riggen")
            MediaJobException.Reason.UNAUTHORIZED, MediaJobException.Reason.UNAVAILABLE,
            MediaJobException.Reason.ORIGIN_REFUSED, MediaJobException.Reason.NOT_PAIRED,
            MediaJobException.Reason.REDIRECT_REFUSED -> ImageJobPhase.Ended(MediaGenerate.message(e))
            else -> if (cur.failures + 1 >= MAX_FAILURES) ImageJobPhase.Ended(gaveUpText(modality), retryable = true)
            else cur.copy(failures = cur.failures + 1)
        }
    }

    /** The completed job's picture arrived (or did not). */
    fun fetched(job: MediaJob, result: Result<Pair<ByteArray, Bitmap>>): ImageJobPhase = result.fold(
        onSuccess = { (bytes, bitmap) -> ImageJobPhase.Shown(job, bitmap, bytes) },
        onFailure = { e ->
            ImageJobPhase.Ended(
                (e as? MediaGalleryException)?.message ?: "Billedet kunne ikke hentes fra riggen",
                retryable = transient(e),
            )
        },
    )

    /** The rig was away for a moment (network, storage); everything else would fail the same way again. */
    fun transient(e: Throwable?): Boolean = when ((e as? MediaGalleryException)?.reason) {
        MediaGalleryException.Reason.NETWORK, MediaGalleryException.Reason.STORAGE_UNAVAILABLE -> true
        else -> false
    }

    /** True while the bubble should keep asking the rig. */
    fun polling(phase: ImageJobPhase): Boolean = phase is ImageJobPhase.Following

    /** The completed job whose picture is still to be fetched, if that is where we are. */
    fun toFetch(phase: ImageJobPhase): MediaJob? =
        (phase as? ImageJobPhase.Following)?.job?.takeIf { it.state == MediaJobState.COMPLETED && it.assetId != null }

    fun label(phase: ImageJobPhase, modality: MediaModality = MediaModality.IMAGE): String = when (phase) {
        is ImageJobPhase.Following -> phase.job?.let { MediaGenerate.stateLabel(it, modality) } ?: "I kø på riggen"
        is ImageJobPhase.Shown -> "Billede"
        is ImageJobPhase.Ended -> phase.text
    }
}

@Composable
fun ImageJobBubble(
    jobId: String,
    jobs: MediaJobSource,
    gallery: MediaGallerySource,
    modifier: Modifier = Modifier,
    io: CoroutineDispatcher = Dispatchers.IO,
    pollMillis: Long = MediaGenerate.POLL_MILLIS,
) {
    // "Prøv igen" starts the asking over: a new attempt is a new phase and a new effect.
    var attempt by remember(jobId) { mutableIntStateOf(0) }
    var phase by remember(jobId, attempt) { mutableStateOf(ImageJobBubbleLogic.initial()) }

    LaunchedEffect(jobId, attempt) {
        // First ask at once, then with backoff; the picture is fetched once, in the
        // same effect, so leaving the composition cancels everything.
        var first = true
        while (ImageJobBubbleLogic.polling(phase)) {
            val toFetch = ImageJobBubbleLogic.toFetch(phase)
            if (toFetch != null) {
                val assetId = toFetch.assetId ?: break
                val picture = withContext(io) {
                    runCatching {
                        val bytes = gallery.asset(assetId)
                        bytes to decodeBounded(bytes, ImageJobBubbleLogic.IMAGE_SIDE_PX)
                    }
                }
                phase = ImageJobBubbleLogic.fetched(toFetch, picture)
                break
            }
            if (!first) delay(ImageJobBubbleLogic.delayMillis(phase, pollMillis))
            first = false
            val result = withContext(io) { runCatching { jobs.status(jobId) } }
            phase = result.fold(
                onSuccess = { ImageJobBubbleLogic.polled(it) },
                onFailure = { e ->
                    ImageJobBubbleLogic.pollFailed(
                        phase,
                        e as? MediaJobException
                            ?: MediaJobException(MediaJobException.Reason.UNAVAILABLE, "Uventet svar fra riggen"),
                    )
                },
            )
        }
    }

    // Tap the picture -> full-size viewer with pinch-zoom (Anders 19/11 23:02).
    var viewing by remember(jobId) { mutableStateOf(false) }
    val shown = phase as? ImageJobPhase.Shown
    ImageJobBubbleContent(
        phase, modifier,
        onOpen = if (shown != null) ({ viewing = true }) else null,
        onRetry = { attempt += 1 },
    )
    if (viewing && shown != null) {
        ZoomableImageDialog(bytes = shown.bytes, onDismiss = { viewing = false }, jobId = jobId)
    }
}

/** Stateless renderer, so the three phases can be screenshot-tested without a rig. */
@Composable
fun ImageJobBubbleContent(
    phase: ImageJobPhase,
    modifier: Modifier = Modifier,
    onOpen: (() -> Unit)? = null,
    modality: MediaModality = MediaModality.IMAGE,
    onRetry: (() -> Unit)? = null,
) {
    val maxWidth = (LocalConfiguration.current.screenWidthDp * 0.78f).dp
    Column(
        modifier = modifier.widthIn(max = maxWidth).padding(top = 8.dp).testTag("image-job-bubble"),
        horizontalAlignment = Alignment.Start,
    ) {
        when (phase) {
            is ImageJobPhase.Shown -> Image(
                bitmap = phase.bitmap.asImageBitmap(),
                contentDescription = "Genereret billede",
                contentScale = ContentScale.Fit,
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(14.dp))
                    .then(if (onOpen != null) Modifier.clickable(onClick = onOpen) else Modifier)
                    .testTag("image-job-picture"),
            )
            is ImageJobPhase.Following -> Surface(
                color = KalivTheme.colors.sheet,
                border = androidx.compose.foundation.BorderStroke(KalivTokens.Layout.hairline, KalivTheme.colors.hairline),
                shape = RoundedCornerShape(14.dp),
                modifier = Modifier.fillMaxWidth().aspectRatio(1f),
            ) {
                Box(contentAlignment = Alignment.Center) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        StreamingCursor()
                        Spacer(Modifier.width(8.dp))
                        Text(
                            ImageJobBubbleLogic.label(phase, modality),
                            color = KalivTheme.colors.textMuted,
                            style = TextStyle(fontFamily = KalivType.Inter, fontSize = 14.sp),
                            modifier = Modifier.testTag("image-job-status"),
                        )
                    }
                }
            }
            is ImageJobPhase.Ended -> Surface(
                color = KalivTheme.colors.sheet,
                border = androidx.compose.foundation.BorderStroke(KalivTokens.Layout.hairline, KalivTheme.colors.hairline),
                shape = RoundedCornerShape(14.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (phase.retryable && onRetry != null) {
                    Column(Modifier.padding(horizontal = 14.dp, vertical = 10.dp)) {
                        Text(
                            phase.text,
                            color = KalivTheme.colors.danger,
                            style = TextStyle(fontFamily = KalivType.Inter, fontSize = 14.sp, lineHeight = 20.sp),
                            modifier = Modifier.testTag("image-job-status"),
                        )
                        Text(
                            ImageJobBubbleLogic.RETRY_LABEL,
                            color = KalivTheme.colors.accent,
                            style = TextStyle(fontFamily = KalivType.Inter, fontSize = 14.sp, lineHeight = 20.sp),
                            modifier = Modifier
                                .padding(top = 2.dp)
                                .clip(RoundedCornerShape(8.dp))
                                .clickable(role = Role.Button, onClick = onRetry)
                                .padding(vertical = 8.dp)
                                .testTag("image-job-retry"),
                        )
                    }
                } else {
                    // Unchanged for every end that cannot be tried again (and for the screenshot baselines).
                    Text(
                        phase.text,
                        color = KalivTheme.colors.danger,
                        style = TextStyle(fontFamily = KalivType.Inter, fontSize = 14.sp, lineHeight = 20.sp),
                        modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp).testTag("image-job-status"),
                    )
                }
            }
        }
        Spacer(Modifier.height(2.dp))
    }
}
