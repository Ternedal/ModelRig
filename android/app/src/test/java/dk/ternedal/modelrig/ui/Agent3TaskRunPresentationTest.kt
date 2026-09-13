package dk.ternedal.modelrig.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Test

class Agent3TaskRunPresentationTest {
    @Test
    fun validatedRunStatesUseBoundedDanishLabelsAndUnknownFailsClosed() {
        assertEquals("Kører", presentAgent3TaskRunState("running"))
        assertEquals("Blokeret", presentAgent3TaskRunState("blocked"))
        assertEquals("Fuldført", presentAgent3TaskRunState("completed"))
        assertEquals("Fejlet", presentAgent3TaskRunState("failed"))
        assertEquals("Annulleret", presentAgent3TaskRunState("cancelled"))
        assertEquals("Status ukendt", presentAgent3TaskRunState("future_state_/api/private"))
        assertEquals("Status ukendt", presentAgent3TaskRunState(null))
    }

    @Test
    fun runRouteUsesBoundedHumanCopy() {
        assertEquals("Lokal rig · værktøjer", presentAgent3TaskRunRoute("rig_tools_local"))
        assertEquals("Rute ukendt", presentAgent3TaskRunRoute("future_route_/api/private"))
        assertEquals("Rute ukendt", presentAgent3TaskRunRoute(null))
    }

    @Test
    fun arbitraryRunErrorsDoNotLeakIntoPrimaryCopy() {
        val raw = "POST https://rig.internal/private failed with token opaque-value"

        val failed = presentAgent3TaskRunError("failed", raw)
        assertEquals("Kørslen fejlede på riggen.", failed)
        assertFalse(failed.orEmpty().contains(raw))
        assertFalse(failed.orEmpty().contains("opaque-value"))

        assertEquals("Kørslen blev blokeret på riggen.", presentAgent3TaskRunError("blocked", raw))
        assertEquals("Kørslen blev annulleret.", presentAgent3TaskRunError("cancelled", raw))
        assertEquals(
            "Riggen rapporterede et problem med kørslen.",
            presentAgent3TaskRunError("running", raw),
        )
    }

    @Test
    fun blankRunErrorProducesNoErrorLine() {
        assertNull(presentAgent3TaskRunError("failed", null))
        assertNull(presentAgent3TaskRunError("failed", ""))
        assertNull(presentAgent3TaskRunError("failed", "   "))
    }
}
