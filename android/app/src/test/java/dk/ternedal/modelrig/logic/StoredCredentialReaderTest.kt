package dk.ternedal.modelrig.logic

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Test

class StoredCredentialReaderTest {
    @Test
    fun missingStorageDoesNotInvokeTheDecryptor() {
        var called = false

        val result = StoredCredentialReader.read(null) {
            called = true
            "unused"
        }

        assertSame(StoredCredentialRead.Missing, result)
        assertFalse(called)
    }

    @Test
    fun decryptableCiphertextIsReady() {
        val result = StoredCredentialReader.read("enc:v1:ciphertext") { "device-token" }

        assertEquals(StoredCredentialRead.Ready("device-token"), result)
    }

    @Test
    fun decryptionFailureIsInvalidRatherThanMissing() {
        val result = StoredCredentialReader.read("enc:v1:corrupt") {
            throw IllegalStateException("Keystore key no longer exists")
        }

        assertSame(StoredCredentialRead.Invalid, result)
    }

    @Test
    fun emptyDecryptedCredentialIsInvalid() {
        val result = StoredCredentialReader.read("enc:v1:empty") { "" }

        assertSame(StoredCredentialRead.Invalid, result)
    }
}
