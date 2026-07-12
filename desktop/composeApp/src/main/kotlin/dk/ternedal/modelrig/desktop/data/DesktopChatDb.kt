package dk.ternedal.modelrig.desktop.data

import java.io.File
import java.sql.Connection
import java.sql.DriverManager
import java.sql.Statement

/**
 * Conversation persistence for desktop, mirroring Android's ChatDb.kt schema
 * (conversation + message tables) so the two clients are conceptually
 * interchangeable. Plain JDBC (org.xerial:sqlite-jdbc), no ORM -- matches the
 * project's SQLite-first, minimal-dependency convention. Android has SQLite
 * built in; plain JVM needs this explicit embedded driver (single file, no
 * server process, no network).
 *
 * DB file: `~/.modelrig/modelrig.db` (created on first use).
 *
 * Scope note (v0.19.3): persistence + silent resume-of-latest-conversation on
 * startup are implemented. A conversation *browser* (list/switch/delete, like
 * Android's Samtaler screen) is NOT — that's a reasonable next increment, kept
 * out to land this in a reviewable chunk.
 *
 * Concurrency note: a single JDBC `Connection` is held for the app's lifetime.
 * JDBC connections aren't inherently thread-safe, but this app only ever has
 * one send() in flight at a time (`busy` blocks new sends in the UI), and all
 * DB calls for a given send happen sequentially on one coroutine -- so this is
 * safe in practice, not because the driver guarantees it.
 *
 * Messages are written once when complete (streaming deltas are not persisted
 * per-token) -- an in-flight reply is lost on a crash; same accepted tradeoff
 * as Android.
 */
class DesktopChatDb(dbPath: String = defaultDbPath()) {

    data class ConvMeta(
        val id: Long,
        val title: String,
        val source: String,
        val model: String,
        val updatedAt: Long,
    )

    data class PresetMeta(
        val id: Long,
        val source: String,
        val name: String,
        val prompt: String,
    )

    private val conn: Connection = DriverManager.getConnection("jdbc:sqlite:$dbPath").also { c ->
        c.createStatement().use { it.execute("PRAGMA foreign_keys=ON") }
        c.createStatement().use { st ->
            st.execute(
                """CREATE TABLE IF NOT EXISTS conversation(
                     id INTEGER PRIMARY KEY AUTOINCREMENT,
                     title TEXT NOT NULL DEFAULT '',
                     source TEXT NOT NULL,
                     model TEXT NOT NULL DEFAULT '',
                     created_at INTEGER NOT NULL,
                     updated_at INTEGER NOT NULL)""",
            )
            st.execute(
                """CREATE TABLE IF NOT EXISTS message(
                     id INTEGER PRIMARY KEY AUTOINCREMENT,
                     conv_id INTEGER NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
                     role TEXT NOT NULL,
                     content TEXT NOT NULL,
                     created_at INTEGER NOT NULL)""",
            )
            st.execute("CREATE INDEX IF NOT EXISTS idx_message_conv ON message(conv_id)")
            st.execute(
                """CREATE TABLE IF NOT EXISTS setting(
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )""",
            )
            st.executeUpdate(
                """CREATE TABLE IF NOT EXISTS preset(
                     id INTEGER PRIMARY KEY AUTOINCREMENT,
                     source TEXT NOT NULL,
                     name TEXT NOT NULL,
                     prompt TEXT NOT NULL,
                     created_at INTEGER NOT NULL)""",
            )
        }
    }

    fun newConversation(source: String, model: String, title: String): Long {
        val now = System.currentTimeMillis()
        conn.prepareStatement(
            "INSERT INTO conversation(title, source, model, created_at, updated_at) VALUES (?,?,?,?,?)",
            Statement.RETURN_GENERATED_KEYS,
        ).use { ps ->
            ps.setString(1, title.take(48))
            ps.setString(2, source)
            ps.setString(3, model)
            ps.setLong(4, now)
            ps.setLong(5, now)
            ps.executeUpdate()
            ps.generatedKeys.use { rs -> rs.next(); return rs.getLong(1) }
        }
    }

    fun addMessage(convId: Long, role: String, content: String) {
        val now = System.currentTimeMillis()
        // Guard against a race: if the conversation was deleted between the send
        // starting and the reply finalizing, inserting would throw a FOREIGN KEY
        // constraint and crash the app. Skip silently instead -- the conversation
        // is gone, so its messages have nowhere to live anyway.
        conn.prepareStatement("SELECT 1 FROM conversation WHERE id=?").use { ps ->
            ps.setLong(1, convId)
            ps.executeQuery().use { if (!it.next()) return }
        }
        conn.prepareStatement("INSERT INTO message(conv_id, role, content, created_at) VALUES (?,?,?,?)").use { ps ->
            ps.setLong(1, convId); ps.setString(2, role); ps.setString(3, content); ps.setLong(4, now)
            ps.executeUpdate()
        }
        conn.prepareStatement("UPDATE conversation SET updated_at=? WHERE id=?").use { ps ->
            ps.setLong(1, now); ps.setLong(2, convId); ps.executeUpdate()
        }
    }

    fun loadMessages(convId: Long): List<Pair<String, String>> {
        val out = mutableListOf<Pair<String, String>>()
        conn.prepareStatement("SELECT role, content FROM message WHERE conv_id=? ORDER BY id ASC").use { ps ->
            ps.setLong(1, convId)
            ps.executeQuery().use { rs -> while (rs.next()) out.add(rs.getString(1) to rs.getString(2)) }
        }
        return out
    }

    fun listConversations(): List<ConvMeta> {
        val out = mutableListOf<ConvMeta>()
        conn.createStatement().use { st ->
            st.executeQuery(
                "SELECT id, title, source, model, updated_at FROM conversation ORDER BY updated_at DESC",
            ).use { rs ->
                while (rs.next()) {
                    out.add(ConvMeta(rs.getLong(1), rs.getString(2), rs.getString(3), rs.getString(4), rs.getLong(5)))
                }
            }
        }
        return out
    }

    fun latestConversationId(): Long? {
        conn.createStatement().use { st ->
            st.executeQuery("SELECT id FROM conversation ORDER BY updated_at DESC LIMIT 1").use { rs ->
                return if (rs.next()) rs.getLong(1) else null
            }
        }
    }

    fun conversationMeta(convId: Long): ConvMeta? {
        conn.prepareStatement(
            "SELECT id, title, source, model, updated_at FROM conversation WHERE id=?",
        ).use { ps ->
            ps.setLong(1, convId)
            ps.executeQuery().use { rs ->
                return if (rs.next()) {
                    ConvMeta(rs.getLong(1), rs.getString(2), rs.getString(3), rs.getString(4), rs.getLong(5))
                } else null
            }
        }
    }

    fun deleteConversation(convId: Long) {
        conn.prepareStatement("DELETE FROM conversation WHERE id=?").use { ps ->
            ps.setLong(1, convId); ps.executeUpdate()
        }
    }

    // Rename a conversation's title. Mirrors Android's ChatDb.renameConversation
    // (UPDATE conversation SET title=? WHERE id=?). Title is trimmed by the
    // caller; an empty title is allowed (the list falls back to "(uden titel)").
    fun renameConversation(convId: Long, newTitle: String) {
        conn.prepareStatement("UPDATE conversation SET title=? WHERE id=?").use { ps ->
            ps.setString(1, newTitle); ps.setLong(2, convId); ps.executeUpdate()
        }
    }

    // Render a conversation as readable markdown for export (desktop has no
    // Android share-sheet -- the panel writes this to a .md file / clipboard).
    // Same shape as Android's share text: "# <title>" then alternating
    // "**Du:**" / "**Model:**" blocks.
    fun conversationAsMarkdown(convId: Long): String {
        val meta = conversationMeta(convId)
        val title = meta?.title?.ifBlank { "Samtale" } ?: "Samtale"
        val sb = StringBuilder("# $title\n\n")
        loadMessages(convId).forEach { (role, content) ->
            val who = if (role == "user") "**Du:**" else "**Model:**"
            sb.append(who).append('\n').append(content).append("\n\n")
        }
        return sb.toString().trimEnd() + "\n"
    }

    // ---- presets (saved system instructions per source, for quick-switch) ----

    fun savePreset(source: String, name: String, prompt: String): Long {
        conn.prepareStatement(
            "INSERT INTO preset(source, name, prompt, created_at) VALUES (?,?,?,?)",
            Statement.RETURN_GENERATED_KEYS,
        ).use { ps ->
            ps.setString(1, source); ps.setString(2, name.take(40)); ps.setString(3, prompt)
            ps.setLong(4, System.currentTimeMillis())
            ps.executeUpdate()
            ps.generatedKeys.use { rs -> rs.next(); return rs.getLong(1) }
        }
    }

    fun listPresets(source: String): List<PresetMeta> {
        val out = mutableListOf<PresetMeta>()
        conn.prepareStatement("SELECT id, source, name, prompt FROM preset WHERE source=? ORDER BY created_at DESC").use { ps ->
            ps.setString(1, source)
            ps.executeQuery().use { rs ->
                while (rs.next()) out.add(PresetMeta(rs.getLong(1), rs.getString(2), rs.getString(3), rs.getString(4)))
            }
        }
        return out
    }

    fun deletePreset(id: Long) {
        conn.prepareStatement("DELETE FROM preset WHERE id=?").use { ps ->
            ps.setLong(1, id); ps.executeUpdate()
        }
    }

    companion object {
        fun defaultDbPath(): String {
            val dir = File(System.getProperty("user.home"), ".modelrig")
            if (!dir.exists()) dir.mkdirs()
            return File(dir, "modelrig.db").absolutePath
        }
    }

    /** Persisted UI/connection settings (v1.35.0 desktop love): the app used
     *  to forget EVERYTHING between launches (env vars or retyping). */
    fun getSetting(key: String): String? = conn.prepareStatement(
        "SELECT value FROM setting WHERE key = ?").use { st ->
        st.setString(1, key)
        st.executeQuery().use { rs -> if (rs.next()) rs.getString(1) else null }
    }

    fun putSetting(key: String, value: String) {
        conn.prepareStatement(
            "INSERT INTO setting(key, value) VALUES(?, ?) " +
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value").use { st ->
            st.setString(1, key); st.setString(2, value); st.executeUpdate()
        }
    }
}
