package dk.ternedal.modelrig.ui.agent

import dk.ternedal.modelrig.net.Agent3Client

/**
 * Hvornår må chatten sætte en agent-kørsel i gang — ADR-A3-001 D2 og D5.
 *
 * Ren logik uden Android og uden netværk, så de to regler der bærer hele
 * åbningen kan BEVISES, ikke bare loves i en kommentar:
 *
 *  D2  Kun en EKSPLICIT menneskehandling kan producere en start. Et
 *      modelforslag, en automatisk genoptagelse, et fallback fra en fejlet
 *      chat-tur — alt sammen null. Det er hele grunden til at dvale-gaten
 *      overhovedet turde åbnes.
 *  D5  Chatten må kun starte READ-planer. Indeholder planen ét skrivetrin,
 *      afvises starten HER, og fladen henviser til godkendelse på
 *      agent-skærmen. Chatten godkender aldrig writes.
 */
object AgentStartPolicy {

    /** Hvor et startforsøg kommer fra. Kun én af dem duer. */
    enum class Source {
        /** Mennesket trykkede på start for netop denne besked. */
        ExplicitUserAction,

        /** Modellen foreslog det. Tæller ikke. */
        ModelSuggestion,

        /** En kørsel skulle "bare fortsætte". Tæller ikke — se D6/kontrakttest 6. */
        AutomaticResume,

        /** En chat-tur fejlede og noget ville prøve agenten i stedet. Tæller ikke. */
        ChatFallback,
    }

    /** Hvad der må ske. Alt andet end Start er en afvisning med en grund. */
    sealed interface Verdict {
        data class Start(val message: String) : Verdict
        data object NotExplicit : Verdict
        data object EmptyMessage : Verdict
        data object NeedsApprovalScreen : Verdict
    }

    /**
     * Må denne besked startes som agent-kørsel?
     *
     * Kaldes FØR planen kendes. Returnerer Start, hvis og kun hvis mennesket
     * bad om det for netop denne (ikke-tomme) besked.
     */
    fun verdict(source: Source, message: String): Verdict = when {
        source != Source.ExplicitUserAction -> Verdict.NotExplicit
        message.isBlank() -> Verdict.EmptyMessage
        else -> Verdict.Start(message.trim())
    }

    /**
     * Skrivetrin genkendes på riggens EGET vokabular — samme tre kendetegn
     * som checkpoint-skærmen bruger, så de to flader er enige om hvad et
     * write er. Er vi i tvivl, er svaret write: en plan vi ikke kan
     * gennemskue, må ikke starte fra en chatboble.
     */
    fun isWriteStep(step: Agent3Client.Step): Boolean =
        step.risk.lowercase().contains("write") ||
            step.tool.lowercase().startsWith("write") ||
            step.egress.lowercase() == "write"

    fun isReadOnly(steps: List<Agent3Client.Step>): Boolean = steps.none { isWriteStep(it) }

    /**
     * Efter previewet: må planen startes fra chatten?
     *
     * En plan UDEN trin startes ikke — der er intet at køre, og et tomt
     * preview er lige så tit et svar riggen ikke kunne lægge en plan for.
     */
    fun verdictForPlan(source: Source, message: String, steps: List<Agent3Client.Step>): Verdict {
        val first = verdict(source, message)
        if (first !is Verdict.Start) return first
        if (steps.isEmpty()) return Verdict.NeedsApprovalScreen
        return if (isReadOnly(steps)) first else Verdict.NeedsApprovalScreen
    }
}
