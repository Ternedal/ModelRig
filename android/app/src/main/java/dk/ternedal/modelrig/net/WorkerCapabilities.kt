package dk.ternedal.modelrig.net

import org.json.JSONObject

/**
 * Hvad den TILSLUTTEDE worker faktisk kan — riggens svar på `GET /capabilities`.
 *
 * Formålet er døde-knapper-princippet: en flade må ikke love noget riggen ikke
 * kan. Den udgivne core-worker sendes UDEN ASR/TTS/PDF/DOCX/PPTX, så en telefon
 * mod en frisk installation har i dag knapper der fejler når man trykker.
 *
 * DEN BÆRENDE REGEL: [supports] er kun falsk når riggen UDTRYKKELIGT har sagt
 * falsk. Ukendt, manglende, ulæseligt eller aldrig hentet betyder TILGÆNGELIG.
 * Det er samme valg som `RagSource.enabled`, og af samme grund: en ældre rig
 * der ikke kender feltet skal opføre sig præcis som den gør i dag. Den modsatte
 * default ville slukke virkende funktioner på enhver rig der ikke svarede — et
 * mislykket probe må aldrig kunne amputere appen.
 *
 * Bemærk at dette er workerens fem-plus-to dependency-booleans, IKKE
 * `/api/v1/tools` (T-030-deskriptorerne som Kontrolcentret læser) og IKKE
 * `/api/v1/experimental/agent3/capabilities`. Tre ting hedder "capabilities" i
 * dette repo; det har allerede kostet én forkert konklusion.
 */
class WorkerCapabilities private constructor(
    private val reported: Map<String, Boolean>,
) {

    /** Har riggen overhovedet svaret? Falsk betyder "vi ved det ikke", ikke "nej". */
    val known: Boolean get() = reported.isNotEmpty()

    /**
     * Kun falsk når riggen udtrykkeligt har rapporteret `false` for [capability].
     * Alt andet — ukendt nøgle, intet svar, ulæseligt svar — er sandt.
     */
    fun supports(capability: String): Boolean = reported[capability] != false

    /**
     * De evner riggen udtrykkeligt siger den IKKE har, sorteret. Tom når intet
     * er hentet. Beregnet til en ærlig begrundelse i fladen — "riggen har ikke
     * PDF-understøttelse" er brugbart; en grå knap uden grund er ikke.
     */
    fun explicitlyMissing(): List<String> =
        reported.filterValues { !it }.keys.sorted()

    override fun toString(): String =
        if (!known) "WorkerCapabilities(ukendt)"
        else "WorkerCapabilities(" + reported.toSortedMap().entries.joinToString(", ") {
            "${it.key}=${it.value}"
        } + ")"

    companion object {
        const val ASR = "asr"
        const val TTS = "tts"
        const val PDF = "pdf"
        const val DOCX = "docx"
        const val PPTX = "pptx"
        const val HTML = "html"
        const val CUDA = "cuda"

        /** Intet hentet endnu. Alt regnes tilgængeligt. */
        val UNKNOWN = WorkerCapabilities(emptyMap())

        /**
         * Læser riggens svar. Fail-soft hele vejen: tomt, ulæseligt eller
         * fremmed indhold giver [UNKNOWN] frem for at kaste — et
         * capability-probe der fejler må ikke vælte en forbindelse der virker.
         *
         * Kun ægte booleans medtages. En nøgle med en streng eller et tal er
         * ikke et "nej"; det er et svar vi ikke forstår, og så gætter vi ikke.
         */
        fun parse(body: String?): WorkerCapabilities {
            if (body.isNullOrBlank()) return UNKNOWN
            val obj = try {
                JSONObject(body)
            } catch (_: Exception) {
                return UNKNOWN
            }
            val out = HashMap<String, Boolean>()
            for (key in obj.keys()) {
                val v = obj.opt(key)
                if (v is Boolean) out[key] = v
            }
            return if (out.isEmpty()) UNKNOWN else WorkerCapabilities(out)
        }
    }
}
