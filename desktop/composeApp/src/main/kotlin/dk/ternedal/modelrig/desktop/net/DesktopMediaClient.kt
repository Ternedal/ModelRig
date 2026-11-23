package dk.ternedal.modelrig.desktop.net

import dk.ternedal.modelrig.desktop.net.DesktopMediaException.Reason
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

/** What the chat's media bubbles need from the rig; the production implementation is [DesktopMediaClient]. */
interface DesktopMediaSource {
    /** `GET /api/v1/media/jobs/{id}`: where one job stands. */
    fun status(jobId: String): DesktopMediaJob

    /** A completed image job's picture, whole and bounded. */
    fun image(assetId: String): ByteArray

    /** A completed video job's clip, streamed once into [out]; returns the bytes written. */
    fun videoInto(assetId: String, out: OutputStream): Long
}

/**
 * Reads media jobs and their results from the rig the desktop is set up for
 * (the same base URL and device token as the tools turn that queued the job).
 *
 * - Never follows a redirect: the bearer token goes to the configured rig and
 *   nowhere else.
 * - Every body is bounded while it is read: a status answer to 64 KiB, a
 *   picture to 25 MiB, a clip to 256 MiB. A body that claims more, or runs
 *   past its own Content-Length, is refused.
 * - A picture must be an image type and a clip a video type; anything else is
 *   a protocol error, never handed to the decoder or written to the user's disk
 *   as if it were the result.
 * - Nothing is cached and nothing is written by this class: the clip goes
 *   straight into the stream the caller owns.
 */
class DesktopMediaClient(baseUrl: String, private val bearer: String?) : DesktopMediaSource {
    private val base: String = baseUrl.trim().trimEnd('/').also { value ->
        val scheme = runCatching { URI.create(value).scheme }.getOrNull()?.lowercase()
        if (scheme != "http" && scheme != "https") {
            throw DesktopMediaException(Reason.UNAVAILABLE, "Rig-adressen er ikke sat op")
        }
    }

    private val http: HttpClient = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(10))
        .followRedirects(HttpClient.Redirect.NEVER)
        .build()

    override fun status(jobId: String): DesktopMediaJob {
        if (!DesktopMediaContract.isJobId(jobId)) throw DesktopMediaException(Reason.NOT_FOUND, "Ugyldigt job-id")
        val response = send(get(DesktopMediaContract.jobPath(jobId), "application/json", STATUS_TIMEOUT))
        response.body().use { stream ->
            val status = response.statusCode()
            if (status in 300..399) throw redirect()
            val text = String(
                readBounded(stream, declaredLength(response), STATUS_MAX_BYTES) {
                    DesktopMediaException(Reason.UNAVAILABLE, "Svaret fra riggen er for stort")
                },
                Charsets.UTF_8,
            )
            if (status == 200) {
                if (contentType(response) != "application/json") {
                    throw DesktopMediaException(Reason.UNAVAILABLE, "Uventet svar fra riggen")
                }
                return DesktopMediaContract.parseJob(text, jobId)
            }
            val code = DesktopMediaContract.errorCode(text)
            throw when (status) {
                401, 403 -> DesktopMediaException(Reason.UNAUTHORIZED, "Parringen med riggen er ikke længere gyldig")
                404 -> if (code != null && code.startsWith("job_not_found")) {
                    DesktopMediaException(Reason.NOT_FOUND, "Jobbet findes ikke længere på riggen", code)
                } else {
                    // The route is absent: the switch is off on this rig. Never a guess at success.
                    DesktopMediaException(Reason.UNAVAILABLE, "Billedgenerering er ikke tilgængelig på denne rig")
                }
                405, 501 -> DesktopMediaException(Reason.UNAVAILABLE, "Billedgenerering er ikke tilgængelig på denne rig")
                // Down or failing for a moment; the job may well be fine on the rig, so the caller decides.
                500, 502, 503, 504 -> DesktopMediaException(Reason.TRANSIENT, "Riggen svarer ikke lige nu", code)
                else -> DesktopMediaException(Reason.HTTP, "Riggen svarede $status")
            }
        }
    }

    override fun image(assetId: String): ByteArray {
        if (!DesktopMediaContract.isSafeAssetId(assetId)) throw DesktopMediaException(Reason.NOT_FOUND, "Ugyldigt billed-id")
        val response = send(get(DesktopMediaContract.mediaPath(assetId), "image/png, image/jpeg, image/webp", ASSET_TIMEOUT))
        response.body().use { stream ->
            checkAssetStatus(response.statusCode())
            requireType(response, "image/")
            return readBounded(stream, declaredLength(response), IMAGE_MAX_BYTES, ::tooLarge)
        }
    }

    override fun videoInto(assetId: String, out: OutputStream): Long {
        if (!DesktopMediaContract.isSafeAssetId(assetId)) throw DesktopMediaException(Reason.NOT_FOUND, "Ugyldigt video-id")
        val response = send(get(DesktopMediaContract.mediaPath(assetId), "video/mp4", CLIP_TIMEOUT))
        response.body().use { stream ->
            checkAssetStatus(response.statusCode())
            requireType(response, "video/")
            val declared = declaredLength(response)
            if (declared > VIDEO_MAX_BYTES) throw tooLarge()
            // A failure to write is the caller's stream (their disk) and reaches them as IOException.
            val total = copyBounded(stream, out, VIDEO_MAX_BYTES, ::tooLarge)
            if (declared >= 0 && total != declared) {
                throw DesktopMediaException(Reason.PROTOCOL, "Ufuldstændigt mediesvar")
            }
            return total
        }
    }

    private fun get(path: String, accept: String, timeout: Duration): HttpRequest {
        val builder = HttpRequest.newBuilder(URI.create(base + path))
            .header("Accept", accept)
            .header("Cache-Control", "no-store")
            .timeout(timeout)
            .GET()
        if (!bearer.isNullOrBlank()) builder.header("Authorization", "Bearer $bearer")
        return builder.build()
    }

    private fun send(request: HttpRequest): HttpResponse<InputStream> = try {
        http.send(request, HttpResponse.BodyHandlers.ofInputStream())
    } catch (e: IOException) {
        throw DesktopMediaException(Reason.NETWORK, "Riggen kan ikke nås")
    } catch (e: InterruptedException) {
        Thread.currentThread().interrupt()
        throw DesktopMediaException(Reason.NETWORK, "Forespørgslen blev afbrudt")
    }

    private fun checkAssetStatus(status: Int) {
        if (status in 300..399) throw redirect()
        when (status) {
            200 -> Unit
            401, 403 -> throw DesktopMediaException(Reason.UNAUTHORIZED, "Parringen med riggen er ikke længere gyldig")
            404 -> throw DesktopMediaException(Reason.NOT_FOUND, "Mediet findes ikke på riggen")
            500, 502, 503, 504 -> throw DesktopMediaException(Reason.TRANSIENT, "Medielageret på riggen er ikke tilgængeligt lige nu")
            else -> throw DesktopMediaException(Reason.HTTP, "Riggen svarede $status")
        }
    }

    private fun requireType(response: HttpResponse<*>, prefix: String) {
        if (!contentType(response).startsWith(prefix)) {
            throw DesktopMediaException(Reason.PROTOCOL, "Uventet medietype fra riggen")
        }
    }

    private fun contentType(response: HttpResponse<*>): String =
        response.headers().firstValue("Content-Type").orElse("").substringBefore(';').trim().lowercase()

    /** The Content-Length the rig declared, or -1 when it declared none (or something unreadable). */
    private fun declaredLength(response: HttpResponse<*>): Long =
        response.headers().firstValue("Content-Length").orElse("").trim().toLongOrNull()?.takeIf { it >= 0 } ?: -1L

    private fun readBounded(
        stream: InputStream,
        declared: Long,
        maxBytes: Long,
        onTooLarge: () -> DesktopMediaException,
    ): ByteArray {
        if (declared > maxBytes) throw onTooLarge()
        val out = ByteArrayOutputStream(if (declared in 1..maxBytes) declared.toInt() else 8192)
        val total = copyBounded(stream, out, maxBytes, onTooLarge)
        if (declared >= 0 && total != declared) {
            throw DesktopMediaException(Reason.PROTOCOL, "Ufuldstændigt svar fra riggen")
        }
        return out.toByteArray()
    }

    /** Reading failing is the rig's side (NETWORK); writing failing is [out]'s and propagates as it is. */
    private fun copyBounded(
        stream: InputStream,
        out: OutputStream,
        maxBytes: Long,
        onTooLarge: () -> DesktopMediaException,
    ): Long {
        val buffer = ByteArray(64 * 1024)
        var total = 0L
        while (true) {
            val n = try {
                stream.read(buffer)
            } catch (e: IOException) {
                throw DesktopMediaException(Reason.NETWORK, "Forbindelsen til riggen blev afbrudt")
            }
            if (n < 0) break
            total += n
            if (total > maxBytes) throw onTooLarge()
            out.write(buffer, 0, n)
        }
        out.flush()
        return total
    }

    private fun tooLarge() = DesktopMediaException(Reason.TOO_LARGE, "For stort til at blive hentet")

    private fun redirect() = DesktopMediaException(Reason.REDIRECT_REFUSED, "Riggen forsøgte at viderestille; afvist")

    companion object {
        /** Client safety caps, not server guarantees. */
        const val STATUS_MAX_BYTES: Long = 64L * 1024
        const val IMAGE_MAX_BYTES: Long = 25L * 1024 * 1024
        const val VIDEO_MAX_BYTES: Long = 256L * 1024 * 1024

        private val STATUS_TIMEOUT: Duration = Duration.ofSeconds(30)
        private val ASSET_TIMEOUT: Duration = Duration.ofMinutes(2)
        private val CLIP_TIMEOUT: Duration = Duration.ofMinutes(10)
    }
}
