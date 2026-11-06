package dk.ternedal.modelrig.net

import dk.ternedal.modelrig.ui.MediaJobPresentation
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * The shared `kaliv-media-job/v1` fixtures (docs/contracts/kaliv-media-job-v1/fixtures.json)
 * must parse on the phone exactly as tests/workflow_media_job_fixtures.py checks them on the
 * worker side. Gradle runs unit tests from android/app, so the repo root is two levels up.
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

    @Test
    fun `every job response in the fixtures parses`() {
        var parsed = 0
        val states = HashSet<MediaJobState>()
        for (e in exchanges()) {
            val response = e.getJSONObject("response")
            val body = response.getJSONObject("body")
            if (response.getInt("status") >= 400 || !body.has("job")) continue
            val job = MediaJobContract.parse(body.toString())
            assertEquals(e.getString("name"), body.getJSONObject("job").getString("state"), job.state.wire)
            states += job.state
            parsed++
        }
        assertTrue("too few job responses: $parsed", parsed >= 10)
        assertEquals(MediaJobState.entries.toSet(), states)
    }

    @Test
    fun `every job in a list page parses`() {
        for (e in exchanges().filter { it.getJSONObject("response").getJSONObject("body").has("jobs") }) {
            val jobs = e.getJSONObject("response").getJSONObject("body").getJSONArray("jobs")
            for (i in 0 until jobs.length()) MediaJobContract.parseJob(jobs.getJSONObject(i))
        }
    }

    @Test
    fun `every error in the fixtures has its own Danish text`() {
        for (e in exchanges()) {
            val body = e.getJSONObject("response").getJSONObject("body")
            val job = body.optJSONObject("job") ?: continue
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
