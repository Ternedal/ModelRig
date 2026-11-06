package dk.ternedal.modelrig.net

import dk.ternedal.modelrig.ui.MediaJobPolling
import dk.ternedal.modelrig.ui.MediaJobPresentation
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * The shared `kaliv-media-job/v1` fixtures (docs/contracts/kaliv-media-job-v1/fixtures.json)
 * must parse on the phone exactly as tests/workflow_media_job_fixtures.py checks them on the
 * worker side. Every exchange goes through the parser the app would use for it. Gradle runs
 * unit tests from android/app, so the repo root is two levels up.
 */
class MediaJobFixturesTest {

    private val fixtures: JSONObject by lazy {
        val file = File("../../docs/contracts/kaliv-media-job-v1/fixtures.json")
        assertTrue("fixtures not found from ${File(".").absolutePath}", file.isFile)
        JSONObject(file.readText())
    }

    private fun exchanges(): List<JSONObject> {
        val array = fixtures.getJSONArray("exchanges")
        return (0 until array.length()).map { array.getJSONObject(it) }
    }

    private val JSONObject.status get() = getJSONObject("response").getInt("status")
    private val JSONObject.body get() = getJSONObject("response").getJSONObject("body").toString()
    private val JSONObject.path get() = getJSONObject("request").getString("path")
    private val JSONObject.method get() = getJSONObject("request").getString("method")

    @Test
    fun `every exchange parses with the parser the app uses for it`() {
        val states = HashSet<MediaJobState>()
        val refusals = HashSet<MediaJobRefusal>()
        val outcomes = HashSet<MediaCancelOutcome>()
        var pages = 0
        var capabilities = 0
        for (e in exchanges()) {
            val name = e.getString("name")
            when {
                e.status >= 400 -> {
                    val refusal = MediaJobContract.refusal(e.body)
                    assertNotEquals(name, MediaJobRefusal.UNKNOWN, refusal)
                    refusals += refusal
                    val headers = e.getJSONObject("response").getJSONObject("headers")
                    if (headers.has("Retry-After")) {
                        assertNotNull(name, MediaJobPolling.retryAfterMs(headers.getString("Retry-After")))
                    }
                }
                e.path.endsWith("/cancel") -> {
                    val result = MediaJobContract.parseCancel(e.body)
                    outcomes += result.outcome
                    states += result.job.state
                }
                e.path == "/api/v1/media/capabilities" -> {
                    assertEquals(name, MediaCapabilities(true, false, false), MediaCapabilities.parse(e.body))
                    capabilities++
                }
                e.method == "GET" && e.path.startsWith("/api/v1/media/jobs?") -> {
                    val page = MediaJobContract.parsePage(e.body)
                    assertEquals(name, 0, page.skipped)
                    page.jobs.forEach { states += it.state }
                    pages++
                }
                else -> {
                    val job = MediaJobContract.parse(e.body)
                    assertEquals(name, JSONObject(e.body).getJSONObject("job").getString("state"), job.state.wire)
                    states += job.state
                    if (e.status == 201) {
                        assertEquals(name, MediaJobContract.jobPath(job.id),
                            e.getJSONObject("response").getJSONObject("headers").getString("Location"))
                    }
                }
            }
        }
        assertEquals(MediaJobState.entries.toSet(), states)
        assertEquals(MediaJobRefusal.entries.toSet() - MediaJobRefusal.UNKNOWN, refusals)
        assertEquals(MediaCancelOutcome.entries.toSet(), outcomes)
        assertEquals(2, pages)
        assertEquals(1, capabilities)
    }

    @Test
    fun `every error in the fixtures has its own Danish text`() {
        for (e in exchanges()) {
            val job = JSONObject(e.body).optJSONObject("job") ?: continue
            val error = job.opt("error") as? String ?: continue
            assertNotNull("${e.getString("name")}: $error", MediaJobPresentation.ERRORS[error])
        }
    }

    @Test
    fun `the fixtures are the proposed contract`() {
        assertEquals(MediaJobContract.SCHEMA, fixtures.getString("contract"))
        assertTrue(fixtures.getString("status").startsWith("PROPOSED"))
    }
}
