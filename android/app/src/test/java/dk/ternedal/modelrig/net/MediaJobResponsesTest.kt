package dk.ternedal.modelrig.net

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

/** Cancel, list, refusals and the capability probe of `kaliv-media-job/v1` (design targets). */
class MediaJobResponsesTest {

    private fun job(id: String, state: String) = JSONObject()
        .put("id", id).put("state", state).put("profile_id", "sdxl-base")
        .put("created_at", "2026-11-06T10:00:00Z").put("updated_at", "2026-11-06T10:00:00Z")
        .put("expires_at", if (state == "queued") "2026-11-07T10:00:00Z" else JSONObject.NULL)
        .put("asset_id", if (state == "completed") "img_1" else JSONObject.NULL)
        .put("error", if (state == "failed") "gpu_busy" else JSONObject.NULL)

    private fun cancel(outcome: String, state: String) = JSONObject()
        .put("schema", MediaJobContract.SCHEMA).put("outcome", outcome).put("job", job("j1", state)).toString()

    private fun page(jobs: List<Any>, cursor: Any? = JSONObject.NULL) = JSONObject()
        .put("schema", MediaJobContract.SCHEMA).put("jobs", JSONArray(jobs)).put("next_cursor", cursor).toString()

    @Test
    fun `cancel outcome must agree with the job`() {
        assertEquals(MediaCancelOutcome.CANCELLED, MediaJobContract.parseCancel(cancel("cancelled", "cancelled")).outcome)
        assertEquals(MediaCancelOutcome.REQUESTED, MediaJobContract.parseCancel(cancel("requested", "running")).outcome)
        assertEquals(MediaCancelOutcome.REQUESTED, MediaJobContract.parseCancel(cancel("requested", "cancelled")).outcome)
        assertEquals(MediaCancelOutcome.TOO_LATE, MediaJobContract.parseCancel(cancel("too_late", "publishing")).outcome)
        assertEquals(MediaCancelOutcome.TOO_LATE, MediaJobContract.parseCancel(cancel("too_late", "completed")).outcome)
        for ((outcome, state) in listOf("cancelled" to "running", "requested" to "queued", "too_late" to "running",
                                        "too_late" to "queued", "stopped" to "cancelled")) {
            assertThrows("$outcome/$state", MediaJobException::class.java) {
                MediaJobContract.parseCancel(cancel(outcome, state))
            }
        }
    }

    @Test
    fun `a broken job is skipped and counted, never the page`() {
        val p = MediaJobContract.parsePage(page(listOf(job("a", "running"), job("b", "archived"), JSONObject().put("id", 1),
                                                      job("a", "queued"), "x"), cursor = "c2"))
        assertEquals(listOf("a"), p.jobs.map { it.id })
        assertEquals(4, p.skipped)
        assertEquals("c2", p.nextCursor)
        assertNull(MediaJobContract.parsePage(page(emptyList())).nextCursor)
    }

    @Test
    fun `page-level damage rejects the page`() {
        val bad = listOf(
            JSONObject().put("schema", MediaJobContract.SCHEMA).put("next_cursor", JSONObject.NULL).toString(),
            JSONObject().put("schema", MediaJobContract.SCHEMA).put("jobs", JSONArray()).toString(),
            page(emptyList(), cursor = ""),
            page(emptyList(), cursor = 7),
            page(List(MediaJobContract.MAX_PAGE + 1) { job("j$it", "running") }),
            page(emptyList()).replace(MediaJobContract.SCHEMA, "kaliv-media-job/v2"),
        )
        for (body in bad) assertThrows(body, MediaJobException::class.java) { MediaJobContract.parsePage(body) }
    }

    @Test
    fun `refusals map their codes and never throw`() {
        fun err(code: Any?) = JSONObject().put("schema", MediaJobContract.SCHEMA).put("error", code ?: JSONObject.NULL).toString()
        assertEquals(MediaJobRefusal.QUEUE_FULL, MediaJobContract.refusal(err("queue_full")))
        assertEquals(MediaJobRefusal.OWNER_ACTIVE_LIMIT, MediaJobContract.refusal(err("owner_active_limit")))
        assertEquals(MediaJobRefusal.UNKNOWN, MediaJobContract.refusal(err("rate_limited")))
        assertEquals(MediaJobRefusal.UNKNOWN, MediaJobContract.refusal(err(429)))
        assertEquals(MediaJobRefusal.UNKNOWN, MediaJobContract.refusal("<html>502</html>"))
        assertEquals(MediaJobRefusal.UNKNOWN, MediaJobContract.refusal(null))
        assertEquals(MediaJobRefusal.UNKNOWN, MediaJobContract.refusal("""{"error":"queue_full"}"""))
    }

    @Test
    fun `capabilities fail closed`() {
        fun caps(vararg pairs: Pair<String, Any>) =
            MediaCapabilities.parse(JSONObject().put("schema", MediaCapabilities.SCHEMA).apply { pairs.forEach { put(it.first, it.second) } }.toString())
        assertEquals(MediaCapabilities(true, true, true),
            caps("text_to_image" to true, "text_to_video" to true, "image_to_video" to true))
        assertEquals(MediaCapabilities.NONE, caps())
        assertEquals(MediaCapabilities.NONE, caps("text_to_image" to "true", "text_to_video" to 1, "image_to_video" to JSONObject()))
        assertEquals(MediaCapabilities(false, true, false), caps("text_to_video" to true, "text_to_image" to false))
        assertEquals(MediaCapabilities.NONE, MediaCapabilities.parse("""{"text_to_image":true}"""))
        assertEquals(MediaCapabilities.NONE, MediaCapabilities.parse("not json"))
        assertEquals(MediaCapabilities.NONE, MediaCapabilities.parse(null))
        assertFalse(MediaCapabilities.NONE.any)
    }
}
