package dk.ternedal.modelrig.ui.agent

import dk.ternedal.modelrig.net.Agent3Client
import dk.ternedal.modelrig.net.Agent3TaskReadinessClient

/**
 * Oversættelse fra riggens agent-kørsel til kortet i chatten — statsløs, og
 * derfor enhedstestbar uden rig.
 *
 * STATUS: FORBEREDT, IKKE WIRET — og det er en ARKITEKTURGRÆNSE, ikke
 * dovenskab. tests/workflow_agent3_dormant.py kræver at AppUi.kt og
 * TurnRouter.kt (den normale tur-routing) IKKE nævner agent3 overhovedet:
 * Agent 3 er et eksperimentelt substrat, der kun må nås gennem sine egne
 * flag-gatede flader. Da jeg wirede kortet ind i chatten, fældede gaten det
 * med rette. At flytte referencen til en anden fil ville bestå gaten og
 * bryde dens hensigt; at ændre grænsen kræver en beslutning FØRST (A4-005's
 * stopregel), derefter kode.
 *
 * Funktionerne her er den oversættelse en sådan beslutning vil skulle bruge:
 * activeRun() afgør hvad der tæller som "kører lige nu" — terminale
 * tilstande gør det aldrig, for et færdigt run må ikke blive stående og se
 * levende ud.
 */
object AgentRunPresentation {

    /** Tilstande hvor kørslen er slut. Alt andet regnes som i gang. */
    val TERMINAL = setOf("completed", "succeeded", "failed", "cancelled", "completed_after_cancel", "blocked")

    /** Den nyeste kørsel der ikke er slut, eller null. */
    fun activeRun(runs: List<Agent3Client.Run>): Agent3Client.Run? =
        runs.lastOrNull { !isTerminal(it) }

    fun isTerminal(run: Agent3Client.Run): Boolean = run.state.trim().lowercase() in TERMINAL

    /**
     * Trinnene som kortet viser dem. Et trins egen state vinder; mangler den,
     * afgør currentStep. Vi GÆTTER aldrig "done" på et trin riggen ikke har
     * meldt færdigt — kortet skal ikke påstå fremdrift der ikke er sket.
     */
    fun steps(run: Agent3Client.Run): List<AgentStepUi> =
        run.steps.mapIndexed { index, step ->
            val declared = step.state?.trim()?.lowercase()
            val state = when {
                declared in setOf("done", "completed", "succeeded") -> AgentStepState.Done
                declared == "running" || declared == "active" -> AgentStepState.Active
                declared != null && declared.isNotEmpty() -> AgentStepState.Pending
                index < run.currentStep -> AgentStepState.Done
                index == run.currentStep -> AgentStepState.Active
                else -> AgentStepState.Pending
            }
            AgentStepUi(text = step.summary.ifBlank { step.tool }, state = state)
        }

    /**
     * Kørslen chatten må vise: den aktive, og KUN hvis den er bundet til
     * netop denne samtale (ADR-A3-001). Et run startet et andet sted hører
     * til på agent-skærmen — ikke i en tilfældig tråd.
     */
    fun visibleRun(runs: List<Agent3Client.Run>, boundRunId: String?): Agent3Client.Run? {
        if (boundRunId.isNullOrBlank()) return null
        // Vi slår MIN kørsel op — ikke "den nyeste, hvis den tilfældigvis er
        // min". Kører riggen to planer, skal chatten stadig vise samtalens
        // egen, også når den ikke er den seneste.
        return runs.firstOrNull { it.id == boundRunId }?.takeUnless { isTerminal(it) }
    }

    /** Trinnene i et PREVIEW: intet er kørt endnu, så intet må se udført ud. */
    fun previewSteps(steps: List<Agent3Client.Step>): List<AgentStepUi> =
        steps.map { AgentStepUi(text = it.summary.ifBlank { it.tool }, state = AgentStepState.Pending) }

    /**
     * Riggens EGEN udmelding om hvilken flade der kører, og hvorfor.
     *
     * Panelet viste kun planens rutenavn, så operatøren kunne ikke se
     * hverken den valgte flade, serverens begrundelse eller at fladen faldt
     * tilbage til agent2 — tre af de tretten krav i
     * scripts/agent3_task_ui_validation.py (selected_surface_visible,
     * server_reason_visible, fallback_visible). Teksten citerer serveren
     * ordret; klienten oversætter ikke og gætter ikke.
     */
    data class SurfaceUi(
        val surface: String,
        val reason: String,
        val fallbackActive: Boolean,
        val fallbackSurface: String,
    )

    fun surfaceUi(readiness: Agent3TaskReadinessClient.Readiness): SurfaceUi {
        val selected = readiness.selectedSurface.trim()
        return SurfaceUi(
            surface = selected,
            reason = readiness.reason.trim(),
            fallbackActive = !readiness.agent3ReadonlySelected,
            fallbackSurface = readiness.fallbackSurface.trim(),
        )
    }

    /** Én linje: flade og begrundelse, som serveren formulerer dem. */
    fun surfaceLine(ui: SurfaceUi): String {
        val surface = ui.surface.ifBlank { "ukendt" }
        val reason = ui.reason
        return if (reason.isBlank()) "Flade: $surface" else "Flade: $surface · $reason"
    }

    /** Fallback-linjen — kun når riggen IKKE har valgt task-fladen. */
    fun fallbackLine(ui: SurfaceUi): String? {
        if (!ui.fallbackActive) return null
        val fallback = ui.fallbackSurface.ifBlank { "agent2" }
        return "Falder tilbage til $fallback — Stop gælder stadig den kørsel der er i gang."
    }

    fun titleOf(routeKind: String): String =
        routeKind.trim().ifEmpty { "Plan" }.replaceFirstChar { it.uppercase() }

    /** Korttitlen: planens rute hvis riggen navngiver den, ellers bare "Plan". */
    fun title(run: Agent3Client.Run): String =
        run.routeKind.trim().ifEmpty { "Plan" }.replaceFirstChar { it.uppercase() }
}
