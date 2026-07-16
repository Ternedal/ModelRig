package dk.ternedal.modelrig.logic

/**
 * What a stored credential string IS, decided before anyone tries to decrypt it.
 *
 * This looks like a triviality and is not: getting it wrong destroyed rig
 * profiles. Until 1.58.37 the reader tried to decrypt and treated ANY failure
 * as "this must be old plaintext" -- so a corrupt value, or a perfectly good
 * ciphertext whose Keystore key was lost after a restore or device move, was
 * returned raw AS A TOKEN and then re-encrypted as if it were one. That
 * laundered garbage into a valid-looking secret and left a profile that could
 * never work again.
 *
 * The fix was to make ciphertext self-identifying and to classify on SHAPE
 * first. That rule now lives here -- pure, table-tested (TokenFormatTest) --
 * instead of inline in a database cursor where no test could reach it.
 */
enum class StoredTokenForm {
    /** "enc:v1:..." -- ours. If this fails to decrypt it is INVALID, never plaintext. */
    ENCRYPTED_V1,

    /** A pre-encryption token, recognisable by the server's own shape. Migrate it. */
    LEGACY_PLAINTEXT,

    /**
     * Prefixless and not token-shaped: ciphertext from 1.58.17..36, before the
     * prefix existed. Decrypt and rewrite it WITH the prefix if possible; if
     * not, it is invalid -- and still never plaintext.
     */
    OLD_FORMAT_CIPHERTEXT,
}

object TokenFormat {
    /**
     * Canonical here, in the layer with no Android dependencies; data.Crypto
     * re-exports it. One definition -- a second copy of this string is how the
     * prefix would quietly stop matching itself.
     */
    const val PREFIX = "enc:v1:"

    /**
     * The server mints device tokens as lowercase hex. That shape is the ONLY
     * thing allowed to read as pre-encryption plaintext: being strict here is
     * what stops a failed decrypt from being mistaken for a credential.
     */
    private val SERVER_TOKEN = Regex("[0-9a-f]{16,}")

    fun classify(raw: String): StoredTokenForm = when {
        raw.startsWith(PREFIX) -> StoredTokenForm.ENCRYPTED_V1
        SERVER_TOKEN.matches(raw) -> StoredTokenForm.LEGACY_PLAINTEXT
        else -> StoredTokenForm.OLD_FORMAT_CIPHERTEXT
    }
}
