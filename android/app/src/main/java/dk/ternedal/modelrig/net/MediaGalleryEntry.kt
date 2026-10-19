package dk.ternedal.modelrig.net

/**
 * Media gallery wire contract shared with ModelRig's experimental media API.
 *
 * This is deliberately transport-neutral. The paired, authenticated HTTP
 * client must perform the request and attach its existing credentials; this
 * class never stores tokens or opens arbitrary URLs from JSON.
 */
data class MediaGalleryEntry(
    val id: String,
    val kind: String,
    val projection: String,
    val stereo: String,
    val thumbnailId: String?
) {
    fun mediaPath(): String = "/experimental/media/$id"

    fun thumbnailPath(): String? = thumbnailId?.let { "/experimental/media/$it" }

    companion object {
        private val SAFE_ID = Regex("^[A-Za-z0-9_-]{1,128}$")
        private val PROJECTIONS = setOf("flat", "equirectangular_180", "equirectangular_360")
        private val STEREO = setOf("mono", "left_right", "top_bottom")

        /** Fail closed on unknown layout or a malicious media identifier. */
        fun parse(
            id: String,
            kind: String,
            projection: String,
            stereo: String,
            thumbnailId: String?,
            mediaUrl: String,
            thumbnailUrl: String?
        ): MediaGalleryEntry? {
            if (!SAFE_ID.matches(id) || kind !in setOf("image", "video")) return null
            if (projection !in PROJECTIONS || stereo !in STEREO) return null
            if (mediaUrl != "/experimental/media/$id") return null
            if (thumbnailId != null && !SAFE_ID.matches(thumbnailId)) return null
            if (thumbnailUrl != thumbnailId?.let { "/experimental/media/$it" }) return null
            return MediaGalleryEntry(id, kind, projection, stereo, thumbnailId)
        }
    }
}
