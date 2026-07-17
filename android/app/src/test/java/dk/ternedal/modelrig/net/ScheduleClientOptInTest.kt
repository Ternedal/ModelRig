package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ScheduleClientOptInTest {
    @Test
    fun missingScheduleRoutesExplainTheSeparateBackendOptIn() {
        val server = MockWebServer()
        server.enqueue(MockResponse().setResponseCode(404).setBody("404 page not found"))
        server.start()
        try {
            val client = ScheduleClient(server.url("/").toString(), "device-token")
            val error = runCatching { client.status() }.exceptionOrNull()
            assertTrue(error is ModelRigException)
            assertTrue(error?.message.orEmpty().contains("KALIV_SCHEDULER_API=1"))
            assertTrue(error?.message.orEmpty().contains("genstart backend"))

            val request = server.takeRequest()
            assertEquals("/api/v1/schedules/status", request.path)
            assertEquals("Bearer device-token", request.getHeader("Authorization"))
        } finally {
            server.shutdown()
        }
    }
}
