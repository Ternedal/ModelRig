package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpServer
import java.net.ConnectException
import java.net.InetSocketAddress
import java.net.http.HttpTimeoutException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertFailsWith

class OllamaClientPrivacyTest {
    private val secretBody = "Bearer SECRET token=abc /data/private"

    @Test
    fun serverFailureCarriesOnlyOperationAndStatus() {
        val rendered = ollamaFailureMessage("chat", 500)
        assertEquals("chat failed (500)", rendered)
        assertRedacted(rendered)
    }

    @Test
    fun transportFailureDoesNotEchoCauseMessage() {
        val rendered = ollamaTransportFailureMessage(
            "chat",
            RuntimeException(secretBody),
        )
        assertEquals("chat request failed", rendered)
        assertRedacted(rendered)
    }

    @Test
    fun safeTransportCategoriesRemainRecognizableWithoutCauseText() {
        assertEquals(
            "chat failed (HttpTimeoutException)",
            ollamaTransportFailureMessage(
                "chat",
                HttpTimeoutException("https://secret.invalid?q=token"),
            ),
        )
        assertEquals(
            "chat failed (ConnectException)",
            ollamaTransportFailureMessage(
                "chat",
                ConnectException("https://secret.invalid?q=token"),
            ),
        )
    }

    @Test
    fun invalidEndpointDoesNotEchoConfiguredUrl() {
        val client = OllamaClient("http://[secret-token")
        val error = assertFailsWith<OllamaException> {
            client.chat("model", emptyList())
        }
        assertEquals("invalid endpoint configuration", error.message)
        assertFalse(error.message.orEmpty().contains("secret-token"))
    }

    @Test
    fun non2xxBodiesAreRedactedAcrossEveryDesktopOllamaOperation() {
        val server = server(500, secretBody)
        try {
            val client = OllamaClient(
                "http://127.0.0.1:${server.address.port}",
                chatPath = "/",
            )

            assertFailure("chat failed (500)") {
                client.chat("model", emptyList())
            }
            assertFailure("chat stream failed (500)") {
                client.chatStream("model", emptyList()) { }
            }
            assertFailure("models failed (500)") {
                client.listModels("/")
            }
            assertFailure("models failed (500)") {
                client.listModelsDetailed("/")
            }
            assertFailure("running models failed (500)") {
                client.listRunningModels("/")
            }
            assertFailure("pull failed (500)") {
                client.pullModel("model", "/") { _, _, _ -> }
            }
            assertFailure("delete failed (500)") {
                client.deleteModel("model", "/")
            }
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun malformedSuccessfulResponseDoesNotEchoPayload() {
        val server = server(200, secretBody)
        try {
            val client = OllamaClient(
                "http://127.0.0.1:${server.address.port}",
                chatPath = "/",
            )
            assertFailure("chat returned invalid response") {
                client.chat("model", emptyList())
            }
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun streamedServerErrorDoesNotEchoPayload() {
        val server = server(
            200,
            """{"error":"Bearer SECRET token=abc /data/private"}""" + "\n",
        )
        try {
            val client = OllamaClient(
                "http://127.0.0.1:${server.address.port}",
                chatPath = "/",
            )
            assertFailure("chat stream failed") {
                client.chatStream("model", emptyList()) { }
            }
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun pullStreamErrorDoesNotEchoPayload() {
        val server = server(
            200,
            """{"error":"Bearer SECRET token=abc /data/private"}""" + "\n",
        )
        try {
            val client = OllamaClient("http://127.0.0.1:${server.address.port}")
            assertFailure("pull failed") {
                client.pullModel("model", "/") { _, _, _ -> }
            }
        } finally {
            server.stop(0)
        }
    }

    private fun assertFailure(expected: String, block: () -> Unit) {
        val error = assertFailsWith<OllamaException> { block() }
        assertEquals(expected, error.message)
        assertRedacted(error.message.orEmpty())
    }

    private fun assertRedacted(text: String) {
        assertFalse(text.contains("SECRET"))
        assertFalse(text.contains("Bearer"))
        assertFalse(text.contains("token="))
        assertFalse(text.contains("/data/"))
    }

    private fun server(status: Int, bodyText: String): HttpServer {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/") { exchange ->
            val body = bodyText.toByteArray()
            exchange.responseHeaders.add("Content-Type", "application/json")
            exchange.sendResponseHeaders(status, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        server.start()
        return server
    }
}
