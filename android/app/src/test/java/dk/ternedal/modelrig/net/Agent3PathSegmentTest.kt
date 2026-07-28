package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Et id maa ikke kunne vaelge sin egen rute.
 *
 * Maalt 27/07-2026 FOER rettelsen: runId = "../../healthz" gav stien
 * /api/v1/experimental/healthz/confirm. Traversalen oploeses foer requesten
 * sendes, saa et misdannet id aendrede hvilket endpoint der blev ramt.
 *
 * Id'erne kommer fra serveren, saa det var ikke udnytteligt i praksis. Men
 * Agent3MemoryClient encodede allerede sine segmenter og de oevrige klienter
 * gjorde ikke -- nogen havde altsaa set behovet eet sted. Nu opfoerer de fire
 * sig ens.
 */
class Agent3PathSegmentTest {

    private fun server(): MockWebServer {
        val s = MockWebServer()
        repeat(4) {
            s.enqueue(
                MockResponse().setHeader("Content-Type", "application/json")
                    .setBody("""{"run":{"id":"r","plan_id":"p","state":"running","steps":[]}}"""),
            )
        }
        s.start()
        return s
    }

    @Test
    fun traversalInARunIdCannotChangeTheEndpoint() {
        val s = server()
        try {
            Agent3Client(s.url("/").toString(), "t")
                .confirm("../../healthz", "step", "digest", approve = true)
            val path = s.takeRequest().path!!
            assertTrue(
                "stien skal stadig ligge under runs/ -- var $path",
                path.startsWith("/api/v1/experimental/agent3/runs/"),
            )
            assertTrue("og stadig ende paa /confirm -- var $path", path.endsWith("/confirm"))
        } finally {
            s.shutdown()
        }
    }

    @Test
    fun queryInjectionInARunIdStaysInTheSegment() {
        val s = server()
        try {
            Agent3Client(s.url("/").toString(), "t")
                .confirm("run-1?x=1", "step", "digest", approve = true)
            val path = s.takeRequest().path!!
            assertTrue("id'et maa ikke blive til en query -- var $path", path.endsWith("/confirm"))
        } finally {
            s.shutdown()
        }
    }

    @Test
    fun anOrdinaryIdIsUnchanged() {
        // Kontrolpunkt. Uden det ville en encoder der oedelagde ALLE id'er bestaa.
        val s = server()
        try {
            Agent3Client(s.url("/").toString(), "t")
                .confirm("run-1", "step", "digest", approve = true)
            assertEquals(
                "/api/v1/experimental/agent3/runs/run-1/confirm",
                s.takeRequest().path,
            )
        } finally {
            s.shutdown()
        }
    }

    @Test
    fun replanApplyEncodesItsPreviewIdToo() {
        val s = MockWebServer()
        s.enqueue(
            MockResponse().setHeader("Content-Type", "application/json").setBody(
                """{"run":{"id":"r","plan_id":"p","state":"running","steps":[]},
                    "replan":{},"preview":{}}""",
            ),
        )
        s.start()
        try {
            runCatching {
                Agent3ReplanClient(s.url("/").toString(), "t").apply("../../healthz")
            }
            val path = s.takeRequest().path!!
            assertTrue(
                "replan-apply skal ogsaa blive i sit segment -- var $path",
                path.startsWith("/api/v1/experimental/agent3/replan-previews/"),
            )
        } finally {
            s.shutdown()
        }
    }
}
