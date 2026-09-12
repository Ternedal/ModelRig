package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class KalivTaskReadinessPresentationTest {
    @Test
    fun knownSurfacesUseHumanLabelsAndUnknownFailsClosed() {
        assertEquals("Agent 3 read-only valgt af serveren", presentTaskReadinessHeadline("agent3_readonly"))
        assertEquals("Agent 2 fallback", presentTaskReadinessHeadline("agent2"))
        assertEquals("Task-routing ikke tilgængelig", presentTaskReadinessHeadline(null))
        assertEquals("Agent 3 read-only", presentTaskReadinessSurface(" AGENT3_READONLY "))
        assertEquals("Agent 2", presentTaskReadinessSurface("agent2"))
        assertEquals("Ikke tilgængelig", presentTaskReadinessSurface("future_surface"))
    }

    @Test
    fun readinessPrimaryCopyNeverEchoesUnknownReasonCodes() {
        assertEquals(
            "Agent 3 read-only er klar til denne taskflade.",
            presentTaskReadinessStatus("agent3_readonly", "agent3_readonly_selected"),
        )
        assertEquals(
            "Agent 3 read-only er ikke slået til; Agent 2 bruges.",
            presentTaskReadinessStatus("agent2", "operator_disabled"),
        )
        assertEquals(
            "Pilotbeviset er udløbet; Agent 2 bruges.",
            presentTaskReadinessStatus("agent2", "pilot_report_stale"),
        )
        assertEquals(
            "Agent 3 read-only er ikke klar; Agent 2 bruges.",
            presentTaskReadinessStatus("agent2", "future_internal_reason"),
        )
        assertEquals(
            "Kunne ikke hente task-routing fra riggen.",
            presentTaskReadinessStatus(null, null),
        )
    }

    @Test
    fun routeAuthorityUsesHumanCopyAndUnknownFailsClosed() {
        assertEquals("Serverstyret", presentTaskReadinessRouteSource("server_authoritative"))
        assertEquals("Routing ukendt", presentTaskReadinessRouteSource("future_route_source"))
        assertEquals("Routing ukendt", presentTaskReadinessRouteSource(null))
    }

    @Test
    fun exactServerReasonRemainsVisibleOnlyAsSecondaryEvidenceCopy() {
        assertEquals(
            "Serverkode: agent3_readonly_selected",
            presentTaskReadinessServerReason("agent3_readonly_selected"),
        )
        assertEquals("Serverkode: future_reason", presentTaskReadinessServerReason(" future_reason "))
        assertNull(presentTaskReadinessServerReason(""))
        assertNull(presentTaskReadinessServerReason(null))
    }
}
