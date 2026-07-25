package dk.ternedal.modelrig.desktop

import dk.ternedal.modelrig.desktop.net.Agent3Step
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * The three pure functions the agent surfaces make decisions with.
 *
 * They are small, and that is exactly why they were untested: nothing about
 * them looks risky. But each one decides something a person acts on.
 *
 *  - `riskOf` decides whether a DESTRUCTIVE badge appears next to a tool that
 *    is about to be approved.
 *  - `isTerminal` decides whether the UI stops offering an approval, and
 *    whether a step counts toward "N af M trin".
 *  - `statusOf` decides which icon a step gets.
 *
 * A wrong answer here is silent. Nothing throws, no test goes red, and the
 * screen simply says something untrue at the moment a human is deciding
 * whether to let software delete a model.
 *
 * The direction of failure is what these tests pin. Both functions must fail
 * toward "this might be dangerous" and "this might still be running" -- never
 * toward "harmless" or "finished".
 */
class KalivRiskDecisionTest {

    // ---------------------------------------------------------------- riskOf

    @Test
    fun `the server's impact wins over any guess from the tool name`() {
        // A tool nobody has seen before, that no name table could classify --
        // but the worker said destructive. That statement must be decisive.
        assertEquals(
            RiskLevel.DESTRUCTIVE,
            riskOf(risk = "write", tool = "purge_everything", impact = "destructive"),
        )
        assertEquals(
            RiskLevel.DESTRUCTIVE,
            riskOf(risk = "write", tool = "some_new_admin_thing", impact = "admin"),
        )
    }

    @Test
    fun `impact separates three tools that share one risk`() {
        // This is the whole reason `impact` was added to the confirmation card:
        // note_append, delete_model and pull_model are ALL risk=write, and the
        // card has to tell them apart without the client knowing their names.
        assertEquals(RiskLevel.WRITE, riskOf("write", "note_append", "write"))
        assertEquals(RiskLevel.DESTRUCTIVE, riskOf("write", "delete_model", "destructive"))
        assertEquals(RiskLevel.DESTRUCTIVE, riskOf("write", "pull_model", "admin"))
    }

    @Test
    fun `a read stays a read`() {
        assertEquals(RiskLevel.READ, riskOf("read", "rig_status", "read"))
        assertEquals(RiskLevel.READ, riskOf("read", "list_models", ""))
    }

    @Test
    fun `the tool-name table is only consulted when the server said nothing`() {
        // Old audit entries predate the impact field. The fallback still has to
        // work for them -- but only for them.
        assertEquals(RiskLevel.DESTRUCTIVE, riskOf("write", "delete_model", ""))
        assertEquals(RiskLevel.WRITE, riskOf("write", "note_append", ""))
    }

    @Test
    fun `a stale name table cannot downgrade what the server called dangerous`() {
        // The failure this guards is real and has happened once: main grew a
        // `desktop` risk class, Agent 3 had never heard of it, and its fallback
        // classified a screenshot as READ. A name table is a second copy of a
        // classification, and a stale copy fails toward "probably harmless".
        // Here the name says nothing and the server says destructive.
        assertEquals(
            RiskLevel.DESTRUCTIVE,
            riskOf(risk = "", tool = "list_something", impact = "destructive"),
        )
        // ...and `desktop` itself must land on WRITE, not READ.
        assertEquals(RiskLevel.WRITE, riskOf(risk = "desktop", tool = "screenshot", impact = "desktop"))
    }

    @Test
    fun `case does not change a verdict`() {
        assertEquals(RiskLevel.DESTRUCTIVE, riskOf("WRITE", "delete_model", "DESTRUCTIVE"))
    }

    // ------------------------------------------------------------ isTerminal

    @Test
    fun `known finished states are terminal`() {
        listOf("done", "completed", "succeeded", "success",
               "denied", "cancelled", "canceled", "failed", "error")
            .forEach { assertTrue(isTerminal(it), "$it should be terminal") }
    }

    @Test
    fun `an unrecognised state is NOT treated as finished`() {
        // The conservative direction. If Agent 3 grows a state this client has
        // never heard of, calling it finished would let the surface claim work
        // completed that may still be running -- and stop offering the approval
        // that step is waiting for.
        assertFalse(isTerminal("awaiting_confirmation"))
        assertFalse(isTerminal("some_future_state"))
        assertFalse(isTerminal("running"))
        assertFalse(isTerminal(null))
        assertFalse(isTerminal(""))
    }

    // -------------------------------------------------------------- statusOf

    private fun step(state: String?) = Agent3Step(id = "s1", tool = "rig_status", state = state)

    @Test
    fun `server state drives the icon`() {
        assertEquals(StepStatus.DONE, statusOf(step("completed"), isCurrent = false))
        assertEquals(StepStatus.CANCELLED, statusOf(step("denied"), isCurrent = false))
        assertEquals(StepStatus.ACTIVE, statusOf(step("running"), isCurrent = false))
        assertEquals(StepStatus.ACTIVE, statusOf(step("awaiting_confirmation"), isCurrent = false))
    }

    @Test
    fun `an unknown state falls back to the run's own pointer, never to done`() {
        // currentStep is the server's word on where the run is. Using it as the
        // fallback keeps the client from inventing a position -- and neither
        // branch may produce DONE, because a state we cannot read is not
        // evidence that anything finished.
        assertEquals(StepStatus.ACTIVE, statusOf(step("mystery"), isCurrent = true))
        assertEquals(StepStatus.PENDING, statusOf(step("mystery"), isCurrent = false))
        assertEquals(StepStatus.PENDING, statusOf(step(null), isCurrent = false))
    }

    @Test
    fun `a cancelled run's steps never read as pending work`() {
        // A rejection is terminal in Agent 3, and the plan panel must not keep
        // advertising the remaining steps as if they were still coming.
        assertEquals(StepStatus.CANCELLED, statusOf(step("cancelled"), isCurrent = true))
        assertEquals(StepStatus.CANCELLED, statusOf(step("failed"), isCurrent = false))
    }
}
