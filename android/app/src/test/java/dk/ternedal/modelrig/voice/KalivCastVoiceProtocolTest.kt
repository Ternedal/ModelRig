package dk.ternedal.modelrig.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class KalivCastVoiceProtocolTest {
    private val session = "session_123456"

    @Test fun statusMessageUsesVersionedNamespaceContract() {
        assertEquals("urn:x-cast:dk.kalivhub.lab", KalivCastVoiceProtocol.NAMESPACE)
        val message = KalivCastVoiceProtocol.status(session, "thinking")
        assertEquals("kaliv_voice_status", message.getString("type"))
        assertEquals(1, message.getInt("version"))
        assertEquals(session, message.getString("session_id"))
        assertEquals("thinking", message.getString("phase"))
    }

    @Test fun textMessageHasExplicitRoleAndBoundedPayload() {
        val message = KalivCastVoiceProtocol.text(session, "assistant", "Hej")
        assertEquals("kaliv_voice_text", message.getString("type"))
        assertEquals("assistant", message.getString("role"))
        assertEquals("Hej", message.getString("text"))
        assertThrows(IllegalArgumentException::class.java) {
            KalivCastVoiceProtocol.text(session, "system", "secret")
        }
        assertThrows(IllegalArgumentException::class.java) {
            KalivCastVoiceProtocol.text(session, "user", "x".repeat(4001))
        }
    }

    @Test fun invalidStatusAndSessionAreRejected() {
        assertThrows(IllegalArgumentException::class.java) {
            KalivCastVoiceProtocol.status(session, "recording_forever")
        }
        assertThrows(IllegalArgumentException::class.java) {
            KalivCastVoiceProtocol.status("bad", "idle")
        }
    }
}
