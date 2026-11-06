package dk.ternedal.modelrig.net

import org.json.JSONException
import org.json.JSONObject
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.time.Instant
import java.time.format.DateTimeParseException

/**
 * `kaliv-media-job/v1`: the owner's read model of one media job.
 *
 * **Read model accepted by ChatGPT (#2275 6693665083); routes not implemented.** The routes are ChatGPT's.
 * This parser is the Android target so the app is ready when they land, the
 * same way [MediaGalleryContract] preceded the gallery routes. See
 * docs/MEDIA_ANDROID_READINESS.md.
 *
 * ```
 * GET /api/v1/media/jobs/{job_id}
 * 200 {"schema":"kaliv-media-job/v1","job":Job}
 * Job = {"id","state","profile_id","created_at","updated_at","expires_at","asset_id","error"}
 * ```
 *
 * The states are exactly the job store's (worker/app/image_job_store.py);
 * tests/workflow_media_job_contract.py fails when the two drift apart.
 * Everything is checked against the store's invariants and fails closed: a job
 * that breaks one is a protocol error, never a guessed status. An unknown
 * state is a protocol error too, so a new terminal state can never be polled
 * forever or shown as success.
 */
enum class MediaJobState(val wire: String, val terminal: Boolean) {
    QUEUED("queued", false),
    RUNNING("running", false),
    PUBLISHING("publishing", false),
    COMPLETED("completed", true),
    FAILED("failed", true),
    CANCELLED("cancelled", true),
    EXPIRED("expired", true),
}

data class MediaJob(
    val id: String,
    val state: MediaJobState,
    val profileId: String,
    val createdAt: Instant,
    val updatedAt: Instant,
    /** When a queued job expires unclaimed (server clock). Non-null exactly when [state] is QUEUED. */
    val expiresAt: Instant?,
    /** The gallery item. Non-null exactly when [state] is COMPLETED. */
    val assetId: String?,
    /**
     * Why it ended. Non-null exactly when [state] is FAILED or EXPIRED. Shown
     * only through MediaJobPresentation, never verbatim.
     */
    val error: String?,
) {
    val assetPath: String? get() = assetId?.let(MediaGalleryContract::mediaPath)
}

object MediaJobContract {
    const val SCHEMA = "kaliv-media-job/v1"

    /** The store's error for a queued job nobody claimed within 24 hours (Anders, 6 Nov 2026). */
    const val EXPIRED_UNCLAIMED = "expired_unclaimed"

    /** uuid4().hex in the store today; the wider gallery alphabet keeps the route free to change it. */
    fun isSafeJobId(value: String): Boolean = MediaGalleryContract.isSafeId(value)

    private val PROFILE_ID = Regex("^[a-z0-9][a-z0-9-]{0,47}$")
    private const val MAX_ERROR_CHARS = 200

    /**
     * Only safe IDs become paths. They are still encoded like every other path
     * segment in the app (tests/workflow_client_path_segments.py); for this
     * alphabet the encoding is the identity.
     */
    fun jobPath(id: String): String {
        require(isSafeJobId(id)) { "unsafe job id" }
        return "/api/v1/media/jobs/${seg(id)}"
    }

    private fun seg(value: String): String =
        URLEncoder.encode(value, StandardCharsets.UTF_8.toString()).replace("+", "%20")

    /** Parse one status response. Throws [MediaJobException] with [MediaJobException.Reason.PROTOCOL]. */
    fun parse(body: String): MediaJob {
        val root = try {
            JSONObject(body)
        } catch (e: JSONException) {
            throw protocol("Jobstatus var ikke gyldig JSON")
        }
        if (root.opt("schema") != SCHEMA) throw protocol("Ukendt jobstatus-format")
        val job = root.opt("job") as? JSONObject ?: throw protocol("Manglende job")
        return parseJob(job)
    }

    fun parseJob(obj: JSONObject): MediaJob {
        val id = (obj.opt("id") as? String)?.takeIf(::isSafeJobId) ?: throw protocol("Ugyldigt job-id")
        val state = MediaJobState.entries.firstOrNull { it.wire == obj.opt("state") }
            ?: throw protocol("Ukendt jobstatus. Opdater appen.")
        val profile = (obj.opt("profile_id") as? String)?.takeIf { PROFILE_ID.matches(it) }
            ?: throw protocol("Ugyldig profil")
        val created = utc(obj, "created_at") ?: throw protocol("Ugyldigt oprettelsestidspunkt")
        val updated = utc(obj, "updated_at") ?: throw protocol("Ugyldigt opdateringstidspunkt")
        if (updated.isBefore(created)) throw protocol("Jobbet blev opdateret før det blev oprettet")
        val expires = nullable(obj, "expires_at") { (it as? String)?.let(::parseUtc) }
        val asset = nullable(obj, "asset_id") { (it as? String)?.takeIf(MediaGalleryContract::isSafeId) }
        val error = nullable(obj, "error") { raw ->
            (raw as? String)?.takeIf { it.isNotBlank() && it.length <= MAX_ERROR_CHARS }
        }
        // The store's invariants, one per field.
        if ((expires.value != null) != (state == MediaJobState.QUEUED)) throw protocol("Udløbstid passer ikke til status")
        if (expires.value != null && !expires.value.isAfter(created)) throw protocol("Udløbstid før oprettelse")
        if ((asset.value != null) != (state == MediaJobState.COMPLETED)) throw protocol("Resultat passer ikke til status")
        val ended = state == MediaJobState.FAILED || state == MediaJobState.EXPIRED
        if ((error.value != null) != ended) throw protocol("Fejl passer ikke til status")
        if (state == MediaJobState.EXPIRED && error.value != EXPIRED_UNCLAIMED) throw protocol("Ukendt udløbsårsag")
        return MediaJob(id, state, profile, created, updated, expires.value, asset.value, error.value)
    }

    /** Absent and JSON null are both "no value"; a present value that [parse] rejects is a protocol error. */
    private class Field<T>(val value: T?)

    private fun <T> nullable(obj: JSONObject, key: String, parse: (Any) -> T?): Field<T> {
        val raw = obj.opt(key)
        if (raw == null || raw === JSONObject.NULL) return Field(null)
        return Field(parse(raw) ?: throw protocol("Ugyldigt felt: $key"))
    }

    private fun utc(obj: JSONObject, key: String): Instant? = (obj.opt(key) as? String)?.let(::parseUtc)

    /** RFC 3339 in UTC only ("…Z"), as in the gallery contract. */
    private fun parseUtc(value: String): Instant? {
        if (!value.endsWith("Z")) return null
        return try {
            Instant.parse(value)
        } catch (e: DateTimeParseException) {
            null
        }
    }

    private fun protocol(message: String) = MediaJobException(MediaJobException.Reason.PROTOCOL, message)
}

/** Messages never contain tokens, paths or the server's error text. */
class MediaJobException(val reason: Reason, message: String) : RuntimeException(message) {
    enum class Reason { PROTOCOL }
}
