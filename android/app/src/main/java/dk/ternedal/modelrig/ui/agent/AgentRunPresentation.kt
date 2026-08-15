package dk.ternedal.modelrig.ui.agent

import dk.ternedal.modelrig.net.Agent3Client

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

    fun titleOf(routeKind: String): String =
        routeKind.trim().ifEmpty { "Plan" }.replaceFirstChar { it.uppercase() }

    /** Korttitlen: planens rute hvis riggen navngiver den, ellers bare "Plan". */
    fun title(run: Agent3Client.Run): String =
        run.routeKind.trim().ifEmpty { "Plan" }.replaceFirstChar { it.uppercase() }
}
