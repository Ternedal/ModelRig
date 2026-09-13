package dk.ternedal.modelrig.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Test

class Agent3TaskStepPresentationTest {
    @Test
    fun summaryNeverFallsBackToInternalToolId() {
        assertEquals("Hent rigstatus", presentAgent3TaskStepHeadline("  Hent rigstatus  "))
        assertEquals("Trin uden beskrivelse", presentAgent3TaskStepHeadline("   "))
        assertEquals("Trin uden beskrivelse", presentAgent3TaskStepHeadline(null))
        assertEquals("Værktøjskode: rig_status", presentAgent3TaskStepToolAudit("rig_status"))
    }

    @Test
    fun validatedStepStatesUseBoundedDanishLabelsAndUnknownFailsClosed() {
        assertEquals("Afventer", presentAgent3TaskStepState("pending"))
        assertEquals("Kører", presentAgent3TaskStepState("executing"))
        assertEquals("Fuldført", presentAgent3TaskStepState("succeeded"))
        assertEquals("Færdig efter stop", presentAgent3TaskStepState("completed_after_cancel"))
        assertEquals("Blokeret", presentAgent3TaskStepState("blocked"))
        assertEquals("Fejlet", presentAgent3TaskStepState("failed"))
        assertEquals("Status ukendt", presentAgent3TaskStepState("future_state"))
        assertNull(presentAgent3TaskStepState(null))
    }

    @Test
    fun readOnlyMetadataUsesHumanCopy() {
        assertEquals(
            "Kun læsning · lokal dataudgang · kan gentages",
            presentAgent3TaskStepReadOnlyMetadata("read", "local", true),
        )
        assertEquals(
            "Sikkerhedsmetadata ukendt",
            presentAgent3TaskStepReadOnlyMetadata("write", "remote", false),
        )
    }

    @Test
    fun structuredArgsAreAcknowledgedWithoutSerializingThem() {
        assertEquals(
            "Tekniske parametre skjult i oversigten",
            presentAgent3TaskStepStructuredDetail(true),
        )
        assertNull(presentAgent3TaskStepStructuredDetail(false))
    }

    @Test
    fun arbitraryErrorsDoNotLeakIntoPrimaryCopy() {
        val raw = "POST https://rig.internal/private failed with diagnostic 42"
        val presented = presentAgent3TaskStepError("failed", raw)
        assertEquals("Trinnet fejlede på riggen.", presented)
        assertFalse(presented.orEmpty().contains(raw))
        assertEquals(
            "Trinnet blev blokeret af read-only-politikken.",
            presentAgent3TaskStepError("blocked", "read-only task policy drifted outside execute"),
        )
        assertEquals(
            "Trinnet kunne ikke starte, fordi kørslens tilstand ændrede sig.",
            presentAgent3TaskStepError("failed", "run changed before execution could start"),
        )
        assertNull(presentAgent3TaskStepError("failed", "   "))
    }
}
