package dk.ternedal.modelrig.logic

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The rule that decides whether a stored string is a secret we can read, a
 * secret we must migrate, or garbage we must refuse. Every row here is a real
 * shape that has been in someone's database.
 */
class TokenFormatTest {

    @Test
    fun ourOwnCiphertextIsRecognisedByItsPrefix() {
        assertEquals(
            StoredTokenForm.ENCRYPTED_V1,
            TokenFormat.classify("enc:v1:AAECAwQFBgcICQoLDA0ODw=="),
        )
    }

    @Test
    fun aServerTokenIsLegacyPlaintext() {
        // What the rig actually mints: lowercase hex, 32 chars here.
        assertEquals(
            StoredTokenForm.LEGACY_PLAINTEXT,
            TokenFormat.classify("a1b2c3d4e5f60718293a4b5c6d7e8f90"),
        )
    }

    @Test
    fun prefixlessNonTokenIsOldFormatCiphertext() {
        // 1.58.17..36 wrote base64 with no prefix. It still decrypts; it just
        // has to be recognised as ciphertext, not as a token.
        assertEquals(
            StoredTokenForm.OLD_FORMAT_CIPHERTEXT,
            TokenFormat.classify("q83vASNFZ4mrze8BI0VniavN7wEjRWeJ"),
        )
    }

    // --- the bug this rule exists to prevent --------------------------------

    @Test
    fun corruptCiphertextIsNeverClassifiedAsPlaintext() {
        // THE one that destroyed profiles: a prefixed value whose bytes are
        // damaged (or whose Keystore key vanished after a restore) must stay
        // ENCRYPTED_V1 -- so the reader refuses it and asks for re-pairing --
        // and must never fall through to "looks like plaintext, migrate it",
        // which re-encrypted garbage into a valid-looking secret.
        assertEquals(
            StoredTokenForm.ENCRYPTED_V1,
            TokenFormat.classify("enc:v1:!!!not-base64-at-all!!!"),
        )
        assertEquals(
            StoredTokenForm.ENCRYPTED_V1,
            TokenFormat.classify("enc:v1:"),
        )
    }

    @Test
    fun onlyTheServersOwnShapeMayReadAsPlaintext() {
        // Strictness is the safety: anything that is not exactly a server
        // token falls to ciphertext handling, which fails closed.
        val notTokens = listOf(
            "A1B2C3D4E5F60718293A4B5C6D7E8F90", // uppercase: the rig never mints this
            "a1b2c3d4",                          // too short to be a token
            "zzzznotanhexstring",                // not hex
            "a1b2 c3d4e5f60718293a4b5c6d7e8f90", // whitespace
            "",                                  // empty
        )
        for (v in notTokens) {
            assertEquals(
                "must not read as plaintext: ${v.take(20)}",
                StoredTokenForm.OLD_FORMAT_CIPHERTEXT,
                TokenFormat.classify(v),
            )
        }
    }

    @Test
    fun thePrefixHasExactlyOneDefinition() {
        // data.Crypto re-exports this constant rather than repeating the
        // literal. If someone reintroduces a second copy and they drift, every
        // stored value stops matching itself -- silently.
        assertEquals("enc:v1:", TokenFormat.PREFIX)
    }
}
