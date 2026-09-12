package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse

class KalivTaskCapabilityPresentationTest {
    @Test
    fun allowedAndBlockedReceiptsUseBoundedHumanPrimaryCopy() {
        assertEquals(
            "Read-only-planen bestod kapabilitetstjekket.",
            presentTaskCapabilityStatus(true),
        )
        assertEquals(
            "Read-only-planen er blokeret af kapabilitetstjekket.",
            presentTaskCapabilityStatus(false),
        )
        assertEquals(
            "Kapabilitetskvittering er ikke tilgængelig.",
            presentTaskCapabilityStatus(null),
        )
    }

    @Test
    fun capabilityRouteUsesExistingFailClosedHumanRoutePolicy() {
        assertEquals("Lokal rig · værktøjer", presentTaskCapabilityRoute("rig_tools_local"))
        assertEquals("Rute ukendt", presentTaskCapabilityRoute("future_remote_route"))
        assertEquals("Rute ukendt", presentTaskCapabilityRoute(null))
    }

    @Test
    fun blockerCountDoesNotInterpretBlockerContents() {
        assertEquals("Ingen blokeringer", presentTaskCapabilityBlockerCount(0))
        assertEquals("Ingen blokeringer", presentTaskCapabilityBlockerCount(-1))
        assertEquals("1 blokering", presentTaskCapabilityBlockerCount(1))
        assertEquals("3 blokeringer", presentTaskCapabilityBlockerCount(3))
    }

    @Test
    fun arbitraryBlockerDiagnosticsStayOutOfPrimaryCopyAndRemainExactAuditEvidence() {
        val capability = "tool:/srv/modelrig/private"
        val state = "blocked_by_future_policy"
        val reason = "request to rig.local/internal failed with diagnostic 42"

        val primary = presentTaskCapabilityStatus(false)
        assertFalse(primary.contains(capability))
        assertFalse(primary.contains(state))
        assertFalse(primary.contains(reason))

        assertEquals(
            listOf(
                TaskCapabilityEvidence("Capability-id", capability),
                TaskCapabilityEvidence("State", state),
                TaskCapabilityEvidence("Reason", reason),
            ),
            taskCapabilityBlockerEvidence(capability, state, reason),
        )
    }
}
