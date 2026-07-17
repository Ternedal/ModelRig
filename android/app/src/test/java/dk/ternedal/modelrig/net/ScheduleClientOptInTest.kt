package dk.ternedal.modelrig.net

import com.sun.net.httpserver.HttpServer
import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.InetSocketAddress

class ScheduleClientOptInTest {
    @Test
    fun missingScheduleRoutesExplainTheSeparateBackendOptIn() {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/") { exchange ->
            val body = "404 page not found".toByteArray()
            exchange.sendResponseHeaders(404, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        server.start()
        try {
            val client = ScheduleClient("http://127.0.0.1:${server.address.port}", "device-token")
            val error = runCatching { client.status() }.exceptionOrNull()
            assertTrue(error is ModelRigException)
            assertTrue(error?.message.orEmpty().contains("KALIV_SCHEDULER_API=1"))
            assertTrue(error?.message.orEmpty().contains("genstart backend"))
        } finally {
            server.stop(0)
        }
    }
}
