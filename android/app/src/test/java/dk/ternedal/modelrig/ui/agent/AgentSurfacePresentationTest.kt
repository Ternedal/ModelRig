package dk.ternedal.modelrig.ui.agent

import dk.ternedal.modelrig.net.Agent3TaskReadinessClient
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Panelet skal citere riggens egen udmelding om fladen.
 *
 * Uden den så operatøren kun planens rutenavn og kunne hverken bekræfte
 * selected_surface_visible, server_reason_visible eller fallback_visible fra
 * scripts/agent3_task_ui_validation.py. Klienten oversætter ikke serverens
 * ord og gætter aldrig en flade den ikke har fået oplyst.
 */
class AgentSurfacePresentationTest {

    private fun readiness(
        selected: String = "agent3_readonly",
        fallback: String = "agent2",
        reason: String = "agent3_readonly_selected",
    ) = Agent3TaskReadinessClient.Readiness(
        selectedSurface = selected,
        candidateSurface = "agent3_readonly",
        fallbackSurface = fallback,
        eligibleForTaskUi = selected == "agent3_readonly",
        operatorEnabled = true,
        normalChatRouteUnchanged = true,
        productionActivation = false,
        reason = reason,
        reasons = emptyList(),
        pilot = Agent3TaskReadinessClient.Pilot(
            configured = true, present = true, structurallyValid = true, fresh = true,
            versionMatch = true, codeMatch = true, finishedAt = null, ageSeconds = null,
            maxAgeHours = 24.0, reportSha256 = null, candidateGitSha = null, tasks = 20,
            successes = 20, failures = 0, taskSuccessRate = 1.0, replans = 0,
            retryEvents = 0, stopFallbackProven = true,
        ),
        rigValidation = Agent3TaskReadinessClient.RigValidation(
            eligibleForDeveloperPreview = true, versionMatch = true,
            codeMatch = true, reportSha256 = null,
        ),
        uiContract = Agent3TaskReadinessClient.UiContract(
            routeSource = "server", stopVisible = true, fallbackVisible = true,
            receiptsVisible = true, replansVisible = true, outcomesVisible = true,
        ),
    )

    @Test
    fun `fladen og serverens begrundelse staar paa linjen`() {
        val ui = AgentRunPresentation.surfaceUi(readiness())
        assertEquals("agent3_readonly", ui.surface)
        assertEquals(
            "Flade: agent3_readonly · agent3_readonly_selected",
            AgentRunPresentation.surfaceLine(ui),
        )
    }

    @Test
    fun `ingen fallback-linje naar task-fladen er valgt`() {
        assertNull(AgentRunPresentation.fallbackLine(AgentRunPresentation.surfaceUi(readiness())))
    }

    @Test
    fun `fallback vises naar riggen ikke har valgt task-fladen`() {
        val ui = AgentRunPresentation.surfaceUi(
            readiness(selected = "agent2", reason = "operator_disabled"),
        )
        assertTrue(ui.fallbackActive)
        val line = AgentRunPresentation.fallbackLine(ui)
        assertTrue(line != null && line.contains("agent2"))
        // Stop skal blive ved med at gælde -- fallback afslutter ikke en kørsel.
        assertTrue(line!!.contains("Stop"))
    }

    @Test
    fun `replan-linjen taeller i ental og flertal`() {
        assertEquals("Ingen omplanlægninger", AgentRunPresentation.replanLine(0))
        assertEquals("1 omplanlægning", AgentRunPresentation.replanLine(1))
        assertEquals("3 omplanlægninger", AgentRunPresentation.replanLine(3))
    }

    @Test
    fun `ukendt replan-tal viser ingen linje frem for at paastaa nul`() {
        // Riggen svarer 501 når replanneren ikke er mountet. "0
        // omplanlægninger" ville da påstå mere end serveren har sagt.
        assertNull(AgentRunPresentation.replanLine(null))
    }

    @Test
    fun `tom begrundelse giver stadig en fladelinje`() {
        val ui = AgentRunPresentation.surfaceUi(readiness(reason = "  "))
        assertEquals("Flade: agent3_readonly", AgentRunPresentation.surfaceLine(ui))
    }
}
