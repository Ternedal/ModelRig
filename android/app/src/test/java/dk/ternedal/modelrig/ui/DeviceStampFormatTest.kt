package dk.ternedal.modelrig.ui

import org.junit.Assert.assertEquals
import org.junit.Test
import java.util.TimeZone

class DeviceStampFormatTest {

    @Test
    fun `ISO-tidsstempel fra riggen formateres dansk`() {
        TimeZone.setDefault(TimeZone.getTimeZone("UTC"))
        assertEquals("15/8 2026 11:16", formatStamp("2026-08-15T11:16:03Z"))
        assertEquals("8/7 2026 21:14", formatStamp("2026-07-08T21:14:00.123456789Z"))
    }

    @Test
    fun `manglende eller ulaeseligt stempel bliver ukendt — aldrig pynt`() {
        assertEquals("ukendt", formatStamp(null))
        assertEquals("ukendt", formatStamp(""))
        assertEquals("ukendt", formatStamp("i gaar"))
        assertEquals("ukendt", formatStamp("0001-01-01"))
    }
}
