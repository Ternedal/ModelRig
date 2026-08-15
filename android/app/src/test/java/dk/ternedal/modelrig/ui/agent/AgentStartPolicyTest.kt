package dk.ternedal.modelrig.ui.agent

import dk.ternedal.modelrig.net.Agent3Client
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Kontrakttest 3 og 5 fra ADR-A3-001. */
class AgentStartPolicyTest {

    private fun step(tool: String = "list_documents", risk: String = "read", egress: String = "none") =
        Agent3Client.Step(
            id = null, tool = tool, args = "{}", risk = risk, sensitivity = "low",
            egress = egress, summary = "", state = null,
            confirmationDigest = null, confirmationExpiresAt = null, error = null,
        )

    @Test
    fun `kun en eksplicit menneskehandling kan starte`() {
        assertTrue(
            AgentStartPolicy.verdict(AgentStartPolicy.Source.ExplicitUserAction, "find noget")
                is AgentStartPolicy.Verdict.Start,
        )
        for (s in listOf(
            AgentStartPolicy.Source.ModelSuggestion,
            AgentStartPolicy.Source.AutomaticResume,
            AgentStartPolicy.Source.ChatFallback,
        )) {
            assertEquals("$s maa ikke kunne starte", AgentStartPolicy.Verdict.NotExplicit,
                AgentStartPolicy.verdict(s, "find noget"))
        }
    }

    @Test
    fun `en tom besked starter ingenting`() {
        assertEquals(
            AgentStartPolicy.Verdict.EmptyMessage,
            AgentStartPolicy.verdict(AgentStartPolicy.Source.ExplicitUserAction, "   "),
        )
    }

    @Test
    fun `beskeden trimmes, men bevares ellers`() {
        val v = AgentStartPolicy.verdict(AgentStartPolicy.Source.ExplicitUserAction, "  hej  ")
        assertEquals(AgentStartPolicy.Verdict.Start("hej"), v)
    }

    @Test
    fun `skrivetrin genkendes paa alle tre kendetegn`() {
        assertTrue(AgentStartPolicy.isWriteStep(step(risk = "write")))
        assertTrue(AgentStartPolicy.isWriteStep(step(risk = "WRITE_LOCAL")))
        assertTrue(AgentStartPolicy.isWriteStep(step(tool = "write_note")))
        assertTrue(AgentStartPolicy.isWriteStep(step(egress = "write")))
        assertFalse(AgentStartPolicy.isWriteStep(step()))
    }

    @Test
    fun `en plan med bare ét skrivetrin kan ikke startes fra chatten`() {
        val plan = listOf(step(), step(), step(risk = "write"))
        assertEquals(
            AgentStartPolicy.Verdict.NeedsApprovalScreen,
            AgentStartPolicy.verdictForPlan(AgentStartPolicy.Source.ExplicitUserAction, "gør noget", plan),
        )
    }

    @Test
    fun `en ren laeseplan startes`() {
        val plan = listOf(step(), step(tool = "list_models"))
        assertTrue(
            AgentStartPolicy.verdictForPlan(AgentStartPolicy.Source.ExplicitUserAction, "hvad er der", plan)
                is AgentStartPolicy.Verdict.Start,
        )
    }

    @Test
    fun `en tom plan startes ikke`() {
        assertEquals(
            AgentStartPolicy.Verdict.NeedsApprovalScreen,
            AgentStartPolicy.verdictForPlan(AgentStartPolicy.Source.ExplicitUserAction, "hmm", emptyList()),
        )
    }

    @Test
    fun `kilden pruves foer planen — en write-plan fra modellen er stadig NotExplicit`() {
        assertEquals(
            AgentStartPolicy.Verdict.NotExplicit,
            AgentStartPolicy.verdictForPlan(
                AgentStartPolicy.Source.ModelSuggestion, "gør noget", listOf(step(risk = "write")),
            ),
        )
    }
}
