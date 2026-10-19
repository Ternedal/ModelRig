package dk.ternedal.modelrig.net

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/** Dormant until the authenticated Go backend provides /api/v1/media. */
class MediaGalleryClient(baseUrl: String, private val token: String) {
    private val base = baseUrl.trimEnd('/')
    init {
        val parsed = base.toHttpUrlOrNull()
        require(parsed != null && parsed.host.isNotBlank() && parsed.username.isEmpty() && parsed.password.isEmpty()) {
            "Invalid paired rig URL"
        }
        require(parsed.scheme == "https" || (parsed.scheme == "http" && isPrivateRigHost(parsed.host))) {
            "Media gallery requires HTTPS or private-network paired rig"
        }
        require(parsed.encodedPath == "/" && parsed.query == null && parsed.fragment == null) {
            "Paired rig URL must be an origin"
        }
    }

    private fun isPrivateRigHost(host: String): Boolean {
        if (host == "localhost" || host == "127.0.0.1" || host == "::1") return true
        val parts = host.split(".")
        if (parts.size != 4) return false
        val octets = parts.map { it.toIntOrNull() ?: return false }
        if (octets.any { it !in 0..255 }) return false
        val first = octets[0]
        val second = octets[1]
        return first == 10 || (first == 172 && second in 16..31) ||
            (first == 192 && second == 168)
    }
    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .followRedirects(false)
        .followSslRedirects(false)
        .build()

    fun list(limit: Int = 50, offset: Int = 0): List<MediaGalleryEntry> {
        require(limit in 1..100 && offset >= 0)
        require(token.isNotBlank()) { "Rig pairing required" }
        val path = "/api/v1/media?limit=" + limit + "&offset=" + offset
        val request = Request.Builder().url(base + path)
            .header("Authorization", "Bearer " + token).get().build()
        http.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw ModelRigException("Mediebibliotek utilgængeligt (" + response.code + ")")
            }
            val json = JSONObject(response.body?.string().orEmpty())
            if (json.optString("schema") != "kaliv-media-gallery/v1") {
                throw ModelRigException("Ukendt mediebibliotek-format")
            }
            val array = json.optJSONArray("items")
                ?: throw ModelRigException("Manglende medieliste")
            return buildList {
                for (i in 0 until array.length()) {
                    val item = array.optJSONObject(i)
                        ?: throw ModelRigException("Ugyldigt medie")
                    val entry = MediaGalleryEntry.parse(
                        id = item.optString("id"),
                        kind = item.optString("kind"),
                        projection = item.optString("projection"),
                        stereo = item.optString("stereo"),
                        thumbnailId = if (item.isNull("thumbnail_id")) null else item.optString("thumbnail_id").ifBlank { null },
                        mediaUrl = item.optString("url"),
                        thumbnailUrl = if (item.isNull("thumbnail_url")) null else item.optString("thumbnail_url").ifBlank { null }
                    ) ?: throw ModelRigException("Ugyldige medieoplysninger")
                    add(entry)
                }
            }
        }
    }
}
