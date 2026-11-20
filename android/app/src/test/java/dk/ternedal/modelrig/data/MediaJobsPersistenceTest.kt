package dk.ternedal.modelrig.data

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

/**
 * #2419: an assistant turn's image-job ids survive an app restart (schema v4,
 * `message.media_jobs`). Real SQLite under Robolectric; includes the v3 -> v4
 * upgrade of an existing database, which must keep every old row.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class MediaJobsPersistenceTest {
    private lateinit var context: Context
    private lateinit var chatDb: ChatDb
    private val a = "0123456789abcdef0123456789abcdef"
    private val b = "fedcba9876543210fedcba9876543210"

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
    fun jobIdsRoundTripOnTheAssistantTurnOnly() {
        val conv = chatDb.newConversation("rig", "local", "billeder")
        chatDb.addMessage(conv, "user", "lav et billede af en sø")
        chatDb.addMessage(conv, "assistant", "Det er på vej.", listOf(a, b))
        chatDb.addMessage(conv, "assistant", "Noget andet.")
        val rows = chatDb.loadMessagesWithMedia(conv)
        assertEquals(3, rows.size)
        assertEquals(emptyList<String>(), rows[0].mediaJobs)
        assertEquals(listOf(a, b), rows[1].mediaJobs)
        assertEquals(emptyList<String>(), rows[2].mediaJobs)
        // The text-only view is unchanged for every caller that compares histories.
        assertEquals(listOf("user" to "lav et billede af en sø", "assistant" to "Det er på vej.", "assistant" to "Noget andet."),
            chatDb.loadMessages(conv))
    }

    @Test
    fun malformedIdsAreDroppedOnWriteAndOnRead() {
        assertEquals("$a,$b", ChatDb.encodeMediaJobs(listOf(a, "short", a, "ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ", b)))
        assertEquals(listOf(a), ChatDb.decodeMediaJobs("$a,garbage,,$a"))
        assertEquals(emptyList<String>(), ChatDb.decodeMediaJobs(null))
        assertEquals(emptyList<String>(), ChatDb.decodeMediaJobs(""))
    }

    @Test
    fun upgradeFromV3KeepsOldRowsAndAddsTheColumn() {
        chatDb.close()
        context.deleteDatabase("modelrig.db")
        // A v3 database as the app wrote it before #2419: no media_jobs column.
        val old = SQLiteDatabase.openOrCreateDatabase(context.getDatabasePath("modelrig.db"), null)
        old.execSQL(
            """CREATE TABLE conversation(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL DEFAULT '',
               source TEXT NOT NULL, model TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)""",
        )
        old.execSQL(
            """CREATE TABLE message(id INTEGER PRIMARY KEY AUTOINCREMENT,
               conv_id INTEGER NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
               role TEXT NOT NULL, content TEXT NOT NULL, created_at INTEGER NOT NULL)""",
        )
        old.execSQL("CREATE INDEX idx_message_conv ON message(conv_id)")
        old.execSQL("CREATE TABLE preset(id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, name TEXT NOT NULL, prompt TEXT NOT NULL, created_at INTEGER NOT NULL)")
        old.execSQL("CREATE TABLE rig_profile(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, server_url TEXT NOT NULL, device_token TEXT NOT NULL, created_at INTEGER NOT NULL)")
        old.execSQL("INSERT INTO conversation(title, source, model, created_at, updated_at) VALUES ('gammel', 'rig', 'local', 1, 1)")
        old.execSQL("INSERT INTO message(conv_id, role, content, created_at) VALUES (1, 'user', 'hej', 1)")
        old.execSQL("INSERT INTO message(conv_id, role, content, created_at) VALUES (1, 'assistant', 'hej selv', 2)")
        old.version = 3
        old.close()

        chatDb = ChatDb(context)
        val rows = chatDb.loadMessagesWithMedia(1L)
        assertEquals(listOf("user" to "hej", "assistant" to "hej selv"), rows.map { it.role to it.content })
        assertEquals(listOf(emptyList<String>(), emptyList()), rows.map { it.mediaJobs })
        chatDb.addMessage(1L, "assistant", "nyt billede", listOf(a))
        assertEquals(listOf(a), chatDb.loadMessagesWithMedia(1L).last().mediaJobs)
    }
}
