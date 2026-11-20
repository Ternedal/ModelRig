package dk.ternedal.modelrig.desktop

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.toComposeImageBitmap
import androidx.compose.ui.input.pointer.PointerEventType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.DialogWindow
import androidx.compose.ui.window.rememberDialogState
import dk.ternedal.modelrig.desktop.net.DesktopMediaJob
import dk.ternedal.modelrig.desktop.net.DesktopMediaJobRef
import dk.ternedal.modelrig.desktop.net.DesktopMediaKind
import dk.ternedal.modelrig.desktop.net.DesktopMediaSource
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.nio.file.Path

/**
 * #2419 on the desktop: the picture or clip a tools turn asked the rig for,
 * shown under the assistant's message.
 *
 * The bubble owns nothing but a job reference. It asks the rig where the job
 * stands ([KalivMediaJob] holds the rules and the words), and when the job is
 * completed:
 *
 * - an image is fetched once, bounded, and shown; a click opens it in its own
 *   resizable window with wheel-zoom, drag-pan and "Gem som …";
 * - a clip is not played here (Compose for Desktop has no video player, and a
 *   new native dependency is not worth it for this): the bubble offers
 *   "Gem klip …", which streams it from the rig straight into the chosen file,
 *   and then "Åbn" in the system's own player.
 *
 * Nothing is written to disk unless the user chooses a place for it, and the
 * prompt is nowhere in here: the bubble never sees it.
 */
internal class LoadedPicture(val bytes: ByteArray, val bitmap: ImageBitmap)

/**
 * The few most recent pictures, so scrolling a bubble out of the lazy list and
 * back does not ask the rig for the same megabytes again. Memory only; gone
 * with the process.
 */
internal object KalivMediaPictureCache {
    private const val MAX_ENTRIES = 6
    private val entries = object : LinkedHashMap<String, LoadedPicture>(8, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, LoadedPicture>?): Boolean =
            size > MAX_ENTRIES
    }

    @Synchronized
    fun get(jobId: String): LoadedPicture? = entries[jobId]

    @Synchronized
    fun put(jobId: String, picture: LoadedPicture) {
        entries[jobId] = picture
    }
}

private fun decodePicture(bytes: ByteArray): ImageBitmap =
    org.jetbrains.skia.Image.makeFromEncoded(bytes).toComposeImageBitmap()

@Composable
internal fun KalivMediaJobBubble(
    ref: DesktopMediaJobRef,
    source: DesktopMediaSource?,
    pollMillis: Long = KalivMediaJob.POLL_MILLIS,
) {
    if (source == null) {
        MediaStatusLine("Rig-adressen er ikke sat op", onRetry = null)
        return
    }
    var attempt by remember(ref.jobId) { mutableStateOf(0) }
    var phase by remember(ref.jobId, attempt) { mutableStateOf(KalivMediaJob.initial()) }
    var picture by remember(ref.jobId) { mutableStateOf(KalivMediaPictureCache.get(ref.jobId)) }
    var transferError by remember(ref.jobId, attempt) { mutableStateOf<String?>(null) }

    LaunchedEffect(ref.jobId, attempt, source) {
        if (picture != null) return@LaunchedEffect
        // First ask at once, then with backoff. Leaving the composition cancels the lot.
        var first = true
        while (phase is DesktopMediaPhase.Following) {
            if (!first) delay(KalivMediaJob.delayMillis(phase, pollMillis))
            first = false
            val answer = withContext(Dispatchers.IO) { runCatching { source.status(ref.jobId) } }
            val before = phase
            phase = answer.fold(
                onSuccess = { KalivMediaJob.polled(it, ref.kind) },
                onFailure = { KalivMediaJob.pollFailed(before, it) },
            )
        }
        val assetId = (phase as? DesktopMediaPhase.Completed)?.job?.assetId
        if (assetId != null && ref.kind == DesktopMediaKind.IMAGE) {
            val fetched = withContext(Dispatchers.IO) { runCatching { source.image(assetId) } }
            val bytes = fetched.getOrNull()
            if (bytes == null) {
                transferError = KalivMediaJob.transferFailedText(fetched.exceptionOrNull(), ref.kind)
            } else {
                val decoded = withContext(Dispatchers.Default) { runCatching { decodePicture(bytes) } }.getOrNull()
                if (decoded == null || decoded.width <= 0 || decoded.height <= 0) {
                    transferError = "Billedet kan ikke vises"
                } else {
                    val loaded = LoadedPicture(bytes, decoded)
                    KalivMediaPictureCache.put(ref.jobId, loaded)
                    picture = loaded
                }
            }
        }
    }

    val shown = picture
    val failed = transferError
    val current = phase
    Column(Modifier.padding(top = 8.dp)) {
        when {
            shown != null -> PictureCard(shown, ref)
            failed != null -> MediaStatusLine(failed, onRetry = { attempt += 1 })
            current is DesktopMediaPhase.Completed && ref.kind == DesktopMediaKind.VIDEO ->
                ClipCard(ref, current.job, source)
            else -> MediaStatusLine(
                KalivMediaJob.label(current, ref.kind),
                onRetry = if ((current as? DesktopMediaPhase.Ended)?.retryable == true) ({ attempt += 1 }) else null,
            )
        }
    }
}

@Composable
private fun MediaStatusLine(text: String, onRetry: (() -> Unit)?) {
    val shape = RoundedCornerShape(14.dp)
    Row(
        Modifier
            .clip(shape)
            .background(KalivTheme.colors.SurfaceHigh)
            .border(1.dp, KalivTheme.colors.Border, shape)
            .padding(horizontal = 14.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(text, color = KalivTheme.colors.TextMuted, fontSize = 14.sp, lineHeight = 20.sp)
        if (onRetry != null) {
            Spacer(Modifier.width(8.dp))
            TextButton(onClick = onRetry) { Text("Prøv igen") }
        }
    }
}

@Composable
private fun PictureCard(picture: LoadedPicture, ref: DesktopMediaJobRef) {
    var viewing by remember(ref.jobId) { mutableStateOf(false) }
    val shape = RoundedCornerShape(14.dp)
    val ratio = picture.bitmap.width.toFloat() / picture.bitmap.height.toFloat()
    Image(
        bitmap = picture.bitmap,
        contentDescription = "Genereret billede. Klik for fuld størrelse",
        contentScale = ContentScale.Fit,
        modifier = Modifier
            .widthIn(max = 420.dp)
            .heightIn(max = 520.dp)
            .aspectRatio(ratio)
            .clip(shape)
            .border(1.dp, KalivTheme.colors.Border, shape)
            .clickable { viewing = true },
    )
    if (viewing) {
        KalivPictureViewer(picture, ref, onClose = { viewing = false })
    }
}

/** The picture in its own window: wheel to zoom, drag to pan, and a place to save it. */
@Composable
private fun KalivPictureViewer(picture: LoadedPicture, ref: DesktopMediaJobRef, onClose: () -> Unit) {
    var scale by remember { mutableStateOf(KalivMediaJob.MIN_SCALE) }
    var panX by remember { mutableStateOf(0f) }
    var panY by remember { mutableStateOf(0f) }
    var view by remember { mutableStateOf(IntSize.Zero) }
    var notice by remember { mutableStateOf<String?>(null) }

    fun zoom(steps: Float) {
        scale = KalivMediaJob.nextScale(scale, steps)
        val (x, y) = KalivMediaJob.nextPan(panX, panY, 0f, 0f, scale, view.width.toFloat(), view.height.toFloat())
        panX = x
        panY = y
    }

    DialogWindow(
        onCloseRequest = onClose,
        state = rememberDialogState(size = DpSize(1100.dp, 820.dp)),
        title = "Kaliv: genereret billede",
    ) {
        val owner = window
        Column(Modifier.fillMaxSize().background(KalivTheme.colors.Graphite)) {
            Box(
                Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .clipToBounds()
                    .onSizeChanged { view = it }
                    .pointerInput(Unit) {
                        awaitPointerEventScope {
                            while (true) {
                                val event = awaitPointerEvent()
                                if (event.type == PointerEventType.Scroll) {
                                    // Wheel away from the user zooms in; scrollDelta.y is positive towards them.
                                    zoom(-(event.changes.firstOrNull()?.scrollDelta?.y ?: 0f))
                                }
                            }
                        }
                    }
                    .pointerInput(Unit) {
                        detectDragGestures { change, drag ->
                            change.consume()
                            val (x, y) = KalivMediaJob.nextPan(
                                panX, panY, drag.x, drag.y, scale, view.width.toFloat(), view.height.toFloat(),
                            )
                            panX = x
                            panY = y
                        }
                    },
                contentAlignment = Alignment.Center,
            ) {
                Image(
                    bitmap = picture.bitmap,
                    contentDescription = "Genereret billede, fuld størrelse",
                    contentScale = ContentScale.Fit,
                    modifier = Modifier.fillMaxSize().graphicsLayer {
                        scaleX = scale
                        scaleY = scale
                        translationX = panX
                        translationY = panY
                    },
                )
            }
            Row(
                Modifier.fillMaxWidth().background(KalivTheme.colors.Surface).padding(horizontal = 12.dp, vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                TextButton(onClick = { zoom(-1f) }) { Text("−") }
                Text(
                    "${Math.round(scale * 100f)} %",
                    color = KalivTheme.colors.TextMuted,
                    fontSize = 13.sp,
                    modifier = Modifier.width(56.dp),
                )
                TextButton(onClick = { zoom(1f) }) { Text("+") }
                TextButton(onClick = {
                    scale = KalivMediaJob.MIN_SCALE
                    panX = 0f
                    panY = 0f
                }) { Text("Tilpas") }
                Spacer(Modifier.weight(1f))
                notice?.let {
                    Text(it, color = KalivTheme.colors.TextMuted, fontSize = 13.sp)
                    Spacer(Modifier.width(12.dp))
                }
                TextButton(onClick = {
                    val extension = KalivMediaJob.imageExtension(picture.bytes)
                    if (extension == null) {
                        notice = "Ukendt billedformat; kan ikke gemmes"
                    } else {
                        val chosen = chooseSaveFile(owner, "Gem billede", KalivMediaJob.fileName(ref.jobId, extension))
                        if (chosen != null) {
                            val target = chosen.resolveSibling(
                                KalivMediaJob.withExtension(chosen.fileName.toString(), extension),
                            )
                            notice = KalivMediaJob.saveTo(target) { it.write(picture.bytes) }.fold(
                                onSuccess = { "Gemt: ${it.fileName}" },
                                onFailure = { "Filen kunne ikke skrives" },
                            )
                        }
                    }
                }) { Text("Gem som …") }
                TextButton(onClick = onClose) { Text("Luk") }
            }
        }
    }
}

@Composable
private fun ClipCard(ref: DesktopMediaJobRef, job: DesktopMediaJob, source: DesktopMediaSource) {
    val assetId = job.assetId ?: return
    val scope = rememberCoroutineScope()
    var busy by remember(ref.jobId) { mutableStateOf(false) }
    var notice by remember(ref.jobId) { mutableStateOf<String?>(null) }
    var saved by remember(ref.jobId) { mutableStateOf<Path?>(null) }
    val shape = RoundedCornerShape(14.dp)
    Column(
        Modifier
            .widthIn(max = 420.dp)
            .clip(shape)
            .background(KalivTheme.colors.SurfaceHigh)
            .border(1.dp, KalivTheme.colors.Border, shape)
            .padding(horizontal = 14.dp, vertical = 8.dp),
    ) {
        Text("Klippet er færdigt", color = KalivTheme.colors.TextHigh, fontSize = 14.sp, lineHeight = 20.sp)
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(
                enabled = !busy,
                onClick = {
                    val chosen = chooseSaveFile(null, "Gem klip", KalivMediaJob.fileName(ref.jobId, "mp4"))
                    if (chosen != null) {
                        val target = chosen.resolveSibling(KalivMediaJob.withExtension(chosen.fileName.toString(), "mp4"))
                        busy = true
                        saved = null
                        notice = "Henter klippet fra riggen …"
                        scope.launch {
                            val result = withContext(Dispatchers.IO) {
                                KalivMediaJob.saveTo(target) { out -> source.videoInto(assetId, out) }
                            }
                            result.fold(
                                onSuccess = {
                                    saved = it
                                    notice = "Gemt: ${it.fileName}"
                                },
                                onFailure = { notice = KalivMediaJob.transferFailedText(it, DesktopMediaKind.VIDEO) },
                            )
                            busy = false
                        }
                    }
                },
            ) { Text("Gem klip …") }
            val file = saved
            if (file != null) {
                TextButton(onClick = {
                    if (!openWithSystem(file)) notice = "Klippet kunne ikke åbnes herfra; det ligger i $file"
                }) { Text("Åbn") }
            }
        }
        notice?.let { Text(it, color = KalivTheme.colors.TextMuted, fontSize = 13.sp, lineHeight = 18.sp) }
    }
}

/** The system's save dialog; null when the user backed out. [owner] keeps it in front of a viewer window. */
private fun chooseSaveFile(owner: java.awt.Dialog?, title: String, suggestedName: String): Path? {
    val dialog = if (owner != null) {
        java.awt.FileDialog(owner, title, java.awt.FileDialog.SAVE)
    } else {
        java.awt.FileDialog(null as java.awt.Frame?, title, java.awt.FileDialog.SAVE)
    }
    dialog.file = suggestedName
    dialog.isVisible = true
    val directory = dialog.directory ?: return null
    val name = dialog.file ?: return null
    return runCatching { Path.of(directory, name) }.getOrNull()
}

private fun openWithSystem(file: Path): Boolean = runCatching {
    val supported = java.awt.Desktop.isDesktopSupported() &&
        java.awt.Desktop.getDesktop().isSupported(java.awt.Desktop.Action.OPEN)
    if (supported) java.awt.Desktop.getDesktop().open(file.toFile())
    supported
}.getOrDefault(false)
