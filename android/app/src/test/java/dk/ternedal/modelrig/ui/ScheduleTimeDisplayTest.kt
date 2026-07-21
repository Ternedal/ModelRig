package dk.ternedal.modelrig.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class ScheduleTimeDisplayTest {
    @Test
    fun serverLocalTimeKeepsItsOffsetAndZone() {
        assertEquals(
            "2027-01-15T08:00:00-05:00 · America/New_York",
            authoritativeScheduleTime(
                dueAtLocal = "2027-01-15T08:00:00-05:00",
                timezone = "America/New_York",
            ),
        )
    }

    @Test
    fun runOncePolicyIsExplainedWithoutReplayLanguage() {
        assertEquals(
            "Kør én gang; ældre forfald registreres som missed",
            scheduleMisfireLabel("run_once"),
        )
        assertEquals("ukendt-policy", scheduleMisfireLabel("ukendt-policy"))
    }
}
