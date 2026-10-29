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

    @Test fun blankAssistantChunkSendsSpeakingStatusWithoutText() {
        val messages = mutableListOf<org.json.JSONObject>()
        val bridge = CastVoiceDisplayBridge({ messages += it; true }, id)
        assertTrue(bridge.speaking("  "))
        assertEquals(1, messages.size)
        assertEquals("kaliv_voice_status", messages.single().getString("type"))
        assertEquals("speaking", messages.single().getString("phase"))
        assertTrue(bridge.speaking(""))
        assertEquals(2, messages.size)
        assertTrue(messages.all { it.getString("type") == "kaliv_voice_status" })
    }

    @Test fun truncationNeverSplitsAnEmojiSurrogatePair() {
        val messages = mutableListOf<org.json.JSONObject>()
        val bridge = CastVoiceDisplayBridge({ messages += it; true }, id)
        val text = "a".repeat(3999) + "😀" + "tail"
        assertTrue(bridge.transcript(text))
        assertEquals("a".repeat(3999), messages.single().getString("text"))
        messages.clear()
        assertTrue(bridge.speaking(text))
        assertEquals("a".repeat(3999), messages.last().getString("text"))
        assertEquals(2, messages.size)
    }

    @Test fun longTextIsBounded() {
        val messages = mutableListOf<org.json.JSONObject>()
        val bridge = CastVoiceDisplayBridge({ messages += it; true }, id)
        assertTrue(bridge.transcript("a".repeat(5000)))
        assertEquals(4000, messages.single().getString("text").length)
    }
}
