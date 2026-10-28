package dk.ternedal.modelrig.net

import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import java.io.IOException
import java.util.concurrent.TimeUnit

/** What the gallery UI needs; the production implementation is [MediaGalleryClient]. */
interface MediaGallerySource {
    fun page(limit: Int = MediaGalleryContract.DEFAULT_LIMIT, cursor: String? = null): MediaPage
    fun thumbnail(item: MediaItem): ByteArray
    fun image(item: MediaItem): ByteArray
}

/**
 * Which paired origin the gallery may talk to (#2275, amendment 4).
 *
 * HTTPS: the paired origin, any host. HTTP: only when the paired origin is a
 * loopback or RFC 1918 IPv4 literal (or `localhost`/`::1`). The origin always
 * comes from pairing ([dk.ternedal.modelrig.data.TokenStore]), never from a
 * server response. No user info, path, query or fragment.
 *
 * Open question on #2275: the rest of the app also pairs over plain HTTP to a
 * Tailscale address (100.64.0.0/10). That is refused here until agreed.
 */
object MediaOriginPolicy {
    fun requireAllowed(pairedOrigin: String?): HttpUrl {
        if (pairedOrigin.isNullOrBlank()) {
            throw MediaGalleryException(MediaGalleryException.Reason.NOT_PAIRED, "Par telefonen med riggen først")
        }
        val url = pairedOrigin.trim().toHttpUrlOrNull()
            ?: throw refused("Den parrede rig-adresse er ugyldig")
        if (url.username.isNotEmpty() || url.password.isNotEmpty() ||
            url.encodedPath != "/" || url.query != null || url.fragment != null
        ) {
            throw refused("Den parrede rig-adresse skal være en ren oprindelse")
        }
        if (url.scheme == "http" && !isLoopbackOrRfc1918(url.host)) {
            throw refused("Mediebiblioteket kræver HTTPS, eller en parret rig på hjemmenettet")
        }
        return url
    }

    fun isLoopbackOrRfc1918(host: String): Boolean {
        if (host == "localhost" || host == "::1") return true
        val parts = host.split(".")
        if (parts.size != 4) return false
        val octets = parts.map { part ->
            if (part.isEmpty() || part.length > 3 || (part.length > 1 && part.startsWith("0")) ||
                !part.all(Char::isDigit)
            ) {
                return false
            }
            part.toInt().takeIf { it in 0..255 } ?: return false
        }
        val (a, b) = octets
        return a == 127 || a == 10 || (a == 172 && b in 16..31) || (a == 192 && b == 168)
    }

    private fun refused(message: String) =
        MediaGalleryException(MediaGalleryException.Reason.ORIGIN_REFUSED, message)
}

/**
 * Read-only client for `kaliv-media-gallery/v1`.
 *
 * - The bearer token goes only to the paired origin; redirects are refused,
 *   never followed (thumbnail and full-size requests included).
 * - Every byte read is bounded: the list body, thumbnails and full images
 *   each have a cap, checked against Content-Length before reading and again
 *   while streaming, so an oversized asset is never downloaded in full.
 * - No HTTP cache: OkHttp has none unless configured, and none is configured.
 *   Private media stays off the phone's disk.
 */
class MediaGalleryClient(
    pairedOrigin: String?,
    private val token: String?,
    private val http: OkHttpClient = defaultHttp(),
) : MediaGallerySource {
    private val origin: HttpUrl = MediaOriginPolicy.requireAllowed(pairedOrigin)

    init {
        if (token.isNullOrBlank()) {
            throw MediaGalleryException(MediaGalleryException.Reason.NOT_PAIRED, "Par telefonen med riggen først")
        }
    }

    override fun page(limit: Int, cursor: String?): MediaPage {
        require(limit in 1..MediaGalleryContract.MAX_LIMIT) { "limit" }
        require(cursor == null || MediaGalleryContract.isValidCursor(cursor)) { "cursor" }
        val url = origin.newBuilder()
            .encodedPath("/api/v1/media")
            .addQueryParameter("limit", limit.toString())
            .apply { if (cursor != null) addQueryParameter("cursor", cursor) }
            .build()
        val body = execute(url, LIST_MAX_BYTES, requireImage = false)
        return MediaGalleryContract.parsePage(String(body, Charsets.UTF_8))
    }

    override fun thumbnail(item: MediaItem): ByteArray {
        val path = item.thumbnailPath
            ?: throw MediaGalleryException(MediaGalleryException.Reason.NOT_FOUND, "Intet miniaturebillede")
        return execute(origin.resolveExact(path), THUMBNAIL_MAX_BYTES, requireImage = true)
    }

    override fun image(item: MediaItem): ByteArray {
        require(item.kind == MediaKind.IMAGE) { "not an image" }
        if (item.sizeBytes > IMAGE_MAX_BYTES) throw tooLarge()
        return execute(origin.resolveExact(item.mediaPath), IMAGE_MAX_BYTES, requireImage = true)
    }

    private fun HttpUrl.resolveExact(path: String): HttpUrl = newBuilder().encodedPath(path).build()

    private fun execute(url: HttpUrl, maxBytes: Long, requireImage: Boolean): ByteArray {
        val request = Request.Builder().url(url)
            .header("Authorization", "Bearer $token")
            .header("Accept", if (requireImage) "image/*" else "application/json")
            .get().build()
        val response = try {
            http.newCall(request).execute()
        } catch (e: IOException) {
            throw MediaGalleryException(MediaGalleryException.Reason.NETWORK, "Riggen kan ikke nås")
        }
        response.use { return readBounded(it, maxBytes, requireImage) }
    }

    private fun readBounded(response: Response, maxBytes: Long, requireImage: Boolean): ByteArray {
        if (response.isRedirect || response.code in 300..399) {
            throw MediaGalleryException(MediaGalleryException.Reason.REDIRECT_REFUSED, "Riggen forsøgte at viderestille; afvist")
        }
        when (response.code) {
            200 -> Unit
            400 -> throw MediaGalleryException(MediaGalleryException.Reason.BAD_REQUEST, "Ugyldig forespørgsel")
            401, 403 -> throw MediaGalleryException(MediaGalleryException.Reason.UNAUTHORIZED, "Parringen er ikke længere gyldig")
            404 -> throw MediaGalleryException(MediaGalleryException.Reason.NOT_FOUND, "Mediet findes ikke")
            503 -> throw MediaGalleryException(MediaGalleryException.Reason.STORAGE_UNAVAILABLE, "Medielageret på riggen er ikke tilgængeligt")
            else -> throw MediaGalleryException(MediaGalleryException.Reason.HTTP, "Mediebiblioteket svarede ${response.code}")
        }
        val type = response.header("Content-Type").orEmpty().substringBefore(';').trim().lowercase()
        if (requireImage && !type.startsWith("image/")) {
            throw MediaGalleryException(MediaGalleryException.Reason.PROTOCOL, "Uventet medietype")
        }
        if (!requireImage && type != "application/json") {
            throw MediaGalleryException(MediaGalleryException.Reason.PROTOCOL, "Uventet svar fra mediebiblioteket")
        }
        val body = response.body
        val declared = body.contentLength()
        if (declared > maxBytes) throw tooLarge()
        return try {
            body.byteStream().use { stream ->
                val out = java.io.ByteArrayOutputStream(if (declared in 1..maxBytes) declared.toInt() else 8192)
                val buffer = ByteArray(8192)
                var total = 0L
                while (true) {
                    val n = stream.read(buffer)
                    if (n < 0) break
                    total += n
                    if (total > maxBytes) throw tooLarge()
                    out.write(buffer, 0, n)
                }
                if (declared >= 0 && total != declared) {
                    throw MediaGalleryException(MediaGalleryException.Reason.PROTOCOL, "Ufuldstændigt mediesvar")
                }
                out.toByteArray()
            }
        } catch (e: IOException) {
            throw MediaGalleryException(MediaGalleryException.Reason.NETWORK, "Forbindelsen til riggen blev afbrudt")
        }
    }

    private fun tooLarge() =
        MediaGalleryException(MediaGalleryException.Reason.TOO_LARGE, "For stort til at blive vist på telefonen")

    companion object {
        /** Client safety caps (#2275 amendment 5), not server guarantees. */
        const val LIST_MAX_BYTES: Long = 1L * 1024 * 1024
        const val THUMBNAIL_MAX_BYTES: Long = 2L * 1024 * 1024
        const val IMAGE_MAX_BYTES: Long = 25L * 1024 * 1024

        fun defaultHttp(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(20, TimeUnit.SECONDS)
            .callTimeout(90, TimeUnit.SECONDS)
            .followRedirects(false)
            .followSslRedirects(false)
            .build()
    }
}
