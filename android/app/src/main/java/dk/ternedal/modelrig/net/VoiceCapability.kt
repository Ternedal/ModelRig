package dk.ternedal.modelrig.net

/**
 * Kan den tilsluttede rig overhovedet føre en talt tur?
 *
 * Uden denne gate optager brugeren en hel sætning, uploader den og får så
 * rigens 501 (`VoiceBackendMissing`) — efter at have talt færdig. Den
 * udgivne core-worker sendes uden faster-whisper og piper-tts, så det er
 * standardtilstanden på en frisk installation, ikke et kantttilfælde.
 *
 * CLOUD REDDER DET IKKE. `voice_pipeline.converse()` siger det selv:
 * *"ASR/TTS cannot move: the models live here."* Voice-via-cloud flytter
 * kun LLM-trinnet — transskription og syntese bliver på riggen. En
 * capability-gate på stemme må derfor ikke lade sig blødgøre af at
 * cloud-nøglen er sat.
 *
 * REN LOGIK som [IngestCapability], og med samme tilbageholdenhed: kun et
 * UDTRYKKELIGT `false` fra riggen blokerer.
 */
object VoiceCapability {

    sealed interface Verdict {
        /** Riggen kan føre turen. */
        data object Allowed : Verdict

        /** Riggen har udtrykkeligt sagt at et nødvendigt trin mangler. */
        data class Blocked(val missing: List<String>, val reason: String) : Verdict
    }

    /**
     * En talt tur kræver BEGGE trin: transskription ind og syntese ud. Mangler
     * kun det ene, er turen stadig umulig — derfor er dette ikke en delvis
     * tilstand, men et nej med en præcis begrundelse.
     */
    fun check(caps: WorkerCapabilities): Verdict {
        val mangler = buildList {
            if (!caps.supports(WorkerCapabilities.ASR)) add(WorkerCapabilities.ASR)
            if (!caps.supports(WorkerCapabilities.TTS)) add(WorkerCapabilities.TTS)
        }
        if (mangler.isEmpty()) return Verdict.Allowed
        return Verdict.Blocked(mangler, grund(mangler))
    }

    private fun grund(mangler: List<String>): String {
        val hvad = when {
            mangler.size == 2 -> "hverken tale-til-tekst eller tekst-til-tale"
            mangler.first() == WorkerCapabilities.ASR -> "tale-til-tekst"
            else -> "tekst-til-tale"
        }
        val pakker = mangler.joinToString(" og ") {
            if (it == WorkerCapabilities.ASR) "faster-whisper" else "piper-tts"
        }
        return "Riggen har ikke $hvad. Den udgivne worker sendes uden $pakker — " +
            "installér det på riggen for at bruge stemme. Cloud hjælper ikke her: " +
            "kun modellens svar kan komme fra cloud, mens lyden ind og ud bliver " +
            "på riggen."
    }
}
