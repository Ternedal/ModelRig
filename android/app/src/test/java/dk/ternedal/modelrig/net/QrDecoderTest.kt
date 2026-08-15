package dk.ternedal.modelrig.net

import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter
import com.google.zxing.qrcode.decoder.ErrorCorrectionLevel
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Afkoderen testes mod QR-koder vi selv tegner — samme bibliotek som
 * rig-siden vil bruge til at VISE koden. Ingen kamera, ingen emulator:
 * en ægte kode, omsat til det grå-plan kameraet ville levere.
 */
class QrDecoderTest {

    /** Tegner en QR og udleverer den som Y-plan, præcis som kameraets format. */
    private fun luminanceOf(text: String, size: Int = 240): Triple<ByteArray, Int, Int> {
        val matrix = QRCodeWriter().encode(
            text, BarcodeFormat.QR_CODE, size, size,
            mapOf(EncodeHintType.ERROR_CORRECTION to ErrorCorrectionLevel.M, EncodeHintType.MARGIN to 2),
        )
        val bytes = ByteArray(size * size)
        for (y in 0 until size) {
            for (x in 0 until size) {
                // Sort modul = 0 (mørk), hvid = 255 (lys) — som et gråtonebillede.
                bytes[y * size + x] = if (matrix.get(x, y)) 0 else 255.toByte()
            }
        }
        return Triple(bytes, size, size)
    }

    @Test
    fun `et rigtigt parringslink laeses tilbage uaendret`() {
        val link = "kaliv://pair?url=http%3A%2F%2F192.168.1.27%3A8080&code=A7K2-M9QX"
        val (bytes, w, h) = luminanceOf(link)
        assertEquals(link, QrDecoder.decodeLuminance(bytes, w, h))
    }

    @Test
    fun `et billede uden kode giver null — ikke en fejl`() {
        val blank = ByteArray(200 * 200) { 255.toByte() }
        assertNull(QrDecoder.decodeLuminance(blank, 200, 200))
        val noise = ByteArray(200 * 200) { ((it * 37) % 256).toByte() }
        assertNull(QrDecoder.decodeLuminance(noise, 200, 200))
    }

    @Test
    fun `urimelige maal afvises frem for at laese uden for bufferen`() {
        val small = ByteArray(16)
        assertNull(QrDecoder.decodeLuminance(small, 200, 200))
        assertNull(QrDecoder.decodeLuminance(small, 0, 0))
        assertNull(QrDecoder.decodeLuminance(small, -4, 4))
    }

    @Test
    fun `afkoderen kan bruges igen efter en mislykket frame`() {
        val blank = ByteArray(120 * 120) { 255.toByte() }
        repeat(3) { assertNull(QrDecoder.decodeLuminance(blank, 120, 120)) }
        val link = "kaliv://pair?url=http://rig.local:8080&code=A7K2-M9QX"
        val (bytes, w, h) = luminanceOf(link)
        assertEquals(link, QrDecoder.decodeLuminance(bytes, w, h))
    }
}
