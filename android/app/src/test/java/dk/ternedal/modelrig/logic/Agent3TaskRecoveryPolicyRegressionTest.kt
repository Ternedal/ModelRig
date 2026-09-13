package dk.ternedal.modelrig.logic

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

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
