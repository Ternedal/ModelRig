package dk.ternedal.modelrig.ui.agent

import dk.ternedal.modelrig.net.Agent3Client
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class AgentRunPresentationTest {

    private fun step(tool: String, summary: String = "", state: String? = null) =
        Agent3Client.Step(
            id = null, tool = tool, args = "{}", risk = "read", sensitivity = "low",
            egress = "none", summary = summary, state = state,
            confirmationDigest = null, confirmationExpiresAt = null, error = null,
        )

    private fun run(
        id: String = "r1",
        state: String = "running",
        currentStep: Int = 0,
        steps: List<Agent3Client.Step> = emptyList(),
    ) = Agent3Client.Run(
        id = id, state = state, routeKind = "plan", currentStep = currentStep,
        steps = steps, answer = null, error = null, termination = null,
    )

    @Test
    fun `terminale koersler taeller aldrig som aktive`() {
        for (s in listOf("completed", "succeeded", "failed", "cancelled", "completed_after_cancel", "blocked")) {
            assertNull("$s burde ikke vaere aktiv", AgentRunPresentation.activeRun(listOf(run(state = s))))
        }
        assertNull(AgentRunPresentation.activeRun(emptyList()))
        assertEquals("r1", AgentRunPresentation.activeRun(listOf(run(state = "RUNNING")))?.id)
    }

    @Test
    fun `nyeste ikke-afsluttede koersel vinder`() {
        val runs = listOf(
            run(id = "gammel", state = "completed"),
            run(id = "nyere", state = "running"),
            run(id = "nyest", state = "awaiting_review"),
        )
        assertEquals("nyest", AgentRunPresentation.activeRun(runs)?.id)
    }

    @Test
    fun `trinnenes egen tilstand vinder over currentStep`() {
        val r = run(
            currentStep = 0,
            steps = listOf(
                step("a", state = "done"),
                step("b", state = "running"),
                step("c", state = "pending"),
            ),
        )
        assertEquals(
            listOf(AgentStepState.Done, AgentStepState.Active, AgentStepState.Pending),
            AgentRunPresentation.steps(r).map { it.state },
        )
    }

    @Test
    fun `uden trin-tilstand afgoer currentStep — og intet gaettes faerdigt`() {
        val r = run(currentStep = 1, steps = listOf(step("a"), step("b"), step("c")))
        assertEquals(
            listOf(AgentStepState.Done, AgentStepState.Active, AgentStepState.Pending),
            AgentRunPresentation.steps(r).map { it.state },
        )
        // currentStep = 0: intet er faerdigt endnu.
        val fresh = run(currentStep = 0, steps = listOf(step("a"), step("b")))
        assertEquals(
            listOf(AgentStepState.Active, AgentStepState.Pending),
            AgentRunPresentation.steps(fresh).map { it.state },
        )
    }

    @Test
    fun `teksten falder tilbage til vaerktoejsnavnet naar resumeet er tomt`() {
        val r = run(steps = listOf(step("note_append", summary = ""), step("x", summary = "Skriver noten")))
        assertEquals(listOf("note_append", "Skriver noten"), AgentRunPresentation.steps(r).map { it.text })
    }

    @Test
    fun `titlen bruger rigens rute — ellers Plan`() {
        assertEquals("Plan", AgentRunPresentation.title(run()))
        assertEquals(
            "Research",
            AgentRunPresentation.title(
                Agent3Client.Run("r", "running", "research", 0, emptyList(), null, null, null),
            ),
        )
        assertEquals(
            "Plan",
            AgentRunPresentation.title(
                Agent3Client.Run("r", "running", "   ", 0, emptyList(), null, null, null),
            ),
        )
    }

    @Test
    fun `kun den koersel der er bundet til samtalen vises`() {
        val runs = listOf(run(id = "mit-run", state = "running"), run(id = "andres", state = "running"))
        assertEquals("mit-run", AgentRunPresentation.visibleRun(runs, "mit-run")?.id)
        // Et run startet et andet sted hoerer til paa agent-skaermen.
        assertNull(AgentRunPresentation.visibleRun(runs, "et-tredje"))
        assertNull(AgentRunPresentation.visibleRun(runs, null))
        assertNull(AgentRunPresentation.visibleRun(runs, ""))
    }

    @Test
    fun `en bundet men afsluttet koersel vises heller ikke`() {
        val runs = listOf(run(id = "mit-run", state = "completed"))
        assertNull(AgentRunPresentation.visibleRun(runs, "mit-run"))
    }
}
