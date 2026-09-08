package dk.ternedal.modelrig.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Test

class Agent3TaskEventPresentationTest {
    @Test
    fun knownEventKindsUseBoundedDanishCopy() {
        assertEquals("Kørsel oprettet", presentAgent3TaskEventKind("run_created"))
        assertEquals("Trin startet", presentAgent3TaskEventKind("step_started"))
        assertEquals("Opgaven fuldført", presentAgent3TaskEventKind("run_completed"))
        assertEquals(
            "Read-only-politikken blokerede opgaven",
            presentAgent3TaskEventKind("task_surface_violation"),
        )
    }

    @Test
    fun unknownEventKindFailsClosedWithoutPrimaryCopyLeakage() {
        val raw = "future_event_/api/private/token"
        val presented = presentAgent3TaskEventKind(raw)
        assertEquals("Teknisk hændelse", presented)
        assertFalse(presented.contains(raw))
    }

    @Test
    fun exactEventKindRemainsAvailableAsSecondaryAuditEvidence() {
        val raw = "future_event_v9"
        assertEquals("Eventkode: future_event_v9", presentAgent3TaskEventAuditCode(raw))
    }

    @Test
    fun nonblankPayloadIsAcknowledgedButNeverSerialized() {
        val raw = "{\"endpoint\":\"/api/private/token\",\"secret\":\"opaque-value\"}"
        val presented = presentAgent3TaskEventStructuredDetail(raw)
        assertEquals("Tekniske eventdetaljer skjult i oversigten", presented)
        assertFalse(presented.orEmpty().contains("/api/private/token"))
        assertFalse(presented.orEmpty().contains("opaque-value"))
    }

    @Test
    fun blankPayloadProducesNoStructuredDetailLine() {
        assertNull(presentAgent3TaskEventStructuredDetail(null))
        assertNull(presentAgent3TaskEventStructuredDetail(""))
        assertNull(presentAgent3TaskEventStructuredDetail("   "))
    }
}
