package dk.ternedal.modelrig.desktop

import com.google.zxing.BinaryBitmap
import com.google.zxing.NotFoundException
import com.google.zxing.RGBLuminanceSource
import com.google.zxing.common.HybridBinarizer
import com.google.zxing.qrcode.QRCodeReader
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * Rig-siden TEGNER QR'en; telefonen LÆSER den. Testen lukker cirklen:
 * den koder linket, læser billedet tilbage med samme bibliotek telefonen
 * bruger, og kræver at teksten er uændret. Går formatet i stykker, eller
 * bliver billedet ulæseligt, fældes den her — ikke på Anders' Pixel.
 */
class PairingQrTest {

    private fun decode(text: String, size: Int = 320): String {
        val img = PairingQr.image(text, size)
        val w = img.width
        val h = img.height
        val pixels = IntArray(w * h)
        img.getRGB(0, 0, w, h, pixels, 0, w)
        val source = RGBLuminanceSource(w, h, pixels)
        return QRCodeReader().decode(BinaryBitmap(HybridBinarizer(source))).text
    }

    @Test
    fun `linket har den form telefonen forventer`() {
        val link = PairingQr.buildLink("http://192.168.1.27:8080/", " a7k2-m9qx ")
        assertEquals("kaliv://pair?url=http%3A%2F%2F192.168.1.27%3A8080&code=A7K2-M9QX", link)
    }

    @Test
    fun `den tegnede kode kan laeses tilbage uaendret`() {
        val link = PairingQr.buildLink("http://192.168.1.27:8080", "A7K2-M9QX")
        assertEquals(link, decode(link))
    }

    @Test
    fun `koden er stadig laesbar i et mindre billede`() {
        val link = PairingQr.buildLink("http://kaliv-rig.local:8080", "A7K2-M9QX")
        assertEquals(link, decode(link, size = 200))
    }

    @Test
    fun `linket baerer aldrig et token`() {
        val link = PairingQr.buildLink("http://192.168.1.27:8080", "A7K2-M9QX")
        assertFalse(link.contains("token", ignoreCase = true))
    }

    @Test
    fun `adresser telefonen ikke kan naa filtreres fra`() {
        val hosts = PairingQr.reachableHosts(
            listOf("127.0.0.1", "192.168.1.27", "169.254.13.5", " 10.0.0.4 ", "192.168.1.27", ""),
        )
        assertEquals(listOf("192.168.1.27", "10.0.0.4"), hosts)
    }

    @Test
    fun `et tomt billede indeholder ingen kode — testens egen kontrol`() {
        // Uden denne ville "kan laeses tilbage" kunne bestaa af en fejl i
        // afkoderen frem for af et rigtigt billede.
        val blank = java.awt.image.BufferedImage(120, 120, java.awt.image.BufferedImage.TYPE_INT_RGB)
        val g = blank.createGraphics()
        g.color = java.awt.Color.WHITE
        g.fillRect(0, 0, 120, 120)
        g.dispose()
        val pixels = IntArray(120 * 120)
        blank.getRGB(0, 0, 120, 120, pixels, 0, 120)
        assertFailsWith<NotFoundException> {
            QRCodeReader().decode(
                BinaryBitmap(HybridBinarizer(RGBLuminanceSource(120, 120, pixels))),
            )
        }
        assertTrue(true)
    }
}
