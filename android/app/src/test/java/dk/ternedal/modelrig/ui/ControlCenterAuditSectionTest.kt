package dk.ternedal.modelrig.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class ControlCenterAuditSectionTest {
    @Test
    fun outcomeLabelsNeverPromoteUnknownValuesToSuccess() {
        assertEquals("Udført", controlCenterAuditOutcomeLabel("executed"))
        assertEquals("Afvist", controlCenterAuditOutcomeLabel("denied"))
        assertEquals("Blokeret", controlCenterAuditOutcomeLabel("blocked"))
        assertEquals("Fejlet", controlCenterAuditOutcomeLabel("failed"))
        assertEquals("Forsøg registreret", controlCenterAuditOutcomeLabel("attempt"))
        assertEquals(
            "Ukendt udfald · future_outcome",
            controlCenterAuditOutcomeLabel("future_outcome"),
        )
    }

    @Test
    fun originLabelsDoNotPretendOriginIsAConnector() {
        assertEquals("Lokal", controlCenterAuditOriginLabel("local"))
        assertEquals("Cloud", controlCenterAuditOriginLabel("cloud"))
        assertEquals("Planlagt", controlCenterAuditOriginLabel("schedule"))
        assertEquals("future-origin", controlCenterAuditOriginLabel("future-origin"))
    }

    @Test
    fun missingConnectorEvidenceIsExplicit() {
        assertEquals(
            "Connector-filter er utilgængeligt: ToolGate-audit registrerer ikke connector-id endnu.",
            controlCenterAuditConnectorEvidenceLabel(
                "unavailable",
                "tool_audit_does_not_record_connector_id",
            ),
        )
        assertEquals(
            "Connector-evidens har ukendt status.",
            controlCenterAuditConnectorEvidenceLabel("future", null),
        )
    }

    @Test
    fun auditErrorsRemainUnavailableEvidence() {
        assertEquals(
            "Audit-loggen er ikke eksponeret på denne rig.",
            controlCenterAuditError("control center audit failed (404): missing"),
        )
        assertEquals(
            "Audit-loggen er midlertidigt utilgængelig fra riggen.",
            controlCenterAuditError("control center audit failed (503): worker down"),
        )
        assertEquals("Audit kunne ikke hentes.", controlCenterAuditError(null))
    }
}
