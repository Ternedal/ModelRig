package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * #2419: `media_jobs` on the tools-chat result, through the real stream reader.
 *
 * A well-formed reference (32-hex id whose `status_url` is the job route) is
 * kept; anything else is dropped rather than guessed at; older rigs without the
 * field give an empty list.
 */
class ToolTurnMediaJobsTest {
    private lateinit var server: MockWebServer

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private val id = "0123456789abcdef0123456789abcdef"
    private val other = "fedcba9876543210fedcba9876543210"

    private fun ref(jobId: String, statusUrl: String = "/api/v1/media/jobs/$jobId") =
        """{"job_id":"$jobId","state":"queued","profile_id":"sdxl-a","status_url":"$statusUrl"}"""

    private fun turn(mediaJobs: String?): ToolTurn {
        val extra = if (mediaJobs == null) "" else ""","media_jobs":$mediaJobs"""
        server.enqueue(
            MockResponse().setResponseCode(200).setHeader("Content-Type", "application/x-ndjson").setBody(
                """{"phase":"generating"}
{"phase":"tool_run"}
{"result":{"status":"answered","answer":"Billedet er på vej.","tool":"image_generate","tools_used":["image_generate"],"sources":[]$extra}}
""",
            ),
        )
        return ModelRigClient(server.url("/").toString().trimEnd('/'), "device-token").toolsChatStream("lav et billede")
    }

    @Test
    fun `a well-formed reference is kept`() {
        val t = turn("[${ref(id)}]")
        assertEquals("answered", t.status)
        assertEquals(listOf(id), t.mediaJobs)
    }

    @Test
    fun `an older rig without the field gives an empty list`() {
        assertEquals(emptyList<String>(), turn(null).mediaJobs)
        assertEquals(emptyList<String>(), turn("[]").mediaJobs)
    }

    @Test
    fun `malformed references are dropped, never guessed at`() {
        val t = turn(
            "[" + listOf(
                ref(id),
                ref("short"),                                   // not a job id
                ref("ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ"),         // not hex
                ref(other, statusUrl = "/api/v1/media/jobs/$id"), // status_url for another job
                ref(other, statusUrl = "https://evil.example/$other"), // foreign url
                """{"state":"queued"}""",                        // no id
                "\"$other\"",                                   // not an object
            ).joinToString(",") + "]",
        )
        assertEquals(listOf(id), t.mediaJobs)
    }

    @Test
    fun `duplicates collapse to one bubble`() {
        assertEquals(listOf(id), turn("[${ref(id)},${ref(id)}]").mediaJobs)
    }

    @Test
    fun `the prompt is never in the parsed turn`() {
        val t = turn("[${ref(id)}]")
        assertTrue(t.toString().contains("image_generate"))
        assertTrue(!t.toString().contains("lav et billede"))
    }
}
