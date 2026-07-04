package dk.ternedal.modelrig.data

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

/**
 * Conversation persistence. Uses Android's built-in SQLite (no new dependency),
 * schema versioned via SQLiteOpenHelper. Messages are written once when complete
 * (streaming deltas are not persisted per-token — an in-flight reply is lost on a
 * crash; accepted V1 tradeoff).
 */
class ChatDb(context: Context) : SQLiteOpenHelper(context, "modelrig.db", null, 1) {

    data class ConvMeta(
        val id: Long,
        val title: String,
        val source: String,
        val model: String,
        val updatedAt: Long,
    )

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """CREATE TABLE conversation(
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 title TEXT NOT NULL DEFAULT '',
                 source TEXT NOT NULL,
                 model TEXT NOT NULL DEFAULT '',
                 created_at INTEGER NOT NULL,
                 updated_at INTEGER NOT NULL)""",
        )
        db.execSQL(
            """CREATE TABLE message(
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 conv_id INTEGER NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
                 role TEXT NOT NULL,
                 content TEXT NOT NULL,
                 created_at INTEGER NOT NULL)""",
        )
        db.execSQL("CREATE INDEX idx_message_conv ON message(conv_id)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldV: Int, newV: Int) {
        // v1 -> future: add ALTER TABLE migrations here, never drop data.
    }

    override fun onOpen(db: SQLiteDatabase) {
        super.onOpen(db)
        db.execSQL("PRAGMA foreign_keys=ON")
    }

    fun newConversation(source: String, model: String, title: String): Long {
        val now = System.currentTimeMillis()
        return writableDatabase.insert("conversation", null, ContentValues().apply {
            put("title", title.take(48))
            put("source", source)
            put("model", model)
            put("created_at", now)
            put("updated_at", now)
        })
    }

    fun addMessage(convId: Long, role: String, content: String) {
        val now = System.currentTimeMillis()
        val db = writableDatabase
        db.insert("message", null, ContentValues().apply {
            put("conv_id", convId)
            put("role", role)
            put("content", content)
            put("created_at", now)
        })
        db.execSQL("UPDATE conversation SET updated_at=? WHERE id=?", arrayOf(now, convId))
    }

    fun loadMessages(convId: Long): List<Pair<String, String>> {
        val out = mutableListOf<Pair<String, String>>()
        readableDatabase.rawQuery(
            "SELECT role, content FROM message WHERE conv_id=? ORDER BY id ASC",
            arrayOf(convId.toString()),
        ).use { c ->
            while (c.moveToNext()) out.add(c.getString(0) to c.getString(1))
        }
        return out
    }

    fun listConversations(): List<ConvMeta> {
        val out = mutableListOf<ConvMeta>()
        readableDatabase.rawQuery(
            "SELECT id, title, source, model, updated_at FROM conversation ORDER BY updated_at DESC",
            null,
        ).use { c ->
            while (c.moveToNext()) out.add(
                ConvMeta(c.getLong(0), c.getString(1), c.getString(2), c.getString(3), c.getLong(4)),
            )
        }
        return out
    }

    fun latestConversationId(): Long? =
        readableDatabase.rawQuery(
            "SELECT id FROM conversation ORDER BY updated_at DESC LIMIT 1", null,
        ).use { c -> if (c.moveToFirst()) c.getLong(0) else null }

    fun conversationMeta(convId: Long): ConvMeta? =
        readableDatabase.rawQuery(
            "SELECT id, title, source, model, updated_at FROM conversation WHERE id=?",
            arrayOf(convId.toString()),
        ).use { c ->
            if (c.moveToFirst()) ConvMeta(c.getLong(0), c.getString(1), c.getString(2), c.getString(3), c.getLong(4)) else null
        }

    fun deleteConversation(convId: Long) {
        writableDatabase.delete("conversation", "id=?", arrayOf(convId.toString()))
    }
}
