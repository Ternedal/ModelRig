package dk.ternedal.modelrig.logic

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CredentialPersistenceTest {
    @Test
    fun encryptionFailureNeverAttemptsPersistence() {
        var persisted = false

        val saved = CredentialPersistence.commitEncrypted(
            plaintext = "secret",
            encrypt = { error("keystore unavailable") },
            persist = { persisted = true; true },
        )

        assertFalse(saved)
        assertFalse(persisted)
    }

    @Test
    fun rejectedCommitIsReportedAsFailure() {
        var received: String? = null

        val saved = CredentialPersistence.commitEncrypted(
            plaintext = "secret",
            encrypt = { "cipher:$it" },
            persist = { received = it; false },
        )

        assertFalse(saved)
        assertEquals("cipher:secret", received)
    }

    @Test
    fun successRequiresEncryptionAndConfirmedCommit() {
        val calls = mutableListOf<String>()

        val saved = CredentialPersistence.commitEncrypted(
            plaintext = "secret",
            encrypt = { calls += "encrypt"; "ciphertext" },
            persist = { calls += "persist:$it"; true },
        )

        assertTrue(saved)
        assertEquals(listOf("encrypt", "persist:ciphertext"), calls)
    }

    @Test
    fun blankOrEmptyCiphertextFailsClosed() {
        var persisted = false

        assertFalse(
            CredentialPersistence.commitEncrypted(
                plaintext = "",
                encrypt = { "ciphertext" },
                persist = { persisted = true; true },
            ),
        )
        assertFalse(
            CredentialPersistence.commitEncrypted(
                plaintext = "secret",
                encrypt = { "" },
                persist = { persisted = true; true },
            ),
        )
        assertFalse(persisted)
    }

    @Test
    fun plainCommitExceptionsAreFailures() {
        assertFalse(CredentialPersistence.commit { error("disk unavailable") })
        assertFalse(CredentialPersistence.commit { false })
        assertTrue(CredentialPersistence.commit { true })
    }
}
