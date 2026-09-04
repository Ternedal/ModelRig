package dk.ternedal.modelrig.net

import com.google.zxing.BinaryBitmap
import com.google.zxing.DecodeHintType
import com.google.zxing.NotFoundException
import com.google.zxing.PlanarYUVLuminanceSource
import com.google.zxing.common.HybridBinarizer
import com.google.zxing.qrcode.QRCodeReader

/**
 * QR-afkodning uden Android-afhængigheder — så den kan enhedstestes uden
 * kamera og uden emulator.
 *
 * Kameraet leverer YUV-billeder; QR-læsning behøver kun luminансplanet (Y),
 * altså de første bredde×højde bytes. Derfor tager funktionen præcis det:
 * en grå-plan, dens mål, og intet andet. Fejler afkodningen — hvilket den
 * gør i næsten hver eneste frame, indtil koden er i billedet — returneres
 * null uden at kaste; en scanner der kaster på hver frame er ubrugelig.
 */
object QrDecoder {

    private val reader = QRCodeReader()
    private val hints = mapOf(DecodeHintType.TRY_HARDER to true)

    /**
     * @param luminance Y-planet, mindst [width] * [height] bytes.
     * @return QR-kodens tekst, eller null hvis der ikke var en læsbar kode.
     */
    @Synchronized
    fun decodeLuminance(luminance: ByteArray, width: Int, height: Int): String? {
        if (width <= 0 || height <= 0) return null
        if (luminance.size < width * height) return null
        val source = PlanarYUVLuminanceSource(
            luminance, width, height, 0, 0, width, height, false,
        )
        return try {
            reader.decode(BinaryBitmap(HybridBinarizer(source)), hints).text
        } catch (_: NotFoundException) {
            null
        } catch (_: Exception) {
            // Checksum- og formatfejl er lige så normale som "ingen kode":
            // en halvt synlig QR skal ikke vælte skærmen.
            null
        } finally {
            reader.reset()
        }
    }
}
