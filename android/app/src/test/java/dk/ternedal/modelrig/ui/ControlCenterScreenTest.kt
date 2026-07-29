package dk.ternedal.modelrig.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ControlCenterScreenTest {
    @Test
    fun overallLabelsNeverTurnUnknownIntoHealthy() {
        assertEquals("Alt ser godt ud", controlCenterOverallLabel("healthy"))
        assertEquals("Kræver opmærksomhed", controlCenterOverallLabel("attention"))
        assertEquals("Utilgængelig", controlCenterOverallLabel("unavailable"))
        assertEquals("Status er ukendt", controlCenterOverallLabel("unknown"))
        assertEquals("Ukendt status", controlCenterOverallLabel("future-state"))
    }

    @Test
    fun componentLabelsKeepStaleUnknownAndDisabledDistinct() {
        assertEquals("Klar", controlCenterStateLabel("healthy"))
        assertEquals("Forældet", controlCenterStateLabel("stale"))
        assertEquals("Ukendt", controlCenterStateLabel("unknown"))
        assertEquals("Slået fra", controlCenterStateLabel("disabled"))
        assertEquals("Fallback", controlCenterStateLabel("fallback"))
        assertEquals("Utilgængelig", controlCenterStateLabel("unavailable"))
        assertEquals("Ukendt", controlCenterStateLabel("synthetic-green"))
    }

    @Test
    fun componentNamesAreHumanReadable() {
        assertEquals("Backend", controlCenterComponentTitle("backend"))
        assertEquals("Worker", controlCenterComponentTitle("worker"))
        assertEquals("Modeller", controlCenterComponentTitle("models"))
        assertEquals("Agent 3", controlCenterComponentTitle("agent3"))
        assertEquals("custom", controlCenterComponentTitle("custom"))
    }

    @Test
    fun ageLabelsAreBoundedAndNeverInventInvalidFreshness() {
        assertEquals("målt nu", controlCenterAgeLabel(0.0))
        assertEquals("målt for 12 sek. siden", controlCenterAgeLabel(12.0))
        assertEquals("målt for 2 min. siden", controlCenterAgeLabel(125.0))
        assertNull(controlCenterAgeLabel(null))
        assertNull(controlCenterAgeLabel(-1.0))
        assertNull(controlCenterAgeLabel(Double.NaN))
        assertNull(controlCenterAgeLabel(Double.POSITIVE_INFINITY))
    }
}
