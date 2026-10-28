package dk.ternedal.modelrig.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CastVoiceDisplayBridgeTest {
    private val id = "session_123456"

    @Test fun streamingEventsProduceExpectedOrder() {
        val events = mutableListOf<String>()
        val bridge = CastVoiceDisplayBridge({ message ->
            events += message.getString("type") + ":" +
                message.optString("phase", message.optString("role"))
            true
        }, id)
        assertTrue(bridge.thinking())
        assertTrue(bridge.transcript("Hej"))
        assertTrue(bridge.speaking("Goddag"))
        assertTrue(bridge.idle())
        assertEquals(listOf(
            "kaliv_voice_status:thinking",
            "kaliv_voice_text:user",
            "kaliv_voice_status:speaking",
            "kaliv_voice_text:assistant",
            "kaliv_voice_status:idle",
        ), events)
    }

    @Test fun castTransportFailureIsNonFatal() {
        val bridge = CastVoiceDisplayBridge({ throw IllegalStateException("disconnected") }, id)
        assertFalse(bridge.thinking())
        assertFalse(bridge.transcript("Hej"))
        assertFalse(bridge.speaking("Goddag"))
        assertFalse(bridge.error())
    }

    @Test fun longTextIsBounded() {
        val messages = mutableListOf<org.json.JSONObject>()
        val bridge = CastVoiceDisplayBridge({ messages += it; true }, id)
        assertTrue(bridge.transcript("a".repeat(5000)))
        assertEquals(4000, messages.single().getString("text").length)
    }
}
