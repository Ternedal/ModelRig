package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class ControlCenterDialogTest {
    @Test
    fun overallLabelsNeverTurnUnknownIntoHealthy() {
        assertEquals("Alt ser godt ud", desktopControlCenterOverallLabel("healthy"))
        assertEquals("Kræver opmærksomhed", desktopControlCenterOverallLabel("attention"))
        assertEquals("Utilgængelig", desktopControlCenterOverallLabel("unavailable"))
        assertEquals("Status er ukendt", desktopControlCenterOverallLabel("unknown"))
        assertEquals("Ukendt status", desktopControlCenterOverallLabel("future-state"))
    }

    @Test
    fun stateLabelsKeepStaleUnknownAndDisabledDistinct() {
        assertEquals("Klar", desktopControlCenterStateLabel("healthy"))
        assertEquals("Forældet", desktopControlCenterStateLabel("stale"))
        assertEquals("Ukendt", desktopControlCenterStateLabel("unknown"))
        assertEquals("Slået fra", desktopControlCenterStateLabel("disabled"))
        assertEquals("Fallback", desktopControlCenterStateLabel("fallback"))
        assertEquals("Ukendt", desktopControlCenterStateLabel("synthetic-green"))
    }

    @Test
    fun titlesAndAgeAreHumanReadableWithoutInventingFreshness() {
        assertEquals("Backend", desktopControlCenterTitle("backend"))
        assertEquals("Worker", desktopControlCenterTitle("worker"))
        assertEquals("Modeller", desktopControlCenterTitle("models"))
        assertEquals("Agent 3", desktopControlCenterTitle("agent3"))
        assertEquals("custom", desktopControlCenterTitle("custom"))
        assertEquals("målt nu", desktopControlCenterAge(0.0))
        assertEquals("målt for 12 sek. siden", desktopControlCenterAge(12.0))
        assertEquals("målt for 2 min. siden", desktopControlCenterAge(125.0))
        assertNull(desktopControlCenterAge(null))
        assertNull(desktopControlCenterAge(-1.0))
        assertNull(desktopControlCenterAge(Double.NaN))
        assertNull(desktopControlCenterAge(Double.POSITIVE_INFINITY))
    }
}
