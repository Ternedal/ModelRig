package dk.ternedal.modelrig.desktop.net

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ChatRouterSystemAuthorityTest {
    private val conversation = listOf(
        ChatMessage("user", "hej"),
        ChatMessage("assistant", "hej"),
    )

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
        assertEquals(conversation, routed.drop(1))
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
        assertEquals(conversation, routed.drop(1))
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
}
