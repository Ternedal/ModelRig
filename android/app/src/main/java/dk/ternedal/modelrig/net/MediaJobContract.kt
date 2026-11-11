package dk.ternedal.modelrig.net

import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

/**
 * `kaliv-media-job/v1`: create, follow and cancel one image generation on the
 * paired rig (#2275 A1, contract 6764680246, API owned by ChatGPT).
 *
 * ```
 * GET  /api/v1/media/jobs/profiles       200 {"schema":"kaliv-media-job/v1","profiles":[Profile]}
 * POST /api/v1/media/jobs                202 Job        body {profile_id,prompt,task?,width?,height?,steps?,seed?}
 * GET  /api/v1/media/jobs/{id}           200 Job
 * POST /api/v1/media/jobs/{id}/cancel    200 {"result":…,"job":Job|null}
 * ```
 *
 * Everything here fails closed: a response this parser does not fully
 * understand (another schema, an unknown state, a wrong type) is
 * [MediaJobException.Reason.UNAVAILABLE], never shown as success. A completed
 * job's picture is opened from its `asset_id` through the gallery contract;
 * the server's `asset_url` is only compared, never followed.
 *
 * Image only. A video profile is not offered by this screen, even when the rig
 * lists one (video is default-off on the rig and not part of A1).
 */
enum class MediaJobState(val wire: String, val terminal: Boolean) {
    QUEUED("queued", false),
    RUNNING("running", false),
    PUBLISHING("publishing", false),
    COMPLETED("completed", true),
    FAILED("failed", true),
    CANCELLED("cancelled", true),
    EXPIRED("expired", true),
    ;

    companion object {
        fun fromWire(value: String): MediaJobState? = entries.firstOrNull { it.wire == value }
    }
}

data class MediaJobProfile(
    val profileId: String,
    val tasks: List<String>,
    /** The sizes the rig accepts, in the rig's order; the first is the default. */
    val sizes: List<Pair<Int, Int>>,
    val maxSteps: Int,
    val maxPromptChars: Int,
)

data class MediaJob(
    val id: String,
    val state: MediaJobState,
    val profileId: String?,
    /** Only for [MediaJobState.COMPLETED], and only a safe gallery ID. */
    val assetId: String?,
    /** A code such as `expired_unclaimed`; never free text from the rig. */
    val errorCode: String?,
    val cancelRequested: Boolean,
)

/**
 * What cancel answered. [result] is the rig's code: `cancelled`, `expired`,
 * `requested` (the executor stops at its next check) or `too_late` (the
 * picture is already being saved; the job carries on to `completed`).
 */
data class MediaJobCancel(val result: String, val job: MediaJob?) {
    val tooLate: Boolean get() = result == TOO_LATE

    companion object {
        const val TOO_LATE = "too_late"
    }
}

data class MediaJobRequest(
    val profileId: String,
    val prompt: String,
    val width: Int,
    val height: Int,
    val steps: Int?,
    val seed: Long?,
    val task: String = "text_to_image",
)

class MediaJobException(val reason: Reason, message: String, val code: String? = null) : Exception(message) {
    enum class Reason {
        NOT_PAIRED,
        ORIGIN_REFUSED,
        UNAUTHORIZED,
        /** The route is absent (switch off), 503, or the answer was not understood. */
        UNAVAILABLE,
        /**
         * The rig answered 502, 503 or 504: down or busy for a moment. While a
         * job is followed this is not the end of it (6780346935 #2).
         */
        TRANSIENT,
        INVALID_REQUEST,
        BUSY,
        NOT_FOUND,
        TOO_LARGE,
        NETWORK,
        REDIRECT_REFUSED,
        HTTP,
    }
}

object MediaJobContract {
    const val SCHEMA = "kaliv-media-job/v1"
    const val PROFILES_PATH = "/api/v1/media/jobs/profiles"
    const val JOBS_PATH = "/api/v1/media/jobs"
    const val IMAGE_TASK = "text_to_image"
    const val MAX_SEED: Long = 4_294_967_295L

    private val JOB_ID = Regex("^[0-9a-f]{32}$")
    private val PROFILE_ID = Regex("^[a-z0-9][a-z0-9._-]{0,47}$")
    private val CODE = Regex("^[a-z0-9_]{1,64}$")
    private val TASK = Regex("^[a-z_]{1,32}$")

    fun isJobId(value: String): Boolean = JOB_ID.matches(value)

    fun jobPath(id: String): String {
        require(isJobId(id)) { "job id" }
        return "/api/v1/media/jobs/${seg(id)}"
    }

    // Encoded like every path segment in the app (tests/workflow_client_path_segments.py);
    // for a validated job ID the encoding is the identity.
    private fun seg(value: String): String =
        URLEncoder.encode(value, StandardCharsets.UTF_8.toString()).replace("+", "%20")

    fun cancelPath(id: String): String = jobPath(id) + "/cancel"

    /**
     * The profiles this screen may offer: image profiles that can do text to
     * image. A profile that is malformed is skipped, never guessed.
     */
    fun parseProfiles(json: String): List<MediaJobProfile> {
        val root = parseObject(json)
        if (root.optString("schema") != SCHEMA) throw unavailable("schema")
        val list = root.opt("profiles") as? JSONArray ?: throw unavailable("profiles")
        val out = ArrayList<MediaJobProfile>()
        for (i in 0 until list.length()) {
            val item = list.opt(i) as? JSONObject ?: continue
            profileOrNull(item)?.let(out::add)
        }
        return out.distinctBy { it.profileId }
    }

    private fun profileOrNull(item: JSONObject): MediaJobProfile? {
        val id = item.opt("profile_id") as? String ?: return null
        if (!PROFILE_ID.matches(id) || item.opt("modality") != "image") return null
        val tasks = stringList(item.opt("tasks")) ?: return null
        if (IMAGE_TASK !in tasks || tasks.any { !TASK.matches(it) }) return null
        val rawSizes = item.opt("sizes") as? JSONArray ?: return null
        val sizes = ArrayList<Pair<Int, Int>>()
        for (i in 0 until rawSizes.length()) {
            val pair = rawSizes.opt(i) as? JSONArray ?: return null
            if (pair.length() != 2) return null
            val w = strictInt(pair.opt(0), 64, 4096) ?: return null
            val h = strictInt(pair.opt(1), 64, 4096) ?: return null
            sizes.add(w to h)
        }
        if (sizes.isEmpty()) return null
        val maxSteps = strictInt(item.opt("max_steps"), 1, 200) ?: return null
        val maxPrompt = strictInt(item.opt("max_prompt_chars"), 1, 4000) ?: return null
        return MediaJobProfile(id, tasks, sizes.distinct(), maxSteps, maxPrompt)
    }

    fun parseJob(json: String): MediaJob = jobFrom(parseObject(json))

    /** `{"result": …, "job": Job|null}` from cancel; the result decides what the screen says. */
    fun parseCancel(json: String): MediaJobCancel {
        val root = parseObject(json)
        val result = root.opt("result") as? String ?: throw unavailable("result")
        if (!CODE.matches(result)) throw unavailable("result")
        val job = root.opt("job")
        return MediaJobCancel(result, when {
            job == null || job == JSONObject.NULL -> null
            job is JSONObject -> jobFrom(job)
            else -> throw unavailable("job")
        })
    }

    private fun jobFrom(obj: JSONObject): MediaJob {
        if (obj.has("schema") && obj.opt("schema") != SCHEMA) throw unavailable("schema")
        val id = obj.opt("id") as? String ?: throw unavailable("id")
        if (!isJobId(id)) throw unavailable("id")
        val stateWire = obj.opt("state") as? String ?: throw unavailable("state")
        val state = MediaJobState.fromWire(stateWire) ?: throw unavailable("state")
        val profileId = nullableString(obj, "profile_id")?.also { if (!PROFILE_ID.matches(it)) throw unavailable("profile_id") }
        val errorCode = nullableString(obj, "error")?.also { if (!CODE.matches(it)) throw unavailable("error") }
        val cancel = obj.opt("cancel_requested")
        if (cancel !is Boolean) throw unavailable("cancel_requested")
        val assetId = nullableString(obj, "asset_id")
        val assetUrl = nullableString(obj, "asset_url")
        if (state == MediaJobState.COMPLETED) {
            // A completed job without a safe asset ID is not a success the screen can show.
            if (assetId == null || !MediaGalleryContract.isSafeId(assetId)) throw unavailable("asset_id")
            if (assetUrl != null && assetUrl != MediaGalleryContract.mediaPath(assetId)) throw unavailable("asset_url")
        } else if (assetId != null || assetUrl != null) {
            throw unavailable("asset_id")
        }
        return MediaJob(id, state, profileId, assetId, errorCode, cancel)
    }

    /** The submit body: exactly the keys the worker's strict schema accepts, nothing else. */
    fun submitBody(request: MediaJobRequest, profile: MediaJobProfile): String {
        require(request.profileId == profile.profileId) { "profile" }
        require(request.task == IMAGE_TASK && request.task in profile.tasks) { "task" }
        val prompt = request.prompt.trim()
        require(prompt.isNotEmpty() && prompt.length <= profile.maxPromptChars) { "prompt" }
        require((request.width to request.height) in profile.sizes) { "size" }
        require(request.steps == null || request.steps in 1..profile.maxSteps) { "steps" }
        require(request.seed == null || request.seed in 0..MAX_SEED) { "seed" }
        return JSONObject().apply {
            put("profile_id", request.profileId)
            put("prompt", prompt)
            put("task", request.task)
            put("width", request.width)
            put("height", request.height)
            request.steps?.let { put("steps", it) }
            request.seed?.let { put("seed", it) }
        }.toString()
    }

    private fun parseObject(json: String): JSONObject = try {
        JSONObject(json)
    } catch (e: JSONException) {
        throw unavailable("json")
    }

    private fun nullableString(obj: JSONObject, key: String): String? = when (val v = obj.opt(key)) {
        null, JSONObject.NULL -> null
        is String -> v
        else -> throw unavailable(key)
    }

    private fun stringList(value: Any?): List<String>? {
        val array = value as? JSONArray ?: return null
        return (0 until array.length()).map { array.opt(it) as? String ?: return null }
    }

    private fun strictInt(value: Any?, low: Int, high: Int): Int? =
        (value as? Int)?.takeIf { it in low..high }

    private fun unavailable(what: String) =
        MediaJobException(MediaJobException.Reason.UNAVAILABLE, "Uventet svar fra riggen ($what)")
}
