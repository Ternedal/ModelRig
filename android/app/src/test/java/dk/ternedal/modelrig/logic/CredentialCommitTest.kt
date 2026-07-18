package dk.ternedal.modelrig.logic

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class CredentialCommitTest {
    @Test
    fun saveReportsSuccessOnlyAfterCommittedCiphertext() {
        var committed: String? = null

        val saved = CredentialCommit.save(
            value = "secret",
            encrypt = { "enc:$it" },
            commit = {
                committed = it
                true
            },
        )

        assertTrue(saved)
        assertEquals("enc:secret", committed)
    }

    @Test
    fun failedCommitIsNotReportedAsSaved() {
        val saved = CredentialCommit.save(
            value = "secret",
            encrypt = { "enc:$it" },
            commit = { false },
        )

        assertFalse(saved)
    }

    @Test
    fun encryptionFailureDoesNotAttemptStorageCommit() {
        var commitCalled = false

        val saved = CredentialCommit.save(
            value = "secret",
            encrypt = { error("keystore unavailable") },
            commit = {
                commitCalled = true
                true
            },
        )

        assertFalse(saved)
        assertFalse(commitCalled)
    }

    @Test
    fun emptyCredentialClearsWithoutCallingEncrypt() {
        var committed: String? = "not-called"

        val saved = CredentialCommit.save(
            value = "",
            encrypt = { error("encrypt must not run") },
            commit = {
                committed = it
                true
            },
        )

        assertTrue(saved)
        assertNull(committed)
    }

    @Test
    fun clearFailsClosedForFalseOrException() {
        assertFalse(CredentialCommit.clear { false })
        assertFalse(CredentialCommit.clear { error("disk unavailable") })
        assertTrue(CredentialCommit.clear { true })
    }
}
