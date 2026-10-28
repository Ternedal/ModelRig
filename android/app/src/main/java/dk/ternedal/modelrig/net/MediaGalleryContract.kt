package dk.ternedal.modelrig.net

import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.math.BigDecimal
import java.math.BigInteger
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.time.Instant
import java.time.format.DateTimeParseException

/**
 * `kaliv-media-gallery/v1`: the read-only media gallery contract agreed on
 * ModelRig #2275 (proposal 6468949085, approved with amendments 6469270137).
 *
 * ```
 * GET /api/v1/media?limit=1..100[&cursor=<opaque>]
 * 200 {"schema":"kaliv-media-gallery/v1","items":[Item],"next_cursor":string|null}
 * GET|HEAD /api/v1/media/{id}
 * ```
 *
 * The contract is the target; no ModelRig backend implements it yet. The
 * parser fails closed per item: an invalid item is skipped and counted, never
 * shown, and never takes the rest of the page with it. Page-level damage
 * (wrong schema, missing list, bad cursor) rejects the whole page.
 */
enum class MediaKind(val wire: String) {
    IMAGE("image"),
    VIDEO("video"),
}

data class MediaItem(
    val id: String,
    val kind: MediaKind,
    val mimeType: String,
    val createdAt: Instant,
    val sizeBytes: Long,
    val width: Int?,
    val height: Int?,
    val durationSeconds: Double?,
    val projection: String,
    val stereo: String,
    val thumbnailId: String?,
    val supportsRange: Boolean,
) {
    /** Always derived from the ID; a path from the server is only compared, never used. */
    val mediaPath: String get() = MediaGalleryContract.mediaPath(id)
    val thumbnailPath: String? get() = thumbnailId?.let(MediaGalleryContract::mediaPath)
    val isFlat: Boolean get() = projection == "flat" && stereo == "mono"
}

data class MediaPage(
    val items: List<MediaItem>,
    /** Null at the end of the list. Opaque: only ever echoed back. */
    val nextCursor: String?,
    /** Items in this page that failed validation and are not shown. */
    val skipped: Int,
)

object MediaGalleryContract {
    const val SCHEMA = "kaliv-media-gallery/v1"
    const val MAX_LIMIT = 100
    const val DEFAULT_LIMIT = 50
    private const val MAX_CURSOR_CHARS = 1024

    private val SAFE_ID = Regex("^[A-Za-z0-9_-]{1,128}$")
    private val MIME_BY_KIND = mapOf(
        MediaKind.IMAGE to setOf("image/png", "image/jpeg", "image/webp"),
        MediaKind.VIDEO to setOf("video/mp4"),
    )
    val PROJECTIONS = setOf("flat", "equirectangular_180", "equirectangular_360")
    val STEREO = setOf("mono", "left_right", "top_bottom")

    fun isSafeId(value: String): Boolean = SAFE_ID.matches(value)

    /**
     * Only safe IDs become paths. They are still encoded like every other path
     * segment in the app (tests/workflow_client_path_segments.py); for this
     * alphabet the encoding is the identity, so the result equals the server's.
     */
    fun mediaPath(id: String): String {
        require(isSafeId(id)) { "unsafe media id" }
        return "/api/v1/media/${seg(id)}"
    }

    private fun seg(value: String): String =
        URLEncoder.encode(value, StandardCharsets.UTF_8.toString()).replace("+", "%20")

    /** Opaque, but bounded and printable ASCII so it can be echoed as a query value. */
    fun isValidCursor(value: String): Boolean =
        value.length in 1..MAX_CURSOR_CHARS && value.all { it.code in 0x21..0x7e }

    /** Parse one page. Throws [MediaGalleryException] with [MediaGalleryException.Reason.PROTOCOL]. */
    fun parsePage(body: String): MediaPage {
        val root = try {
            JSONObject(body)
        } catch (e: JSONException) {
            throw protocol("Mediebiblioteket svarede ikke med gyldig JSON")
        }
        if (root.opt("schema") != SCHEMA) throw protocol("Ukendt mediebibliotek-format")
        val array = root.opt("items") as? JSONArray ?: throw protocol("Manglende medieliste")
        if (array.length() > MAX_LIMIT) throw protocol("For mange medier i ét svar")
        if (!root.has("next_cursor")) throw protocol("Manglende next_cursor")
        val cursor = when (val raw = root.opt("next_cursor").orJsonNull()) {
            null -> null
            is String -> raw.takeIf(::isValidCursor) ?: throw protocol("Ugyldig next_cursor")
            else -> throw protocol("Ugyldig next_cursor")
        }
        val items = ArrayList<MediaItem>(array.length())
        val seen = HashSet<String>()
        var skipped = 0
        for (i in 0 until array.length()) {
            val item = (array.opt(i) as? JSONObject)?.let(::parseItem)
            if (item == null || !seen.add(item.id)) {
                skipped++
            } else {
                items += item
            }
        }
        return MediaPage(items, cursor, skipped)
    }

    /** Null when the item breaks the contract in any way. Unknown fields are ignored. */
    fun parseItem(obj: JSONObject): MediaItem? {
        val id = obj.opt("id") as? String ?: return null
        if (!isSafeId(id)) return null
        val kind = MediaKind.entries.firstOrNull { it.wire == obj.opt("kind") } ?: return null
        val mime = obj.opt("mime_type") as? String ?: return null
        if (mime !in MIME_BY_KIND.getValue(kind)) return null
        val createdAt = (obj.opt("created_at") as? String)?.let(::parseUtc) ?: return null
        val size = strictLong(obj.opt("size_bytes")) ?: return null
        if (size < 0) return null
        val width = optionalDimension(obj, "width") ?: return null
        val height = optionalDimension(obj, "height") ?: return null
        val duration = when (val raw = obj.opt("duration_seconds").orJsonNull()) {
            null -> null
            is Number -> raw.toDouble().takeIf { it.isFinite() && it >= 0 } ?: return null
            else -> return null
        }
        if (kind == MediaKind.IMAGE && duration != null) return null
        val projection = obj.opt("projection") as? String ?: return null
        val stereo = obj.opt("stereo") as? String ?: return null
        if (projection !in PROJECTIONS || stereo !in STEREO) return null
        val thumbnailId = when (val raw = obj.opt("thumbnail_id").orJsonNull()) {
            null -> null
            is String -> raw.takeIf(::isSafeId) ?: return null
            else -> return null
        }
        val playback = obj.opt("playback") as? JSONObject ?: return null
        val supportsRange = playback.opt("supports_range") as? Boolean ?: return null
        // The server's paths must equal what the ID implies. They are never used.
        if (obj.opt("url") != mediaPath(id)) return null
        val thumbnailUrl = obj.opt("thumbnail_url").orJsonNull()
        if (thumbnailUrl != thumbnailId?.let(::mediaPath)) return null
        return MediaItem(
            id = id, kind = kind, mimeType = mime, createdAt = createdAt, sizeBytes = size,
            width = width.value, height = height.value, durationSeconds = duration,
            projection = projection, stereo = stereo, thumbnailId = thumbnailId,
            supportsRange = supportsRange,
        )
    }

    /** RFC 3339 in UTC only ("…Z"); an offset or a local time is a contract break. */
    private fun parseUtc(value: String): Instant? {
        if (!value.endsWith("Z")) return null
        return try {
            Instant.parse(value)
        } catch (e: DateTimeParseException) {
            null
        }
    }

    /**
     * JSON integers only; 1.0, 1e3, 1.5, "1" or a value beyond Long are rejected.
     * Android's org.json yields Double for decimals, the test library BigDecimal;
     * both are refused so the phone and the tests agree.
     */
    private fun strictLong(raw: Any?): Long? = when (raw) {
        is Int -> raw.toLong()
        is Long -> raw
        is BigInteger -> if (raw.bitLength() < 64) raw.toLong() else null
        is BigDecimal, is Double, is Float -> null
        else -> null
    }

    /** Wrapper so "absent/null" (valid) and "broken" (null result) stay distinct. */
    private class Dimension(val value: Int?)

    private fun optionalDimension(obj: JSONObject, key: String): Dimension? =
        when (val raw = obj.opt(key).orJsonNull()) {
            null -> Dimension(null)
            else -> strictLong(raw)?.takeIf { it in 0..Int.MAX_VALUE.toLong() }?.let { Dimension(it.toInt()) }
        }

    /** Absent and explicit JSON null both become Kotlin null. */
    private fun Any?.orJsonNull(): Any? = if (this == null || this === JSONObject.NULL) null else this

    private fun protocol(message: String) =
        MediaGalleryException(MediaGalleryException.Reason.PROTOCOL, message)
}

/** Every gallery failure the UI distinguishes. Messages never contain tokens or paths. */
class MediaGalleryException(val reason: Reason, message: String) : RuntimeException(message) {
    enum class Reason {
        NOT_PAIRED,
        ORIGIN_REFUSED,
        UNAUTHORIZED,
        NOT_FOUND,
        BAD_REQUEST,
        STORAGE_UNAVAILABLE,
        TOO_LARGE,
        REDIRECT_REFUSED,
        PROTOCOL,
        NETWORK,
        HTTP,
    }
}
