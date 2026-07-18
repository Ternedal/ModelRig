package dk.ternedal.modelrig.logic

/**
 * Result of reading one encrypted credential from local storage.
 *
 * Missing and invalid are deliberately different. A missing credential means
 * setup has not happened yet; invalid means ciphertext exists but the current
 * Keystore can no longer decrypt it (for example after restore/device move) and
 * the user must pair or enter the key again.
 */
sealed interface StoredCredentialRead {
    data object Missing : StoredCredentialRead
    data class Ready(val value: String) : StoredCredentialRead
    data object Invalid : StoredCredentialRead
}

/** Pure boundary around decryption so credential-state semantics stay testable. */
object StoredCredentialReader {
    fun read(
        raw: String?,
        decrypt: (String) -> String,
    ): StoredCredentialRead {
        if (raw.isNullOrEmpty()) return StoredCredentialRead.Missing

        return runCatching { decrypt(raw) }
            .fold(
                onSuccess = { plain ->
                    if (plain.isEmpty()) StoredCredentialRead.Invalid
                    else StoredCredentialRead.Ready(plain)
                },
                onFailure = { StoredCredentialRead.Invalid },
            )
    }
}
