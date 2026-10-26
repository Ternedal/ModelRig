package dk.ternedal.modelrig.data

import android.content.Context
import android.database.SQLException
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

/**
 * Regression for the transactional spoken-turn persistence introduced by #2213.
 * Uses real SQLite under Robolectric, not a fake ChatDb implementation.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class VoiceTurnPersistenceTest {
    private lateinit var context: Context
    private lateinit var chatDb: ChatDb

    @Before
    fun setUp() {
        context = RuntimeEnvironment.getApplication()
        context.deleteDatabase("modelrig.db")
        chatDb = ChatDb(context)
    }

    @After
    fun tearDown() {
        chatDb.close()
        context.deleteDatabase("modelrig.db")
    }

    @Test
    fun completedVoiceTurnPersistsBothRolesInOriginalConversation() {
        val original = chatDb.newConversation("rig", "local", "original")
        val other = chatDb.newConversation("rig", "local", "other")
        chatDb.addCompletedVoiceTurn(
            original,
            "Mit hemmelige testord er blå elefant.",
            "Det husker jeg.",
        )
        assertEquals(
            listOf("user" to "Mit hemmelige testord er blå elefant.",
                "assistant" to "Det husker jeg."),
            chatDb.loadMessages(original),
        )
        assertTrue("a different chat must remain empty", chatDb.loadMessages(other).isEmpty())
    }

    @Test
    fun emptyTurnDoesNotWriteMessagesOrChangeRecency() {
        val id = chatDb.newConversation("rig", "local", "empty")
        val before = chatDb.conversationMeta(id)!!.updatedAt
        chatDb.addCompletedVoiceTurn(id, "", "  ")
        assertTrue(chatDb.loadMessages(id).isEmpty())
        assertEquals(before, chatDb.conversationMeta(id)!!.updatedAt)
    }

    @Test
    fun transcriptOnlyTurnPersistsUserWithoutEmptyAssistantRow() {
        val id = chatDb.newConversation("rig", "local", "transcript-only")
        chatDb.addCompletedVoiceTurn(id, "Blå elefant", "")
        assertEquals(listOf("user" to "Blå elefant"), chatDb.loadMessages(id))
    }

    @Test
    fun replyOnlyTurnPersistsAssistantWithoutEmptyUserRow() {
        val id = chatDb.newConversation("rig", "local", "reply-only")
        chatDb.addCompletedVoiceTurn(id, "  ", "Jeg husker det.")
        assertEquals(listOf("assistant" to "Jeg husker det."), chatDb.loadMessages(id))
    }

    @Test
    fun absentOrDeletedConversationCannotReceiveLateVoiceMessages() {
        val id = chatDb.newConversation("rig", "local", "removed")
        chatDb.deleteConversation(id)
        chatDb.addCompletedVoiceTurn(id, "stale transcript", "stale reply")
        assertTrue(chatDb.loadMessages(id).isEmpty())
        assertEquals(null, chatDb.conversationMeta(id))
    }

    @Test
    fun deletedConversationDoesNotReappearAfterFailedVoiceWrite() {
        val id = chatDb.newConversation("rig", "local", "deleted")
        chatDb.deleteConversation(id)
        chatDb.addCompletedVoiceTurn(id, "late user", "late assistant")
        assertEquals(null, chatDb.conversationMeta(id))
        assertTrue(chatDb.loadMessages(id).isEmpty())
    }

    @Test
    fun failedAssistantInsertRollsBackEarlierUserInsert() {
        val id = chatDb.newConversation("rig", "local", "rollback")
        val before = chatDb.conversationMeta(id)!!.updatedAt
        chatDb.writableDatabase.execSQL(
            """CREATE TRIGGER reject_assistant BEFORE INSERT ON message
               WHEN NEW.role='assistant'
               BEGIN SELECT RAISE(ABORT, 'test-only failure'); END""",
        )
        assertThrows(SQLException::class.java) {
            chatDb.addCompletedVoiceTurn(id, "Blå elefant", "Svar")
        }
        assertTrue("no partial user transcript may survive", chatDb.loadMessages(id).isEmpty())
        assertEquals(before, chatDb.conversationMeta(id)!!.updatedAt)
    }
}
