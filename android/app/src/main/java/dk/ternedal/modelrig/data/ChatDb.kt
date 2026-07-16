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
class ChatDb(context: Context) : SQLiteOpenHelper(context, "modelrig.db", null, 3) {

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
                 created_at INTEGER NOT NULL)""",
        )
        db.execSQL("CREATE INDEX idx_message_conv ON message(conv_id)")
        db.execSQL(PRESET_TABLE_SQL)
        db.execSQL(RIG_PROFILE_TABLE_SQL)
    }

    override fun onUpgrade(db: SQLiteDatabase, oldV: Int, newV: Int) {
        // v1 -> v2: added the preset table. v2 -> v3: added rig_profile.
        // Never drops existing data.
        if (oldV < 2) db.execSQL(PRESET_TABLE_SQL)
        if (oldV < 3) db.execSQL(RIG_PROFILE_TABLE_SQL)
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
        val out = mutableListOf<RigProfile>()
        val migrate = mutableListOf<Pair<Long, String>>() // id -> legacy plaintext to re-encrypt
        readableDatabase.rawQuery(
            "SELECT id, name, server_url, device_token FROM rig_profile ORDER BY created_at DESC",
            null,
        ).use { c ->
            while (c.moveToNext()) {
                val id = c.getLong(0)
                val raw = c.getString(3)
                // Three-way, fail-closed (audit 1.58.36): an "enc:v1:" value
                // that fails to decrypt is INVALID (corrupt, or the Keystore
                // key was lost after restore/device move) -- never treat it as
                // plaintext and never re-encrypt it: that launders garbage into
                // a valid-looking secret and destroys the profile. Server
                // tokens are lowercase hex, so true pre-encryption plaintext is
                // recognizable; anything else prefixless is old-format
                // ciphertext (1.58.17..36) and gets the prefix on rewrite.
                val tok = when (dk.ternedal.modelrig.logic.TokenFormat.classify(raw)) {
                    dk.ternedal.modelrig.logic.StoredTokenForm.ENCRYPTED_V1 ->
                        runCatching { Crypto.decrypt(raw) }.getOrElse { "" } // invalid -> re-pair
                    dk.ternedal.modelrig.logic.StoredTokenForm.LEGACY_PLAINTEXT ->
                        raw.also { migrate.add(id to it) }
                    dk.ternedal.modelrig.logic.StoredTokenForm.OLD_FORMAT_CIPHERTEXT ->
                        runCatching { Crypto.decrypt(raw) }
                            .getOrElse { "" } // undecryptable -> re-pair, never plaintext
                            .also { if (it.isNotEmpty()) migrate.add(id to it) } // rewrite with prefix
                }
                out.add(RigProfile(id, c.getString(1), c.getString(2), tok))
            }
        }
        // Re-encrypt legacy plaintext at rest, after the cursor is closed. A
        // failure here doesn't affect the values already returned.
        for ((id, plain) in migrate) {
            runCatching {
                writableDatabase.update(
                    "rig_profile",
                    ContentValues().apply { put("device_token", Crypto.encrypt(plain)) },
                    "id=?", arrayOf(id.toString()),
                )
            }
        }
        return out
    }

    fun deleteRigProfile(id: Long) {
        writableDatabase.delete("rig_profile", "id=?", arrayOf(id.toString()))
    }

    companion object {
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
