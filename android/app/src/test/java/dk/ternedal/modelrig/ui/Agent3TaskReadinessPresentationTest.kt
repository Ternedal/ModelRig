package dk.ternedal.modelrig.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Test

class Agent3TaskReadinessPresentationTest {
    @Test
    fun knownReadinessValuesUseHumanFacingCopy() {
        assertEquals(
            "Agent 3 read-only valgt af serveren",
            presentAgent3TaskReadinessHeadline("agent3_readonly"),
        )
        assertEquals(
            "Agent 3 read-only er klar til denne taskflade.",
            presentAgent3TaskReadinessStatus("agent3_readonly", "agent3_readonly_selected"),
        )
        assertEquals("Agent 3 read-only", presentAgent3TaskReadinessSurface("agent3_readonly"))
        assertEquals("Agent 2", presentAgent3TaskReadinessSurface("agent2"))
        assertEquals("Serverstyret", presentAgent3TaskReadinessRouteSource("server_authoritative"))
    }

    @Test
    fun knownFallbackReasonsHaveBoundedExplanations() {
        assertEquals(
            "Agent 3 read-only er ikke slået til; Agent 2 bruges.",
            presentAgent3TaskReadinessStatus("agent2", "operator_disabled"),
        )
        assertEquals(
            "Pilotbevis er ikke konfigureret; Agent 2 bruges.",
            presentAgent3TaskReadinessStatus("agent2", "pilot_report_path_not_configured"),
        )
        assertEquals(
            "Pilotbeviset er udløbet; Agent 2 bruges.",
            presentAgent3TaskReadinessStatus("agent2", "pilot_report_stale"),
        )
        assertEquals(
            "Rigvalideringen er ikke klar; Agent 2 bruges.",
            presentAgent3TaskReadinessStatus("agent2", "rig_validation_not_ready"),
        )
    }

    @Test
    fun unknownContractValuesFailClosedWithoutLeakingIntoPrimaryCopy() {
        val surface = "https://rig.internal/future_surface"
        val route = "route:/srv/private"
        val reason = "future_reason_with_internal_detail"

        val primary = listOf(
            presentAgent3TaskReadinessHeadline(surface),
            presentAgent3TaskReadinessStatus(surface, reason),
            presentAgent3TaskReadinessSurface(surface),
            presentAgent3TaskReadinessRouteSource(route),
        ).joinToString(" ")

        assertEquals("Task-routing ikke tilgængelig", presentAgent3TaskReadinessHeadline(surface))
        assertEquals("Kunne ikke hente task-routing fra riggen.", presentAgent3TaskReadinessStatus(surface, reason))
        assertEquals("Ikke tilgængelig", presentAgent3TaskReadinessSurface(surface))
        assertEquals("Routing ukendt", presentAgent3TaskReadinessRouteSource(route))
        assertFalse(primary.contains(surface))
        assertFalse(primary.contains(route))
        assertFalse(primary.contains(reason))
    }

    @Test
    fun exactServerReasonIsSecondaryEvidenceOnly() {
        val raw = "future_reason_with_internal_detail"
        assertEquals("Serverkode: $raw", presentAgent3TaskReadinessServerReason(raw))
        assertNull(presentAgent3TaskReadinessServerReason("   "))
        assertNull(presentAgent3TaskReadinessServerReason(null))
    }
}
