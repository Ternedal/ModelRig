package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * #2419 on the desktop: which job references a turn result is believed about,
 * and which job answers are understood. The reference parser is tolerant (a bad
 * entry is dropped, the answer stands); the job parser fails closed.
 */
class DesktopMediaContractTest {
    private val json = Json { ignoreUnknownKeys = true }
    private val id = "0123456789abcdef0123456789abcdef"
    private val other = "fedcba9876543210fedcba9876543210"

    private fun ref(jobId: String, kind: String? = "\"image\"", url: String = "/api/v1/media/jobs/$jobId"): String {
        val kindPart = if (kind == null) "" else ""","kind":$kind"""
        return """{"job_id":"$jobId","state":"queued","profile_id":"sdxl-a","status_url":"$url"$kindPart}"""
    }

    private fun turn(mediaJobs: String?): ToolTurn {
        val extra = if (mediaJobs == null) "" else ""","media_jobs":$mediaJobs"""
        return json.decodeFromString(
            ToolTurn.serializer(),
            """{"status":"answered","answer":"Billedet er på vej.","tools_used":["image_generate"]$extra}""",
        )
    }

    @Test
    fun aWellFormedReferenceIsLiftedWithItsKind() {
        assertEquals(listOf(DesktopMediaJobRef(id, DesktopMediaKind.IMAGE)), turn("[${ref(id)}]").mediaJobRefs())
        assertEquals(
            listOf(DesktopMediaJobRef(id, DesktopMediaKind.VIDEO)),
            turn("[${ref(id, kind = "\"video\"")}]").mediaJobRefs(),
        )
    }

    @Test
    fun aRigWithoutKindMeansAnImageJob() {
        assertEquals(listOf(DesktopMediaJobRef(id, DesktopMediaKind.IMAGE)), turn("[${ref(id, kind = null)}]").mediaJobRefs())
        assertEquals(listOf(DesktopMediaJobRef(id, DesktopMediaKind.IMAGE)), turn("[${ref(id, kind = "\"\"")}]").mediaJobRefs())
    }

    @Test
    fun anOlderRigOrAnEmptyListMeansNoBubbles() {
        assertEquals(emptyList(), turn(null).mediaJobRefs())
        assertEquals(emptyList(), turn("[]").mediaJobRefs())
        assertEquals(emptyList(), turn("null").mediaJobRefs())
    }

    @Test
    fun malformedEntriesAreDroppedAndNeverBreakTheAnswer() {
        val cases = listOf(
            """{"job_id":"not-hex","status_url":"/api/v1/media/jobs/not-hex"}""",
            ref(id, url = "/api/v1/media/jobs/$other"),
            ref(id, url = "https://elsewhere.example/api/v1/media/jobs/$id"),
            ref(id, url = "/api/v1/media/jobs/$id/cancel"),
            ref(id, kind = "\"audio\""),
            ref(id, kind = "7"),
            ref(id, kind = "null"),
            """{"job_id":7,"status_url":"/api/v1/media/jobs/$id"}""",
            "\"$id\"",
            "17",
        )
        for (case in cases) {
            val t = turn("[$case]")
            assertEquals("Billedet er på vej.", t.answer, case)
            assertEquals(emptyList(), t.mediaJobRefs(), case)
        }
        // A wrong shape for the whole field is no jobs, and still an answer.
        for (shape in listOf("\"x\"", "{}", "3", "true")) {
            val t = turn(shape)
            assertEquals("answered", t.status, shape)
            assertEquals(emptyList(), t.mediaJobRefs(), shape)
        }
    }

    @Test
    fun aGoodEntryStandsBesideABadOneAndDuplicatesCollapse() {
        val refs = turn("[${ref("zz")},${ref(id)},${ref(id)},${ref(other, kind = "\"video\"")}]").mediaJobRefs()
        assertEquals(
            listOf(DesktopMediaJobRef(id, DesktopMediaKind.IMAGE), DesktopMediaJobRef(other, DesktopMediaKind.VIDEO)),
            refs,
        )
    }

    private fun job(
        state: String,
        jobId: String = id,
        assetId: String? = null,
        assetUrl: String? = null,
        error: String? = null,
        cancel: String = "false",
        schema: String? = DesktopMediaContract.SCHEMA,
    ): String {
        fun q(value: String?) = if (value == null) "null" else "\"$value\""
        val schemaPart = if (schema == null) "" else "\"schema\":\"$schema\","
        return """{$schemaPart"id":"$jobId","state":"$state","profile_id":"sdxl-a","asset_id":${q(assetId)},""" +
            """"asset_url":${q(assetUrl)},"error":${q(error)},"cancel_requested":$cancel}"""
    }

    @Test
    fun everyStateIsReadAndOnlyCompletedCarriesAnAsset() {
        for (state in listOf("queued", "running", "publishing", "cancelled", "expired")) {
            val parsed = DesktopMediaContract.parseJob(job(state), id)
            assertEquals(state, parsed.state.wire)
            assertNull(parsed.assetId)
        }
        val failed = DesktopMediaContract.parseJob(job("failed", error = "gpu_unavailable"), id)
        assertEquals("gpu_unavailable", failed.errorCode)
        val done = DesktopMediaContract.parseJob(
            job("completed", assetId = "img_abc-1", assetUrl = "/api/v1/media/img_abc-1"), id,
        )
        assertEquals(DesktopMediaJobState.COMPLETED, done.state)
        assertEquals("img_abc-1", done.assetId)
        assertTrue(done.state.terminal)
        // The schema line is optional on the wire; a job without it is still a job.
        assertEquals(DesktopMediaJobState.RUNNING, DesktopMediaContract.parseJob(job("running", schema = null), id).state)
        assertTrue(DesktopMediaContract.parseJob(job("running", cancel = "true"), id).cancelRequested)
    }

    @Test
    fun anAnswerThatIsNotFullyUnderstoodIsNeverASuccess() {
        val refused = listOf(
            "not json",
            "[]",
            job("running", schema = "kaliv-media-job/v2"),
            job("running", jobId = other),
            job("running", jobId = "short"),
            job("dreaming"),
            job("running", cancel = "\"false\""),
            job("running", cancel = "null"),
            job("failed", error = "Free text from the rig"),
            job("completed"),
            job("completed", assetId = "../../healthz"),
            job("completed", assetId = "img_1", assetUrl = "/api/v1/media/img_2"),
            job("completed", assetId = "img_1", assetUrl = "https://elsewhere.example/img_1"),
            job("running", assetId = "img_1"),
            job("queued", assetUrl = "/api/v1/media/img_1"),
        )
        for (body in refused) {
            val e = assertFailsWith<DesktopMediaException>(body) { DesktopMediaContract.parseJob(body, id) }
            assertEquals(DesktopMediaException.Reason.UNAVAILABLE, e.reason, body)
        }
    }

    @Test
    fun pathsAreBuiltOnlyFromValidatedIds() {
        assertEquals("/api/v1/media/jobs/$id", DesktopMediaContract.jobPath(id))
        assertEquals("/api/v1/media/img_abc-1", DesktopMediaContract.mediaPath("img_abc-1"))
        assertFailsWith<IllegalArgumentException> { DesktopMediaContract.jobPath("../../healthz") }
        assertFailsWith<IllegalArgumentException> { DesktopMediaContract.mediaPath("a/b") }
        assertFailsWith<IllegalArgumentException> { DesktopMediaContract.mediaPath("") }
    }

    @Test
    fun errorCodesAreOnlyPlainCodes() {
        assertEquals("job_not_found", DesktopMediaContract.errorCode("""{"detail":"job_not_found"}"""))
        assertNull(DesktopMediaContract.errorCode("""{"detail":"Server text never shown"}"""))
        assertNull(DesktopMediaContract.errorCode("""{"detail":{"code":"x"}}"""))
        assertNull(DesktopMediaContract.errorCode("<html>"))
    }

    @Test
    fun storedJobsRoundTripAndOnlyWellFormedEntriesAreKept() {
        val refs = listOf(DesktopMediaJobRef(id, DesktopMediaKind.IMAGE), DesktopMediaJobRef(other, DesktopMediaKind.VIDEO))
        val stored = DesktopMediaContract.encodeRefs(refs)
        assertEquals("$id,video:$other", stored)
        assertEquals(refs, DesktopMediaContract.decodeRefs(stored))
        assertEquals("", DesktopMediaContract.encodeRefs(emptyList()))
        assertEquals("", DesktopMediaContract.encodeRefs(listOf(DesktopMediaJobRef("nope", DesktopMediaKind.IMAGE))))
        assertEquals(emptyList(), DesktopMediaContract.decodeRefs(""))
        assertEquals(emptyList(), DesktopMediaContract.decodeRefs(null))
        assertEquals(
            listOf(DesktopMediaJobRef(id, DesktopMediaKind.IMAGE)),
            DesktopMediaContract.decodeRefs("junk,$id,video:junk,audio:$other,$id"),
        )
    }
}
