package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class ControlCenterAuditSectionTest {
    @Test
    fun knownAndFutureOutcomesNeverPromoteUnknownToSuccess() {
        assertEquals("Udført", desktopControlCenterAuditOutcomeLabel("executed"))
        assertEquals("Afvist", desktopControlCenterAuditOutcomeLabel("denied"))
        assertEquals("Blokeret", desktopControlCenterAuditOutcomeLabel("blocked"))
        assertEquals("Fejlet", desktopControlCenterAuditOutcomeLabel("failed"))
        assertEquals("Forsøg registreret", desktopControlCenterAuditOutcomeLabel("attempt"))
        assertEquals(
            "Ukendt udfald · future_outcome",
            desktopControlCenterAuditOutcomeLabel("future_outcome"),
        )
    }

    @Test
    fun connectorEvidenceIsExplicitlyUnavailableInsteadOfInferredFromOrigin() {
        val label = desktopControlCenterAuditConnectorEvidenceLabel(
            "unavailable",
            "tool_audit_does_not_record_connector_id",
        )
        assertTrue(label.contains("registrerer ikke connector-id"))
        assertEquals("Cloud", desktopControlCenterAuditOriginLabel("cloud"))
    }

    @Test
    fun auditFailuresStayNeutralAndVisible() {
        assertTrue(desktopControlCenterAuditError("failed (401)").contains("Ikke godkendt"))
        assertTrue(desktopControlCenterAuditError("failed (404)").contains("ikke eksponeret"))
        assertTrue(desktopControlCenterAuditError("failed (502)").contains("utilgængelig"))
        assertTrue(desktopControlCenterAuditError("").contains("kunne ikke hentes"))
    }
}
