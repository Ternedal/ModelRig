package dk.ternedal.modelrig.logic

/**
 * Pure fail-closed boundary for durable encrypted credential writes.
 *
 * AndroidKeyStore encryption and SharedPreferences persistence can fail
 * independently. Callers only get true after both have completed, so UI code
 * never treats an asynchronous or rejected write as a saved credential.
 */
object CredentialPersistence {
    fun commit(write: () -> Boolean): Boolean =
        runCatching(write).getOrDefault(false)

    fun commitEncrypted(
        plaintext: String,
        encrypt: (String) -> String,
        persist: (String) -> Boolean,
    ): Boolean {
        if (plaintext.isEmpty()) return false

        val ciphertext = runCatching { encrypt(plaintext) }.getOrNull()
            ?.takeIf { it.isNotEmpty() }
            ?: return false
        return commit { persist(ciphertext) }
    }
}
