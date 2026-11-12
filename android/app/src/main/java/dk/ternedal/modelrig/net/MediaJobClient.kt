package dk.ternedal.modelrig.net

import dk.ternedal.modelrig.net.MediaJobException.Reason
import okhttp3.HttpUrl
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

/** What the generate screen needs; the production implementation is [MediaJobClient]. */
interface MediaJobSource {
    fun profiles(): List<MediaJobProfile>
    fun submit(request: MediaJobRequest, profile: MediaJobProfile): MediaJob
    fun status(id: String): MediaJob
    fun cancel(id: String): MediaJobCancel
}

/**
 * Client for `kaliv-media-job/v1` on the paired rig.
 *
 * The same boundaries as [MediaGalleryClient]: the origin comes from pairing
 * and passes [MediaOriginPolicy]; the bearer token goes only to that origin;
 * redirects are refused, never followed; every response body is bounded.
 *
 * The prompt is sent in the request body and nowhere else: it is not logged,
 * not put in an exception message, and not kept by this class.
 */
class MediaJobClient(
    pairedOrigin: String?,
    private val token: String?,
    http: OkHttpClient = defaultHttp(),
) : MediaJobSource {
    private val origin: HttpUrl = try {
        MediaOriginPolicy.requireAllowed(pairedOrigin)
    } catch (e: MediaGalleryException) {
        throw MediaJobException(
            if (e.reason == MediaGalleryException.Reason.NOT_PAIRED) Reason.NOT_PAIRED else Reason.ORIGIN_REFUSED,
            e.message ?: "Den parrede rig-adresse er afvist",
        )
    }

    private val http: OkHttpClient = http.newBuilder()
        .followRedirects(false)
        .followSslRedirects(false)
        .cache(null)
        .addInterceptor(Interceptor { chain ->
            val url = chain.request().url
            if (url.scheme != origin.scheme || url.host != origin.host || url.port != origin.port) {
                throw MediaOriginRefusedIOException("request outside the paired origin refused")
            }
            chain.proceed(chain.request())
        })
        .build()

    init {
        if (token.isNullOrBlank()) throw MediaJobException(Reason.NOT_PAIRED, "Par telefonen med riggen først")
    }

    override fun profiles(): List<MediaJobProfile> =
        MediaJobContract.parseProfiles(call(get(MediaJobContract.PROFILES_PATH), Route.COLLECTION))

    override fun submit(request: MediaJobRequest, profile: MediaJobProfile): MediaJob {
        val body = try {
            MediaJobContract.submitBody(request, profile)
        } catch (e: IllegalArgumentException) {
            throw MediaJobException(Reason.INVALID_REQUEST, "Forespørgslen passer ikke til profilen")
        }
        val post = Request.Builder().url(url(MediaJobContract.JOBS_PATH))
            .post(body.toRequestBody(JSON))
            .build()
        return MediaJobContract.parseJob(call(post, Route.COLLECTION))
    }

    override fun status(id: String): MediaJob = MediaJobContract.parseJob(call(get(MediaJobContract.jobPath(id)), Route.JOB))

    override fun cancel(id: String): MediaJobCancel {
        val post = Request.Builder().url(url(MediaJobContract.cancelPath(id)))
            .post(ByteArray(0).toRequestBody(null))
            .build()
        return MediaJobContract.parseCancel(call(post, Route.JOB))
    }

    private enum class Route { COLLECTION, JOB }

    private fun url(path: String): HttpUrl = origin.newBuilder().encodedPath(path).build()

    private fun get(path: String): Request = Request.Builder().url(url(path)).get().build()

    private fun call(base: Request, route: Route): String {
        val request = base.newBuilder()
            .header("Authorization", "Bearer $token")
            .header("Accept", "application/json")
            .header("Cache-Control", "no-store")
            .build()
        val response = try {
            http.newCall(request).execute()
        } catch (e: MediaOriginRefusedIOException) {
            throw MediaJobException(Reason.ORIGIN_REFUSED, "Forespørgsel uden for den parrede rig afvist")
        } catch (e: IOException) {
            throw MediaJobException(Reason.NETWORK, "Riggen kan ikke nås")
        }
        response.use { return read(it, route) }
    }

    private fun read(response: Response, route: Route): String {
        if (response.isRedirect || response.code in 300..399) {
            throw MediaJobException(Reason.REDIRECT_REFUSED, "Riggen forsøgte at viderestille; afvist")
        }
        val text = bounded(response)
        if (response.code == 200 || response.code == 202) {
            val type = response.header("Content-Type").orEmpty().substringBefore(';').trim().lowercase()
            if (type != "application/json") throw MediaJobException(Reason.UNAVAILABLE, "Uventet svar fra riggen")
            return text
        }
        val code = errorCode(text)
        throw when (response.code) {
            400, 413, 415, 422 -> MediaJobException(Reason.INVALID_REQUEST, "Riggen afviste forespørgslen", code)
            401, 403 -> MediaJobException(Reason.UNAUTHORIZED, "Parringen er ikke længere gyldig")
            404 -> if (route == Route.JOB && code != null && code.startsWith("job_not_found")) {
                MediaJobException(Reason.NOT_FOUND, "Jobbet findes ikke længere", code)
            } else {
                // The routes are absent: the switch is off on this rig. Never a guess at success.
                MediaJobException(Reason.UNAVAILABLE, "Billedgenerering er ikke tilgængelig på denne rig")
            }
            429 -> MediaJobException(Reason.BUSY, "Riggen har for mange job i kø", code)
            // The route or method is not there (an older rig, or the switch off behind a
            // proxy): the same as a missing route, never a guess (matrix 6780346935 P3 #5).
            405, 501 -> MediaJobException(Reason.UNAVAILABLE, "Billedgenerering er ikke tilgængelig på denne rig")
            // Down, busy or failing for a moment (the worker restarting, a work-area check
            // blip, an unexpected error): the job may well be fine on the rig, so the caller
            // decides whether that ends anything (6780346935 #2; #2275 backlog task 3).
            500, 502, 503, 504 -> MediaJobException(Reason.TRANSIENT, "Riggen svarer ikke lige nu", code)
            else -> MediaJobException(Reason.HTTP, "Riggen svarede ${response.code}")
        }
    }

    /** A code the rig sent (`{"detail": "queue_full"}`), only when it is a plain code. */
    private fun errorCode(text: String): String? = try {
        (JSONObject(text).opt("detail") as? String)?.takeIf { CODE.matches(it) }
    } catch (e: JSONException) {
        null
    }

    private fun bounded(response: Response): String {
        val body = response.body
        val declared = body.contentLength()
        if (declared > MAX_BYTES) throw MediaJobException(Reason.UNAVAILABLE, "Svaret fra riggen er for stort")
        return try {
            body.byteStream().use { stream ->
                val out = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(4096)
                var total = 0L
                while (true) {
                    val n = stream.read(buffer)
                    if (n < 0) break
                    total += n
                    if (total > MAX_BYTES) throw MediaJobException(Reason.UNAVAILABLE, "Svaret fra riggen er for stort")
                    out.write(buffer, 0, n)
                }
                String(out.toByteArray(), Charsets.UTF_8)
            }
        } catch (e: IOException) {
            throw MediaJobException(Reason.NETWORK, "Forbindelsen til riggen blev afbrudt")
        }
    }

    companion object {
        const val MAX_BYTES: Long = 64L * 1024
        private val JSON = "application/json; charset=utf-8".toMediaType()
        private val CODE = Regex("^[a-z0-9_]{1,64}$")

        fun defaultHttp(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(15, TimeUnit.SECONDS)
            .callTimeout(30, TimeUnit.SECONDS)
            .followRedirects(false)
            .followSslRedirects(false)
            .build()
    }
}
