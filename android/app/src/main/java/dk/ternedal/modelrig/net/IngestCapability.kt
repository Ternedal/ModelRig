package dk.ternedal.modelrig.net

/**
 * Må dette dokumentformat overhovedet sendes til den tilsluttede rig?
 *
 * Den udgivne core-worker sendes UDEN PyMuPDF, python-docx og python-pptx. En
 * telefon mod en frisk installation sender i dag PDF'en afsted alligevel og
 * viser rigens rå fejl bagefter. Brugeren har så brugt et filvalg, en upload og
 * en ventetid på at få at vide, at det aldrig kunne lade sig gøre.
 *
 * REN LOGIK MED VILJE: ingen Android-typer, ingen netværk. Afgørelsen kan
 * derfor drives direkte af tests, og gaten ligger ikke begravet i en composable
 * hvor kun et skærmbillede kunne fælde den.
 *
 * Tilbageholdenheden arves fra [WorkerCapabilities]: kun et UDTRYKKELIGT `false`
 * fra riggen blokerer. Ukendt, ældre rig eller mislykket probe → send som hidtil.
 */
object IngestCapability {

    /** De formater klienten selv har en egen ingest-vej for. */
    enum class Format(val capability: String, val visesSom: String) {
        PDF(WorkerCapabilities.PDF, "PDF"),
        DOCX(WorkerCapabilities.DOCX, "DOCX"),
        PPTX(WorkerCapabilities.PPTX, "PPTX"),
        HTML(WorkerCapabilities.HTML, "HTML"),

        /**
         * Ren tekst og markdown går gennem `ingestText` og kræver ingen
         * valgfri dependency. Den har med vilje en capability der ikke findes
         * i riggens svar — så [WorkerCapabilities.supports] giver true, og
         * tekst kan aldrig blive blokeret af denne gate.
         */
        TEXT("", "tekst"),
    }

    sealed interface Verdict {
        /** Send den. */
        data object Allowed : Verdict

        /** Riggen har udtrykkeligt sagt at den ikke kan læse formatet. */
        data class Blocked(val format: Format, val reason: String) : Verdict
    }

    /**
     * Afgør om [format] må sendes. Blokerer KUN når [caps] udtrykkeligt
     * rapporterer `false` for formatets capability.
     */
    fun check(format: Format, caps: WorkerCapabilities): Verdict {
        if (format == Format.TEXT) return Verdict.Allowed
        if (caps.supports(format.capability)) return Verdict.Allowed
        return Verdict.Blocked(format, grund(format))
    }

    /**
     * Begrundelsen brugeren får at se. Den siger hvad riggen mangler og hvad
     * der kan gøres ved det — en grå knap uden grund er ikke bedre end en der
     * fejler. Formuleret som rigens tilstand, ikke som brugerens fejl.
     */
    private fun grund(format: Format): String = when (format) {
        Format.PDF -> "Riggen kan ikke læse PDF. Den udgivne worker sendes uden " +
            "PyMuPDF — installér det på riggen (pip install pymupdf), eller " +
            "indsæt teksten i stedet."
        Format.DOCX -> "Riggen kan ikke læse DOCX. Den udgivne worker sendes uden " +
            "python-docx — installér det på riggen (pip install python-docx), " +
            "eller indsæt teksten i stedet."
        Format.PPTX -> "Riggen kan ikke læse PPTX. Den udgivne worker sendes uden " +
            "python-pptx — installér det på riggen (pip install python-pptx), " +
            "eller indsæt teksten i stedet."
        Format.HTML -> "Riggen kan ikke læse HTML. Det er uventet — html.parser " +
            "følger med Python, så det tyder på en fejl i workeren snarere end " +
            "på en manglende pakke."
        Format.TEXT -> ""
    }
}
