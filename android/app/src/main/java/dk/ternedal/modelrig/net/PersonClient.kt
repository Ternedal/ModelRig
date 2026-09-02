package dk.ternedal.modelrig.net

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Person Profile-registret (#752), læst gennem backendens `/api/v1/persons`
 * bag device-tokenet. Klienten er bevidst smal: liste, vælg, aktiv. Der er
 * ingen aktiveringskald her -- at aktivere en Person Revision er en
 * operatørhandling med review, og den hører ikke hjemme i et tryk i chatten.
 */
class PersonClient(baseUrl: String, private val token: String) {
    private val base = baseUrl.trimEnd('/')
    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .build()

    data class Person(
        val personId: String,
        val displayName: String,
        val activePersonRevision: String?,
        val bodyRevisions: Int,
        val voiceRevisions: Int,
        val personalityRevisions: Int,
        val personRevisions: Int,
    )

    data class Active(
        val personId: String,
        val displayName: String,
        val personRevision: String,
        val bodyId: String,
        val bodySource: String,
        val voiceId: String,
        val voiceSource: String,
        val personalityId: String,
        val defaultLanguage: String,
        val styleNotes: String,
    )

    data class Listing(val selectedPersonId: String?, val persons: List<Person>)

    fun list(): Listing {
        val root = execute(get("/api/v1/persons"))
        val arr = root.optJSONArray("persons")
        val persons = buildList {
            if (arr != null) for (i in 0 until arr.length()) arr.optJSONObject(i)?.let { add(parsePerson(it)) }
        }
        return Listing(root.optString("selected_person_id").ifBlank { null }, persons)
    }

    fun select(personId: String): Person {
        val body = JSONObject().put("person_id", personId).toString()
        return parsePerson(execute(post("/api/v1/persons/select", body)))
    }

    fun active(): Active? {
        val root = execute(get("/api/v1/persons/active"))
        val a = root.optJSONObject("active") ?: return null
        val body = a.optJSONObject("body") ?: JSONObject()
        val voice = a.optJSONObject("voice") ?: JSONObject()
        val personality = a.optJSONObject("personality") ?: JSONObject()
        return Active(
            personId = a.optString("person_id"),
            displayName = a.optString("display_name"),
            personRevision = a.optString("person_revision"),
            bodyId = body.optString("id"),
            bodySource = body.optString("source_id"),
            voiceId = voice.optString("id"),
            voiceSource = voice.optString("source_id"),
            personalityId = personality.optString("id"),
            defaultLanguage = personality.optString("default_language"),
            styleNotes = personality.optString("style_notes"),
        )
    }

    private fun parsePerson(o: JSONObject): Person = Person(
        personId = o.optString("person_id"),
        displayName = o.optString("display_name"),
        activePersonRevision = o.optString("active_person_revision").ifBlank { null },
        bodyRevisions = o.optJSONArray("body_revisions")?.length() ?: 0,
        voiceRevisions = o.optJSONArray("voice_revisions")?.length() ?: 0,
        personalityRevisions = o.optJSONArray("personality_revisions")?.length() ?: 0,
        personRevisions = o.optJSONArray("person_revisions")?.length() ?: 0,
    )

    private fun get(path: String): Request =
        Request.Builder().url(base + path).get().header("Authorization", "Bearer $token").build()

    private fun post(path: String, json: String): Request =
        Request.Builder().url(base + path)
            .post(json.toRequestBody("application/json".toMediaType()))
            .header("Authorization", "Bearer $token").build()

    private fun execute(request: Request): JSONObject {
        http.newCall(request).execute().use { response ->
            val text = response.body?.string().orEmpty()
            if (!response.isSuccessful) {
                val detail = runCatching {
                    val root = JSONObject(text)
                    root.optString("error").ifBlank { root.optString("detail") }
                }.getOrNull()?.ifBlank { null } ?: text.take(500)
                throw ModelRigException("Personer fejlede (${response.code}): $detail")
            }
            return runCatching { JSONObject(text) }
                .getOrElse { throw ModelRigException("Personer returnerede ugyldig JSON") }
        }
    }
}
