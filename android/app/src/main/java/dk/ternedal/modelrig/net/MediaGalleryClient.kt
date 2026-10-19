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
        val octets = parts.map { part ->
            if (part.isEmpty() || (part.length > 1 && part.startsWith("0"))) return false
            part.toIntOrNull() ?: return false
        }
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

    /**
     * Read a bounded media segment through the paired backend. No redirects,
     * no arbitrary URLs, and never buffer an entire video into memory.
     */
    fun readRange(entry: MediaGalleryEntry, start: Long, endInclusive: Long): ByteArray {
        require(start >= 0 && endInclusive >= start && endInclusive - start < 1024 * 1024) {
            "Media range must be at most 1 MiB"
        }
        require(token.isNotBlank()) { "Rig pairing required" }
        val request = Request.Builder().url(base + entry.mediaPath())
            .header("Authorization", "Bearer " + token)
            .header("Range", "bytes=" + start + "-" + endInclusive)
            .get().build()
        http.newCall(request).execute().use { response ->
            if (response.code != 206) {
                throw ModelRigException("Medieserveren understøtter ikke sikker delvis hentning (" + response.code + ")")
            }
            val expected = endInclusive - start + 1
            val range = response.header("Content-Range").orEmpty()
            val total = range.substringAfter("/", "").toLongOrNull()
            if (range.substringBefore("/") != "bytes " + start + "-" + endInclusive ||
                total == null || total <= endInclusive) {
                throw ModelRigException("Ugyldigt byte-interval fra medieserveren")
            }
            if (response.header("Content-Length")?.toLongOrNull()?.let { it != expected } == true) {
                throw ModelRigException("Ugyldig medielængde")
            }
            val body = response.body ?: throw ModelRigException("Tomt mediesvar")
            val data = body.byteStream().use { stream ->
                val bytes = ByteArray(expected.toInt() + 1)
                var read = 0
                while (read < bytes.size) {
                    val n = stream.read(bytes, read, bytes.size - read)
                    if (n < 0) break
                    read += n
                }
                if (read != expected.toInt()) throw ModelRigException("Ufuldstændigt mediesvar")
                if (read == bytes.size) throw ModelRigException("For langt mediesvar")
                bytes.copyOf(read)
            }
            return data
        }
    }

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
            val body = response.body ?: throw ModelRigException("Tomt mediebibliotek")
            val maxBytes = 1024 * 1024
            if (body.contentLength() > maxBytes) throw ModelRigException("Mediebiblioteket er for stort")
            val payload = body.byteStream().use { stream ->
                val buffer = ByteArray(maxBytes + 1)
                var count = 0
                while (count < buffer.size) {
                    val n = stream.read(buffer, count, buffer.size - count)
                    if (n < 0) break
                    if (n == 0) continue
                    count += n
                }
                if (count > maxBytes) throw ModelRigException("Mediebiblioteket er for stort")
                String(buffer, 0, count, Charsets.UTF_8)
            }
            val json = JSONObject(payload)
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
