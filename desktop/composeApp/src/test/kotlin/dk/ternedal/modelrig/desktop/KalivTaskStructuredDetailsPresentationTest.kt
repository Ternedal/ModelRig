package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
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

    @Test
    fun knownTaskEventKindsUseHumanLabels() {
        val expected = mapOf(
            "run_created" to "Kørsel oprettet",
            "task_surface_bound" to "Read-only-kørsel klargjort",
            "policy_decision" to "Sikkerhedstjek udført",
            "step_started" to "Trin startet",
            "step_succeeded" to "Trin fuldført",
            "step_failed" to "Trin fejlede",
            "step_failed_after_cancel" to "Trin fejlede efter stop",
            "step_completed_after_cancel" to "Trin blev færdigt efter stop",
            "run_completed" to "Opgaven fuldført",
            "run_cancelled" to "Opgaven stoppet",
            "task_surface_violation" to "Read-only-politikken blokerede opgaven",
            "task_execution_failed" to "Opgaven fejlede under udførelse",
        )

        expected.forEach { (kind, label) ->
            assertEquals(label, presentTaskEventKind(kind))
            assertFalse(label.contains(kind))
        }
    }

    @Test
    fun unknownEventKindFailsClosedInPrimaryCopy() {
        val raw = "future_worker_event.v2"
        val presented = presentTaskEventKind(raw)
        assertEquals("Teknisk hændelse", presented)
        assertFalse(presented.contains(raw))
    }

    @Test
    fun exactEventKindRemainsSecondaryAuditEvidence() {
        val raw = "future_worker_event.v2"
        assertEquals("Eventkode: future_worker_event.v2", presentTaskEventAuditCode(raw))
    }
}
