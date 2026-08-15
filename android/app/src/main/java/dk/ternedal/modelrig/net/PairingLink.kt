package dk.ternedal.modelrig.net

/**
 * Parringslink — grundlaget for QR-parring.
 *
 * En QR-kode (eller et almindeligt link) kan bære riggens adresse og en
 * parringskode, så man slipper for at taste 8 tegn og en IP med tommelfingre:
 *
 *     kaliv://pair?url=http://192.168.1.27:8080&code=A7K2-M9QX
 *
 * SIKKERHEDSMODEL — det vigtigste ved hele denne fil:
 * et scannet eller tappet link PARRER ALDRIG AF SIG SELV. Alt hvad et gyldigt
 * link gør, er at udfylde felterne og VISE hvilken vært man er ved at parre
 * med; det er stadig et bevidst tryk der bruger koden. Et link peger nemlig på
 * en vilkårlig adresse, og en QR-kode kan man ikke læse med øjnene — så uden
 * det tryk ville en fremmed kode kunne binde telefonen til en fremmed rig.
 *
 * Koden selv er kortlivet og engangs (riggens pairing.Code()), og linket bærer
 * ALDRIG et token — kun adressen og koden, præcis som når man taster dem.
 */
data class PairingLink(val baseUrl: String, val code: String) {

    /** Vært:port til bekræftelsesteksten — det man skal genkende, ikke hele URL'en. */
    val host: String
        get() = baseUrl.substringAfter("://").trimEnd('/')

    companion object {
        const val SCHEME = "kaliv"
        const val ACTION = "pair"

        // Riggens kode er otte tegn fra et forvekslingsfrit alfabet, skrevet
        // som XXXX-XXXX. Vi accepterer den med og uden bindestreg, men intet
        // andet: et link med en 200 tegn lang "kode" er ikke vores link.
        private val CODE = Regex("^[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}-?[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{4}$")

        /**
         * Læser et link. Returnerer null ved ALT der ikke er præcis vores form
         * — aldrig en delvis udfyldning, for et halvt link er et gæt.
         */
        fun parse(raw: String?): PairingLink? {
            val text = raw?.trim().orEmpty()
            if (text.isEmpty()) return null
            val uri = runCatching { android.net.Uri.parse(text) }.getOrNull() ?: return null
            if (!SCHEME.equals(uri.scheme, ignoreCase = true)) return null
            // Både kaliv://pair?... og kaliv:pair?... er samme hensigt.
            val action = uri.authority?.takeIf { it.isNotEmpty() } ?: uri.path?.trim('/')
            if (!ACTION.equals(action, ignoreCase = true)) return null

            val url = runCatching { uri.getQueryParameter("url") }.getOrNull()?.trim().orEmpty()
            val code = runCatching { uri.getQueryParameter("code") }.getOrNull()?.trim().orEmpty()
            val cleanUrl = normalizeBaseUrl(url) ?: return null
            val cleanCode = code.uppercase()
            if (!CODE.matches(cleanCode)) return null
            return PairingLink(cleanUrl, cleanCode)
        }

        /** Bygger linket — samme form som riggen skal kode i sin QR. */
        fun build(baseUrl: String, code: String): String {
            val url = android.net.Uri.encode(baseUrl.trimEnd('/'))
            return "$SCHEME://$ACTION?url=$url&code=${android.net.Uri.encode(code.trim().uppercase())}"
        }

        /**
         * Kun http/https med en vært. Uden den regel kunne et link sende
         * parringskoden til hvad som helst — file://, en adresse med
         * indlejret brugernavn, eller ingenting.
         */
        private fun normalizeBaseUrl(raw: String): String? {
            if (raw.isEmpty()) return null
            val uri = runCatching { android.net.Uri.parse(raw) }.getOrNull() ?: return null
            val scheme = uri.scheme?.lowercase() ?: return null
            if (scheme != "http" && scheme != "https") return null
            val host = uri.host?.takeIf { it.isNotEmpty() } ?: return null
            if (uri.userInfo != null) return null
            val port = if (uri.port > 0) ":${uri.port}" else ""
            return "$scheme://$host$port"
        }
    }
}
