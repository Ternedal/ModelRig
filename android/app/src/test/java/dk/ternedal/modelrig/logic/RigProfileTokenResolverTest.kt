package dk.ternedal.modelrig.logic

import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertThrows
import org.junit.Test

class RigProfileTokenResolverTest {

    @Test
    fun validEnvelopeIsReturnedWithoutMigration() {
        val resolved = RigProfileTokenResolver.resolve(
            raw = "enc:v1:ciphertext",
            decrypt = { "plain-token" },
            encrypt = { error("must not encrypt an already current envelope") },
        )

        assertEquals(RigProfileTokenResolution.Ready("plain-token"), resolved)
    }

    @Test
    fun corruptEnvelopeFailsClosed() {
        val resolved = RigProfileTokenResolver.resolve(
            raw = "enc:v1:broken",
            decrypt = { error("cannot decrypt") },
            encrypt = { error("must not launder corrupt ciphertext") },
        )

        assertSame(RigProfileTokenResolution.Invalid, resolved)
    }

    @Test
    fun legacyPlaintextRequiresARecognisedEnvelope() {
        val failure = assertThrows(IllegalStateException::class.java) {
            RigProfileTokenResolver.resolve(
                raw = "a1b2c3d4e5f60718293a4b5c6d7e8f90",
                decrypt = { error("legacy plaintext is not decrypted") },
                encrypt = { "not-an-envelope" },
            )
        }

        assertEquals(
            "Credential encryption did not return a recognised envelope",
            failure.message,
        )
    }

    @Test
    fun legacyPlaintextIsNotReadyUntilMigrationIsPersistedByTheCaller() {
        val resolved = RigProfileTokenResolver.resolve(
            raw = "a1b2c3d4e5f60718293a4b5c6d7e8f90",
            decrypt = { error("legacy plaintext is not decrypted") },
            encrypt = { "enc:v1:new-envelope" },
        )

        assertEquals(
            RigProfileTokenResolution.Migration(
                token = "a1b2c3d4e5f60718293a4b5c6d7e8f90",
                envelope = "enc:v1:new-envelope",
            ),
            resolved,
        )
    }

    @Test
    fun oldCiphertextIsRewrappedWithTheCurrentEnvelope() {
        val resolved = RigProfileTokenResolver.resolve(
            raw = "old-prefixless-ciphertext",
            decrypt = { "decrypted-token" },
            encrypt = { "enc:v1:rewrapped" },
        )

        assertEquals(
            RigProfileTokenResolution.Migration(
                token = "decrypted-token",
                envelope = "enc:v1:rewrapped",
            ),
            resolved,
        )
    }

    @Test
    fun oldCiphertextThatCannotDecryptIsInvalidAndNeverReEncrypted() {
        val resolved = RigProfileTokenResolver.resolve(
            raw = "old-prefixless-ciphertext",
            decrypt = { error("key lost") },
            encrypt = { error("must not encrypt undecryptable data") },
        )

        assertSame(RigProfileTokenResolution.Invalid, resolved)
    }

    @Test
    fun encryptionFailurePropagatesSoPlaintextCannotBeReturned() {
        assertThrows(IllegalArgumentException::class.java) {
            RigProfileTokenResolver.resolve(
                raw = "a1b2c3d4e5f60718293a4b5c6d7e8f90",
                decrypt = { error("legacy plaintext is not decrypted") },
                encrypt = { throw IllegalArgumentException("keystore unavailable") },
            )
        }
    }
}
