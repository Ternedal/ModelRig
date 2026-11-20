package dk.ternedal.modelrig.ui.chat

import android.graphics.Bitmap
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import dk.ternedal.modelrig.R
import dk.ternedal.modelrig.ui.decodeBounded
import dk.ternedal.modelrig.ui.theme.KalivType

/**
 * #2419: the generated picture full-screen, with pinch-zoom and pan (Anders, 19/11
 * 23:02: "trykke på billedet for at se det i stort format og kunne zoome").
 *
 * The bytes are the ones the bubble already fetched; they are decoded again here
 * with the gallery's detail bound (2048 px on the longest side), so zooming shows
 * more than the bubble's 1024 px preview without a second request to the rig.
 * "Gem" puts the bytes in the gallery album Pictures/Kaliv, "Del" hands a copy
 * to an app of the user's choice ([ImageExport]); nothing leaves the device by
 * itself.
 */
object ZoomableImage {
    const val DETAIL_PX = 2048
    const val MIN_SCALE = 1f
    const val MAX_SCALE = 6f

    /** The next scale after a pinch: clamped so the picture can neither vanish nor explode. */
    fun nextScale(current: Float, zoom: Float): Float = (current * zoom).coerceIn(MIN_SCALE, MAX_SCALE)

    /** At scale 1 the picture sits where it is laid out; panning only makes sense zoomed in. */
    fun nextOffset(current: Offset, pan: Offset, scale: Float): Offset =
        if (scale <= MIN_SCALE) Offset.Zero else current + pan
}

@Composable
fun ZoomableImageDialog(bytes: ByteArray, onDismiss: () -> Unit, jobId: String = "") {
    val bitmap: Bitmap? = remember(bytes) { runCatching { decodeBounded(bytes, ZoomableImage.DETAIL_PX) }.getOrNull() }
    val context = LocalContext.current
    var notice by remember { mutableStateOf<String?>(null) }
    var scale by remember { mutableFloatStateOf(ZoomableImage.MIN_SCALE) }
    var offset by remember { mutableStateOf(Offset.Zero) }

    Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(Color.Black)
                .testTag("image-viewer")
                .pointerInput(Unit) {
                    detectTransformGestures { _, pan, zoom, _ ->
                        scale = ZoomableImage.nextScale(scale, zoom)
                        offset = ZoomableImage.nextOffset(offset, pan, scale)
                    }
                }
                .pointerInput(Unit) {
                    detectTapGestures(onDoubleTap = {
                        // Double tap toggles between fit and a close look, and always resets the pan.
                        scale = if (scale > ZoomableImage.MIN_SCALE) ZoomableImage.MIN_SCALE else 2.5f
                        offset = Offset.Zero
                    })
                },
        ) {
            if (bitmap != null) {
                Image(
                    bitmap = bitmap.asImageBitmap(),
                    contentDescription = "Genereret billede, fuld størrelse",
                    contentScale = ContentScale.Fit,
                    modifier = Modifier
                        .fillMaxSize()
                        .graphicsLayer {
                            scaleX = scale
                            scaleY = scale
                            translationX = offset.x
                            translationY = offset.y
                        }
                        .testTag("image-viewer-picture"),
                )
            } else {
                Text(
                    "Billedet kan ikke vises",
                    color = Color.White,
                    fontFamily = KalivType.Inter,
                    fontSize = 15.sp,
                    modifier = Modifier.align(Alignment.Center),
                )
            }
            IconButton(
                onClick = onDismiss,
                modifier = Modifier.align(Alignment.TopEnd).padding(12.dp).size(40.dp).testTag("image-viewer-close"),
            ) {
                Icon(painterResource(R.drawable.ic_kaliv_close), contentDescription = "Luk", tint = Color.White)
            }
            // Save to the gallery album / hand to another app. Both on the bytes in
            // hand; both report in one short line instead of a toast over a dialog.
            Row(
                modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 20.dp),
                horizontalArrangement = Arrangement.spacedBy(18.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                ViewerAction("Gem", R.drawable.ic_kaliv_download, "image-viewer-save") {
                    notice = when (val r = ImageExport.saveToGallery(context, bytes, jobId)) {
                        is ImageExport.SaveResult.Saved -> "Gemt i Billeder/Kaliv"
                        is ImageExport.SaveResult.Refused -> r.reason
                    }
                }
                ViewerAction("Del", null, "image-viewer-share") {
                    if (!ImageExport.share(context, bytes, jobId)) notice = "Billedet kan ikke deles"
                }
            }
            notice?.let {
                Text(
                    it,
                    color = Color.White,
                    fontFamily = KalivType.Inter,
                    fontSize = 13.sp,
                    modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 68.dp).testTag("image-viewer-notice"),
                )
            }
        }
    }
}

@Composable
private fun ViewerAction(label: String, icon: Int?, tag: String, onClick: () -> Unit) {
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
