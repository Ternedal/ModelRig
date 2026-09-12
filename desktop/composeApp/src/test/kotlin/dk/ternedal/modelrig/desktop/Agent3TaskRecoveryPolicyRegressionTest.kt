package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class Agent3TaskRecoveryPolicyRegressionTest {
    @Test
    fun cancelledRunKeepsRecoveryReferenceUntilActiveToolSettles() {
        assertEquals(
            "run_abc123",
            Agent3TaskUiPolicy.retainedRunIdAfterSnapshot(
                runId = "run_abc123",
                terminal = false,
                activeToolState = null,
                activeToolRequestState = null,
            ),
        )
        assertEquals(
            "run_abc123",
            Agent3TaskUiPolicy.retainedRunIdAfterSnapshot(
                runId = "run_abc123",
                terminal = true,
                activeToolState = "executing",
                activeToolRequestState = "unavailable",
            ),
        )
        assertEquals(
            "run_abc123",
            Agent3TaskUiPolicy.retainedRunIdAfterSnapshot(
                runId = "run_abc123",
                terminal = true,
                activeToolState = "completed_after_cancel",
                activeToolRequestState = "pending",
            ),
        )
        assertNull(
            Agent3TaskUiPolicy.retainedRunIdAfterSnapshot(
                runId = "run_abc123",
                terminal = true,
                activeToolState = "completed_after_cancel",
                activeToolRequestState = "terminal",
            ),
        )
    }

    @Test
    fun ambiguousStartFailuresPreserveSamePlanRecovery() {
        assertTrue(Agent3TaskUiPolicy.shouldRetainStartRecovery(null))
        assertTrue(Agent3TaskUiPolicy.shouldRetainStartRecovery("task_start_pending"))
        assertTrue(Agent3TaskUiPolicy.shouldRetainStartRecovery("task_start_capacity_unavailable"))
        assertTrue(Agent3TaskUiPolicy.shouldRetainStartRecovery("future_unknown_reason"))

        assertFalse(Agent3TaskUiPolicy.shouldRetainStartRecovery("task_start_refused"))
        assertFalse(Agent3TaskUiPolicy.shouldRetainStartRecovery("task_start_executor_unavailable"))
    }
}
