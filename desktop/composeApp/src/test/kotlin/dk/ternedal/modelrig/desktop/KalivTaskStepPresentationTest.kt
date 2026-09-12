package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class KalivTaskStepPresentationTest {
    @Test
    fun everyKnownWorkerStepStateUsesHumanDanishCopy() {
        val expected = mapOf(
            "pending" to "Afventer",
            "completed_after_cancel" to "Færdig efter stop",
            "waiting_confirmation" to "Afventer godkendelse",
            "approved" to "Godkendt",
            "executing" to "Kører",
            "succeeded" to "Fuldført",
            "denied" to "Afvist",
            "blocked" to "Blokeret",
            "failed" to "Fejlet",
        )
        expected.forEach { (raw, label) ->
            assertEquals(label, presentTaskStepState(raw), raw)
        }
        assertEquals("Kører", presentTaskStepState(" EXECUTING "))
    }

    @Test
    fun unknownStateFailsClosedAndMissingStateDoesNotInventProgress() {
        assertEquals("Status ukendt", presentTaskStepState("future_internal_state"))
        assertNull(presentTaskStepState(""))
        assertNull(presentTaskStepState("   "))
        assertNull(presentTaskStepState(null))
    }

    @Test
    fun validatedReadOnlyMetadataUsesHumanCopy() {
        assertEquals(
            "Kun læsning · lokal dataudgang · kan gentages",
            presentTaskStepReadOnlyMetadata("read", "local", true),
        )
        assertEquals(
            "Kun læsning · lokal dataudgang · kan gentages",
            presentTaskStepReadOnlyMetadata(" READ ", " LOCAL ", true),
        )
    }

    @Test
    fun nonReadOnlyOrUnknownMetadataFailsClosedWithoutEchoingValues() {
        assertEquals("Sikkerhedsmetadata ukendt", presentTaskStepReadOnlyMetadata("write", "local", true))
        assertEquals("Sikkerhedsmetadata ukendt", presentTaskStepReadOnlyMetadata("read", "cloud", true))
        assertEquals("Sikkerhedsmetadata ukendt", presentTaskStepReadOnlyMetadata("read", "local", false))
        assertEquals("Sikkerhedsmetadata ukendt", presentTaskStepReadOnlyMetadata(null, null, false))
    }
}
