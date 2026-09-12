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
    @Test
    fun controlledReadOnlyErrorsUseBoundedProductCopy() {
        assertEquals(
            "Trinnet blev blokeret af read-only-politikken.",
            presentTaskStepError("blocked", "Read-only task policy drifted outside execute"),
        )
        assertEquals(
            "Trinnet kunne ikke starte, fordi kørslens tilstand ændrede sig.",
            presentTaskStepError("blocked", "Run changed before execution could start"),
        )
    }

    @Test
    fun arbitraryWorkerAndToolDiagnosticsNeverLeakIntoPrimaryCopy() {
        assertEquals(
            "Trinnet fejlede på riggen.",
            presentTaskStepError("failed", "C:\\Users\\anders\\secret.txt: HTTP 500 /internal?token=abc"),
        )
        assertEquals(
            "Trinnet blev blokeret på riggen.",
            presentTaskStepError("blocked", "SocketTimeoutException: 10.0.0.4:11434"),
        )
        assertEquals(
            "Riggen rapporterede et problem med trinnet.",
            presentTaskStepError("executing", "future internal diagnostic details"),
        )
        assertNull(presentTaskStepError("failed", ""))
        assertNull(presentTaskStepError("failed", null))
    }

}
