package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.time.Duration
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertFailsWith

class OllamaClientPrivacyTest {
    @Test
    fun httpFailureKeepsStatusButDoesNotEchoResponseBody() {
        val secret = "token=super-secret /internal/path"
        val server = server(500, secret)
        try {
            val error = assertFailsWith<OllamaException> {
                client(server).chat("model", listOf(ChatMessage("user", "hej")))
            }
            assertEquals("chat failed (500)", error.message)
            assertFalse(error.message.orEmpty().contains(secret))
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun chatStreamRemoteErrorDoesNotEchoServerControlledText() {
        val secret = "secret-token from /srv/private"
        val server = server(200, """{"error":"$secret"}
""")
        try {
            val error = assertFailsWith<OllamaException> {
                client(server).chatStream("model", listOf(ChatMessage("user", "hej"))) { }
            }
            assertEquals("chat stream failed (remote error)", error.message)
            assertFalse(error.message.orEmpty().contains(secret))
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun malformedChatStreamDoesNotEchoRawLine() {
        val secret = "not-json token=super-secret /private/path"
        val server = server(200, "$secret\n")
        try {
            val error = assertFailsWith<OllamaException> {
                client(server).chatStream("model", listOf(ChatMessage("user", "hej"))) { }
            }
            assertEquals("chat stream failed (invalid response)", error.message)
            assertFalse(error.message.orEmpty().contains(secret))
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun deleteFailureDoesNotEchoResponseBody() {
        val secret = """{"error":"filesystem /private/models secret-token"}"""
        val server = server(503, secret)
        try {
            val error = assertFailsWith<OllamaException> {
                client(server).deleteModel("model")
            }
            assertEquals("delete failed (503)", error.message)
            assertFalse(error.message.orEmpty().contains(secret))
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun malformedModelsResponseIsBounded() {
        val secret = "not-json token=server-secret"
        val server = server(200, secret)
        try {
            val error = assertFailsWith<OllamaException> {
                client(server).listModels()
            }
            assertEquals("models failed (invalid response)", error.message)
            assertFalse(error.message.orEmpty().contains(secret))
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun malformedEndpointDoesNotEchoConfiguredUrl() {
        val rawEndpoint = "http://[secret-host"
        val error = assertFailsWith<OllamaException> {
            OllamaClient(rawEndpoint).listModels()
        }
        assertEquals("models failed (invalid endpoint)", error.message)
        assertFalse(error.message.orEmpty().contains("secret-host"))
        assertFalse(error.message.orEmpty().contains(rawEndpoint))
    }

    @Test
    fun transportFailureDoesNotEchoEndpointOrExceptionDetail() {
        val probe = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        probe.start()
        val port = probe.address.port
        probe.stop(0)
        val base = "http://127.0.0.1:$port"

        val error = assertFailsWith<OllamaException> {
            OllamaClient(
                baseUrl = base,
                connectTimeout = Duration.ofMillis(250),
                requestTimeout = Duration.ofSeconds(1),
            ).listModels()
        }
        assertEquals("models unavailable", error.message)
        assertFalse(error.message.orEmpty().contains(base))
        assertFalse(error.message.orEmpty().contains(port.toString()))
    }

    private fun client(server: HttpServer) =
        OllamaClient("http://127.0.0.1:${server.address.port}")

    private fun server(status: Int, response: String): HttpServer {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/") { exchange ->
            val body = response.toByteArray()
            exchange.sendResponseHeaders(status, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        server.start()
        return server
    }
}
