package dk.ternedal.modelrig.logic

/**
 * Fail-closed policy for persisting encrypted credentials.
 *
 * Android's SharedPreferences `apply()` cannot report whether data reached the
 * backing file. Credential writes therefore use synchronous `commit()` and only
 * report success when encryption and the storage commit both succeed.
 */
object CredentialCommit {
    fun save(
        value: String?,
        encrypt: (String) -> String,
        commit: (encryptedValue: String?) -> Boolean,
    ): Boolean = try {
        val encrypted = value
            ?.takeUnless { it.isEmpty() }
            ?.let(encrypt)
        commit(encrypted)
    } catch (_: Exception) {
        false
    }

    fun clear(commit: () -> Boolean): Boolean = try {
        commit()
    } catch (_: Exception) {
        false
    }
}
