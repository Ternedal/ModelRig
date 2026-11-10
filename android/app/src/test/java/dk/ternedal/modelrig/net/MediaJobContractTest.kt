package dk.ternedal.modelrig.net

import dk.ternedal.modelrig.net.MediaJobException.Reason
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

/** `kaliv-media-job/v1` parsing and the submit body; fail closed on anything not understood. */
class MediaJobContractTest {
    companion object {
        const val JOB_ID = "0123456789abcdef0123456789abcdef"

        fun job(
            state: String = "queued",
            assetId: String? = null,
            assetUrl: String? = assetId?.let { "/api/v1/media/$it" },
            error: String? = null,
            cancelRequested: Boolean = false,
            id: String = JOB_ID,
            extra: Map<String, Any?> = emptyMap(),
        ): String = JSONObject().apply {
            put("id", id)
            put("state", state)
            put("profile_id", "sdxl-a")
            put("asset_id", assetId ?: JSONObject.NULL)
            put("asset_url", assetUrl ?: JSONObject.NULL)
            put("error", error ?: JSONObject.NULL)
            put("cancel_requested", cancelRequested)
            put("created", 1.0)
            put("updated", 2.0)
            extra.forEach { (k, v) -> put(k, v ?: JSONObject.NULL) }
        }.toString()

        fun profile(
            id: String = "sdxl-a",
            modality: String = "image",
            tasks: List<String> = listOf("text_to_image"),
            sizes: List<List<Int>> = listOf(listOf(1024, 1024), listOf(832, 1216)),
            maxSteps: Int = 40,
            maxPrompt: Int = 500,
        ): JSONObject = JSONObject().apply {
            put("profile_id", id)
            put("modality", modality)
            put("tasks", JSONArray(tasks))
            put("sizes", JSONArray(sizes.map { JSONArray(it) }))
            put("max_steps", maxSteps)
            put("max_prompt_chars", maxPrompt)
        }

        fun profiles(vararg items: JSONObject, schema: String = MediaJobContract.SCHEMA): String =
            JSONObject().put("schema", schema).put("profiles", JSONArray(items.toList())).toString()

        val SDXL = MediaJobProfile("sdxl-a", listOf("text_to_image"), listOf(1024 to 1024, 832 to 1216), 40, 500)
    }

    private fun unavailable(block: () -> Unit) {
        val e = assertThrows(MediaJobException::class.java) { block() }
        assertEquals(Reason.UNAVAILABLE, e.reason)
    }

    @Test
    fun `a queued job parses`() {
        val parsed = MediaJobContract.parseJob(job())
        assertEquals(JOB_ID, parsed.id)
        assertEquals(MediaJobState.QUEUED, parsed.state)
        assertNull(parsed.assetId)
        assertFalse(parsed.state.terminal)
    }

    @Test
    fun `a completed job needs a safe asset id, and asset_url only has to agree with it`() {
        val done = MediaJobContract.parseJob(job(state = "completed", assetId = "asset_0123456789abcdef"))
        assertEquals("asset_0123456789abcdef", done.assetId)
        assertTrue(done.state.terminal)
        assertEquals("asset_0123456789abcdef",
            MediaJobContract.parseJob(job(state = "completed", assetId = "asset_0123456789abcdef", assetUrl = null)).assetId)
        unavailable { MediaJobContract.parseJob(job(state = "completed")) }
        unavailable { MediaJobContract.parseJob(job(state = "completed", assetId = "../etc/passwd")) }
        unavailable { MediaJobContract.parseJob(job(state = "completed", assetId = "a b")) }
        unavailable {
            MediaJobContract.parseJob(job(state = "completed", assetId = "asset_1", assetUrl = "https://elsewhere.example/x"))
        }
        unavailable { MediaJobContract.parseJob(job(state = "completed", assetId = "asset_1", assetUrl = "/api/v1/media/asset_2")) }
    }

    @Test
    fun `an asset on a job that is not completed is refused`() {
        unavailable { MediaJobContract.parseJob(job(state = "running", assetId = "asset_1")) }
        unavailable { MediaJobContract.parseJob(job(state = "failed", assetId = null, assetUrl = "/api/v1/media/x")) }
    }

    @Test
    fun `every state the rig has today is known and anything else is unavailable`() {
        for (state in listOf("queued", "running", "publishing", "completed", "failed", "cancelled", "expired")) {
            val asset = if (state == "completed") "asset_1" else null
            assertEquals(state, MediaJobContract.parseJob(job(state = state, assetId = asset)).state.wire)
        }
        for (state in listOf("done", "COMPLETED", "", "success")) {
            unavailable { MediaJobContract.parseJob(job(state = state)) }
        }
    }

    @Test
    fun `a wrong type or a foreign schema is unavailable, never a guess`() {
        unavailable { MediaJobContract.parseJob("not json") }
        unavailable { MediaJobContract.parseJob(job(id = "ABCDEF")) }
        unavailable { MediaJobContract.parseJob(job(id = "../" + JOB_ID.drop(3))) }
        unavailable { MediaJobContract.parseJob(job(extra = mapOf("cancel_requested" to "false"))) }
        unavailable { MediaJobContract.parseJob(job(extra = mapOf("schema" to "kaliv-media-job/v2"))) }
        unavailable { MediaJobContract.parseJob(job(error = "Something went wrong: /secret/path")) }
        assertEquals(MediaJobState.QUEUED,
            MediaJobContract.parseJob(job(extra = mapOf("schema" to MediaJobContract.SCHEMA))).state)
    }

    @Test
    fun `error codes come through as codes`() {
        val failed = MediaJobContract.parseJob(job(state = "failed", error = "interrupted_by_restart"))
        assertEquals("interrupted_by_restart", failed.errorCode)
    }

    @Test
    fun `cancel returns its job or none`() {
        val body = JSONObject().put("result", "cancelled").put("job", JSONObject(job(state = "cancelled"))).toString()
        assertEquals(MediaJobState.CANCELLED, MediaJobContract.parseCancel(body)!!.state)
        assertNull(MediaJobContract.parseCancel(JSONObject().put("result", "cancel_requested").put("job", JSONObject.NULL).toString()))
        unavailable { MediaJobContract.parseCancel(JSONObject().put("job", JSONObject(job())).toString()) }
        unavailable { MediaJobContract.parseCancel(JSONObject().put("result", "ok").put("job", "x").toString()) }
    }

    @Test
    fun `only image profiles that do text to image are offered, malformed ones skipped`() {
        val list = MediaJobContract.parseProfiles(profiles(
            profile(),
            profile(id = "wan-t2v", modality = "video", tasks = listOf("text_to_video")),
            profile(id = "video-claims-image", modality = "video"),
            profile(id = "i2i-only", tasks = listOf("image_to_image")),
            profile(id = "Bad Id"),
            profile(id = "no-sizes", sizes = emptyList()),
            profile(id = "odd-size", sizes = listOf(listOf(1024))),
            profile(id = "huge", sizes = listOf(listOf(100_000, 1024))),
            profile(id = "sdxl-b", maxSteps = 0),
            profile(),
        ))
        assertEquals(listOf("sdxl-a"), list.map { it.profileId })
        assertEquals(listOf(1024 to 1024, 832 to 1216), list.single().sizes)
    }

    @Test
    fun `a profile list with another schema or shape is unavailable`() {
        unavailable { MediaJobContract.parseProfiles(profiles(profile(), schema = "kaliv-media-job/v2")) }
        unavailable { MediaJobContract.parseProfiles("""{"schema":"kaliv-media-job/v1"}""") }
        unavailable { MediaJobContract.parseProfiles("[]") }
        assertTrue(MediaJobContract.parseProfiles(profiles()).isEmpty())
    }

    @Test
    fun `the submit body has exactly the worker's keys and a trimmed prompt`() {
        val body = JSONObject(MediaJobContract.submitBody(
            MediaJobRequest("sdxl-a", "  a red bicycle  ", 832, 1216, steps = null, seed = null), SDXL))
        assertEquals(setOf("profile_id", "prompt", "task", "width", "height"), body.keys().asSequence().toSet())
        assertEquals("a red bicycle", body.getString("prompt"))
        assertEquals("text_to_image", body.getString("task"))
        val withSteps = JSONObject(MediaJobContract.submitBody(
            MediaJobRequest("sdxl-a", "x", 1024, 1024, steps = 20, seed = 7L), SDXL))
        assertEquals(20, withSteps.getInt("steps"))
        assertEquals(7L, withSteps.getLong("seed"))
        assertFalse(withSteps.has("owner"))
    }

    @Test
    fun `a request the profile does not allow is refused before anything is sent`() {
        val bad = listOf(
            MediaJobRequest("other", "x", 1024, 1024, null, null),
            MediaJobRequest("sdxl-a", "   ", 1024, 1024, null, null),
            MediaJobRequest("sdxl-a", "x".repeat(501), 1024, 1024, null, null),
            MediaJobRequest("sdxl-a", "x", 1000, 1000, null, null),
            MediaJobRequest("sdxl-a", "x", 1024, 1024, 41, null),
            MediaJobRequest("sdxl-a", "x", 1024, 1024, null, -1),
            MediaJobRequest("sdxl-a", "x", 1024, 1024, null, null, task = "image_to_image"),
        )
        for (request in bad) {
            assertThrows(IllegalArgumentException::class.java) { MediaJobContract.submitBody(request, SDXL) }
        }
    }

    @Test
    fun `job paths come only from a valid id`() {
        assertEquals("/api/v1/media/jobs/$JOB_ID", MediaJobContract.jobPath(JOB_ID))
        assertEquals("/api/v1/media/jobs/$JOB_ID/cancel", MediaJobContract.cancelPath(JOB_ID))
        for (bad in listOf("../../healthz", JOB_ID.uppercase(), JOB_ID + "0", "")) {
            assertThrows(IllegalArgumentException::class.java) { MediaJobContract.jobPath(bad) }
        }
    }
}
