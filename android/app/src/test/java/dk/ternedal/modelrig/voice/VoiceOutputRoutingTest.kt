package dk.ternedal.modelrig.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

class VoiceOutputRoutingTest {
    @Test fun phoneAlwaysRemainsPhone() {
        assertEquals(VoiceOutputTarget.Phone,
            VoiceOutputRouting.effectiveTarget(VoiceOutputTarget.Phone, "living-room"))
    }

    @Test fun matchingActiveCastDeviceIsSelected() {
        val target = VoiceOutputTarget.Cast("living-room", "Nest Hub")
        assertEquals(target, VoiceOutputRouting.effectiveTarget(target, "living-room"))
    }

    @Test fun disconnectedCastFallsBackToPhone() {
        val target = VoiceOutputTarget.Cast("living-room", "Nest Hub")
        assertEquals(VoiceOutputTarget.Phone,
            VoiceOutputRouting.effectiveTarget(target, null))
        assertEquals(VoiceOutputTarget.Phone,
            VoiceOutputRouting.effectiveTarget(target, "bedroom"))
    }

    @Test fun invalidCastDeviceIsRejected() {
        assertThrows(IllegalArgumentException::class.java) {
            VoiceOutputTarget.Cast("", "Nest Hub")
        }
        assertThrows(IllegalArgumentException::class.java) {
            VoiceOutputTarget.Cast("living-room", "")
        }
    }
}
