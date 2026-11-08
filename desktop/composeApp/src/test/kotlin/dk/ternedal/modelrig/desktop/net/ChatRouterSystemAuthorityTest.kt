package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ChatRouterSystemAuthorityTest {
    private val conversation = listOf(
        ChatMessage("user", "hej"),
        ChatMessage("assistant", "hej"),
        ChatMessage("user", "hvad er klokken"),
    )

    // Anders 2026-10-26 (#2275): cloud receives only the current user message.
    private val currentOnly = listOf(ChatMessage("user", "hvad er klokken"))

    @Test
    fun localOnlyUsesLocalSystemWithoutCloudRewrite() {
        val local = "Du er Kaliv på den lokale rig."
        val routed = messagesForChatSource(
            source = ChatResult.Source.LOCAL,
            conversation = conversation,
            localSystem = local,
            cloudSystem = "cloud prompt",
        )

        assertEquals(ChatMessage("system", local), routed.first())
        assertEquals(conversation, routed.drop(1))
    }

    @Test
    fun cloudFirstDefaultCannotClaimLocalExecution() {
        val legacyDefault =
            "Du er Kaliv, en personlig AI-assistent der kører på Anders' egen maskine. " +
                "Du taler dansk.\n\n" +
                "- Du er en lokal assistent med værktøjer (bl.a. læse riggens status og " +
                "tilføje noter) når de er slået til. Kald et værktøj når det giver mening."

        val routed = messagesForChatSource(
            source = ChatResult.Source.CLOUD,
            conversation = conversation,
            localSystem = "local prompt",
            cloudSystem = legacyDefault,
        )
        val system = routed.first().content

        assertTrue(system.contains("Denne modelkørsel foregår via en cloud-model"))
        assertFalse(system.contains("kører på Anders' egen maskine"))
        assertFalse(system.contains("Du er en lokal assistent med værktøjer"))
        assertTrue(system.contains("Du taler dansk."))
        assertEquals(currentOnly, routed.drop(1))
    }

    @Test
    fun cloudFallbackSelectsCloudSystemInsteadOfPreferredLocalSystem() {
        val routed = messagesForChatSource(
            source = ChatResult.Source.CLOUD,
            conversation = listOf(ChatMessage("system", "stale preferred local system")) + conversation,
            localSystem = "LOCAL-ONLY-INSTRUCTION",
            cloudSystem = "CLOUD-ONLY-INSTRUCTION",
        )
        val system = routed.first().content

        assertTrue(system.contains("CLOUD-ONLY-INSTRUCTION"))
        assertFalse(system.contains("LOCAL-ONLY-INSTRUCTION"))
        assertFalse(routed.any { it.content == "stale preferred local system" })
        assertEquals(currentOnly, routed.drop(1))
    }

    @Test
    fun arbitraryCustomCloudProseIsPreserved() {
        val custom = "Svar kort. Brug mit interne projektnavn uændret."
        val system = messagesForChatSource(
            source = ChatResult.Source.CLOUD,
            conversation = conversation,
            localSystem = "local",
            cloudSystem = custom,
        ).first().content

        assertTrue(system.contains(custom))
    }

    @Test
    fun cloudNeverReceivesEarlierTurnsOnTheWire() {
        val secret = "kodeord-7731"
        val bodies = mutableListOf<String>()
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/") { exchange ->
            bodies += exchange.requestBody.readBytes().decodeToString()
            val reply = "{\"message\":{\"content\":\"ok\"},\"done\":true}\n".toByteArray()
            exchange.sendResponseHeaders(200, reply.size.toLong())
            exchange.responseBody.use { it.write(reply) }
        }
        server.start()
        try {
            val cloud = OllamaClient("http://127.0.0.1:${server.address.port}", bearer = "test-only")
            val history = listOf(
                ChatMessage("system", "Du er Kaliv."),
                ChatMessage("user", "Mit kodeord er $secret"),
                ChatMessage("assistant", "Noteret."),
                ChatMessage("user", "hvad er klokken"),
            )
            // Without route systems (the raw path) and with them (the app's path).
            ChatRouter(local = null, localModel = "l", cloud = cloud, cloudModel = "c", preferLocal = false)
                .chatStream(history) { _, _ -> }
            ChatRouter(
                local = null, localModel = "l", cloud = cloud, cloudModel = "c", preferLocal = false,
                localSystem = "LOCAL", cloudSystem = "CLOUD",
            ).chatStream(history) { _, _ -> }

            assertEquals(2, bodies.size)
            for (body in bodies) {
                assertFalse(body.contains(secret), "no earlier turn on the wire: $body")
                assertFalse(body.contains("Noteret."), "no earlier assistant turn on the wire: $body")
                assertTrue(body.contains("hvad er klokken"), "current message is sent: $body")
            }
        } finally {
            server.stop(0)
        }
    }
}
