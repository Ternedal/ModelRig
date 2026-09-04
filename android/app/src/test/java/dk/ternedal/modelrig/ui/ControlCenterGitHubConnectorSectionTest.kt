package dk.ternedal.modelrig.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ControlCenterGitHubConnectorSectionTest {
    @Test
    fun operationLabelsStayHumanReadableWithoutChangingAuthorityIds() {
        assertEquals("Repository", controlCenterGitHubOperationLabel("repository"))
        assertEquals("Issue", controlCenterGitHubOperationLabel("issue"))
        assertEquals("Pull request", controlCenterGitHubOperationLabel("pull_request"))
        assertEquals("CI / workflow-run", controlCenterGitHubOperationLabel("workflow_run"))
        assertEquals("future_operation", controlCenterGitHubOperationLabel("future_operation"))
    }

    @Test
    fun unknownOutcomeIsNeverRenderedAsSuccess() {
        assertEquals("Udført", controlCenterGitHubOutcomeLabel("executed"))
        assertEquals("Blokeret", controlCenterGitHubOutcomeLabel("blocked"))
        assertEquals("Fejl", controlCenterGitHubOutcomeLabel("error"))
        assertEquals("Ukendt · future", controlCenterGitHubOutcomeLabel("future"))
    }

    @Test
    fun connectorFilterUsesTheValidatedFirstClassConnectorIdentity() {
        assertTrue(controlCenterGitHubConnectorMatchesFilter(""))
        assertTrue(controlCenterGitHubConnectorMatchesFilter("github"))
        assertTrue(controlCenterGitHubConnectorMatchesFilter(" GITHUB "))
        assertFalse(controlCenterGitHubConnectorMatchesFilter("gitlab"))
        assertFalse(controlCenterGitHubConnectorMatchesFilter("local"))
    }

    @Test
    fun externalAccountAndOutboundDataBoundaryStayExplicit() {
        assertEquals(
            "Ekstern konto: GitHub · ternedal",
            controlCenterGitHubExternalAccountLabel("ternedal"),
        )
        assertEquals(
            "Data der sendes til GitHub ved læsning: repository, valgt read-operation og evt. objekt-id. Credentialen tilføjes kun i worker-transporten og vises aldrig i Control Center.",
            controlCenterGitHubOutboundDataLabel(),
        )
    }

    @Test
    fun missingPilotAndBackendFailuresRemainExplicitlyUnavailable() {
        assertEquals(
            "GitHub connector-piloten er slået fra eller ikke landet på denne rig.",
            controlCenterGitHubError("GitHub connector GET /api/v1/github-connector/grants failed (404): missing"),
        )
        assertEquals(
            "GitHub connector-authority kan ikke nå den lokale worker lige nu.",
            controlCenterGitHubError("request failed (503): unavailable"),
        )
    }

    @Test
    fun revoke404IsNotMisreportedAsMissingPilot() {
        assertEquals(
            "GitHub-tilladelsen findes ikke længere eller er allerede tilbagekaldt. Opdatér status før et nyt forsøg.",
            controlCenterGitHubError(
                "GitHub connector POST /api/v1/github-connector/grants/ghg_dead/revoke failed (404): unknown GitHub connector grant",
            ),
        )
    }
}
