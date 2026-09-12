package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals

class KalivTaskRunPresentationTest {
    @Test
    fun knownRunStatesUseHumanDanishCopy() {
        assertEquals("Kører", presentTaskRunState("running"))
        assertEquals("Blokeret", presentTaskRunState("blocked"))
        assertEquals("Fuldført", presentTaskRunState("completed"))
        assertEquals("Fejlet", presentTaskRunState("failed"))
        assertEquals("Annulleret", presentTaskRunState("cancelled"))
    }

    @Test
    fun unknownRunStateFailsClosedWithoutEchoingIdentifier() {
        assertEquals("Status ukendt", presentTaskRunState("future_internal_state"))
        assertEquals("Status ukendt", presentTaskRunState(""))
        assertEquals("Status ukendt", presentTaskRunState(null))
    }

    @Test
    fun knownRouteUsesHumanCopyAndUnknownRouteFailsClosed() {
        assertEquals("Lokal rig · værktøjer", presentTaskRunRoute("rig_tools_local"))
        assertEquals("Lokal rig · værktøjer", presentTaskRunRoute(" RIG_TOOLS_LOCAL "))
        assertEquals("Rute ukendt", presentTaskRunRoute("future_route"))
        assertEquals("Rute ukendt", presentTaskRunRoute(null))
    }
}
