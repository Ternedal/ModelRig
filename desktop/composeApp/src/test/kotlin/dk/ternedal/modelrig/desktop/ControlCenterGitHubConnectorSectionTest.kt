package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ControlCenterGitHubConnectorSectionTest {
    @Test
    fun labelsPreserveUnknownAuthorityValues() {
        assertEquals("Repository", desktopGitHubOperationLabel("repository"))
        assertEquals("Issue", desktopGitHubOperationLabel("issue"))
        assertEquals("Pull request", desktopGitHubOperationLabel("pull_request"))
        assertEquals("CI / workflow-run", desktopGitHubOperationLabel("workflow_run"))
        assertEquals("future_operation", desktopGitHubOperationLabel("future_operation"))

        assertEquals("Udført", desktopGitHubOutcomeLabel("executed"))
        assertEquals("Blokeret", desktopGitHubOutcomeLabel("blocked"))
        assertEquals("Fejl", desktopGitHubOutcomeLabel("error"))
        assertEquals("Ukendt · future", desktopGitHubOutcomeLabel("future"))
    }

    @Test
    fun connectorFilterUsesTheValidatedFirstClassConnectorIdentity() {
        assertTrue(desktopGitHubConnectorMatchesFilter(""))
        assertTrue(desktopGitHubConnectorMatchesFilter("github"))
        assertTrue(desktopGitHubConnectorMatchesFilter(" GITHUB "))
        assertFalse(desktopGitHubConnectorMatchesFilter("gitlab"))
        assertFalse(desktopGitHubConnectorMatchesFilter("local"))
    }

    @Test
    fun externalAccountAndOutboundDataBoundaryStayExplicit() {
        assertEquals(
            "Ekstern konto: GitHub · ternedal",
            desktopGitHubExternalAccountLabel("ternedal"),
        )
        assertEquals(
            "Data der sendes til GitHub ved læsning: repository, valgt read-operation og evt. objekt-id. Credentialen tilføjes kun i worker-transporten og vises aldrig i Control Center.",
            desktopGitHubOutboundDataLabel(),
        )
    }

    @Test
    fun missingPilotAndStaleRevokeRemainDistinct() {
        assertEquals(
            "GitHub connector-piloten er slået fra eller ikke landet på denne rig.",
            desktopGitHubConnectorError("GitHub connector GET grants failed (404): missing"),
        )
        assertEquals(
            "GitHub-tilladelsen findes ikke længere eller er allerede tilbagekaldt. Opdatér status før et nyt forsøg.",
            desktopGitHubConnectorError("GitHub connector POST revoke failed (404): unknown grant"),
        )
    }

    @Test
    fun backendUnavailabilityDoesNotRenderAsHealthy() {
        assertEquals(
            "GitHub connector-authority kan ikke nå den lokale worker lige nu.",
            desktopGitHubConnectorError("request failed (503): unavailable"),
        )
    }
}
