package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

/**
 * The desktop side of "pictures and clips in the chat" (#2419): what a tools
 * turn says it queued, and what the rig answers about one job.
 *
 * Ported from the Android client's shapes so both clients read the same wire
 * the same way:
 *
 * - `media_jobs` on a turn result (additive; absent on older rigs) names the
 *   jobs `image_generate` / `video_generate` queued. Only a well-formed
 *   reference counts: a 32-hex job id whose `status_url` is exactly the job
 *   route for that id, and a `kind` that is absent, `image` or `video`.
 *   Anything else is dropped, never guessed at, and never breaks the answer.
 * - `GET /api/v1/media/jobs/{id}` answers `kaliv-media-job/v1`. That parser
 *   fails closed: an answer it does not fully understand is
 *   [DesktopMediaException.Reason.UNAVAILABLE], never shown as success. A
 *   completed job's file is opened from its `asset_id`; the server's
 *   `asset_url` is only compared, never followed.
 */
enum class DesktopMediaKind(val wire: String) {
    IMAGE("image"),
    VIDEO("video"),
    ;

    companion object {
        /** Blank = image (rigs before video_generate); anything else unknown = null. */
        fun parse(raw: String?): DesktopMediaKind? = when (raw?.trim().orEmpty()) {
            "", "image" -> IMAGE
            "video" -> VIDEO
            else -> null
        }
    }
}

data class DesktopMediaJobRef(val jobId: String, val kind: DesktopMediaKind)

/** One media tool call the rig refused (nothing was queued): what was asked for, and the rig's code. */
data class DesktopMediaRefusal(val kind: DesktopMediaKind, val code: String)

enum class DesktopMediaJobState(val wire: String, val terminal: Boolean) {
    QUEUED("queued", false),
    RUNNING("running", false),
    PUBLISHING("publishing", false),
    COMPLETED("completed", true),
    FAILED("failed", true),
    CANCELLED("cancelled", true),
    EXPIRED("expired", true),
    ;

    companion object {
        fun fromWire(value: String): DesktopMediaJobState? = entries.firstOrNull { it.wire == value }
    }
}

data class DesktopMediaJob(
    val id: String,
    val state: DesktopMediaJobState,
    /** Only for [DesktopMediaJobState.COMPLETED], and only a safe media id. */
    val assetId: String?,
    /** A code such as `expired_unclaimed`; never free text from the rig. */
    val errorCode: String?,
    val cancelRequested: Boolean,
)

class DesktopMediaException(
    val reason: Reason,
    message: String,
    val code: String? = null,
) : RuntimeException(message) {
    enum class Reason {
        UNAUTHORIZED,
        /** The route is absent (switch off, older rig), or the answer was not understood. */
        UNAVAILABLE,
        /** 500/502/503/504: down or failing for a moment; a followed job is not over. */
        TRANSIENT,
        NOT_FOUND,
        TOO_LARGE,
        NETWORK,
        REDIRECT_REFUSED,
        /** The body was not what the route promises (wrong type, cut short). */
        PROTOCOL,
        HTTP,
    }
}

object DesktopMediaContract {
    const val SCHEMA = "kaliv-media-job/v1"

    private val JOB_ID = Regex("^[0-9a-f]{32}$")
    private val SAFE_ID = Regex("^[A-Za-z0-9_-]{1,128}$")
    private val CODE = Regex("^[a-z0-9_]{1,64}$")
    private const val VIDEO_PREFIX = "video:"

    fun isJobId(value: String): Boolean = JOB_ID.matches(value)

    fun isSafeAssetId(value: String): Boolean = SAFE_ID.matches(value)

    fun isCode(value: String): Boolean = CODE.matches(value)

    fun jobPath(id: String): String {
        require(isJobId(id)) { "job id" }
        return "/api/v1/media/jobs/${seg(id)}"
    }

    fun mediaPath(id: String): String {
        require(isSafeAssetId(id)) { "unsafe media id" }
        return "/api/v1/media/${seg(id)}"
    }

    // Encoded like every path segment in the clients (tests/workflow_client_path_segments.py);
    // for these validated alphabets the encoding is the identity.
    private fun seg(value: String): String =
        URLEncoder.encode(value, StandardCharsets.UTF_8).replace("+", "%20")

    /** The jobs a turn result names. Tolerant by design: a malformed entry is dropped, the rest stand. */
    fun refs(mediaJobs: JsonElement?): List<DesktopMediaJobRef> {
        val array = mediaJobs as? JsonArray ?: return emptyList()
        return array.mapNotNull { element ->
            val obj = element as? JsonObject ?: return@mapNotNull null
            val id = stringOf(obj["job_id"]) ?: return@mapNotNull null
            if (!isJobId(id)) return@mapNotNull null
            if (stringOf(obj["status_url"]) != jobPath(id)) return@mapNotNull null
            // `kind` is additive (video_generate): absent means an image job; present must be a known word.
            val kind = if (obj.containsKey("kind")) {
                DesktopMediaKind.parse(stringOf(obj["kind"]) ?: return@mapNotNull null) ?: return@mapNotNull null
            } else {
                DesktopMediaKind.IMAGE
            }
            DesktopMediaJobRef(id, kind)
        }.distinctBy { it.jobId }
    }

    /**
     * The media jobs of one user turn across a confirmation card: queued before it and after the
     * decision. Neither list alone is the turn. Order kept, no duplicates.
     */
    fun across(before: List<DesktopMediaJobRef>, after: List<DesktopMediaJobRef>): List<DesktopMediaJobRef> =
        (before + after).distinctBy { it.jobId }

    /**
     * The stored text of a turn that queued media and then stopped on a confirmation card
     * (#2462 review, ChatGPT P2). The job is rendering whatever happens to the card, and a card
     * lives in memory only, so the references are saved the moment they arrive -- with words,
     * because this client sends every stored assistant turn to the model as history.
     */
    const val QUEUED_BEFORE_CARD_TEXT = "Sat i kø på riggen."

    /** At most this many picture ids ride on a turn; the rig keeps the newest of them anyway. */
    const val MAX_CONVERSATION_IMAGE_JOBS = 32

    /**
     * The image jobs a conversation holds, oldest first, for the turn's `conversation_image_jobs`:
     * every picture reference of every message in order, without repeats, the newest
     * [MAX_CONVERSATION_IMAGE_JOBS]. Clips are not pictures and are left out.
     */
    fun conversationImageJobs(messages: List<List<DesktopMediaJobRef>>): List<String> =
        messages.asSequence().flatten()
            .filter { it.kind == DesktopMediaKind.IMAGE }
            .map { it.jobId }
            .toList().asReversed().distinct().asReversed()
            .takeLast(MAX_CONVERSATION_IMAGE_JOBS)

    private val REFUSAL_CODE = Regex("[a-z0-9_]{1,64}")
    private const val MAX_REFUSALS = 8

    /**
     * The media tool calls of a turn that queued nothing (`media_refusals`, additive; absent on
     * older rigs). Only the two media tools with a well-formed code count; the rest is dropped.
     */
    fun refusals(mediaRefusals: JsonElement?): List<DesktopMediaRefusal> {
        val array = mediaRefusals as? JsonArray ?: return emptyList()
        return array.take(MAX_REFUSALS).mapNotNull { element ->
            val obj = element as? JsonObject ?: return@mapNotNull null
            val kind = when (stringOf(obj["tool"])) {
                "image_generate" -> DesktopMediaKind.IMAGE
                "video_generate" -> DesktopMediaKind.VIDEO
                else -> return@mapNotNull null
            }
            val code = stringOf(obj["code"]) ?: return@mapNotNull null
            if (!REFUSAL_CODE.matches(code)) return@mapNotNull null
            DesktopMediaRefusal(kind, code)
        }
    }

    /**
     * The line under an answer when the rig refused a picture or a clip. Rig 20/11: the refusal
     * reached the user only in the model's words ("der er tekniske problemer"). This says why
     * and what to do, from the rig's own code, and keeps the code visible. Null when nothing
     * was refused, or when the turn queued a job after all -- then the bubble is the answer.
     */
    fun refusalNotice(refusals: List<DesktopMediaRefusal>, queuedJobs: Int): String? {
        if (queuedJobs > 0) return null
        val last = refusals.lastOrNull() ?: return null
        val what = if (last.kind == DesktopMediaKind.VIDEO) "videoen" else "billedet"
        val sentence = when (last.code) {
            "owner_limit", "queue_full" ->
                "Riggen er optaget med andre job. Bed om $what igen, når et af dem er færdigt."
            "invalid_arguments", "invalid_request", "profile_not_enabled", "source_not_understood" ->
                "Riggen kunne ikke bruge det, modellen bad om. Prøv at bede om $what igen."
            "no_source_image", "source_job_not_found", "source_job_not_completed", "source_not_found",
            "source_not_an_image", "source_profile_not_enabled" ->
                "Der er ikke et færdigt billede at lave video af endnu."
            else -> "Riggen lavede ikke $what."
        }
        return "$sentence (${last.code})"
    }

    /**
     * One job as the rig describes it. [expectedId] is the job that was asked
     * about: an answer about another job is not ours and is refused.
     */
    fun parseJob(body: String, expectedId: String): DesktopMediaJob {
        val parsed: JsonObject? = try {
            Json.parseToJsonElement(body) as? JsonObject
        } catch (e: Exception) {
            null
        }
        val obj = parsed ?: throw unavailable("json")
        if (obj.containsKey("schema") && stringOf(obj["schema"]) != SCHEMA) throw unavailable("schema")
        val id = stringOf(obj["id"]) ?: throw unavailable("id")
        if (!isJobId(id) || id != expectedId) throw unavailable("id")
        val state = stringOf(obj["state"])?.let(DesktopMediaJobState::fromWire) ?: throw unavailable("state")
        val errorCode = nullableString(obj, "error")?.also { if (!isCode(it)) throw unavailable("error") }
        val cancel = (obj["cancel_requested"] as? JsonPrimitive)?.takeIf { !it.isString }?.booleanOrNull
            ?: throw unavailable("cancel_requested")
        val assetId = nullableString(obj, "asset_id")
        val assetUrl = nullableString(obj, "asset_url")
        if (state == DesktopMediaJobState.COMPLETED) {
            // A completed job without a safe asset id is not a success the bubble can show.
            if (assetId == null || !isSafeAssetId(assetId)) throw unavailable("asset_id")
            if (assetUrl != null && assetUrl != mediaPath(assetId)) throw unavailable("asset_url")
        } else if (assetId != null || assetUrl != null) {
            throw unavailable("asset_id")
        }
        return DesktopMediaJob(id, state, assetId, errorCode, cancel)
    }

    /** A code the rig sent with an error status (`{"detail": "job_not_found"}`), only when it is a plain code. */
    fun errorCode(body: String): String? = try {
        stringOf((Json.parseToJsonElement(body) as? JsonObject)?.get("detail"))?.takeIf(::isCode)
    } catch (e: Exception) {
        null
    }

    /**
     * How a message's jobs are stored with it (same text form as Android's
     * `message.media_jobs`): comma-separated, an image job as its bare id, a
     * video job as `video:<id>`. Only well-formed entries are written or read.
     */
    fun encodeRefs(refs: List<DesktopMediaJobRef>): String = refs
        .filter { isJobId(it.jobId) }
        .distinctBy { it.jobId }
        .joinToString(",") { if (it.kind == DesktopMediaKind.VIDEO) VIDEO_PREFIX + it.jobId else it.jobId }

    fun decodeRefs(stored: String?): List<DesktopMediaJobRef> = stored.orEmpty().split(',')
        .mapNotNull { entry ->
            val video = entry.startsWith(VIDEO_PREFIX)
            val id = if (video) entry.removePrefix(VIDEO_PREFIX) else entry
            if (isJobId(id)) DesktopMediaJobRef(id, if (video) DesktopMediaKind.VIDEO else DesktopMediaKind.IMAGE) else null
        }
        .distinctBy { it.jobId }

    private fun stringOf(element: JsonElement?): String? =
        (element as? JsonPrimitive)?.takeIf { it.isString }?.content

    private fun nullableString(obj: JsonObject, key: String): String? {
        val value = obj[key]
        if (value == null || value is JsonNull) return null
        return stringOf(value) ?: throw unavailable(key)
    }

    private fun unavailable(what: String) =
        DesktopMediaException(DesktopMediaException.Reason.UNAVAILABLE, "Uventet svar fra riggen ($what)")
}
