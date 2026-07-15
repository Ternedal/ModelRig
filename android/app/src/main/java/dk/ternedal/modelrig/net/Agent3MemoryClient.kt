package dk.ternedal.modelrig.net

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.concurrent.TimeUnit

/** Developer-only Memory 3.0 transport. It is not used by the ordinary app. */
class Agent3MemoryClient(baseUrl: String, private val token: String) {
    private val base = baseUrl.trimEnd('/')
    private val jsonType = "application/json".toMediaType()
    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(45, TimeUnit.SECONDS)
        .build()

    data class Memory(
        val id: String,
        val subject: String,
        val predicate: String,
        val value: String,
        val kind: String,
        val sensitivity: String,
        val sourceType: String,
        val sourceRef: String?,
        val confidence: Double,
        val reviewStatus: String,
        val lifecycleStatus: String,
        val supersedesId: String?,
        val createdAt: Double,
        val updatedAt: Double,
        val expiresAt: Double?,
        val deletedAt: Double?,
    )

    fun list(subject: String? = null): List<Memory> {
        val suffix = subject?.trim()?.takeIf { it.isNotEmpty() }?.let { "?subject=${query(it)}" }.orEmpty()
        return parseArray(get("/api/v1/experimental/agent3/memory$suffix").optJSONArray("memories"))
    }

    fun search(text: String): List<Memory> = parseArray(
        get("/api/v1/experimental/agent3/memory/search?q=${query(text.trim())}").optJSONArray("memories")
    )

    fun history(memoryId: String): List<Memory> = parseArray(
        get("/api/v1/experimental/agent3/memory/${path(memoryId)}/history").optJSONArray("memories")
    )

    fun create(subject: String, predicate: String, value: String, kind: String, sensitivity: String): Memory {
        val payload = JSONObject()
            .put("subject", subject)
            .put("predicate", predicate)
            .put("value", value)
            .put("kind", kind)
            .put("sensitivity", sensitivity)
        return parseMemory(post("/api/v1/experimental/agent3/memory", payload).requireObject("memory"))
    }

    fun confirm(memoryId: String): Memory = parseMemory(
        post("/api/v1/experimental/agent3/memory/${path(memoryId)}/confirm", JSONObject()).requireObject("memory")
    )

    fun reject(memoryId: String): Memory = parseMemory(
        post("/api/v1/experimental/agent3/memory/${path(memoryId)}/reject", JSONObject()).requireObject("memory")
    )

    fun correct(memoryId: String, value: String, sensitivity: String): Memory {
        val payload = JSONObject().put("value", value).put("sensitivity", sensitivity)
        return parseMemory(
            post("/api/v1/experimental/agent3/memory/${path(memoryId)}/correct", payload).requireObject("memory")
        )
    }

    fun delete(memoryId: String): Memory = parseMemory(
        deleteRequest("/api/v1/experimental/agent3/memory/${path(memoryId)}").requireObject("memory")
    )

    private fun get(path: String): JSONObject = execute(
        Request.Builder().url(base + path).get().header("Authorization", "Bearer $token").build()
    )

    private fun post(path: String, payload: JSONObject): JSONObject = execute(
        Request.Builder()
            .url(base + path)
            .post(payload.toString().toRequestBody(jsonType))
            .header("Authorization", "Bearer $token")
            .build()
    )

    private fun deleteRequest(path: String): JSONObject = execute(
        Request.Builder().url(base + path).delete().header("Authorization", "Bearer $token").build()
    )

    private fun execute(request: Request): JSONObject {
        http.newCall(request).execute().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                val detail = runCatching {
                    val root = JSONObject(text)
                    root.optString("error").ifBlank { root.optString("detail") }
                }.getOrNull()?.ifBlank { null } ?: text.take(500)
                throw ModelRigException("Memory 3.0 failed (${response.code}): $detail")
            }
            return runCatching { JSONObject(text) }
                .getOrElse { throw ModelRigException("Memory 3.0 returned invalid JSON") }
        }
    }

    private fun parseArray(array: JSONArray?): List<Memory> = buildList {
        val items = array ?: JSONArray()
        for (index in 0 until items.length()) {
            items.optJSONObject(index)?.let { add(parseMemory(it)) }
        }
    }

    private fun parseMemory(o: JSONObject): Memory = Memory(
        id = o.optString("id"),
        subject = o.optString("subject"),
        predicate = o.optString("predicate"),
        value = o.optString("value"),
        kind = o.optString("kind"),
        sensitivity = o.optString("sensitivity"),
        sourceType = o.optString("source_type"),
        sourceRef = o.nullableString("source_ref"),
        confidence = o.optDouble("confidence", 1.0),
        reviewStatus = o.optString("review_status"),
        lifecycleStatus = o.optString("lifecycle_status"),
        supersedesId = o.nullableString("supersedes_id"),
        createdAt = o.optDouble("created_at"),
        updatedAt = o.optDouble("updated_at"),
        expiresAt = o.nullableDouble("expires_at"),
        deletedAt = o.nullableDouble("deleted_at"),
    )

    private fun JSONObject.requireObject(name: String): JSONObject =
        optJSONObject(name) ?: throw ModelRigException("Memory 3.0 response missing '$name'")

    private fun JSONObject.nullableString(name: String): String? =
        if (!has(name) || isNull(name)) null else optString(name).ifBlank { null }

    private fun JSONObject.nullableDouble(name: String): Double? =
        if (!has(name) || isNull(name)) null else optDouble(name)

    private fun query(value: String): String = URLEncoder.encode(value, StandardCharsets.UTF_8.toString())

    private fun path(value: String): String = query(value).replace("+", "%20")
}
