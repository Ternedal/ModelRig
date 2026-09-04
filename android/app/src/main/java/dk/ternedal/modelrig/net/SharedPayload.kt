package dk.ternedal.modelrig.net

/**
 * Det Kaliv har fået delt fra en anden app — "Del til Kaliv".
 *
 * Ren datamodel + parser uden Android-typer, så reglerne kan enhedstestes:
 * en delefunktion der opfører sig forkert på et tomt eller mærkeligt input,
 * opdager man ellers først med en fremmed app i hånden.
 *
 * VIGTIGSTE REGEL: en deling GØR ingenting af sig selv. Den lander i et kort
 * hvor mennesket vælger — chat eller Viden. Automatisk indeksering ville
 * lægge en andens dokument i din viden, fordi du kom til at trykke Del.
 */
sealed interface SharedPayload {

    /** Delt tekst (inkl. links, som blot er tekst der ligner et link). */
    data class Text(val text: String, val subject: String?) : SharedPayload {
        /** Forslag til kildenavn, hvis teksten gemmes i Viden. */
        val suggestedName: String
            get() = subject?.trim()?.takeIf { it.isNotEmpty() }
                ?: text.trim().lineSequence().firstOrNull()?.take(60)?.trim().orEmpty()
                    .ifEmpty { "delt tekst" }
    }

    /** Delt fil. Vi kender kun uri + type; indholdet læses først ved valg. */
    data class Document(val uri: String, val mimeType: String?, val displayName: String?) : SharedPayload {
        val suggestedName: String
            get() = displayName?.trim()?.takeIf { it.isNotEmpty() }
                ?: uri.substringAfterLast('/').substringBefore('?').takeIf { it.isNotEmpty() }
                ?: "delt fil"
    }

    companion object {
        /** Grænse for hvor meget delt tekst vi tager med. */
        const val MAX_TEXT = 200_000

        /**
         * Bygger en payload af det en share-intent bar.
         *
         * Fail-closed: tom tekst uden fil giver null, og så starter appen helt
         * almindeligt. Vi FORTOLKER ikke — en delt URL er tekst, ikke en
         * kommando om at hente noget.
         */
        fun from(text: String?, subject: String?, uri: String?, mimeType: String?, displayName: String?): SharedPayload? {
            val t = text?.trim().orEmpty()
            if (uri != null && uri.isNotBlank()) {
                return Document(uri = uri, mimeType = mimeType?.takeIf { it.isNotBlank() }, displayName = displayName)
            }
            if (t.isEmpty()) return null
            return Text(text = t.take(MAX_TEXT), subject = subject?.trim()?.takeIf { it.isNotEmpty() })
        }

        /** Blev teksten klippet? Så skal fladen sige det frem for at lade som om. */
        fun wasTruncated(original: String?): Boolean = (original?.trim()?.length ?: 0) > MAX_TEXT
    }
}
