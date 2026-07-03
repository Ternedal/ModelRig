package dk.ternedal.modelrig.data

import android.content.Context

/**
 * V1 token storage in plain SharedPreferences.
 *
 * NOTE: stores the device bearer token in cleartext prefs — acceptable for a
 * LAN-only V1. For hardening, move to DataStore + an Android Keystore-wrapped
 * key. (Jetpack Security's EncryptedSharedPreferences is deprecated/unmaintained,
 * so it is intentionally NOT used here.)
 */
class TokenStore(context: Context) {
    private val prefs = context.getSharedPreferences("modelrig", Context.MODE_PRIVATE)

    var baseUrl: String?
        get() = prefs.getString("base_url", null)
        set(v) { prefs.edit().putString("base_url", v).apply() }

    var token: String?
        get() = prefs.getString("token", null)
        set(v) { prefs.edit().putString("token", v).apply() }

    var model: String
        get() = prefs.getString("model", "qwen2.5-coder:7b") ?: "qwen2.5-coder:7b"
        set(v) { prefs.edit().putString("model", v).apply() }

    fun clear() { prefs.edit().clear().apply() }
}
