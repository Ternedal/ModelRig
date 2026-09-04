package dk.ternedal.modelrig.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class PairingLinkTest {

    @Test
    fun `et gyldigt link giver adresse og kode`() {
        val link = PairingLink.parse("kaliv://pair?url=http%3A%2F%2F192.168.1.27%3A8080&code=A7K2-M9QX")
        assertEquals("http://192.168.1.27:8080", link?.baseUrl)
        assertEquals("A7K2-M9QX", link?.code)
        assertEquals("192.168.1.27:8080", link?.host)
    }

    @Test
    fun `koden accepteres uden bindestreg og i smaa bogstaver`() {
        val link = PairingLink.parse("kaliv://pair?url=http://rig.local:8080&code=a7k2m9qx")
        assertEquals("A7K2M9QX", link?.code)
    }

    @Test
    fun `build og parse er hinandens modsatte`() {
        val raw = PairingLink.build("http://192.168.1.27:8080/", "a7k2-m9qx")
        val link = PairingLink.parse(raw)
        assertEquals("http://192.168.1.27:8080", link?.baseUrl)
        assertEquals("A7K2-M9QX", link?.code)
    }

    @Test
    fun `fremmede skemaer og handlinger afvises`() {
        assertNull(PairingLink.parse("https://example.com/pair?url=http://a:1&code=A7K2-M9QX"))
        assertNull(PairingLink.parse("kaliv://claim?url=http://a:1&code=A7K2-M9QX"))
        assertNull(PairingLink.parse(""))
        assertNull(PairingLink.parse(null))
        assertNull(PairingLink.parse("ikke et link"))
    }

    @Test
    fun `adressen skal vaere http eller https med en vaert`() {
        assertNull(PairingLink.parse("kaliv://pair?url=file%3A%2F%2F%2Fetc%2Fpasswd&code=A7K2-M9QX"))
        assertNull(PairingLink.parse("kaliv://pair?url=ftp%3A%2F%2Frig%3A21&code=A7K2-M9QX"))
        assertNull(PairingLink.parse("kaliv://pair?url=http%3A%2F%2F&code=A7K2-M9QX"))
        assertNull(PairingLink.parse("kaliv://pair?code=A7K2-M9QX"))
        // Indlejret brugernavn er en klassisk maskering af den rigtige vaert.
        assertNull(PairingLink.parse("kaliv://pair?url=http%3A%2F%2Fmin-rig%40ondsindet.dk&code=A7K2-M9QX"))
    }

    @Test
    fun `kun rigens egen kodeform accepteres`() {
        assertNull(PairingLink.parse("kaliv://pair?url=http://rig:8080&code="))
        assertNull(PairingLink.parse("kaliv://pair?url=http://rig:8080&code=KORT"))
        // 0, 1, I, L og O er ikke i rigens alfabet — de forveksles for let.
        assertNull(PairingLink.parse("kaliv://pair?url=http://rig:8080&code=A0K2-M9QX"))
        assertNull(PairingLink.parse("kaliv://pair?url=http://rig:8080&code=" + "A".repeat(200)))
    }

    @Test
    fun `linket baerer aldrig et token`() {
        val raw = PairingLink.build("http://192.168.1.27:8080", "A7K2-M9QX")
        assert(!raw.contains("token", ignoreCase = true))
    }
}
