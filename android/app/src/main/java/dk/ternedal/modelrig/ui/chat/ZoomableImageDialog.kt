package dk.ternedal.modelrig.ui.chat

import android.graphics.Bitmap
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.Box
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
 * Nothing leaves the device: no share, no save in this slice (V1).
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
fun ZoomableImageDialog(bytes: ByteArray, onDismiss: () -> Unit) {
    val bitmap: Bitmap? = remember(bytes) { runCatching { decodeBounded(bytes, ZoomableImage.DETAIL_PX) }.getOrNull() }
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
        }
    }
}
