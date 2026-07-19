package dk.ternedal.modelrig.ui

import dk.ternedal.modelrig.net.ToolInfo
import org.junit.Assert.assertEquals
import org.junit.Test

class ScheduleToolPolicyTest {
    @Test
    fun pickerOnlySelectsExplicitlySchedulableEnabledTools() {
        val options = scheduleToolOptions(
            listOf(
                tool("clock", schedulable = true, enabled = true),
                tool("delete", schedulable = false, enabled = true, reason = "destructive"),
                tool("disabled", schedulable = true, enabled = false),
                tool("missing-contract", enabled = true),
                tool("clock", schedulable = true, enabled = true),
                tool("", schedulable = true, enabled = true),
            ),
        )

        assertEquals(listOf("clock"), options.selectable.map { it.name })
        assertEquals(
            listOf("delete", "disabled", "missing-contract"),
            options.blocked.map { it.name },
        )
        assertEquals("destructive", options.blocked[0].scheduleBlockReason)
        assertEquals("Værktøjet er slået fra på riggen.", options.blocked[1].scheduleBlockReason)
        assertEquals(
            "Riggen har ikke markeret værktøjet som planlægbart.",
            options.blocked[2].scheduleBlockReason,
        )
    }

    private fun tool(
        name: String,
        schedulable: Boolean = false,
        enabled: Boolean,
        reason: String? = null,
    ) = ToolInfo(
        name = name,
        risk = "read",
        description = name,
        enabled = enabled,
        schedulable = schedulable,
        unschedulableReason = reason,
    )
}
