package dk.ternedal.modelrig.desktop.data

import java.util.Base64
import java.util.UUID
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class WindowsDpapiCredentialProtectorTest {

    @Test
    fun `Windows DPAPI round trips and rejects tampered ciphertext`() {
        if (!System.getProperty("os.name", "").startsWith("Windows", ignoreCase = true)) return

        val protector = WindowsDpapiCredentialProtector()
        val plaintext = "modelrig-dpapi-test-${UUID.randomUUID()}"
        val envelope = protector.protect(plaintext)

        assertTrue(envelope.startsWith(CREDENTIAL_ENVELOPE_PREFIX))
        assertFalse(envelope.contains(plaintext))
        assertEquals(plaintext, protector.unprotect(envelope))

        val ciphertext = Base64.getDecoder().decode(envelope.removePrefix(CREDENTIAL_ENVELOPE_PREFIX))
        ciphertext[ciphertext.lastIndex] = (ciphertext.last().toInt() xor 0x01).toByte()
        val tampered = CREDENTIAL_ENVELOPE_PREFIX + Base64.getEncoder().encodeToString(ciphertext)
        ciphertext.fill(0)

        assertFailsWith<CredentialProtectionException> { protector.unprotect(tampered) }
    }
}
