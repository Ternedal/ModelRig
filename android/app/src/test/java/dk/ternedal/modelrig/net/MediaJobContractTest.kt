package dk.ternedal.modelrig.net

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

/** `kaliv-media-job/v1`, PROPOSED on ModelRig #2275 (not agreed; routes are ChatGPT's). */
class MediaJobContractTest {

    private val created = "2026-11-06T10:00:00Z"

    private fun job(
        state: String,
        assetId: Any? = null,
        error: Any? = null,
        expiresAt: Any? = if (state == "queued") "2026-11-07T10:00:00Z" else null,
        updatedAt: String = "2026-11-06T10:05:00Z",
        id: Any = "0123456789abcdef0123456789abcdef",
        profile: Any = "wan-t2v-480p",
    ): JSONObject = JSONObject()
        .put("id", id)
        .put("state", state)
        .put("profile_id", profile)
        .put("created_at", created)
        .put("updated_at", updatedAt)
        .put("expires_at", expiresAt ?: JSONObject.NULL)
        .put("asset_id", assetId ?: JSONObject.NULL)
        .put("error", error ?: JSONObject.NULL)

    private fun body(job: JSONObject, schema: String = MediaJobContract.SCHEMA) =
        JSONObject().put("schema", schema).put("job", job).toString()

    private fun refused(job: JSONObject) {
        val e = assertThrows(MediaJobException::class.java) { MediaJobContract.parse(body(job)) }
        assertEquals(MediaJobException.Reason.PROTOCOL, e.reason)
    }

    @Test
    fun `every store state parses with its invariants`() {
        val queued = MediaJobContract.parse(body(job("queued")))
        assertEquals(MediaJobState.QUEUED, queued.state)
        assertEquals(Instant.parse("2026-11-07T10:00:00Z"), queued.expiresAt)
        assertEquals(Instant.parse(created), queued.createdAt)
        assertEquals("wan-t2v-480p", queued.profileId)
        for (s in listOf("running", "publishing", "cancelled")) {
            val j = MediaJobContract.parse(body(job(s)))
            assertNull(j.assetId)
            assertNull(j.error)
            assertNull(j.expiresAt)
        }
        val done = MediaJobContract.parse(body(job("completed", assetId = "vid_42")))
        assertEquals("vid_42", done.assetId)
        assertEquals("/api/v1/media/vid_42", done.assetPath)
        assertEquals("generation_failed", MediaJobContract.parse(body(job("failed", error = "generation_failed"))).error)
        val expired = MediaJobContract.parse(body(job("expired", error = "expired_unclaimed")))
        assertEquals(MediaJobState.EXPIRED, expired.state)
        assertTrue(expired.state.terminal)
    }

    @Test
    fun `the store's restart sentences are accepted as errors`() {
        val j = MediaJobContract.parse(body(job("failed", error = "interrupted by restart")))
        assertEquals("interrupted by restart", j.error)
    }

    @Test
    fun `terminal states are exactly the store's finished states`() {
        assertEquals(
            setOf("completed", "failed", "cancelled", "expired"),
            MediaJobState.entries.filter { it.terminal }.map { it.wire }.toSet(),
        )
        assertFalse(MediaJobState.PUBLISHING.terminal)
    }

    @Test
    fun `unknown state is a protocol error, never polled forever`() = refused(job("archived"))

    @Test
    fun `wrong schema, missing job or bad json is refused`() {
        assertThrows(MediaJobException::class.java) { MediaJobContract.parse(body(job("running"), schema = "kaliv-media-job/v2")) }
        assertThrows(MediaJobException::class.java) { MediaJobContract.parse("""{"schema":"kaliv-media-job/v1"}""") }
        assertThrows(MediaJobException::class.java) { MediaJobContract.parse("not json") }
    }

    @Test
    fun `completed needs an asset and only completed may have one`() {
        refused(job("completed"))
        refused(job("completed", assetId = "../x"))
        refused(job("running", assetId = "vid_1"))
        refused(job("failed", assetId = "vid_1", error = "generation_failed"))
    }

    @Test
    fun `failed and expired need an error and only they may have one`() {
        refused(job("failed"))
        refused(job("failed", error = ""))
        refused(job("failed", error = "x".repeat(201)))
        refused(job("failed", error = 7))
        refused(job("expired"))
        refused(job("expired", error = "generation_failed"))
        refused(job("cancelled", error = "generation_failed"))
        refused(job("completed", assetId = "vid_1", error = "generation_failed"))
    }

    @Test
    fun `expires_at belongs to queued jobs only and lies after creation`() {
        refused(job("queued", expiresAt = null))
        refused(job("queued", expiresAt = created))
        refused(job("queued", expiresAt = "2026-11-07T11:00:00+01:00"))
        refused(job("running", expiresAt = "2026-11-07T10:00:00Z"))
    }

    @Test
    fun `ids, profile and timestamps are checked`() {
        refused(job("running", id = "a/b"))
        refused(job("running", id = 12))
        refused(job("running", profile = "Wan T2V"))
        refused(job("running", updatedAt = "2026-11-06T09:59:59Z"))
        refused(job("running", updatedAt = "2026-11-06T10:05:00+00:00"))
    }

    @Test
    fun `job path only from a safe id`() {
        assertEquals("/api/v1/media/jobs/abc_1", MediaJobContract.jobPath("abc_1"))
        assertThrows(IllegalArgumentException::class.java) { MediaJobContract.jobPath("../etc") }
    }

    @Test
    fun `unknown fields are ignored`() {
        val j = job("running").put("claimed_by", "GPU-1:abc").put("progress", 0.5)
        assertEquals(MediaJobState.RUNNING, MediaJobContract.parse(body(j)).state)
    }
}
