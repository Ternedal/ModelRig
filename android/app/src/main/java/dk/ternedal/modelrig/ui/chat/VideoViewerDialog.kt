package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import dk.ternedal.modelrig.R
import dk.ternedal.modelrig.net.MediaGalleryException
import dk.ternedal.modelrig.net.MediaGallerySource
import dk.ternedal.modelrig.net.MediaItem
import dk.ternedal.modelrig.net.MediaVideoStream
import dk.ternedal.modelrig.ui.mediaGalleryMessage
import dk.ternedal.modelrig.ui.theme.KalivType
import dk.ternedal.modelrig.ui.videoAspect
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * The generated clip full-screen (the video side of Anders' 19/11 ask: tap the
 * result to see it large). Same player as the bubble -- bearer-authenticated
 * range requests to the paired origin -- on a black canvas with the system
 * controls, and "Gem"/"Del" below.
 *
 * Save and share stream the clip once more from the rig through
 * [MediaGallerySource.videoInto] into the gallery row or the share copy
 * ([VideoExport]); nothing is buffered in memory and nothing leaves the phone
 * by itself. One action at a time: the buttons report "Henter …" while a copy
 * runs, and the result in one short line.
 */
object VideoViewer {
    const val SAVED_TEXT = "Gemt i Film/Kaliv"
    const val BUSY_TEXT = "Henter videoen fra riggen …"
}

@Composable
fun VideoViewerDialog(
    playable: VideoJobOutcome.Playable,
    gallery: MediaGallerySource,
    onDismiss: () -> Unit,
    io: CoroutineDispatcher = Dispatchers.IO,
    player: @Composable (MediaVideoStream, MediaItem, (MediaGalleryException.Reason) -> Unit) -> Unit,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var notice by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var playbackError by remember(playable.item.id) { mutableStateOf<String?>(null) }

    fun copy(out: java.io.OutputStream) = gallery.videoInto(playable.item, out)

    fun run(action: suspend () -> String?) {
        if (busy) return
        busy = true
        notice = VideoViewer.BUSY_TEXT
        scope.launch {
            notice = withContext(io) { runCatching { action() }.getOrElse { VideoExport.copyFailureText(it) } }
            busy = false
        }
    }

    Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Box(modifier = Modifier.fillMaxSize().background(Color.Black).testTag("video-viewer")) {
            val error = playbackError
            if (error != null) {
                Text(
                    error,
                    color = Color.White,
                    fontFamily = KalivType.Inter,
                    fontSize = 15.sp,
                    modifier = Modifier.align(Alignment.Center).padding(24.dp).testTag("video-viewer-error"),
                )
            } else {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .aspectRatio(videoAspect(playable.item))
                        .align(Alignment.Center)
                        .testTag("video-viewer-player"),
                ) {
                    player(playable.stream, playable.item) { reason -> playbackError = mediaGalleryMessage(reason) }
                }
            }
            IconButton(
                onClick = onDismiss,
                modifier = Modifier.align(Alignment.TopEnd).padding(12.dp).size(40.dp).testTag("video-viewer-close"),
            ) {
                Icon(painterResource(R.drawable.ic_kaliv_close), contentDescription = "Luk", tint = Color.White)
            }
            Row(
                modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 20.dp),
                horizontalArrangement = Arrangement.spacedBy(18.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                ViewerChip("Gem", R.drawable.ic_kaliv_download, "video-viewer-save") {
                    run {
                        when (val r = VideoExport.saveToGallery(context, playable.job.id, ::copy)) {
                            is VideoExport.SaveResult.Saved -> VideoViewer.SAVED_TEXT
                            is VideoExport.SaveResult.Refused -> r.reason
                        }
                    }
                }
                ViewerChip("Del", null, "video-viewer-share") {
                    run {
                        when (val r = VideoExport.share(context, playable.job.id, ::copy)) {
                            is VideoExport.ShareResult.Shared -> null
                            is VideoExport.ShareResult.Refused -> r.reason
                        }
                    }
                }
            }
            notice?.let {
                Text(
                    it,
                    color = Color.White,
                    fontFamily = KalivType.Inter,
                    fontSize = 13.sp,
                    modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 68.dp).testTag("video-viewer-notice"),
                )
            }
        }
    }
}

@Composable
private fun ViewerChip(label: String, icon: Int?, tag: String, onClick: () -> Unit) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .clip(RoundedCornerShape(20.dp))
            .background(Color.White.copy(alpha = 0.14f))
            .clickable(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 10.dp)
            .testTag(tag),
    ) {
        if (icon != null) {
            Icon(painterResource(icon), contentDescription = null, tint = Color.White, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
        }
        Text(label, color = Color.White, fontFamily = KalivType.Inter, fontSize = 14.sp)
    }
}
