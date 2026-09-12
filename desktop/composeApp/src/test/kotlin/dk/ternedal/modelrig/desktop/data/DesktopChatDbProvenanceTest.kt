package dk.ternedal.modelrig.desktop.data

import java.nio.file.Files
import java.nio.file.Path
import kotlin.io.path.deleteIfExists
import kotlin.test.Test
import kotlin.test.assertEquals

class DesktopChatDbProvenanceTest {
    @Test
    fun normalConversationCanMoveFromPendingToActualAnswerRoute() {
        withDatabase { db ->
            val id = db.newConversation(source = "pending", model = "", title = "test")
            assertEquals("pending", db.conversationMeta(id)?.source)
            assertEquals("", db.conversationMeta(id)?.model)

            db.updateConversationRoute(id, source = "cloud", model = "cloud-model")
            assertEquals("cloud", db.conversationMeta(id)?.source)
            assertEquals("cloud-model", db.conversationMeta(id)?.model)

            // Conversation metadata denotes the latest successful normal-chat answer.
            db.updateConversationRoute(id, source = "rig", model = "local-model")
            assertEquals("rig", db.conversationMeta(id)?.source)
            assertEquals("local-model", db.conversationMeta(id)?.model)
        }
    }

    private fun withDatabase(block: (DesktopChatDb) -> Unit) {
        val path = Files.createTempFile("modelrig-provenance-", ".db")
        try {
            DesktopChatDb(path.toString()).use(block)
        } finally {
            path.deleteIfExists()
            Path.of("$path-journal").deleteIfExists()
            Path.of("$path-shm").deleteIfExists()
            Path.of("$path-wal").deleteIfExists()
        }
    }
}
