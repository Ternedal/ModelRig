package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/**
 * C5 F2 (#2275): the capability probe must reach something that exists.
 *
 * The backend has no `/capabilities` route, so the old probe always got 404 and therefore
 * UNKNOWN ("everything available"), and the gate never worked. The probe now reads the
 * `capabilities` object from the Bearer-protected `/api/v1/health/full`.
 */
class WorkerCapabilitiesProbeTest {
    private lateinit var server: MockWebServer

    private val healthFull = """
        {"ok":false,"faults":["ollama"],
         "capabilities":{"asr":false,"tts":false,"pdf":false,"docx":true,"pptx":true,"html":true,"cuda":false},
         "checks":{"worker":{"ok":true},"ollama":{"ok":false}}}
    """.trimIndent()

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    @Test
    fun probeAsksTheAuthenticatedHealthRouteAndReadsOnlyItsCapabilities() {
        server.enqueue(MockResponse().setResponseCode(200).setBody(healthFull))
        val caps = ModelRigClient(server.url("/").toString(), "paired-token").workerCapabilities()
        val request = server.takeRequest()
        assertEquals("/api/v1/health/full", request.path)
        assertEquals("Bearer paired-token", request.getHeader("Authorization"))
        assertTrue(caps.known)
        assertEquals(listOf("asr", "cuda", "pdf", "tts"), caps.explicitlyMissing())
        assertTrue(caps.supports(WorkerCapabilities.DOCX))
        // Top-level booleans of the health verdict are not capabilities.
        assertTrue("ok=false must not read as a missing capability", caps.supports("ok"))
    }

    @Test
    fun aRigThatDoesNotAnswerStaysUnknownAndNothingIsSwitchedOff() {
        server.enqueue(MockResponse().setResponseCode(404))
        val caps = ModelRigClient(server.url("/").toString(), "paired-token").workerCapabilities()
        assertFalse(caps.known)
        assertTrue(caps.supports(WorkerCapabilities.PDF))
    }

    @Test
    fun anOlderWorkerWithoutTheObjectIsUnknown() {
        assertFalse(WorkerCapabilities.fromHealthFull("""{"ok":true,"faults":[]}""").known)
        assertFalse(WorkerCapabilities.fromHealthFull("""{"capabilities":"pdf"}""").known)
        assertFalse(WorkerCapabilities.fromHealthFull("not json").known)
        assertFalse(WorkerCapabilities.fromHealthFull(null).known)
        assertFalse(WorkerCapabilities.fromHealthFull("""{"capabilities":{}}""").known)
    }

    @Test
    fun theOldPathIsNeverRequested() {
        server.enqueue(MockResponse().setResponseCode(200).setBody(healthFull))
        ModelRigClient(server.url("/").toString(), "paired-token").workerCapabilities()
        assertEquals(1, server.requestCount)
        assertFalse(server.takeRequest().path!!.endsWith("/capabilities"))
    }
}
