package dk.ternedal.modelrig.ui.chat

import org.junit.Assert.assertEquals
import org.junit.Test

class UptimeFormatTest {

    @Test
    fun `referencens eksempel formateres som mockuppen`() {
        assertEquals("6 t 12 m", formatUptime(6 * 3600L + 12 * 60L + 30L))
    }

    @Test
    fun `under en time vises kun minutter`() {
        assertEquals("42 m", formatUptime(42 * 60L + 59L))
        assertEquals("1 m", formatUptime(60L))
    }

    @Test
    fun `under et minut vises sekunder`() {
        assertEquals("0 s", formatUptime(0L))
        assertEquals("59 s", formatUptime(59L))
    }

    @Test
    fun `over et doegn skifter til dage og timer`() {
        assertEquals("1 d 0 t", formatUptime(24 * 3600L))
        assertEquals("2 d 3 t", formatUptime(2 * 86_400L + 3 * 3600L + 40 * 60L))
    }
}
