package dk.ternedal.modelrig.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class Agent3CapabilityReceiptPresentationTest {
    @Test
    fun statusUsesBoundedHumanCopy() {
        assertEquals("KLAR", presentAgent3CapabilityStatusLabel(true))
        assertEquals("BLOKERET", presentAgent3CapabilityStatusLabel(false))
        assertEquals("Planen bestod kapabilitetstjekket.", presentAgent3CapabilityStatusMessage(true))
        assertEquals("Planen er blokeret af kapabilitetstjekket.", presentAgent3CapabilityStatusMessage(false))
    }

    @Test
    fun routeIsHumanizedAndUnknownValuesFailClosed() {
        assertEquals("Lokal rig · værktøjer", presentAgent3CapabilityRoute("rig_tools_local"))
        assertEquals("Rute ukendt", presentAgent3CapabilityRoute("future_remote_route"))
        assertEquals("Rute ukendt", presentAgent3CapabilityRoute(null))
    }

    @Test
    fun countsUseBoundedHumanCopy() {
        assertEquals("Ingen krav", presentAgent3RequiredCapabilityCount(0))
        assertEquals("1 krav", presentAgent3RequiredCapabilityCount(1))
        assertEquals("3 krav", presentAgent3RequiredCapabilityCount(3))
        assertEquals("Ingen blokeringer", presentAgent3CapabilityBlockerCount(0))
        assertEquals("1 blokering", presentAgent3CapabilityBlockerCount(1))
        assertEquals("2 blokeringer", presentAgent3CapabilityBlockerCount(2))
    }

    @Test
    fun arbitraryReceiptInternalsStayOutOfPrimaryCopyAndRemainExactAuditEvidence() {
        val capability = "tool:/srv/modelrig/private"
        val state = "blocked_by_future_policy"
        val reason = "request to rig.local/internal failed with diagnostic 42"

        val primary = listOf(
            presentAgent3CapabilityStatusLabel(false),
            presentAgent3CapabilityStatusMessage(false),
            presentAgent3CapabilityRoute("future_remote_route"),
            presentAgent3RequiredCapabilityCount(1),
            presentAgent3CapabilityBlockerCount(1),
        ).joinToString(" ")
        assertFalse(primary.contains(capability))
        assertFalse(primary.contains(state))
        assertFalse(primary.contains(reason))
        assertFalse(primary.contains("future_remote_route"))

        assertEquals(
            Agent3CapabilityEvidence("Capability-id", capability),
            agent3RequiredCapabilityEvidence(capability),
        )
        assertEquals(
            listOf(
                Agent3CapabilityEvidence("Capability-id", capability),
                Agent3CapabilityEvidence("State", state),
                Agent3CapabilityEvidence("Reason", reason),
            ),
            agent3CapabilityBlockerEvidence(capability, state, reason),
        )
    }
}
