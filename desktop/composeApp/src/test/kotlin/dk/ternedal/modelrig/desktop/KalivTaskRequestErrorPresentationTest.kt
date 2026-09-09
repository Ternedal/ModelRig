package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse

class KalivTaskRequestErrorPresentationTest {
    @Test
    fun productOwnedConnectionPrerequisitesUseExplicitHumanCopy() {
        assertEquals(
            "Backend-adressen mangler.",
            presentTaskRequestError(TaskRequestOperation.READINESS, "Ingen ModelRig backend-URL er gemt"),
        )
        assertEquals(
            "Device-token mangler.",
            presentTaskRequestError(TaskRequestOperation.PREVIEW, "Ingen device-token er gemt"),
        )
    }

    @Test
    fun operationFailuresUseDeterministicCopy() {
        val raw = "HTTP 503 https://127.0.0.1:8080/internal?token=secret body=/srv/private"
        val expected = mapOf(
            TaskRequestOperation.READINESS to "Task-readiness kunne ikke hentes.",
            TaskRequestOperation.PREVIEW to "Plan-preview kunne ikke hentes.",
            TaskRequestOperation.START to "Startstatus kunne ikke bekræftes. Prøv Start igen; samme preview starter ikke en ny task.",
            TaskRequestOperation.START_NOT_ACCEPTED to "Opgaven blev ikke accepteret. Prøv samme preview igen.",
            TaskRequestOperation.START_REFUSED to "Opgaven blev ikke accepteret. Lav et nyt plan-preview.",
            TaskRequestOperation.STATUS to "Task-status kunne ikke hentes.",
            TaskRequestOperation.STOP_PLAN to "Planen kunne ikke stoppes.",
            TaskRequestOperation.POLLING to "Automatisk task-status kunne ikke hentes.",
            TaskRequestOperation.LOCAL_REFERENCE to "Task-referencen kunne ikke gemmes lokalt. Hold taskfladen åben.",
            TaskRequestOperation.UNKNOWN to "Task-handlingen kunne ikke gennemføres.",
        )
        expected.forEach { (operation, copy) ->
            val presented = presentTaskRequestError(operation, raw)
            assertEquals(copy, presented)
            assertFalse(presented.contains(raw))
            assertFalse(presented.contains("secret"))
            assertFalse(presented.contains("/srv/private"))
        }
    }

    @Test
    fun pathAndExceptionDetailsNeverEcho() {
        val raw = "java.net.ConnectException: /opt/modelrig/private/worker.sock"
        val presented = presentTaskRequestError(TaskRequestOperation.STATUS, raw)
        assertEquals("Task-status kunne ikke hentes.", presented)
        assertFalse(presented.contains("ConnectException"))
        assertFalse(presented.contains("worker.sock"))
    }

    @Test
    fun nearMatchDoesNotGainControlledPrerequisiteSemantics() {
        val raw = "Ingen device-token er gemt: secret-token"
        val presented = presentTaskRequestError(TaskRequestOperation.START, raw)
        assertEquals(
            "Startstatus kunne ikke bekræftes. Prøv Start igen; samme preview starter ikke en ny task.",
            presented,
        )
        assertFalse(presented.contains("secret-token"))
    }

    @Test
    fun nullOrBlankDiagnosticsStillUseOperationCopy() {
        assertEquals(
            "Planen kunne ikke stoppes.",
            presentTaskRequestError(TaskRequestOperation.STOP_PLAN, null),
        )
        assertEquals(
            "Plan-preview kunne ikke hentes.",
            presentTaskRequestError(TaskRequestOperation.PREVIEW, "   "),
        )
    }
}
