package dk.ternedal.modelrig.net

import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/** Dormant until the authenticated Go backend provides /api/v1/media. */
class MediaGalleryClient(baseUrl: String, private val token: String) {
    private val base = baseUrl.trimEnd('/')
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
