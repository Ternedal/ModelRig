package dk.ternedal.modelrig.desktop

import dk.ternedal.modelrig.desktop.net.ChatResult
import kotlin.test.Test
import kotlin.test.assertEquals

class ChatConversationProvenanceTest {
    @Test
    fun newNormalConversationStartsUnresolved() {
        assertEquals("pending", PendingChatConversationProvenance.source)
        assertEquals("", PendingChatConversationProvenance.model)
    }

    @Test
    fun localSuccessPersistsActualLocalModel() {
        val p = completedChatConversationProvenance(
            source = ChatResult.Source.LOCAL,
            localModel = "local-model",
            cloudModel = "cloud-model",
        )
        assertEquals(ChatConversationProvenance("rig", "local-model"), p)
    }

    @Test
    fun localFirstFallbackToCloudPersistsCloudAnswer() {
        val p = completedChatConversationProvenance(
            source = ChatResult.Source.CLOUD,
            localModel = "preferred-local",
            cloudModel = "actual-cloud",
        )
        assertEquals(ChatConversationProvenance("cloud", "actual-cloud"), p)
    }

    @Test
    fun cloudFirstFallbackToLocalPersistsLocalAnswer() {
        val p = completedChatConversationProvenance(
            source = ChatResult.Source.LOCAL,
            localModel = "actual-local",
            cloudModel = "preferred-cloud",
        )
        assertEquals(ChatConversationProvenance("rig", "actual-local"), p)
    }
}
