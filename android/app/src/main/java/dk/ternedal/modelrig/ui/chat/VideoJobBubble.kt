package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.net.MediaGalleryException
import dk.ternedal.modelrig.net.MediaGallerySource
import dk.ternedal.modelrig.net.MediaItem
import dk.ternedal.modelrig.net.MediaJob
import dk.ternedal.modelrig.net.MediaJobException
import dk.ternedal.modelrig.net.MediaJobSource
import dk.ternedal.modelrig.net.MediaKind
import dk.ternedal.modelrig.net.MediaModality
import dk.ternedal.modelrig.net.MediaVideoStream
import dk.ternedal.modelrig.ui.MediaGenerate
import dk.ternedal.modelrig.ui.MediaVideoPlayer
import dk.ternedal.modelrig.ui.mediaGalleryMessage
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens
import dk.ternedal.modelrig.ui.theme.KalivType
import dk.ternedal.modelrig.ui.videoAspect
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext

/**
 * The video twin of [ImageJobBubble] for `video_generate` jobs (kind=video).
 *
 * Same polling and the same words while the job runs ([ImageJobBubbleLogic] is
 * reused for backoff, failures and labels). On completion the clip is *not*
 * downloaded: the bubble looks the asset up on the gallery's first page to get
 * its [MediaItem] (size, aspect, range support) and plays it through the
 * gallery's own [MediaVideoPlayer] -- bearer-authenticated range requests to the
 * paired origin, exactly as the Medier screen does. A clip not on the first page
 * (older than the newest page) is said to be in the gallery rather than fetched
 * blindly. Save/share for video is V1.
 */
sealed class VideoJobOutcome {
    data class Playable(val job: MediaJob, val item: MediaItem, val stream: MediaVideoStream) : VideoJobOutcome()
    data class Ended(val text: String) : VideoJobOutcome()
}

object VideoJobBubbleLogic {
    const val LOOKUP_PAGE = 24
    const val IN_GALLERY_TEXT = "Klippet er færdigt og ligger i galleriet"

    /** Find the completed job's asset among the newest gallery items; null when it is not there. */
    fun findItem(items: List<MediaItem>, assetId: String): MediaItem? =
        items.firstOrNull { it.id == assetId && it.kind == MediaKind.VIDEO }

    fun resolved(job: MediaJob, item: MediaItem?, stream: Result<MediaVideoStream>?): VideoJobOutcome = when {
        item == null -> VideoJobOutcome.Ended(IN_GALLERY_TEXT)
        stream == null -> VideoJobOutcome.Ended(IN_GALLERY_TEXT)
        else -> stream.fold(
            onSuccess = { VideoJobOutcome.Playable(job, item, it) },
            onFailure = { e -> VideoJobOutcome.Ended((e as? MediaGalleryException)?.message ?: IN_GALLERY_TEXT) },
        )
    }
}

@Composable
fun VideoJobBubble(
    jobId: String,
    jobs: MediaJobSource,
    gallery: MediaGallerySource,
    modifier: Modifier = Modifier,
    io: CoroutineDispatcher = Dispatchers.IO,
    pollMillis: Long = MediaGenerate.POLL_MILLIS,
    // Injected as the gallery screen does, so tests need no ExoPlayer.
    player: @Composable (MediaVideoStream, MediaItem, (MediaGalleryException.Reason) -> Unit) -> Unit =
        { stream, item, onError -> MediaVideoPlayer(stream, item, onError) },
) {
    var phase by remember(jobId) { mutableStateOf(ImageJobBubbleLogic.initial()) }
    var outcome by remember(jobId) { mutableStateOf<VideoJobOutcome?>(null) }

    LaunchedEffect(jobId) {
        // ImageJobBubbleLogic.catching, never runCatching: a cancellation must end this loop,
        // not be counted as a failed call (review 6004386757 on the image bubble).
        var first = true
        while (ImageJobBubbleLogic.polling(phase)) {
            val done = ImageJobBubbleLogic.toFetch(phase)
            if (done != null) {
                val assetId = done.assetId ?: break
                val resolvedOutcome = withContext(io) {
                    val item = ImageJobBubbleLogic.catching { gallery.page(VideoJobBubbleLogic.LOOKUP_PAGE).items }
                        .getOrNull()?.let { VideoJobBubbleLogic.findItem(it, assetId) }
                    val stream = item?.let { ImageJobBubbleLogic.catching { gallery.video(it) } }
                    VideoJobBubbleLogic.resolved(done, item, stream)
                }
                outcome = resolvedOutcome
                phase = when (resolvedOutcome) {
                    is VideoJobOutcome.Playable -> ImageJobPhase.Ended("") // terminal; rendered by outcome
                    is VideoJobOutcome.Ended -> ImageJobPhase.Ended(resolvedOutcome.text)
                }
                break
            }
            if (!first) delay(ImageJobBubbleLogic.delayMillis(phase, pollMillis))
            first = false
            val result = withContext(io) { ImageJobBubbleLogic.catching { jobs.status(jobId) } }
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

    val playable = outcome as? VideoJobOutcome.Playable
    if (playable != null) {
        VideoJobBubblePlayer(playable, modifier, player)
    } else {
        ImageJobBubbleContent(phase, modifier, modality = MediaModality.VIDEO)
    }
}

@Composable
private fun VideoJobBubblePlayer(
    playable: VideoJobOutcome.Playable,
    modifier: Modifier,
    player: @Composable (MediaVideoStream, MediaItem, (MediaGalleryException.Reason) -> Unit) -> Unit,
) {
    val maxWidth = (LocalConfiguration.current.screenWidthDp * 0.78f).dp
    var playbackError by remember(playable.item.id) { mutableStateOf<String?>(null) }
    Column(modifier = modifier.widthIn(max = maxWidth).padding(top = 8.dp).testTag("video-job-bubble")) {
        val error = playbackError
        if (error != null) {
            Surface(
                color = KalivTheme.colors.sheet,
                border = BorderStroke(KalivTokens.Layout.hairline, KalivTheme.colors.hairline),
                shape = RoundedCornerShape(14.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    error,
                    color = KalivTheme.colors.danger,
                    style = TextStyle(fontFamily = KalivType.Inter, fontSize = 14.sp, lineHeight = 20.sp),
                    modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp).testTag("video-job-status"),
                )
            }
        } else {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(videoAspect(playable.item))
                    .clip(RoundedCornerShape(14.dp))
                    .testTag("video-job-player"),
            ) {
                player(playable.stream, playable.item) { reason -> playbackError = mediaGalleryMessage(reason) }
            }
        }
        Spacer(Modifier.height(2.dp))
    }
}
