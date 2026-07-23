package dk.ternedal.modelrig.net

import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.util.concurrent.TimeUnit

internal class SchedulerToolCatalogLoader(
    baseUrl: String,
    private val deviceCredential: String,
) {
    private val endpoint = baseUrl.trimEnd('/') + "/api/v1/tools"
    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    fun load(): SchedulerToolCatalog {
        val request = Request.Builder()
            .url(endpoint)
            .header("Authorization", listOf("Bearer", deviceCredential).joinToString(" "))
            .get()
            .build()
        http.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                throw ModelRigException("tools list failed (${response.code}): $body")
            }
            if (body.isBlank()) throw ModelRigException("tools list returned an empty body")
            return parseSchedulerToolCatalog(JSONObject(body))
        }
    }
}
