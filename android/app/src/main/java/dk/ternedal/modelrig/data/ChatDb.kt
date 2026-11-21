package dk.ternedal.modelrig.data

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import dk.ternedal.modelrig.logic.RigProfileTokenResolution
import dk.ternedal.modelrig.logic.RigProfileTokenResolver

/**
 * Conversation persistence. Uses Android's built-in SQLite (no new dependency),
 * schema versioned via SQLiteOpenHelper. Messages are written once when complete
 * (streaming deltas are not persisted per-token — an in-flight reply is lost on a
 * crash; accepted V1 tradeoff).
 */
class ChatDb(context: Context) : SQLiteOpenHelper(context, "modelrig.db", null, SCHEMA_VERSION) {

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
                 created_at INTEGER NOT NULL,
                 media_jobs TEXT NOT NULL DEFAULT '')""",
        )
        db.execSQL("CREATE INDEX idx_message_conv ON message(conv_id)")
        db.execSQL(PRESET_TABLE_SQL)
        db.execSQL(RIG_PROFILE_TABLE_SQL)
    }

    override fun onUpgrade(db: SQLiteDatabase, oldV: Int, newV: Int) {
        // v1 -> v2: added the preset table. v2 -> v3: added rig_profile.
        // message.media_jobs (#2419) is NOT a version step: see ensureMediaJobsColumn.
        if (oldV < 2) db.execSQL(PRESET_TABLE_SQL)
        if (oldV < 3) db.execSQL(RIG_PROFILE_TABLE_SQL)
    }

    override fun onOpen(db: SQLiteDatabase) {
        super.onOpen(db)
        db.execSQL("PRAGMA foreign_keys=ON")
        ensureMediaJobsColumn(db)
    }

    /**
     * #2419: `message.media_jobs` -- the image jobs an assistant turn queued, so the
     * bubble survives an app restart -- is added here, when it is missing, and **not**
     * through a schema version bump.
     *
     * A bump would make the database unreadable to the app version before it:
     * SQLiteOpenHelper refuses to open a newer database ("Can't downgrade database
     * from version 4 to 3"), and that app has no onDowngrade. So trying a build with
     * media bubbles and going back to the released app -- or an updater rollback to
     * it -- would crash on every start until the app's data, every stored
     * conversation, was cleared. Without the bump the older app opens the same file
     * and never notices the extra column: its INSERT gets the default, its SELECT
     * names its own columns.
     */
    private fun ensureMediaJobsColumn(db: SQLiteDatabase) {
        if (db.isReadOnly) return
        val present = db.rawQuery("PRAGMA table_info(message)", null).use { c ->
            val name = c.getColumnIndex("name")
            var found = false
            while (name >= 0 && c.moveToNext()) if (c.getString(name) == "media_jobs") found = true
            found
        }
        if (!present) db.execSQL(MEDIA_JOBS_COLUMN_SQL)
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

    /**
     * #2419: [mediaJobs] are the 32-hex ids of image jobs the turn queued; stored
     * comma-separated, only well-formed ids, so a restart redraws the bubbles.
     */
    fun addMessage(convId: Long, role: String, content: String, mediaJobs: List<String> = emptyList()) {
        val now = System.currentTimeMillis()
        val db = writableDatabase
        // If the conversation was deleted mid-send, skip rather than insert an
        // orphan / touch a gone row. (SQLiteDatabase.insert wouldn't throw here,
        // but the desktop path with JDBC does -- keep both consistent.)
        db.rawQuery("SELECT 1 FROM conversation WHERE id=?", arrayOf(convId.toString())).use {
            if (!it.moveToFirst()) return
        }
        db.insert("message", null, ContentValues().apply {
            put("conv_id", convId)
            put("role", role)
            put("content", content)
            put("created_at", now)
            put("media_jobs", encodeMediaJobs(mediaJobs))
        })
        db.execSQL("UPDATE conversation SET updated_at=? WHERE id=?", arrayOf(now, convId))
    }

    /** One stored message with what the bubble needs; [loadMessages] is the text-only view of the same rows. */
    data class StoredMessage(val role: String, val content: String, val mediaJobs: List<String>)

    fun loadMessagesWithMedia(convId: Long): List<StoredMessage> {
        val out = mutableListOf<StoredMessage>()
        readableDatabase.rawQuery(
            "SELECT role, content, media_jobs FROM message WHERE conv_id=? ORDER BY id ASC",
            arrayOf(convId.toString()),
        ).use { c ->
            while (c.moveToNext()) out.add(StoredMessage(c.getString(0), c.getString(1), decodeMediaJobs(c.getString(2))))
        }
        return out
    }

    /**
     * Atomically persist a completed spoken turn in the intended conversation.
     * A failed second insert rolls back the first; a removed conversation gets
     * no orphan records. Empty turns do not update conversation recency.
     */
    fun addCompletedVoiceTurn(convId: Long, transcript: String, reply: String) {
        if (transcript.isBlank() && reply.isBlank()) return
        val db = writableDatabase
        db.beginTransaction()
        try {
            db.rawQuery("SELECT 1 FROM conversation WHERE id=?", arrayOf(convId.toString())).use {
                if (!it.moveToFirst()) {
                    db.setTransactionSuccessful()
                    return
                }
            }
            val now = System.currentTimeMillis()
            var inserted = 0
            for ((role, content) in listOf("user" to transcript, "assistant" to reply)) {
                if (content.isBlank()) continue
                db.insertOrThrow("message", null, ContentValues().apply {
                    put("conv_id", convId)
                    put("role", role)
                    put("content", content)
                    put("created_at", now)
                })
                inserted++
            }
            if (inserted > 0) {
                db.execSQL("UPDATE conversation SET updated_at=? WHERE id=?", arrayOf(now, convId))
            }
            db.setTransactionSuccessful()
        } finally {
            db.endTransaction()
        }
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

    fun renameConversation(convId: Long, newTitle: String) {
        writableDatabase.update(
            "conversation",
            ContentValues().apply { put("title", newTitle.take(80)) },
            "id=?", arrayOf(convId.toString()),
        )
    }

    // ---- presets (saved system instructions per source, for quick-switch) ----

    fun savePreset(source: String, name: String, prompt: String): Long {
        return writableDatabase.insert("preset", null, ContentValues().apply {
            put("source", source)
            put("name", name.take(40))
            put("prompt", prompt)
            put("created_at", System.currentTimeMillis())
        })
    }

    fun listPresets(source: String): List<PresetMeta> {
        val out = mutableListOf<PresetMeta>()
        readableDatabase.rawQuery(
            "SELECT id, source, name, prompt FROM preset WHERE source=? ORDER BY created_at DESC",
            arrayOf(source),
        ).use { c ->
            while (c.moveToNext()) out.add(PresetMeta(c.getLong(0), c.getString(1), c.getString(2), c.getString(3)))
        }
        return out
    }

    fun deletePreset(id: Long) {
        writableDatabase.delete("preset", "id=?", arrayOf(id.toString()))
    }

    // ---- rig profiles (named server-url + device-token pairs, for quick-switch
    // between e.g. "Hjemme" and "Arbejde" without re-pairing each time) ----

    data class RigProfile(val id: Long, val name: String, val serverUrl: String, val deviceToken: String)

    private data class StoredRigProfile(
        val id: Long,
        val name: String,
        val serverUrl: String,
        val rawToken: String,
    )

    fun saveRigProfile(name: String, serverUrl: String, deviceToken: String): Long {
        return writableDatabase.insert("rig_profile", null, ContentValues().apply {
            put("name", name.take(40))
            put("server_url", serverUrl)
            // Encrypted at rest (Crypto = Keystore AES-GCM). The column type is
            // unchanged; it now holds ciphertext instead of the raw token.
            put("device_token", Crypto.encrypt(deviceToken))
            put("created_at", System.currentTimeMillis())
        })
    }

    fun listRigProfiles(): List<RigProfile> {
        val db = writableDatabase
        db.beginTransaction()
        try {
            val stored = mutableListOf<StoredRigProfile>()
            db.rawQuery(
                "SELECT id, name, server_url, device_token FROM rig_profile ORDER BY created_at DESC",
                null,
            ).use { c ->
                while (c.moveToNext()) {
                    stored.add(
                        StoredRigProfile(
                            id = c.getLong(0),
                            name = c.getString(1),
                            serverUrl = c.getString(2),
                            rawToken = c.getString(3),
                        ),
                    )
                }
            }

            val out = ArrayList<RigProfile>(stored.size)
            for (profile in stored) {
                when (
                    val resolved = RigProfileTokenResolver.resolve(
                        raw = profile.rawToken,
                        decrypt = Crypto::decrypt,
                        encrypt = Crypto::encrypt,
                    )
                ) {
                    is RigProfileTokenResolution.Ready ->
                        out.add(RigProfile(profile.id, profile.name, profile.serverUrl, resolved.token))

                    is RigProfileTokenResolution.Migration -> {
                        // The encrypted replacement MUST be committed before the
                        // plaintext token can leave this method. A failed Keystore
                        // operation or a missing row aborts and rolls back the whole
                        // read instead of quietly using a cleartext credential.
                        val updated = db.update(
                            "rig_profile",
                            ContentValues().apply { put("device_token", resolved.envelope) },
                            "id=?",
                            arrayOf(profile.id.toString()),
                        )
                        check(updated == 1) {
                            "Rig profile ${profile.id} disappeared during credential migration"
                        }
                        out.add(RigProfile(profile.id, profile.name, profile.serverUrl, resolved.token))
                    }

                    RigProfileTokenResolution.Invalid ->
                        // Corrupt/current ciphertext or an old envelope whose key
                        // was lost is never exposed as plaintext. Keep the profile
                        // visible so the user can remove it or pair it again.
                        out.add(RigProfile(profile.id, profile.name, profile.serverUrl, ""))
                }
            }

            db.setTransactionSuccessful()
            return out
        } finally {
            db.endTransaction()
        }
    }

    fun deleteRigProfile(id: Long) {
        writableDatabase.delete("rig_profile", "id=?", arrayOf(id.toString()))
    }

    companion object {
        /**
         * The schema version the released app (2.0.21) writes and can open. Raising it
         * makes every older app version crash on this database; do that only together
         * with a plan for going back (see [ensureMediaJobsColumn]).
         */
        const val SCHEMA_VERSION = 3
        private const val MEDIA_JOBS_COLUMN_SQL =
            "ALTER TABLE message ADD COLUMN media_jobs TEXT NOT NULL DEFAULT ''"
        private val JOB_ID = Regex("^[0-9a-f]{32}$")

        /** Comma-separated, well-formed ids only; anything else is dropped on write. */
        fun encodeMediaJobs(ids: List<String>): String = ids.filter { JOB_ID.matches(it) }.distinct().joinToString(",")

        fun decodeMediaJobs(stored: String?): List<String> =
            stored.orEmpty().split(',').filter { JOB_ID.matches(it) }.distinct()
        private const val PRESET_TABLE_SQL =
            """CREATE TABLE IF NOT EXISTS preset(
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 source TEXT NOT NULL,
                 name TEXT NOT NULL,
                 prompt TEXT NOT NULL,
                 created_at INTEGER NOT NULL)"""
        private const val RIG_PROFILE_TABLE_SQL =
            """CREATE TABLE IF NOT EXISTS rig_profile(
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 name TEXT NOT NULL,
                 server_url TEXT NOT NULL,
                 device_token TEXT NOT NULL,
                 created_at INTEGER NOT NULL)"""
    }
}
