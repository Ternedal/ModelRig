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
    fun mediaPath(): String = "/api/v1/media/${seg(id)}"

    fun thumbnailPath(): String? = thumbnailId?.let { "/api/v1/media/${seg(it)}" }

    companion object {
        private fun seg(value: String): String = java.net.URLEncoder.encode(value, "UTF-8").replace("+", "%20")
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
            if (mediaUrl != "/api/v1/media/$id") return null
            if (thumbnailId != null && !SAFE_ID.matches(thumbnailId)) return null
            if (thumbnailUrl != thumbnailId?.let { "/api/v1/media/$it" }) return null
            return MediaGalleryEntry(id, kind, projection, stereo, thumbnailId)
        }
    }
}
