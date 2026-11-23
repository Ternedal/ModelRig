package dk.ternedal.modelrig.desktop.data

import dk.ternedal.modelrig.desktop.net.DesktopMediaContract
import dk.ternedal.modelrig.desktop.net.DesktopMediaJobRef
import dk.ternedal.modelrig.desktop.net.DesktopMediaKind
import java.nio.file.Files
import java.nio.file.Path
import java.sql.DriverManager
import kotlin.io.path.deleteIfExists
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse

/**
 * #2419: the picture/clip jobs an assistant message queued are stored with the
 * message (job ids only), so reopening a conversation shows its media bubbles
 * again. An existing database without the column is upgraded in place.
 */
class DesktopChatDbMediaJobsTest {
    private val image = DesktopMediaJobRef("0123456789abcdef0123456789abcdef", DesktopMediaKind.IMAGE)
    private val video = DesktopMediaJobRef("fedcba9876543210fedcba9876543210", DesktopMediaKind.VIDEO)

    @Test
    fun aMessageKeepsItsJobsAndEveryOtherMessageHasNone() {
        withPath { path ->
            DesktopChatDb(path.toString()).use { db ->
                val conv = db.newConversation(source = "tools", model = "qwen3:14b", title = "billede")
                db.addMessage(conv, "user", "lav et billede og en video")
                db.addMessage(conv, "assistant", "Begge er på vej.", DesktopMediaContract.encodeRefs(listOf(image, video)))
                db.addMessage(conv, "assistant", "Et almindeligt svar.")

                val rows = db.loadMessages(conv)
                assertEquals(listOf("user", "assistant", "assistant"), rows.map { it.role })
                assertEquals(emptyList(), DesktopMediaContract.decodeRefs(rows[0].mediaJobs))
                assertEquals(listOf(image, video), DesktopMediaContract.decodeRefs(rows[1].mediaJobs))
                assertEquals("", rows[2].mediaJobs)
                // Only ids are stored: the prompt lives in the user's own message, nowhere else.
                assertFalse(rows[1].mediaJobs.contains("billede"))
                // The text-only views are untouched by the extra column.
                val (role, content) = rows[1]
                assertEquals("assistant" to "Begge er på vej.", role to content)
                assertFalse(db.conversationAsMarkdown(conv).contains(image.jobId))
            }
            // Reopening the same file finds the column and the jobs again.
            DesktopChatDb(path.toString()).use { db ->
                val conv = db.latestConversationId()!!
                assertEquals(listOf(image, video), DesktopMediaContract.decodeRefs(db.loadMessages(conv)[1].mediaJobs))
            }
        }
    }

    @Test
    fun aDatabaseFromBeforeTheColumnIsUpgradedAndItsOldRowsHaveNoJobs() {
        withPath { path ->
            DriverManager.getConnection("jdbc:sqlite:$path").use { c ->
                c.createStatement().use { st ->
                    st.execute(
                        """CREATE TABLE conversation(
                             id INTEGER PRIMARY KEY AUTOINCREMENT,
                             title TEXT NOT NULL DEFAULT '',
                             source TEXT NOT NULL,
                             model TEXT NOT NULL DEFAULT '',
                             created_at INTEGER NOT NULL,
                             updated_at INTEGER NOT NULL)""",
                    )
                    st.execute(
                        """CREATE TABLE message(
                             id INTEGER PRIMARY KEY AUTOINCREMENT,
                             conv_id INTEGER NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
                             role TEXT NOT NULL,
                             content TEXT NOT NULL,
                             created_at INTEGER NOT NULL)""",
                    )
                    st.execute("INSERT INTO conversation(title, source, model, created_at, updated_at) VALUES ('gammel','tools','m',1,1)")
                    st.execute("INSERT INTO message(conv_id, role, content, created_at) VALUES (1,'assistant','fra før',1)")
                }
            }
            DesktopChatDb(path.toString()).use { db ->
                val old = db.loadMessages(1)
                assertEquals(1, old.size)
                assertEquals("fra før", old[0].content)
                assertEquals("", old[0].mediaJobs)
                db.addMessage(1, "assistant", "nyt", DesktopMediaContract.encodeRefs(listOf(image)))
                assertEquals(listOf(image), DesktopMediaContract.decodeRefs(db.loadMessages(1)[1].mediaJobs))
            }
            // A second open must not try to add the column again.
            DesktopChatDb(path.toString()).use { db -> assertEquals(2, db.loadMessages(1).size) }
        }
    }

    private fun withPath(block: (Path) -> Unit) {
        val path = Files.createTempFile("modelrig-media-jobs-", ".db")
        try {
            block(path)
        } finally {
            path.deleteIfExists()
            Path.of("$path-journal").deleteIfExists()
            Path.of("$path-shm").deleteIfExists()
            Path.of("$path-wal").deleteIfExists()
        }
    }
}
