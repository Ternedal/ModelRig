package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class KalivPerformancePolicyTest {
    @Test
    fun unavailableTelemetryNeverInventsNumbersOrSparkline() {
        val presentation = presentPerformance(KalivPerformanceTelemetry.Unavailable)

        assertFalse(presentation.measured)
        assertEquals("Ikke målt endnu", presentation.tokensPerSecondText)
        assertEquals("—", presentation.responseTimeText)
        assertNull(presentation.sparkline)
    }

    @Test
    fun measuredTelemetryPreservesObservedValues() {
        val presentation = presentPerformance(
            KalivPerformanceTelemetry.Measured(
                tokensPerSecond = 37,
                responseSeconds = 1.25,
                sparkline = listOf(1f, 2f, 3f),
            ),
        )

        assertTrue(presentation.measured)
        assertEquals("37", presentation.tokensPerSecondText)
        assertEquals("1,25 s", presentation.responseTimeText)
        assertEquals(listOf(1f, 2f, 3f), presentation.sparkline)
    }

    @Test
    fun measuredTelemetryDoesNotFabricateSparklineWhenNoneWasObserved() {
        val presentation = presentPerformance(
            KalivPerformanceTelemetry.Measured(
                tokensPerSecond = 0,
                responseSeconds = 0.0,
            ),
        )

        assertTrue(presentation.measured)
        assertNull(presentation.sparkline)
    }
}
