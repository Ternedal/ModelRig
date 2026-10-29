package dk.ternedal.modelrig.ui

import androidx.annotation.OptIn
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.common.util.UnstableApi
import androidx.media3.datasource.HttpDataSource
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.ProgressiveMediaSource
import androidx.media3.ui.PlayerView
import dk.ternedal.modelrig.net.MediaGalleryException.Reason
import dk.ternedal.modelrig.net.MediaItem
import dk.ternedal.modelrig.net.MediaOriginRefusedIOException
import dk.ternedal.modelrig.net.MediaVideoStream

/**
 * Media3 player for one gallery video (same library as SkyPlayer).
 *
 * - Progressive MP4 only (the contract's only video type): no HLS/DASH, so
 *   the server cannot point the player at other URLs through a manifest.
 * - Every byte comes through [MediaVideoStream.dataSourceFactory]: the
 *   gallery's OkHttp client with the bearer token, origin guard and no
 *   redirects. There is no player cache, so nothing is written to disk.
 * - Nothing is fetched until the user presses play: the player is created
 *   idle (no prepare()), and PlayerView's play button prepares an idle player
 *   (Util.handlePlayButtonAction, checked in Media3 1.11.1). It pauses when
 *   the app is stopped and is released when the view leaves composition.
 */
@OptIn(UnstableApi::class)
@Composable
internal fun MediaVideoPlayer(stream: MediaVideoStream, item: MediaItem, onError: (Reason) -> Unit) {
    val context = LocalContext.current
    val currentOnError = rememberUpdatedState(onError)
    val player = remember(stream.url) {
        ExoPlayer.Builder(context)
            .setMediaSourceFactory(ProgressiveMediaSource.Factory(stream.dataSourceFactory))
            .build()
            .apply {
                setMediaItem(androidx.media3.common.MediaItem.fromUri(stream.url))
                playWhenReady = false
            }
    }
    DisposableEffect(player) {
        val listener = object : Player.Listener {
            override fun onPlayerError(error: PlaybackException) {
                currentOnError.value(playbackReason(error))
            }
        }
        player.addListener(listener)
        onDispose {
            player.removeListener(listener)
            player.release()
        }
    }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(lifecycle, player) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_STOP) player.pause()
        }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer) }
    }
    AndroidView(
        factory = { PlayerView(it).apply { this.player = player } },
        onRelease = { it.player = null },
        modifier = Modifier.fillMaxWidth().aspectRatio(videoAspect(item)),
    )
}

/** Width/height from the catalogue when sane, otherwise 16:9. */
internal fun videoAspect(item: MediaItem): Float {
    val w = item.width ?: 0
    val h = item.height ?: 0
    if (w <= 0 || h <= 0) return 16f / 9f
    return (w.toFloat() / h).coerceIn(0.25f, 4f)
}

/**
 * Map a player failure to the gallery's reasons. The whole cause chain is
 * searched first, because the data source wraps the meaningful exception
 * (an HTTP status, or the origin guard) inside a generic IO failure.
 */
@OptIn(UnstableApi::class)
internal fun playbackReason(error: PlaybackException): Reason {
    val chain = generateSequence<Throwable>(error) { it.cause }.take(16).toList()
    if (chain.any { it is MediaOriginRefusedIOException }) return Reason.ORIGIN_REFUSED
    chain.firstNotNullOfOrNull { it as? HttpDataSource.InvalidResponseCodeException }?.let {
        return when (it.responseCode) {
            in 300..399 -> Reason.REDIRECT_REFUSED
            401, 403 -> Reason.UNAUTHORIZED
            404 -> Reason.NOT_FOUND
            503 -> Reason.STORAGE_UNAVAILABLE
            else -> Reason.HTTP
        }
    }
    return if (error.errorCode in IO_ERRORS) Reason.NETWORK else Reason.UNPLAYABLE
}

/** PlaybackException's IO error codes are the 2000 range; decoding and format errors are not. */
private val IO_ERRORS = 2000..2999
