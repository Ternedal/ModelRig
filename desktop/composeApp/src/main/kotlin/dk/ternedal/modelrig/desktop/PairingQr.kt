package dk.ternedal.modelrig.desktop

import com.google.zxing.BarcodeFormat
import com.google.zxing.EncodeHintType
import com.google.zxing.qrcode.QRCodeWriter
import com.google.zxing.qrcode.decoder.ErrorCorrectionLevel
import java.awt.image.BufferedImage
import java.net.Inet4Address
import java.net.NetworkInterface
import java.net.URLEncoder

/**
 * Rig-siden af QR-parringen: riggen TEGNER koden, telefonen læser den.
 *
 * Formatet er det samme som Android-klientens PairingLink kender —
 * kaliv://pair?url=...&code=... — og de to filer holdes i sync af
 * tests/workflow_pairing_link_parity.py, fordi to implementeringer af
 * samme format ellers driver fra hinanden i stilhed.
 *
 * QR'en bærer ALDRIG et token: kun adressen og en kortlivet engangskode,
 * præcis som når man taster dem. Og telefonen parrer stadig ikke af sig
 * selv — den viser værten og venter på et tryk.
 */
object PairingQr {

    const val SCHEME = "kaliv"
    const val ACTION = "pair"
    const val PARAM_URL = "url"
    const val PARAM_CODE = "code"

    /** Bygger linket. Adressen SKAL være en telefonen kan nå — ikke 127.0.0.1. */
    fun buildLink(baseUrl: String, code: String): String {
        val url = URLEncoder.encode(baseUrl.trim().trimEnd('/'), Charsets.UTF_8)
        val c = URLEncoder.encode(code.trim().uppercase(), Charsets.UTF_8)
        return "$SCHEME://$ACTION?$PARAM_URL=$url&$PARAM_CODE=$c"
    }

    /** QR som sort/hvidt billede, klar til at vises på skærmen. */
    fun image(text: String, size: Int = 320): BufferedImage {
        val matrix = QRCodeWriter().encode(
            text, BarcodeFormat.QR_CODE, size, size,
            mapOf(
                EncodeHintType.ERROR_CORRECTION to ErrorCorrectionLevel.M,
                EncodeHintType.MARGIN to 2,
                EncodeHintType.CHARACTER_SET to "UTF-8",
            ),
        )
        val img = BufferedImage(matrix.width, matrix.height, BufferedImage.TYPE_INT_RGB)
        for (y in 0 until matrix.height) {
            for (x in 0 until matrix.width) {
                img.setRGB(x, y, if (matrix.get(x, y)) 0x000000 else 0xFFFFFF)
            }
        }
        return img
    }

    /**
     * Adresser telefonen kan nå. Loopback duer ikke fra en telefon, og
     * link-local (169.254.x) er en fejlkonfiguration — begge udelades, så
     * QR'en ikke sender telefonen et sted den aldrig kommer i kontakt med.
     */
    fun reachableHosts(candidates: List<String>): List<String> =
        candidates.map { it.trim() }
            .filter { it.isNotEmpty() }
            .filterNot { it.startsWith("127.") || it == "::1" || it.startsWith("169.254.") }
            .distinct()

    /** Maskinens egne IPv4-adresser, filtreret som ovenfor. */
    fun localAddresses(): List<String> {
        val found = buildList {
            runCatching {
                for (nic in NetworkInterface.getNetworkInterfaces()) {
                    if (!nic.isUp || nic.isLoopback) continue
                    for (addr in nic.inetAddresses) {
                        if (addr is Inet4Address) add(addr.hostAddress)
                    }
                }
            }
        }
        return reachableHosts(found)
    }
}
