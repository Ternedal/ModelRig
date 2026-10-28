package dk.ternedal.modelrig.ui

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.LruCache
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
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
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.net.MediaGalleryClient
import dk.ternedal.modelrig.net.MediaGalleryException
import dk.ternedal.modelrig.net.MediaGalleryException.Reason
import dk.ternedal.modelrig.net.MediaGallerySource
import dk.ternedal.modelrig.net.MediaItem
import dk.ternedal.modelrig.net.MediaKind
import dk.ternedal.modelrig.ui.components.kalivScreenInsets
import dk.ternedal.modelrig.ui.theme.KalivTheme
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext

/**
 * Read-only gallery for `kaliv-media-gallery/v1` (ModelRig #2275).
 *
 * Reached only through MainActivity's EXTRA_MEDIA_GALLERY, not from the app's
 * navigation; the backend API is not on main yet. Images are shown; video
 * playback comes in a later PR with its own dependency approval.
 */
@Composable
fun MediaGalleryScreen(store: TokenStore, onClose: () -> Unit) {
    val baseUrl = store.baseUrl
    val token = store.token
    val source = remember(baseUrl, token) { runCatching { MediaGalleryClient(baseUrl, token) } }
    source.fold(
        onSuccess = { MediaGalleryContent(it, onClose) },
        onFailure = { MediaGalleryUnavailable(reasonOf(it), onClose) },
    )
}

internal fun reasonOf(error: Throwable): Reason = (error as? MediaGalleryException)?.reason ?: Reason.PROTOCOL

@Composable
internal fun MediaGalleryUnavailable(reason: Reason, onClose: () -> Unit) {
    GallerySurface {
        Button(onClick = onClose) { Text("Tilbage") }
        Text("Mediebibliotek", color = KalivTheme.colors.textHigh, modifier = Modifier.padding(vertical = 16.dp))
        Text(mediaGalleryMessage(reason), color = KalivTheme.colors.danger)
    }
}

@Composable
internal fun MediaGalleryContent(
    source: MediaGallerySource,
    onClose: () -> Unit,
    io: CoroutineDispatcher = Dispatchers.IO,
) {
    var state by remember { mutableStateOf(MediaGalleryState()) }
    var selected by remember { mutableStateOf<MediaItem?>(null) }
    val scope = rememberCoroutineScope()
    val thumbnails = remember { ThumbnailCache() }
    // A grid of thumbnails must not open dozens of requests to the rig at once.
    val gate = remember { Semaphore(THUMBNAIL_PARALLELISM) }

    fun refresh() {
        if (state.loading) return
        state = MediaGalleryPaging.startRefresh(state)
        scope.launch {
            val result = withContext(io) { runCatching { source.page() } }
            state = result.fold(
                onSuccess = { MediaGalleryPaging.refreshed(it) },
                onFailure = { MediaGalleryPaging.failed(state, reasonOf(it)) },
            )
        }
    }

    fun loadMore() {
        val cursor = state.nextCursor ?: return
        if (state.loading || state.endReached) return
        state = MediaGalleryPaging.startLoadMore(state)
        scope.launch {
            val result = withContext(io) { runCatching { source.page(cursor = cursor) } }
            state = result.fold(
                onSuccess = { MediaGalleryPaging.appended(state, it) },
                onFailure = { MediaGalleryPaging.failed(state, reasonOf(it)) },
            )
        }
    }

    LaunchedEffect(Unit) { refresh() }
    BackHandler(enabled = selected != null) { selected = null }

    selected?.let { item ->
        MediaDetail(item, source, io, onBack = { selected = null })
        return
    }

    GallerySurface(scroll = false) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Button(onClick = onClose) { Text("Tilbage") }
            Button(onClick = { refresh() }, enabled = !state.loading) {
                Text(if (state.loading && !state.loaded) "Henter…" else "Opdater")
            }
        }
        Text("Mediebibliotek", color = KalivTheme.colors.textHigh, modifier = Modifier.padding(vertical = 16.dp))
        val error = state.error
        when {
            !state.loaded && error != null -> {
                Text(mediaGalleryMessage(error), color = KalivTheme.colors.danger)
                Button(onClick = { refresh() }, modifier = Modifier.padding(top = 12.dp)) { Text("Prøv igen") }
            }
            !state.loaded -> Text("Henter mediebiblioteket…", color = KalivTheme.colors.textMuted)
            state.isEmpty -> {
                Text("Ingen billeder eller videoer endnu.", color = KalivTheme.colors.textMuted)
                skippedMessage(state.skipped)?.let { Text(it, color = KalivTheme.colors.textMuted) }
            }
            else -> LazyVerticalGrid(
                columns = GridCells.Adaptive(112.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.fillMaxSize(),
            ) {
                items(state.items, key = { it.id }) { item ->
                    MediaTile(item, source, io, thumbnails, gate, onOpen = { selected = it })
                }
                item(span = { GridItemSpan(maxLineSpan) }) {
                    Column(Modifier.padding(vertical = 12.dp)) {
                        skippedMessage(state.skipped)?.let { Text(it, color = KalivTheme.colors.textMuted) }
                        when {
                            error == Reason.BAD_REQUEST -> {
                                Text(mediaGalleryMessage(error), color = KalivTheme.colors.danger)
                                Button(onClick = { refresh() }) { Text("Opdater") }
                            }
                            error != null -> {
                                Text(mediaGalleryMessage(error), color = KalivTheme.colors.danger)
                                Button(onClick = {
                                    state = state.copy(error = null)
                                    loadMore()
                                }) { Text("Prøv igen") }
                            }
                            state.loading -> Text("Henter flere…", color = KalivTheme.colors.textMuted)
                            state.canLoadMore -> Button(onClick = { loadMore() }) { Text("Hent flere") }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun MediaTile(
    item: MediaItem,
    source: MediaGallerySource,
    io: CoroutineDispatcher,
    cache: ThumbnailCache,
    gate: Semaphore,
    onOpen: (MediaItem) -> Unit,
) {
    var bitmap by remember(item.id) { mutableStateOf(cache.get(item.id)) }
    LaunchedEffect(item.id) {
        if (bitmap == null && item.thumbnailId != null) {
            val decoded = withContext(io) {
                gate.withPermit { runCatching { decodeBounded(source.thumbnail(item), THUMBNAIL_PX) } }
            }
            decoded.getOrNull()?.let {
                cache.put(item.id, it)
                bitmap = it
            }
        }
    }
    val label = mediaKindLabel(item)
    val created = mediaCreated(item)
    Box(
        modifier = Modifier
            .aspectRatio(1f)
            .clip(RoundedCornerShape(8.dp))
            .background(KalivTheme.colors.surface)
            .clickable { onOpen(item) }
            .semantics { contentDescription = "$label, $created" },
        contentAlignment = Alignment.Center,
    ) {
        val shown = bitmap
        if (shown != null) {
            Image(shown.asImageBitmap(), contentDescription = null, contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize())
        } else {
            Text(label, color = KalivTheme.colors.textMuted)
        }
        if (item.kind == MediaKind.VIDEO) {
            Text(
                mediaDuration(item.durationSeconds) ?: "Video",
                color = KalivTheme.colors.textHigh,
                modifier = Modifier.align(Alignment.BottomEnd)
                    .background(KalivTheme.colors.background)
                    .padding(horizontal = 6.dp, vertical = 2.dp),
            )
        }
    }
}

@Composable
private fun MediaDetail(item: MediaItem, source: MediaGallerySource, io: CoroutineDispatcher, onBack: () -> Unit) {
    val tooLarge = item.kind == MediaKind.IMAGE && item.sizeBytes > MediaGalleryClient.IMAGE_MAX_BYTES
    var bitmap by remember(item.id) { mutableStateOf<Bitmap?>(null) }
    var error by remember(item.id) { mutableStateOf<Reason?>(null) }
    LaunchedEffect(item.id) {
        if (item.kind == MediaKind.IMAGE && !tooLarge) {
            withContext(io) { runCatching { decodeBounded(source.image(item), DETAIL_PX) } }
                .onSuccess { bitmap = it }
                .onFailure { error = reasonOf(it) }
        }
    }
    GallerySurface {
        Button(onClick = onBack) { Text("Til galleriet") }
        val shown = bitmap
        val failure = error
        Box(Modifier.fillMaxWidth().padding(vertical = 16.dp), contentAlignment = Alignment.Center) {
            when {
                item.kind == MediaKind.VIDEO ->
                    Text("Videoafspilning kommer i en senere version.", color = KalivTheme.colors.textMuted)
                tooLarge -> Text(mediaGalleryMessage(Reason.TOO_LARGE), color = KalivTheme.colors.danger)
                failure != null -> Text(mediaGalleryMessage(failure), color = KalivTheme.colors.danger)
                shown != null -> Image(shown.asImageBitmap(), contentDescription = mediaKindLabel(item),
                    contentScale = ContentScale.Fit, modifier = Modifier.fillMaxWidth())
                else -> Text("Henter billedet…", color = KalivTheme.colors.textMuted)
            }
        }
        mediaLayoutNote(item)?.let { Text(it, color = KalivTheme.colors.textMuted) }
        Text(mediaKindLabel(item) + " · " + mediaCreated(item), color = KalivTheme.colors.textHigh)
        Text(mediaSize(item.sizeBytes), color = KalivTheme.colors.textMuted)
        if (item.width != null && item.height != null) {
            Text("${item.width} × ${item.height}", color = KalivTheme.colors.textMuted)
        }
        mediaDuration(item.durationSeconds)?.let { Text("Varighed $it", color = KalivTheme.colors.textMuted) }
    }
}

@Composable
private fun GallerySurface(scroll: Boolean = true, content: @Composable () -> Unit) {
    Surface(color = KalivTheme.colors.background, modifier = Modifier.fillMaxSize().kalivScreenInsets()) {
        val base = Modifier.fillMaxSize().padding(18.dp)
        Column(if (scroll) base.verticalScroll(rememberScrollState()) else base) { content() }
    }
}

private const val THUMBNAIL_PX = 384
private const val DETAIL_PX = 2048
private const val THUMBNAIL_PARALLELISM = 4
/** Header-declared size above which an image is not decoded at all. */
private const val MAX_SOURCE_PIXELS = 120L * 1_000_000

/**
 * Decode with the longest side at most about [maxSidePx]. Reads the bounds
 * first, so a huge image is sampled down instead of allocated at full size.
 */
internal fun decodeBounded(bytes: ByteArray, maxSidePx: Int): Bitmap {
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
    val width = bounds.outWidth
    val height = bounds.outHeight
    if (width <= 0 || height <= 0) throw MediaGalleryException(Reason.PROTOCOL, "Billedet kan ikke læses")
    if (width.toLong() * height > MAX_SOURCE_PIXELS) {
        throw MediaGalleryException(Reason.TOO_LARGE, "For stort til at blive vist på telefonen")
    }
    var sample = 1
    while (maxOf(width, height) / (sample * 2) >= maxSidePx) sample *= 2
    val options = BitmapFactory.Options().apply { inSampleSize = sample }
    return BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)
        ?: throw MediaGalleryException(Reason.PROTOCOL, "Billedet kan ikke læses")
}

/** Memory-only thumbnail cache, bounded by bytes; private media never goes to disk. */
internal class ThumbnailCache(maxKb: Int = defaultKb()) {
    private val cache = object : LruCache<String, Bitmap>(maxKb) {
        override fun sizeOf(key: String, value: Bitmap): Int = (value.byteCount / 1024).coerceAtLeast(1)
    }

    fun get(id: String): Bitmap? = cache.get(id)
    fun put(id: String, bitmap: Bitmap) {
        cache.put(id, bitmap)
    }

    private companion object {
        fun defaultKb(): Int = (Runtime.getRuntime().maxMemory() / 1024 / 16).coerceAtMost(32L * 1024).toInt()
    }
}
