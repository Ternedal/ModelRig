package dk.ternedal.modelrig.desktop.net

import java.net.ConnectException
import java.net.http.HttpTimeoutException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertFailsWith

class OllamaClientPrivacyTest {
    @Test
    fun serverFailureCarriesOnlyOperationAndStatus() {
        val rendered = ollamaFailureMessage("chat", 500)
        assertEquals("chat failed (500)", rendered)
        assertFalse(rendered.contains("Bearer"))
        assertFalse(rendered.contains("/data/"))
        assertFalse(rendered.contains("token="))
    }

    @Test
    fun transportFailureDoesNotEchoCauseMessage() {
        val rendered = ollamaTransportFailureMessage(
            "chat",
            RuntimeException("Bearer SECRET token=abc /data/private"),
        )
        assertEquals("chat request failed", rendered)
        assertFalse(rendered.contains("SECRET"))
        assertFalse(rendered.contains("token="))
        assertFalse(rendered.contains("/data/"))
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
}
