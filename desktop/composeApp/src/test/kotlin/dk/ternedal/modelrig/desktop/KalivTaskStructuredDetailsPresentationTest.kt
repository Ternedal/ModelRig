package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class KalivTaskStructuredDetailsPresentationTest {
    @Test
    fun stepArgsAreAcknowledgedWithoutSerializingStructuredContent() {
        assertEquals(
            "Tekniske parametre skjult i oversigten",
            presentTaskStepStructuredDetail(hasArgs = true),
        )
        assertNull(presentTaskStepStructuredDetail(hasArgs = false))
    }

    @Test
    fun eventPayloadIsAcknowledgedWithoutSerializingStructuredContent() {
        assertEquals(
            "Tekniske eventdetaljer skjult i oversigten",
            presentTaskEventStructuredDetail(hasPayload = true),
        )
        assertNull(presentTaskEventStructuredDetail(hasPayload = false))
    }
}
